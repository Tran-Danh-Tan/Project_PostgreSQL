"""Benchmark runner: 3 states x 4 datasets x 10 runs, with EXPLAIN ANALYZE."""

from __future__ import annotations

import datetime
import logging

import psycopg
import pandas as pd

from .config import (
    DATASETS,
    QUERY_COLUMN_BY_STATE,
    RUNS_PER_COMBINATION,
    STATE_PK,
    STATE_PK_CLONE_INDEXED,
    STATE_PK_CLONE_NO_INDEX,
    STATE_ROLES,
    STATES,
    TABLE_NAME,
    WARMUP_RUNS,
    generate_target_ids,
)
from .explain_parser import ExplainResult, parse_explain_json
from .seed import analyze_table, create_pk_clone_index, drop_pk_clone_index, index_exists, seed_dataset

logger = logging.getLogger(__name__)


def _explain_one(conn: psycopg.Connection, column: str, target_id: int) -> ExplainResult:
    """Run EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) for one equality query."""
    with conn.cursor() as cur:
        cur.execute(
            f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) SELECT * FROM {TABLE_NAME} WHERE {column} = %s",
            (target_id,),
        )
        rows = cur.fetchall()
    return parse_explain_json(rows)


def run_state(conn: psycopg.Connection, state: str, dataset: str, target_ids: list[int] | None = None) -> list[dict]:
    """Run warm-up + 10 measured runs for one state/dataset. Returns raw measurements."""
    column = QUERY_COLUMN_BY_STATE[state]
    target_ids = target_ids if target_ids is not None else generate_target_ids(dataset)
    if len(target_ids) != RUNS_PER_COMBINATION:
        raise ValueError("Số target IDs phải bằng số measured runs.")

    indexed = state == STATE_PK or state == STATE_PK_CLONE_INDEXED
    if index_exists(conn) != (state == STATE_PK_CLONE_INDEXED):
        raise RuntimeError(f"Trạng thái index trên pk_clone không phù hợp với {state}.")
    label = {STATE_PK: "PK (index tự động)", STATE_PK_CLONE_NO_INDEX: "pk_clone (no index)", STATE_PK_CLONE_INDEXED: "pk_clone (indexed)"}[state]
    logger.info("Benchmark state=%s dataset=%s column=%s indexed=%s targets=%s", label, dataset, column, indexed, target_ids)

    # Warm-up runs (không tính vào thống kê).
    for _ in range(WARMUP_RUNS):
        _explain_one(conn, column, target_ids[0])

    measurements = []
    for run_number, target_id in enumerate(target_ids, start=1):
        result = _explain_one(conn, column, target_id)
        measurements.append(
            {
                "dataset": dataset,
                "row_count": DATASETS[dataset],
                "state": state,
                "state_role": STATE_ROLES[state],
                "query_column": column,
                "indexed": indexed,
                "run_number": run_number,
                "target_id": target_id,
                "execution_time_ms": result.execution_time_ms,
                "planning_time_ms": result.planning_time_ms,
                "actual_rows": result.actual_rows,
                "actual_loops": result.actual_loops,
                "rows_removed_by_filter": result.rows_removed_by_filter,
                "scan_type": result.scan_type,
                "shared_hit_blocks": result.shared_hit_blocks,
                "shared_read_blocks": result.shared_read_blocks,
                "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }
        )
        logger.info(
            "  run %d/%d target_id=%d -> %.3f ms (plan=%.3f ms, %s, hit=%d, read=%d, rows_removed=%d)",
            run_number, RUNS_PER_COMBINATION, target_id,
            result.execution_time_ms, result.planning_time_ms, result.scan_type,
            result.shared_hit_blocks, result.shared_read_blocks,
            result.rows_removed_by_filter,
        )
    return measurements


def run_benchmark(conn: psycopg.Connection) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Run the full benchmark matrix: 4 datasets x 3 states x 10 runs = 120 measurements."""
    raw_rows: list[dict] = []
    try:
        for dataset in DATASETS:
            seed_dataset(conn, dataset)
            analyze_table(conn)
            target_ids = generate_target_ids(dataset)
            logger.info("Dataset=%s sẵn sàng với %s rows.", dataset, f"{DATASETS[dataset]:,}")
            before = reproduce_problem(conn, dataset, target_ids)
            verify_assumption(before)
            apply_index_solution(conn)
            raw_rows.extend(before + run_state(conn, STATE_PK_CLONE_INDEXED, dataset, target_ids))
    finally:
        if index_exists(conn):
            drop_pk_clone_index(conn)

    raw_df = pd.DataFrame(raw_rows)
    if len(raw_df) != len(DATASETS) * len(STATES) * RUNS_PER_COMBINATION:
        raise RuntimeError(
            f"Số measurement không đúng: {len(raw_df)} thay vì "
            f"{len(DATASETS) * len(STATES) * RUNS_PER_COMBINATION}."
        )

    return summarize_results(raw_df), raw_df


def summarize_results(raw_df: pd.DataFrame) -> pd.DataFrame:
    # Share one aggregation between live benchmark and offline report regeneration."
    return (
        raw_df.groupby(["dataset", "row_count", "state", "state_role", "query_column", "indexed"], sort=False)
        .agg(
            avg_execution_time_ms=("execution_time_ms", "mean"),
            min_execution_time_ms=("execution_time_ms", "min"),
            max_execution_time_ms=("execution_time_ms", "max"),
            avg_planning_time_ms=("planning_time_ms", "mean"),
            scan_type=("scan_type", lambda scans: ", ".join(dict.fromkeys(scans.fillna("Unknown")))),
            avg_actual_rows=("actual_rows", "mean"),
            avg_rows_removed_by_filter=("rows_removed_by_filter", "mean"),
            avg_shared_hit_blocks=("shared_hit_blocks", "mean"),
            avg_shared_read_blocks=("shared_read_blocks", "mean"),
        )
        .reset_index()
    )


def reproduce_problem(conn: psycopg.Connection, dataset: str, target_ids: list[int]) -> list[dict]:
    # Measure baseline and unindexed clone before applying the solution."
    if index_exists(conn):
        drop_pk_clone_index(conn)
        analyze_table(conn)
    return (run_state(conn, STATE_PK, dataset, target_ids)
            + run_state(conn, STATE_PK_CLONE_NO_INDEX, dataset, target_ids))


def verify_assumption(rows: list[dict]) -> None:
    # Log evidence before the index is created; do not presume the hypothesis true."
    for row in summarize_results(pd.DataFrame(rows)).itertuples():
        logger.info("Evidence %s: %s, avg=%.3f ms, removed=%.1f, hit=%.1f, read=%.1f",
                    row.state, row.scan_type, row.avg_execution_time_ms,
                    row.avg_rows_removed_by_filter, row.avg_shared_hit_blocks,
                    row.avg_shared_read_blocks)


def apply_index_solution(conn: psycopg.Connection) -> None:
    create_pk_clone_index(conn)
    analyze_table(conn)
