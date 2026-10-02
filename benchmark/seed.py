"""Schema creation and fast bulk seeding via generate_series()."""

from __future__ import annotations

import logging

import psycopg

from .config import DATASETS, PK_CLONE_INDEX, TABLE_NAME

logger = logging.getLogger(__name__)

CREATE_TABLE_SQL = f"""
CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
    id BIGINT PRIMARY KEY,
    pk_clone BIGINT NOT NULL
)
"""


def create_table(conn: psycopg.Connection) -> None:
    """Create the benchmark table (no error if it already exists)."""
    with conn.cursor() as cur:
        cur.execute(CREATE_TABLE_SQL)
    conn.commit()
    logger.info("Bảng %s sẵn sàng.", TABLE_NAME)


def table_row_count(conn: psycopg.Connection, table: str = TABLE_NAME) -> int:
    with conn.cursor() as cur:
        cur.execute(f"SELECT count(*) FROM {table}")
        return cur.fetchone()[0]


def truncate_table(conn: psycopg.Connection, table: str = TABLE_NAME) -> None:
    with conn.cursor() as cur:
        cur.execute(f"TRUNCATE TABLE {table}")
    conn.commit()
    logger.info("Đã truncate bảng %s.", table)


def index_exists(conn: psycopg.Connection, index_name: str = PK_CLONE_INDEX) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_indexes WHERE indexname = %s", (index_name,))
        return cur.fetchone() is not None


def create_pk_clone_index(conn: psycopg.Connection) -> None:
    if index_exists(conn):
        logger.info("Index %s đã tồn tại, bỏ qua CREATE INDEX.", PK_CLONE_INDEX)
        return
    with conn.cursor() as cur:
        cur.execute(f"CREATE INDEX {PK_CLONE_INDEX} ON {TABLE_NAME}(pk_clone)")
    conn.commit()
    logger.info("Đã tạo index %s.", PK_CLONE_INDEX)


def drop_pk_clone_index(conn: psycopg.Connection) -> None:
    if not index_exists(conn):
        logger.info("Index %s không tồn tại, không cần DROP.", PK_CLONE_INDEX)
        return
    with conn.cursor() as cur:
        cur.execute(f"DROP INDEX {PK_CLONE_INDEX}")
    conn.commit()
    logger.info("Đã drop index %s.", PK_CLONE_INDEX)


def analyze_table(conn: psycopg.Connection) -> None:
    """Refresh planner statistics after schema/index changes."""
    with conn.cursor() as cur:
        cur.execute(f"ANALYZE {TABLE_NAME}")
    conn.commit()
    logger.info("Đã chạy ANALYZE %s.", TABLE_NAME)


def seed_dataset(conn: psycopg.Connection, dataset: str) -> int:
    """Seed one dataset using generate_series(); truncate first for determinism."""
    row_count = DATASETS[dataset]
    logger.info("Seeding %s (%s rows) bằng generate_series()...", dataset, f"{row_count:,}")
    truncate_table(conn)
    drop_pk_clone_index(conn)  # keep table index-free while loading
    with conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO {TABLE_NAME} (id, pk_clone)
            SELECT gs, gs
            FROM generate_series(1, %s) AS gs
            """,
            (row_count,),
        )
        inserted = cur.rowcount
    conn.commit()
    logger.info("Seed %s hoàn tất: %s rows.", dataset, f"{inserted:,}")
    return inserted
