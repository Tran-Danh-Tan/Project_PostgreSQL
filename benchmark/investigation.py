# Evidence-based comparison and charts for the performance investigation report."
from __future__ import annotations
import base64
import datetime
import io
import logging
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
from jinja2 import Environment, FileSystemLoader, select_autoescape
from .config import (DATASETS, HTML_REPORT, RAW_CSV, REPORTS_DIR, RESULTS_CSV,
                     RUNS_PER_COMBINATION, STATE_PK, STATE_PK_CLONE_INDEXED,
                     STATE_PK_CLONE_NO_INDEX, STATE_ROLE_LABELS)

logger = logging.getLogger(__name__)
LABELS = {STATE_PK: "PK / Baseline", STATE_PK_CLONE_NO_INDEX: "pk_clone WITHOUT INDEX / Reproduce problem",
          STATE_PK_CLONE_INDEXED: "pk_clone WITH INDEX / Solution / Verification"}


def _ratio(numerator: float, denominator: float) -> float | None:
    return numerator / denominator if denominator else None

def compare_results(summary_df: pd.DataFrame) -> tuple[list[dict], list[dict]]:
    # Compute comparisons and interpret plans only when measurements support them."
    records = summary_df.to_dict("records")
    lookup = {(r["dataset"], r["state"]): r for r in records}
    comparisons = []
    for dataset in DATASETS:
        pk, no_index, indexed = (lookup[(dataset, state)] for state in
                                 (STATE_PK, STATE_PK_CLONE_NO_INDEX, STATE_PK_CLONE_INDEXED))
        pk_ms, no_ms, idx_ms = (float(r["avg_execution_time_ms"]) for r in (pk, no_index, indexed))
        for row in (pk, no_index, indexed):
            row["state_label"] = LABELS[row["state"]]
            row["role_label"] = STATE_ROLE_LABELS[row["state_role"]]
            row["speedup_vs_pk"] = _ratio(no_ms, float(row["avg_execution_time_ms"]))
            row["improvement_vs_no_index"] = ((no_ms - idx_ms) / no_ms * 100
                                               if row["state"] == STATE_PK_CLONE_INDEXED and no_ms else None)
        confirms = (pk["scan_type"] in ("Index Scan", "Index Only Scan")
                    and no_index["scan_type"] == "Seq Scan" and no_ms > pk_ms)
        root = ("Giả thuyết phù hợp với kết quả đo" if confirms else "Chưa xác nhận đầy đủ giả thuyết")
        root += (f": PK dùng {pk['scan_type']} ({pk_ms*1000:.3f} µs, {pk['avg_actual_rows']:.1f} actual rows, "
                 f"{pk['avg_rows_removed_by_filter']:.1f} rows removed, "
                 f"{pk['avg_shared_hit_blocks']:.1f} hit / {pk['avg_shared_read_blocks']:.1f} read blocks); "
                 f"clone chưa index dùng {no_index['scan_type']} ({no_ms*1000:.3f} µs, "
                 f"{no_index['avg_actual_rows']:.1f} actual rows, "
                 f"{no_index['avg_rows_removed_by_filter']:.1f} rows removed, "
                 f"{no_index['avg_shared_hit_blocks']:.1f} hit / {no_index['avg_shared_read_blocks']:.1f} read blocks). "
                 "Rows removed thể hiện công lọc; ở parallel scan PostgreSQL có thể báo giá trị trung bình "
                 "theo worker/loop. Hit/read cho thấy truy cập buffer (không mặc định là disk I/O).")
        changed = no_index["scan_type"] != indexed["scan_type"]
        effect = "giảm" if idx_ms < no_ms else "không giảm"
        solution = (f"Plan {'thay đổi' if changed else 'không thay đổi'}: {no_index['scan_type']} → "
                    f"{indexed['scan_type']}; execution time {effect} ({no_ms*1000:.3f} → {idx_ms*1000:.3f} µs). "
                    f"Rows removed {no_index['avg_rows_removed_by_filter']:.1f} → {indexed['avg_rows_removed_by_filter']:.1f}; "
                    f"hit {no_index['avg_shared_hit_blocks']:.1f} → {indexed['avg_shared_hit_blocks']:.1f}; "
                    f"read {no_index['avg_shared_read_blocks']:.1f} → {indexed['avg_shared_read_blocks']:.1f} blocks.")
        comparisons.append(dict(dataset=dataset, pk=pk, no_index=no_index, indexed=indexed,
                                reproduce_difference=no_ms - pk_ms, speedup_vs_pk=_ratio(no_ms, pk_ms),
                                improvement_vs_no_index=indexed["improvement_vs_no_index"],
                                root_cause=root, solution_evidence=solution,
                                answer_pk=(f"clone chưa index {no_ms*1000:.3f} µs vs PK {pk_ms*1000:.3f} µs; "
                                           f"{'chậm hơn' if no_ms > pk_ms else 'không chậm hơn'} trong lần đo này; "
                                           f"plan {no_index['scan_type']} vs {pk['scan_type']}."),
                                answer_solution=(f"{solution} "
                                                 f"{'Nhanh hơn' if no_ms > idx_ms else 'Chưa nhanh hơn'} "
                                                 f"{_ratio(no_ms, idx_ms):.2f}× so với chưa index."
                                                 if idx_ms else solution + " Không tính speedup (mẫu số bằng 0).")))
    return records, comparisons

