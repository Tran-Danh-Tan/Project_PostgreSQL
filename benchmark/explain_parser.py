"""Parser for EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) output."""

from __future__ import annotations

from dataclasses import dataclass

SCAN_TYPES = ("Seq Scan", "Index Scan", "Index Only Scan")


@dataclass
class ExplainResult:
    execution_time_ms: float
    scan_type: str
    shared_hit_blocks: int
    shared_read_blocks: int


def parse_explain_json(explain_rows: list) -> ExplainResult:
    """Parse the rows returned by `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)`.

    psycopg returns a single row with one column: a list of JSON plan dicts.
    """
    plans = explain_rows[0][0]
    if not plans:
        raise ValueError(f"Kết quả EXPLAIN JSON không đúng định dạng mong đợi: {explain_rows!r}")

    plan = plans[0]["Plan"]
    execution_time = plans[0]["Execution Time"]

    # Find the first scan node in the plan tree (breadth-first).
    scan_node = plan
    scan_type = "Unknown"
    queue = [plan]
    while queue:
        node = queue.pop(0)
        node_type = node.get("Node Type", "")
        if node_type in ("Seq Scan", "Index Scan", "Index Only Scan"):
            scan_node = node
            scan_type = node_type
            break
        queue.extend(node.get("Plans", []))
    return ExplainResult(
        execution_time_ms=float(execution_time),
        scan_type=scan_type,
        shared_hit_blocks=int(scan_node.get("Shared Hit Blocks", 0)),
        shared_read_blocks=int(scan_node.get("Shared Read Blocks", 0)),
    )
