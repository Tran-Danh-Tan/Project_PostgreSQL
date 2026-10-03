"""Generate CSV outputs and the HTML report (Jinja2 + matplotlib bar chart)."""

from __future__ import annotations

import base64
import datetime
import io
import logging
import platform
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
from jinja2 import Template

from .config import DATASETS, HTML_REPORT, RAW_CSV, REPORTS_DIR, RESULTS_CSV, RUNS_PER_COMBINATION, STATE_PK, STATE_PK_CLONE_INDEXED, STATE_PK_CLONE_NO_INDEX

logger = logging.getLogger(__name__)

TEMPLATE = """<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="utf-8">
<title>Báo cáo Benchmark PostgreSQL — PK vs pk_clone</title>
<style>
 :root { --primary: #336791; --bg-light: #f4f6f8; --border: #ddd; --accent-green: #27ae60; --accent-red: #e74c3c; --accent-orange: #f39c12; }
 * { box-sizing: border-box; }
 body { font-family: "Segoe UI", Arial, sans-serif; margin: 0; padding: 2rem; max-width: 1200px; margin: 0 auto; color: #222; line-height: 1.6; }
 h1 { border-bottom: 3px solid var(--primary); padding-bottom: .5rem; color: var(--primary); font-size: 1.8rem; }
 h2 { color: var(--primary); margin-top: 2.5rem; font-size: 1.4rem; border-left: 4px solid var(--primary); padding-left: .8rem; }
 h3 { color: #555; margin-top: 1.5rem; }
 table { border-collapse: collapse; width: 100%; margin: 1rem 0; font-size: .9rem; }
 th, td { border: 1px solid var(--border); padding: 8px 12px; text-align: right; }
 th { background: var(--primary); color: white; font-weight: 600; }
 td:first-child, th:first-child { text-align: left; }
 tr:nth-child(even) { background: #f9f9fb; }
 img.chart { width: 100%; margin: 1rem 0; border: 1px solid var(--border); border-radius: 6px; }
 .box { background: var(--bg-light); border-left: 4px solid var(--primary); padding: 1rem 1.2rem; margin: 1rem 0; border-radius: 0 6px 6px 0; }
 .box-green { border-left-color: var(--accent-green); }
 .box-red { border-left-color: var(--accent-red); }
 .box-orange { border-left-color: var(--accent-orange); }
 pre, code { background: #e8ecef; padding: 2px 6px; border-radius: 3px; font-family: "Consolas", "Courier New", monospace; font-size: .88rem; }
 pre { padding: .8rem 1rem; overflow-x: auto; display: block; white-space: pre-wrap; }
 .highlight { font-weight: bold; color: var(--primary); }
 .slow { color: var(--accent-red); font-weight: bold; }
 .fast { color: var(--accent-green); font-weight: bold; }
 ul { padding-left: 1.5rem; }
 li { margin-bottom: .4rem; }
 .footer { margin-top: 3rem; padding-top: 1rem; border-top: 1px solid var(--border); font-size: .8rem; color: #999; text-align: center; }
</style>
</head>
<body>

<h1>Báo cáo Benchmark PostgreSQL — So sánh truy vấn PK vs pk_clone</h1>


<!-- ==================== 2. SETUP & NGUỒN GỐC DỮ LIỆU ==================== -->
<h2>2. Setup & Nguồn gốc dữ liệu</h2>

<h3>2.1. Cấu trúc bảng</h3>
<pre>CREATE TABLE benchmark_table (
    id        BIGINT PRIMARY KEY,   -- Cột PK (PostgreSQL tự tạo B-tree index)
    pk_clone  BIGINT NOT NULL       -- Cột clone, giá trị giống hệt id
);</pre>

<h3>2.2. Dữ liệu được tạo như thế nào?</h3>
<div class="box box-orange">
<p><b>Dữ liệu được tạo hoàn toàn bằng hàm <code>generate_series()</code> của PostgreSQL</b> — không lấy từ nguồn bên ngoài nào.</p>
<p>Với mỗi mức (1K, 100K, 1M, 10M), chương trình chạy câu SQL sau:</p>
<pre>INSERT INTO benchmark_table (id, pk_clone)
SELECT gs, gs
FROM generate_series(1, N) AS gs;</pre>
<p>Trong đó <code>N</code> lần lượt là 1,000 / 100,000 / 1,000,000 / 10,000,000.</p>
<p>→ Kết quả: cột <code>id</code> và <code>pk_clone</code> đều chứa các số nguyên từ 1 đến N, <b>hoàn toàn giống nhau</b>.</p>
</div>

<h3>2.3. Benchmark gồm 3 trạng thái (state)</h3>
<table>
<tr><th>#</th><th>Trạng thái</th><th>Điều kiện WHERE</th><th>Index trên cột truy vấn?</th></tr>
<tr><td>1</td><td>PK (khóa chính)</td><td><code>WHERE id = ?</code></td><td>Có (PK index tự động)</td></tr>
<tr><td>2</td><td>pk_clone (không index)</td><td><code>WHERE pk_clone = ?</code></td><td>Không</td></tr>
<tr><td>3</td><td>pk_clone (có index)</td><td><code>WHERE pk_clone = ?</code></td><td>Có (index tạo thủ công)</td></tr>
</table>
<p>Mỗi tổ hợp (dataset × state) được đo <b>{{ runs }} lần</b> (+ 1 lần warm-up không tính), sử dụng <code>EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)</code>.</p>


<!-- ==================== 3. KẾT QUẢ BENCHMARK ==================== -->
<h2>3. Kết quả Benchmark</h2>

<h3>3.1. Bảng tổng hợp</h3>
<table>
<tr>
  <th>Bộ dữ liệu</th><th>Trạng thái</th><th>Index?</th>
  <th>TB (ms)</th><th>Min (ms)</th><th>Max (ms)</th>
  <th>Kiểu quét</th>
</tr>
{% for r in summary %}
<tr>
  <td>{{ r.dataset }}</td>
  <td>{{ r.state_label }}</td>
  <td>{{ r.index_label }}</td>
  <td>{{ "%.3f"|format(r.avg_ms) }}</td>
  <td>{{ "%.3f"|format(r.min_ms) }}</td>
  <td>{{ "%.3f"|format(r.max_ms) }}</td>
  <td>{{ r.scan_type }}</td>
</tr>
{% endfor %}
</table>

<h3>3.2. Biểu đồ so sánh</h3>
<img class="chart" src="data:image/png;base64,{{ chart_base64 }}" alt="Biểu đồ so sánh benchmark">

<!-- ==================== 4. PHÂN TÍCH ==================== -->
<h2>4. Phân tích: WHERE trên pk_clone có nhanh như PK không?</h2>

<div class="box box-red">
<p><b>Trả lời: KHÔNG.</b> Dù giá trị 2 cột hoàn toàn giống nhau, truy vấn <code>WHERE pk_clone = ?</code> <b class="slow">chậm hơn rất nhiều</b> so với <code>WHERE id = ?</code> khi cột <code>pk_clone</code> không có index.</p>
</div>

{{ analysis|safe }}

<!-- ==================== 5. GIẢI PHÁP ==================== -->
<h2>5. Giải pháp: Làm sao để nhanh?</h2>

<div class="box box-green">
<p><b>Tạo index trên cột <code>pk_clone</code>:</b></p>
<pre>CREATE INDEX idx_benchmark_table_pk_clone ON benchmark_table(pk_clone);</pre>
<p>Sau khi tạo index, chạy <code>ANALYZE</code> để PostgreSQL cập nhật thống kê:</p>
<pre>ANALYZE benchmark_table;</pre>
</div>

<p>Kết quả sau khi tạo index — xem cột <b>"pk_clone (có index)"</b> trong bảng kết quả ở mục 3 — cho thấy thời gian truy vấn <b class="fast">trở lại tương đương với PK</b>.</p>

<!-- ==================== 6. GIẢI THÍCH ==================== -->
<h2>6. Giải thích: Vì sao tạo index giúp nhanh?</h2>

<div class="box">
<h3>6.1. PK tự động có index</h3>
<p>Khi khai báo <code>id BIGINT PRIMARY KEY</code>, PostgreSQL <b>tự động tạo B-tree index</b> trên cột <code>id</code>. B-tree cho phép tìm kiếm một giá trị cụ thể trong <b>O(log N)</b> — rất nhanh, không phụ thuộc vào kích thước bảng.</p>

<h3>6.2. pk_clone không có index → Seq Scan</h3>
<p>Cột <code>pk_clone</code> dù <b>chứa cùng giá trị</b> với <code>id</code>, nhưng PostgreSQL <b>không biết điều đó</b>. Index của PK chỉ ánh xạ <code>id → vị trí dòng</code>, không liên quan gì đến <code>pk_clone</code>.</p>
<p>Khi truy vấn <code>WHERE pk_clone = ?</code> mà không có index trên <code>pk_clone</code>, query planner buộc phải chọn <b>Seq Scan (quét tuần tự)</b> — đọc <b>từng dòng một</b> từ đầu đến cuối bảng cho đến khi tìm thấy dòng thỏa điều kiện.</p>
<p>→ Độ phức tạp: <b>O(N)</b> — càng nhiều rows càng chậm (tuyến tính).</p>

<h3>6.3. Tạo index trên pk_clone → Index Scan</h3>
<p>Khi chạy <code>CREATE INDEX ... ON benchmark_table(pk_clone)</code>, PostgreSQL xây dựng thêm một cây B-tree riêng cho cột <code>pk_clone</code>.</p>
<p>Bây giờ khi truy vấn <code>WHERE pk_clone = ?</code>, query planner thấy có index phù hợp → chọn <b>Index Scan</b> → tìm kiếm trong <b>O(log N)</b> giống như PK.</p>

<h3>6.4. Bản chất vấn đề</h3>
<p>Yếu tố quyết định tốc độ truy vấn là <b class="highlight">index trên đúng cột trong điều kiện WHERE</b>, chứ <b>không phải</b> giá trị của các cột có giống nhau hay không.</p>
<ul>
  <li>Index giống như <b>mục lục sách</b>: có mục lục theo tên → tìm theo tên nhanh; muốn tìm theo chủ đề → cần mục lục riêng theo chủ đề.</li>
  <li>Hai cột cùng giá trị nhưng mỗi cột cần <b>index riêng</b> để được truy vấn nhanh.</li>
</ul>
</div>


<div class="footer">
  <p>Báo cáo được tạo tự động bởi <code>postgres-benchmark</code> tool — Python project dùng uv build tool.</p>
  <p>Chạy: <code>uv run benchmark run</code> để tái tạo kết quả.</p>
</div>

</body>
</html>
"""

