# PostgreSQL benchmark — PK vs pk_clone

Đây là repository cho một điều tra hiệu năng nhằm trả lời câu hỏi: với một bảng có hai cột chứa giá trị giống nhau — `id` (PRIMARY KEY) và `pk_clone` — liệu truy vấn theo `pk_clone` có chạy nhanh tương tự `id`? Nếu không, vì sao và cách khắc phục?

Tóm tắt workflow mà nhóm cần làm theo (vì đây không chỉ là đo thời gian đơn thuần):

1. Reproduce vấn đề (làm cho kết quả chậm xuất hiện) — thu thập bằng EXPLAIN ANALYZE + BUFFERS
2. Đưa ra assumption (giả thuyết vì sao chậm)
3. Chia nhỏ thành các metric để verify assumption (không chỉ query duration)
4. Thực hiện giải pháp, đo lại và so sánh kết quả → kết luận

----

## Yêu cầu môi trường
- Docker & Docker Compose (dùng cho PostgreSQL trong dev)
- Python 3.10+
- uv (recommended) — chỉ để đồng bộ dependency nhanh; không bắt buộc nếu bạn chạy bằng pip/venv

## Các lệnh chính
- `uv run benchmark run` — chạy toàn bộ: tạo bảng, seed dữ liệu (1K / 100K / 1M / 10M), reproduce, đo (warm-up + measured runs), tạo index, đo lại, xuất CSV + HTML report.
- `uv run benchmark seed` — chỉ seed dữ liệu
- `uv run benchmark benchmark` — chỉ chạy benchmark trên dữ liệu đã seed
- `uv run benchmark report` — sinh lại HTML từ `reports/benchmark_raw.csv` (offline)
- `uv run benchmark clean` — drop index pk_clone (nếu có) và truncate bảng

(Trong Windows: `start reports\benchmark_report.html` — mở báo cáo; macOS/Linux dùng `open reports/benchmark_report.html`.)

----

## 1) Reproduce (mục tiêu & cách làm)
Mục tiêu: tạo lại scenario mà tụi em từng bàn — `WHERE pk_clone = ?` chậm hơn rõ rệt so với `WHERE id = ?` khi `pk_clone` không có index.

Cách thực hiện (tóm tắt):
- Seed bảng: phân biệt 4 kích thước dữ liệu (1K, 100K, 1M, 10M).
- Warm-up: 1 run (không tính vào thống kê) để model warm-cache; sau đó thực hiện N measured runs (config ở `config.py`, mặc định 10) sử dụng cùng tập target IDs cho mọi state.
- States:
  - PK (Baseline): `WHERE id = ?` (có index PK tự động)
  - pk_clone WITHOUT INDEX: `WHERE pk_clone = ?` (không có index)
  - pk_clone WITH INDEX: `WHERE pk_clone = ?` (tạo index rồi đo lại)
- Mỗi run sử dụng `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` để lấy execution time, planning time, scan node info, buffer counters, actual rows/loops, rows removed.

Kết quả mong đợi: trong nhiều dataset lớn (100K+), pk_clone WITHOUT INDEX sẽ có execution time lớn hơn do planner chọn Seq Scan.

----

## 2) Assumption (giả thuyết)
Cấu trúc giả thuyết nhóm đã đề xuất và cần kiểm chứng:
- Nguyên nhân chính: `pk_clone` không có index → planner chọn Seq Scan → tốn O(N) để tìm row → query chậm.
- Các nguyên nhân phụ có thể ảnh hưởng: thống kê planner lỗi/không cập nhật, cache (warm vs cold) làm che dấu I/O, index-only vs index + heap fetch, hoặc dữ liệu phân bố đặc biệt.

Mục tiêu của bước này là chuyển giả thuyết thành các chỉ số có thể đo được.

----

## 3) Metrics để verify (chia nhỏ vấn đề)
Query duration là metric dễ thấy nhất, nhưng để tìm root cause phải chia nhỏ như sau — mọi metric đều lấy từ `EXPLAIN (ANALYZE, BUFFERS)` hoặc tổng hợp từ các run:

A. Thời gian
- execution_time_ms: thời gian thực thi (ANALYZE) — dùng cho so sánh trực tiếp
- planning_time_ms: thời gian lập plan (có thể gây khác biệt nếu planner chậm)

