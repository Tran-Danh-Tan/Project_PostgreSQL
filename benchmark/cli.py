"""CLI entry point: `uv run benchmark run|seed|benchmark|report|clean`."""

from __future__ import annotations

import argparse
import logging
import sys

import pandas as pd

from . import __version__
from .benchmark import run_benchmark
from .config import DATASETS, HTML_REPORT, RAW_CSV, RESULTS_CSV, TABLE_NAME, load_db_config
from .database import check_connection, connect
from .seed import (
    analyze_table,
    create_table,
    create_pk_clone_index,
    drop_pk_clone_index,
    seed_dataset,
    table_row_count,
    truncate_table,
)
from .report import save_results

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def _cmd_run(args: argparse.Namespace) -> None:
    db_config = load_db_config()
    logger.info("Bước 1/6: Kiểm tra PostgreSQL connection...")
    pg_version = check_connection(db_config)

    with connect(db_config) as conn:
        logger.info("Bước 2/6: Tạo table %s...", TABLE_NAME)
        create_table(conn)

        logger.info("Bước 3/6: Seed và benchmark từng dataset (1K -> 100K -> 1M -> 10M)...")
        logger.info("Bước 4+5/6: Chạy benchmark 3 states (warm-up + 10 measured runs mỗi combination)...")
        summary, raw = run_benchmark(conn)

    logger.info("Bước 6/6: Sinh CSV + HTML report...")
    save_results(summary, raw, pg_version)
    logger.info("Hoàn tất! Kết quả: %s và %s", RESULTS_CSV, HTML_REPORT)


def _cmd_seed(args: argparse.Namespace) -> None:
    db_config = load_db_config()
    pg_version = check_connection(db_config)
    with connect(db_config) as conn:
        create_table(conn)
        for dataset in (args.datasets or list(DATASETS)):
            if dataset not in DATASETS:
                raise SystemExit(f"Dataset không hợp lệ: {dataset}. Chọn trong {list(DATASETS)}")
            seed_dataset(conn, dataset)
        analyze_table(conn)


def _cmd_benchmark(args: argparse.Namespace) -> None:
    db_config = load_db_config()
    pg_version = check_connection(db_config)
    with connect(db_config) as conn:
        summary, raw = run_benchmark(conn)
    save_results(summary, raw, pg_version)
    logger.info("Hoàn tất! Kết quả: %s và %s", RESULTS_CSV, HTML_REPORT)


def _cmd_report(args: argparse.Namespace) -> None:
    if not RESULTS_CSV.exists():
        raise SystemExit(f"Chưa có {RESULTS_CSV}. Hãy chạy `uv run benchmark run` hoặc `benchmark benchmark` trước.")
    raw = pd.read_csv(RAW_CSV) if RAW_CSV.exists() else None
    if raw is None:
        raise SystemExit(f"Chưa có {RAW_CSV}. Hãy chạy `uv run benchmark` trước.")
    summary = (
        raw.groupby(["dataset", "row_count", "state", "query_column", "indexed"], sort=False)
        .agg(avg_ms=("execution_time_ms", "mean"), min_ms=("execution_time_ms", "min"),
             max_ms=("execution_time_ms", "max"), scan_type=("scan_type", "first"),
             shared_hit_blocks=("shared_hit_blocks", "mean"), shared_read_blocks=("shared_read_blocks", "mean"))
        .reset_index()
    )
    for col in ("shared_hit_blocks", "shared_read_blocks"):
        summary[col] = summary[col].round(1)
    # Try to get pg_version from DB, but don't fail if DB is down (offline report regen)
    pg_version = "PostgreSQL (version unknown — DB offline)"
    try:
        db_config = load_db_config()
        pg_version = check_connection(db_config)
    except Exception:
        logger.warning("Không kết nối được PostgreSQL — dùng version mặc định cho report.")
    save_results(summary, raw, pg_version)
    logger.info("Đã sinh lại report: %s", HTML_REPORT)


def _cmd_clean(args: argparse.Namespace) -> None:
    db_config = load_db_config()
    with connect(db_config) as conn:
        drop_pk_clone_index(conn)
        truncate_table(conn)
    logger.info("Đã drop index pk_clone (nếu có) và truncate %s.", TABLE_NAME)


def main() -> None:
    parser = argparse.ArgumentParser(prog="benchmark", description="PostgreSQL equality-query benchmark")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("run", help="Chạy toàn bộ pipeline: seed -> benchmark -> CSV + HTML report").set_defaults(func=_cmd_run)

    p_seed = sub.add_parser("seed", help="Chỉ seed dữ liệu")
    p_seed.add_argument("--datasets", nargs="*", choices=list(DATASETS), help="Ví dụ: 1K 100K")
    p_seed.set_defaults(func=_cmd_seed)

    sub.add_parser("benchmark", help="Chỉ chạy benchmark (dùng dữ liệu đã seed)").set_defaults(func=_cmd_benchmark)
    sub.add_parser("report", help="Chỉ sinh lại CSV + HTML từ benchmark_raw.csv").set_defaults(func=_cmd_report)
    sub.add_parser("clean", help="Drop index pk_clone + truncate bảng").set_defaults(func=_cmd_clean)

    args = parser.parse_args()
    try:
        args.func(args)
    except RuntimeError as exc:
        logger.error("%s", exc)
        sys.exit(1)
    except KeyboardInterrupt:
        logger.error("Benchmark bị dừng giữa chừng bởi người dùng. Dữ liệu có thể chưa đủ; chạy lại `uv run benchmark run`.")
        sys.exit(130)


if __name__ == "__main__":
    main()