def _chart(comparisons: list[dict], states: tuple[str, ...]) -> str:
    fig, ax = plt.subplots(figsize=(11, 5))
    width = .8 / len(states)
    for i, state in enumerate(states):
        values = [float(next(r for r in (c["pk"], c["no_index"], c["indexed"])
                             if r["state"] == state)["avg_execution_time_ms"]) * 1000 for c in comparisons]
        ax.bar([n + (i - (len(states) - 1) / 2) * width for n in range(len(comparisons))],
               values, width, label=LABELS[state])
    ax.set_xticks(range(len(comparisons)), [c["dataset"] for c in comparisons])
    ax.set_ylabel("Avg execution time (µs, log)")
    ax.set_yscale("log")
    ax.grid(axis="y", alpha=.25)
    ax.legend(fontsize=8)
    fig.tight_layout()
    output = io.BytesIO()
    fig.savefig(output, format="png", dpi=120)
    plt.close(fig)
    return base64.b64encode(output.getvalue()).decode("ascii")


def generate_report(summary_df: pd.DataFrame, pg_version: str) -> None:
    records, comparisons = compare_results(summary_df)
    environment = Environment(loader=FileSystemLoader(Path(__file__).parent),
                              autoescape=select_autoescape(["html"]))
    html = environment.get_template("investigation.html").render(
        summary=records, comparisons=comparisons, pg_version=pg_version,
        timestamp=datetime.datetime.now().isoformat(timespec="seconds"),
        dataset_sizes=", ".join(f"{k}={v:,}" for k, v in DATASETS.items()),
        runs=RUNS_PER_COMBINATION,
        reproduce_chart=_chart(comparisons, (STATE_PK, STATE_PK_CLONE_NO_INDEX)),
        comparison_chart=_chart(comparisons, (STATE_PK, STATE_PK_CLONE_NO_INDEX, STATE_PK_CLONE_INDEXED)))
    HTML_REPORT.write_text(html, encoding="utf-8")
    logger.info("Đã ghi %s", HTML_REPORT)


def save_results(summary_df: pd.DataFrame, raw_df: pd.DataFrame, pg_version: str) -> None:
    REPORTS_DIR.mkdir(exist_ok=True)
    raw_df.to_csv(RAW_CSV, index=False)
    summary_df.to_csv(RESULTS_CSV, index=False)
    logger.info("Đã ghi %s và %s", RAW_CSV, RESULTS_CSV)
    generate_report(summary_df, pg_version)
