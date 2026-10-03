# PostgreSQL Benchmark — PK vs pk_clone
Dự án là một bài **performance investigation** trên PostgreSQL, không chỉ đo thời gian query. Flow: **Problem → Assumption → Metrics → Verification → Solution → Comparison → Conclusion**.

**Mục tiêu giải quyết câu hỏi:**
Nếu có 1 bảng CSDL gồm 1 cột PK (`id`) và 1 cột `pk_clone` có giá trị giống hệt PK. Khi truy xuất bằng điều kiện trên cột PK thì cực kỳ nhanh. Vậy truy xuất trên `pk_clone` có nhanh tương tự hay không (vì giá trị 2 cột hoàn toàn giống nhau)? Nếu chậm thì làm sao để nó nhanh và tại sao?

Dự án được setup dưới dạng một ứng dụng Python sử dụng **uv build tool**, tự động sinh dữ liệu (các mức 1k, 100k, 1M, 10M rows), chạy benchmark và xuất ra báo cáo HTML trực quan.

## 🛠 Hướng dẫn Setup & Chạy dự án (Dành cho nhóm)

### Yêu cầu cài đặt
- Docker & Docker Compose (để chạy database)
- [uv](https://docs.astral.sh/uv/) (Công cụ quản lý môi trường Python cực nhanh)
- Python 3.10+

### Các bước thực hiện

**1. Clone dự án và chuẩn bị môi trường:**
```bash
git clone <đường_dẫn_repo_của_bạn>
cd "Project PostgreSQL"

# Copy file cấu hình môi trường
cp .env.example .env
```

**2. Khởi động PostgreSQL bằng Docker:**
```bash
docker compose up -d
```

**3. Cài đặt các thư viện tự động qua `uv`:**
```bash
uv sync
```

**4. Chạy lệnh Benchmark (quan trọng nhất):**
```bash
uv run benchmark run
```
*Lệnh này kết nối DB, tạo bảng, sinh dữ liệu ở 4 mức (1K, 100K, 1M, 10M rows), reproduce vấn đề, thu thập metrics bằng `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)`, tạo index, đo lại và xuất CSV/HTML. Mỗi state có 1 warm-up (không tính) và 10 measured runs với cùng target IDs trong từng dataset.*

```bash
uv build
```

Các lệnh hiện có: `uv run benchmark seed`, `uv run benchmark`, `uv run benchmark report` (sinh lại từ raw CSV), `uv run benchmark clean`.

---

## 📊 Xem kết quả Báo cáo
Sau khi chạy xong lệnh trên, chương trình sẽ tự động tạo thư mục `reports/` chứa kết quả. Bạn hãy mở file báo cáo HTML lên để xem:

- **Windows:** Double-click vào file `reports\benchmark_report.html` hoặc gõ `start reports\benchmark_report.html`
- **macOS/Linux:** `open reports/benchmark_report.html`

Các output:

- `reports/benchmark_raw.csv`: một dòng mỗi lần đo (dataset, state/role, run, target ID, timestamp, planning/execution time, scan type, actual rows/loops, rows removed, shared hit/read blocks). Tổng cộng 120 dòng đo cho 4 datasets × 3 states × 10 runs.
- `reports/benchmark_results.csv`: một dòng mỗi tổ hợp dataset × state với avg/min/max execution time, avg planning time, scan type và các metric trung bình.
- `reports/benchmark_report.html`: báo cáo điều tra, hai biểu đồ và kết luận tính từ số đo thực tế.

## How to interpret the benchmark
1. **Problem / Reproduce:** so sánh PK / Baseline (`WHERE id = ?`) với pk_clone WITHOUT INDEX (`WHERE pk_clone = ?`) ở từng dataset. Query duration cho biết vấn đề performance *có xuất hiện trong lần đo đó hay không*.
2. **Assumption:** giả thuyết `pk_clone` chậm do không có index và PostgreSQL dùng Seq Scan. Chưa xem plan thì chưa kết luận.
3. **Metrics / Root Cause Verification:** `EXPLAIN ANALYZE + BUFFERS` giúp tìm nguyên nhân. Scan Type cho biết PostgreSQL đang dùng Seq Scan, Index Scan hay Index Only Scan. Rows Removed by Filter và Buffer metrics giúp giải thích chi phí của execution plan; Actual Rows cho biết rows trả về, Shared Hit là cache của PostgreSQL, Shared Read không nhất thiết là disk I/O.
4. **Solution / Verify Solution:** tạo `CREATE INDEX idx_benchmark_table_pk_clone ON benchmark_table(pk_clone);`, cập nhật thống kê bằng `ANALYZE`, đo lại cùng query/target IDs/method. So sánh scan type, execution time, rows removed, hit/read; không ép planner chọn index.
5. **Final Comparison / Conclusion:** so sánh ba state theo dataset; `speedup_vs_pk = avg_no_index / avg_state` và `improvement_vs_no_index = (avg_no_index - avg_with_index) / avg_no_index × 100`. Không hiển thị tỷ lệ khi mẫu số bằng 0; không suy diễn index luôn nhanh hơn ở mọi dataset.

Kết quả phụ thuộc cache, planner và môi trường đo. Dùng raw CSV để audit từng execution, không xem giả thuyết là kết luận trước khi kiểm tra metrics.
