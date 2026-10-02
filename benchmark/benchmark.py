"""Benchmark runner: 3 states x 4 datasets x 10 runs, with EXPLAIN ANALYZE."""

from __future__ import annotations

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


def run_state(conn: psycopg.Connection, state: str, dataset: str) -> list[dict]:
    """Run warm-up + 10 measured runs for one state/dataset. Returns raw measurements."""
    column = QUERY_COLUMN_BY_STATE[state]
    target_ids = generate_target_ids(dataset)

    # Đảm bảo 3 state độc lập về mặt index.
    has_index = index_exists(conn)
    if state == STATE_PK_CLONE_INDEXED:
        if not has_index:
            create_pk_clone_index(conn)
            analyze_table(conn)
    else:  # STATE_PK và STATE_PK_CLONE_NO_INDEX đều không được có index trên pk_clone
        if has_index:
            drop_pk_clone_index(conn)
            analyze_table(conn)

    indexed = state == STATE_PK or state == STATE_PK_CLONE_INDEXED
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
                "query_column": column,
                "indexed": indexed,
                "run_number": run_number,
                "target_id": target_id,
                "execution_time_ms": result.execution_time_ms,
                "scan_type": result.scan_type,
                "shared_hit_blocks": result.shared_hit_blocks,
                "shared_read_blocks": result.shared_read_blocks,
            }
        )
        logger.info(
            "  run %d/%d target_id=%d -> %.3f ms (%s, hit=%d, read=%d)",
            run_number, RUNS_PER_COMBINATION, target_id,
            result.execution_time_ms, result.scan_type,
            result.shared_hit_blocks, result.shared_read_blocks,
        )
    return measurements


def run_benchmark(conn: psycopg.Connection) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Run the full benchmark matrix: 4 datasets x 3 states x 10 runs = 120 measurements."""
    raw_rows: list[dict] = []
    for dataset in DATASETS:
        # Seed ngay trước khi đo để số rows thực tế khớp với nhãn dataset.
        seed_dataset(conn, dataset)
        analyze_table(conn)
        logger.info("Dataset=%s sẵn sàng với %s rows.", dataset, f"{DATASETS[dataset]:,}")
        for state in STATES:
            raw_rows.extend(run_state(conn, state, dataset))

    raw_df = pd.DataFrame(raw_rows)
    if len(raw_df) != len(DATASETS) * len(STATES) * RUNS_PER_COMBINATION:
        raise RuntimeError(
            f"Số measurement không đúng: {len(raw_df)} thay vì "
            f"{len(DATASETS) * len(STATES) * RUNS_PER_COMBINATION}."
        )

    summary = (
        raw_df.groupby(["dataset", "row_count", "state", "query_column", "indexed"], sort=False)
        .agg(
            avg_ms=("execution_time_ms", "mean"),
            min_ms=("execution_time_ms", "min"),
            max_ms=("execution_time_ms", "max"),
            scan_type=("scan_type", "first"),
            shared_hit_blocks=("shared_hit_blocks", "mean"),
            shared_read_blocks=("shared_read_blocks", "mean"),
        )
        .reset_index()
    )
    for col in ("shared_hit_blocks", "shared_read_blocks"):
        summary[col] = summary[col].round(1)

    # Đảm bảo index được dọn lại về trạng thái không index sau khi chạy xong.
    if index_exists(conn):
        drop_pk_clone_index(conn)
        conn.commit()

    return summary, raw_df