B. Plan-level (rất quan trọng)
- scan_type: Seq Scan / Index Scan / Index Only Scan — nếu Seq Scan xuất hiện cho pk_clone → giả thuyết có xác lực
- actual_rows, actual_loops — xác nhận số row và số lần lặp của node
- rows_removed_by_filter — cho biết công lọc của node

C. Buffer/I/O
- shared_hit_blocks: page được đọc từ shared_buffers (cache) — hit
- shared_read_blocks: page đọc vào shared_buffers (counts of pages brought from disk) — nếu muốn đo I/O thực sự, cần cold-cache runs

D. Derived / aggregate metrics
- avg / min / max per state × dataset
- speedup_vs_pk = avg_no_index / avg_state  (tỉ số, unitless)
- improvement_vs_no_index = (avg_no_index - avg_with_index) / avg_no_index × 100 (%)
- counts of runs where `shared_read_blocks > 0` (để biết có I/O thực sự xảy ra)
- phân bố (boxplot) execution_time để xem nhiễu

E. Per-target inspection
- giữ cùng target IDs trên mọi state để tránh bias từ target chọn ngẫu nhiên
- inspect raw EXPLAIN JSON cho một vài run bất thường (outliers)

Gợi ý đo: báo cáo gồm cả CSV thô (`benchmark_raw.csv`) và summary (`benchmark_results.csv`) — dùng raw để audit run cụ thể.

----

## 4) So sánh & Kết luận (cách dựng báo cáo)
- So sánh ba state theo từng dataset: trình bày avg µs (hoặc ms) + min/max + kiểu scan.
- Luận lý:
  1. Nếu pk_clone WITHOUT INDEX cho scan_type = Seq Scan và execution_time >> PK → xác nhận giả thuyết.
  2. Nếu sau tạo index, scan_type chuyển thành Index Scan và execution_time giảm tương ứng → index là giải pháp hợp lý.
  3. Nếu shared_read_blocks = 0 cho tất cả run → có thể do warm-cache; để đo I/O thực sự cần cold-cache runs.
- Tránh suy diễn: cache, planner và nhiễu môi trường có thể làm kết quả dao động; báo cáo nên nêu rõ điều kiện warm/cold cache.

----

## Lưu ý vận hành / debug
- Để có cold-cache runs (đo I/O thực tế):
  - Linux: khởi động lại PostgreSQL service hoặc (với quyền root) `echo 3 > /proc/sys/vm/drop_caches` — thao tác này ảnh hưởng toàn hệ thống, cẩn thận.
  - Windows: khởi động lại service PostgreSQL hoặc reboot để xóa page cache.
  - Thực hiện cold-run tách biệt, không mix warm và cold trong cùng một tập measured runs.

- Nếu `Shared Read avg` = 0 trong báo cáo, đó thường là vì runs được thực hiện trên bộ nhớ cache (shared_buffers hoặc OS page cache) hoặc truy vấn chỉ cần index pages (Index Only Scan) — không phải lỗi parser.

----

## Outputs & nơi lưu
- `reports/benchmark_raw.csv` — dòng trên từng run
- `reports/benchmark_results.csv` — bảng tóm tắt (dataset × state)
- `reports/benchmark_report.html` — báo cáo điều tra (HTML)

----

## Gợi ý cải tiến code (tóm tắt nhanh)
- Hiện có hai module sinh báo cáo (`benchmark/report.py` và `benchmark/investigation.py`) làm việc tương tự nhau — có thể gộp lại thành một module để tránh trùng lặp template/logic và để duy trì một nơi chỉnh sửa.
- Tách helper chung (ví dụ: format time, hàm vẽ chart, hàm ratio) vào `benchmark/utils.py` để cả báo cáo và script khác dùng chung.
- Cân nhắc thêm flag cho `cold_run` trong config để dễ reproduce I/O test (nhưng phải cảnh báo khi gọi vì tác động hệ thống).

----

Nếu bạn muốn, mình sẽ tiếp tục thực hiện một trong các việc sau (chọn 1):
- 1) Gộp `report.py` và `investigation.py` thành một module báo cáo duy nhất
- 2) Tách các helper chung vào `benchmark/utils.py` và refactor nhẹ các call sites
- 3) Chỉ thay README theo yêu cầu (đã xong)

Chỉ cần trả lời số (1/2/3) hoặc nêu yêu cầu khác.
