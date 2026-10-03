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
    planning_time_ms: float
    actual_rows: int
    actual_loops: int
    rows_removed_by_filter: int


def parse_explain_json(explain_rows: list) -> ExplainResult:
    """Parse the rows returned by `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)`.

    psycopg returns a single row with one column: a list of JSON plan dicts.
    """
    plans = explain_rows[0][0]
    if not plans:
        raise ValueError(f"Kết quả EXPLAIN JSON không đúng định dạng mong đợi: {explain_rows!r}")

    plan = plans[0].get("Plan", {})
    execution_time = plans[0].get("Execution Time", 0)
    planning_time = plans[0].get("Planning Time", 0)

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
        execution_time_ms=float(execution_time or 0),
        scan_type=scan_type,
        shared_hit_blocks=int(scan_node.get("Shared Hit Blocks") or 0),
        shared_read_blocks=int(scan_node.get("Shared Read Blocks") or 0),
        planning_time_ms=float(planning_time or 0),
        actual_rows=int(scan_node.get("Actual Rows") or 0),
        actual_loops=int(scan_node.get("Actual Loops") or 0),
        rows_removed_by_filter=int(scan_node.get("Rows Removed by Filter") or 0),
    )