STATE_LABELS = {
    STATE_PK: "PK (khóa chính)",
    STATE_PK_CLONE_NO_INDEX: "pk_clone (không index)",
    STATE_PK_CLONE_INDEXED: "pk_clone (có index)",
}


def _build_chart(summary_df: pd.DataFrame) -> str:
    """Render a grouped bar chart (avg ms per state for each dataset) -> base64 PNG."""
    datasets = list(DATASETS.keys())
    states = [STATE_PK, STATE_PK_CLONE_NO_INDEX, STATE_PK_CLONE_INDEXED]
    bar_labels = ["PK (có index)", "pk_clone (không index)", "pk_clone (có index)"]

    fig, ax = plt.subplots(figsize=(10, 5))
    width = 0.25
    x = range(len(datasets))
    for i, state in enumerate(states):
        values = []
        for ds in datasets:
            row = summary_df[(summary_df["dataset"] == ds) & (summary_df["state"] == state)]
            values.append(float(row["avg_ms"].iloc[0]) if len(row) else 0.0)
        bars = ax.bar([xi + i * width for xi in x], values, width, label=bar_labels[i])
        for bar, v in zip(bars, values):
            if v > 0:
                ax.text(bar.get_x() + bar.get_width() / 2, v, f"{v:.2f}", ha="center", va="bottom", fontsize=8)

    ax.set_yscale("log")
    ax.set_xticks([xi + width for xi in x])
    ax.set_xticklabels(datasets)
    ax.set_ylabel("Thời gian thực thi trung bình (ms, thang log)")
    ax.set_title("Truy vấn equality: PK và pk_clone")
    ax.legend()
    ax.grid(axis="y", alpha=0.3)

    buf = io.BytesIO()
    fig.tight_layout()
    fig.savefig(buf, format="png", dpi=120)
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _build_analysis(summary_df: pd.DataFrame) -> str:
    """Generate per-dataset analysis showing the speed differences."""
    lines = []
    for ds in DATASETS:
        def avg(state):
            row = summary_df[(summary_df["dataset"] == ds) & (summary_df["state"] == state)]
            return float(row["avg_ms"].iloc[0]) if len(row) else None

        def scan(state):
            row = summary_df[(summary_df["dataset"] == ds) & (summary_df["state"] == state)]
            return str(row["scan_type"].iloc[0]) if len(row) else "?"

        pk, no_idx, idx = avg(STATE_PK), avg(STATE_PK_CLONE_NO_INDEX), avg(STATE_PK_CLONE_INDEXED)
        if None in (pk, no_idx, idx):
            continue

        ratio = no_idx / pk if pk > 0 else 0
        lines.append(f'<h3>Dataset {ds} ({DATASETS[ds]:,} rows)</h3>')
        lines.append('<table>')
        lines.append('<tr><th>Truy vấn</th><th>TB (ms)</th><th>Kiểu quét</th><th>Chênh lệch</th></tr>')
        lines.append(f'<tr><td><code>WHERE id = ?</code></td><td>{pk:.3f}</td>'
                     f'<td>{scan(STATE_PK)}</td><td>—</td></tr>')
        lines.append(f'<tr><td><code>WHERE pk_clone = ?</code> (không index)</td>'
                     f'<td><b class="slow">{no_idx:.3f}</b></td>'
                     f'<td>{scan(STATE_PK_CLONE_NO_INDEX)}</td>'
                     f'<td class="slow">Chậm hơn ~{ratio:,.0f}x</td></tr>')
        lines.append(f'<tr><td><code>WHERE pk_clone = ?</code> (có index)</td>'
                     f'<td><b class="fast">{idx:.3f}</b></td>'
                     f'<td>{scan(STATE_PK_CLONE_INDEXED)}</td>'
                     f'<td class="fast">≈ tương đương PK</td></tr>')
        lines.append('</table>')

    return "\n".join(lines)


