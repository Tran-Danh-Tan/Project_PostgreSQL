# PostgreSQL Benchmark — PK vs pk_clone

Dự án này là bài tập nhằm kiểm chứng hiệu năng truy vấn trên PostgreSQL. 

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
*Lệnh này sẽ tự động làm mọi thứ: kết nối DB, tạo bảng, sinh dữ liệu ở 4 mức (1K, 100K, 1M, 10M rows), chạy bài test bằng `EXPLAIN ANALYZE` và cuối cùng xuất ra kết quả.*

---

## 📊 Xem kết quả Báo cáo
Sau khi chạy xong lệnh trên, chương trình sẽ tự động tạo thư mục `reports/` chứa kết quả. Bạn hãy mở file báo cáo HTML lên để xem:

- **Windows:** Double-click vào file `reports\benchmark_report.html` hoặc gõ `start reports\benchmark_report.html`
- **macOS/Linux:** `open reports/benchmark_report.html`

File báo cáo HTML sẽ giải thích cực kỳ chi tiết bằng biểu đồ và số liệu thực tế về việc tại sao truy vấn trên `pk_clone` lại rất chậm, giải pháp (tạo Index) và nguyên lý hoạt động đằng sau.

---

## 💡 Tóm tắt kiến thức (Trả lời bài tập)

Qua quá trình benchmark, dự án chứng minh được các luận điểm sau:

1. **WHERE trên `pk_clone` (khi chưa làm gì) CỰC KỲ CHẬM:** Dù giá trị của 2 cột giống hệt nhau, PostgreSQL không hề biết điều đó. Vì `pk_clone` không có Mục lục (Index), hệ thống buộc phải quét toàn bộ bảng (`Seq Scan`) làm thời gian truy vấn tuyến tính (O(N)) thay vì dùng `Index Scan` (O(log N)) như cột Khóa chính.
2. **Làm sao để nhanh?** Rất đơn giản, chỉ cần thêm Index cho cột đó:
   ```sql
   CREATE INDEX idx_benchmark_table_pk_clone ON benchmark_table(pk_clone);
   ```
3. **Giải thích:** Yếu tố quyết định tốc độ của một câu truy vấn `WHERE` nằm ở việc **cột điều kiện có cấu trúc Index vật lý (B-Tree) hay không**, chứ không nằm ở việc giá trị của nó có giống với Khóa chính hay không. Tạo Index xong, Query Planner sẽ thấy mục lục và sử dụng `Index Scan`, giúp tốc độ truy vấn `pk_clone` nhanh ngang ngửa với `id`.
