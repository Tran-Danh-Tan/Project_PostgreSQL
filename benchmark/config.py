"""Central configuration: benchmark parameters, dataset sizes, constants."""

from __future__ import annotations

import os
import random
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REPORTS_DIR = PROJECT_ROOT / "reports"
RESULTS_CSV = REPORTS_DIR / "benchmark_results.csv"
RAW_CSV = REPORTS_DIR / "benchmark_raw.csv"
HTML_REPORT = REPORTS_DIR / "benchmark_report.html"

TABLE_NAME = "benchmark_table"
PK_CLONE_INDEX = "idx_benchmark_table_pk_clone"

RUNS_PER_COMBINATION = 10
WARMUP_RUNS = 1
RANDOM_SEED = 42

# dataset name -> row count
DATASETS: dict[str, int] = {
    "1K": 1_000,
    "100K": 100_000,
    "1M": 1_000_000,
    "10M": 10_000_000,
}

STATE_PK = "PK"
STATE_PK_CLONE_NO_INDEX = "pk_clone_no_index"
STATE_PK_CLONE_INDEXED = "pk_clone_indexed"
STATES = [STATE_PK, STATE_PK_CLONE_NO_INDEX, STATE_PK_CLONE_INDEXED]

QUERY_COLUMN_BY_STATE = {
    STATE_PK: "id",
    STATE_PK_CLONE_NO_INDEX: "pk_clone",
    STATE_PK_CLONE_INDEXED: "pk_clone",
}

STATE_ROLES: dict[str, str] = {
    STATE_PK: "baseline",
    STATE_PK_CLONE_NO_INDEX: "reproduce_problem",
    STATE_PK_CLONE_INDEXED: "verify_solution",
}

STATE_ROLE_LABELS: dict[str, str] = {
    "baseline": "Baseline",
    "reproduce_problem": "Reproduce Problem",
    "verify_solution": "Verify Solution",
}


@dataclass(frozen=True)
class DatabaseConfig:
    host: str
    port: int
    dbname: str
    user: str
    password: str

    def as_kwargs(self) -> dict:
        return {
            "host": self.host,
            "port": self.port,
            "dbname": self.dbname,
            "user": self.user,
            "password": self.password,
        }


def load_db_config(env_file: Path | None = None) -> DatabaseConfig:
    """Read database configuration from .env (no hard-coded credentials in code)."""
    load_dotenv(env_file or PROJECT_ROOT / ".env")
    try:
        return DatabaseConfig(
            host=os.environ.get("POSTGRES_HOST", "localhost"),
            port=int(os.environ.get("POSTGRES_PORT", "5432")),
            dbname=os.environ["POSTGRES_DB"],
            user=os.environ["POSTGRES_USER"],
            password=os.environ["POSTGRES_PASSWORD"],
        )
    except KeyError as exc:
        raise RuntimeError(
            f"Thiếu biến môi trường {exc}. Hãy copy .env.example thành .env và điền đủ giá trị."
        ) from exc


def generate_target_ids(dataset: str) -> list[int]:
    """Deterministic target IDs, reproducible via RANDOM_SEED, inside dataset range."""
    row_count = DATASETS[dataset]
    rng = random.Random(RANDOM_SEED + row_count)
    return sorted(rng.randint(1, row_count) for _ in range(RUNS_PER_COMBINATION))
