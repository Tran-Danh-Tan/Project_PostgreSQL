"""PostgreSQL connection handling with clear error messages."""

from __future__ import annotations

import logging

import psycopg

from .config import DatabaseConfig

logger = logging.getLogger(__name__)


def connect(db_config: DatabaseConfig) -> psycopg.Connection:
    try:
        conn = psycopg.connect(**db_config.as_kwargs(), connect_timeout=10)
    except psycopg.OperationalError as exc:
        raise RuntimeError(
            "Không kết nối được PostgreSQL. Hãy kiểm tra container đã chạy chưa "
            f"(docker compose up -d) và cấu hình trong .env. Chi tiết: {exc}"
        ) from exc
    return conn


def check_connection(db_config: DatabaseConfig) -> str:
    """Verify the connection works; return the PostgreSQL version string."""
    with connect(db_config) as conn, conn.cursor() as cur:
        cur.execute("SELECT version()")
        version = cur.fetchone()[0]
    logger.info("Kết nối PostgreSQL thành công: %s", version)
    return version