def _build_conclusion(summary_df: pd.DataFrame) -> str:
    """Generate conclusions from real measured numbers (không hard-code kết quả)."""
    lines = []
    for ds in DATASETS:
        def avg(state):
            row = summary_df[(summary_df["dataset"] == ds) & (summary_df["state"] == state)]
            return float(row["avg_ms"].iloc[0]) if len(row) else None

        pk, no_idx, idx = avg(STATE_PK), avg(STATE_PK_CLONE_NO_INDEX), avg(STATE_PK_CLONE_INDEXED)
        if None in (pk, no_idx, idx):
            continue
        lines.append(f"<p><b>{ds} ({DATASETS[ds]:,} rows):</b> "
                     f"PK = {pk:.3f} ms | pk_clone (không index) = {no_idx:.3f} ms | "
                     f"pk_clone (có index) = {idx:.3f} ms.")
        if no_idx > 0 and idx > 0 and no_idx > idx:
            lines.append(f" → Tạo index giúp nhanh hơn <b>{no_idx / idx:.0f}x</b>.</p>")
        else:
            lines.append("</p>")

    lines.append(
        "<p><b>Tóm lại:</b> Giá trị giống nhau ≠ tốc độ giống nhau. "
        "Yếu tố quyết định là <b>index trên đúng cột trong điều kiện WHERE</b>. "
        "Tạo index (B-tree) trên <code>pk_clone</code> → hiệu năng tương đương PK.</p>"
    )
    return "\n".join(lines)


def save_results(summary_df: pd.DataFrame, raw_df: pd.DataFrame, pg_version: str) -> None:
    """Compatibility wrapper — delegate to the consolidated implementation in investigation.py.

    This function preserves the original public API used by callers but forwards
    the actual work to `benchmark.investigation.save_results` to avoid duplicated
    report-generation logic.
    """
    from .investigation import save_results as _investigation_save

    # Delegate the work; keep behavior identical.
    _investigation_save(summary_df, raw_df, pg_version)
