# Báo cáo cá nhân — Day 6 · Data Ingestion Engineering

- **Học viên:** Nguyễn Đức Trọng
- **MSSV:** 2A202603367
- **Lớp:** L3A
- **Chủ đề:** Xây dựng Pipeline Ingestion & Đánh giá Truy xuất Kho Tri thức Datasheet Vi điều khiển STM32F103C8

---

## Dữ liệu và pipeline

### 1. Chủ đề, nguồn/quyền, số trang và quy tắc tính trang
- **Chủ đề:** Tài liệu kỹ thuật vi điều khiển dòng hiệu năng trung bình STM32F103C8 (Arm Cortex-M3 32-bit RISC core, 72 MHz, 64/128 KB Flash).
- **Nguồn & Giấy phép:** Tài liệu Datasheet chính thức từ STMicroelectronics (`DS5319 Rev 19`), thuộc diện công khai cho cộng đồng kỹ thuật và lập trình viên nhúng (`Public Datasheet`).
- **Số trang vật lý:** 114 trang.
- **Quy tắc chọn trang:** Chọn lọc 35 trang nội dung kỹ thuật cốt lõi (từ trang 1 đến trang 35), bao gồm: tóm tắt đặc tính (`Features`, `Device summary`), sơ đồ khối (`Block diagram`), cây xung nhịp (`Clock tree`), mô tả chức năng chi tiết (`Overview: Core, Flash, SRAM, DMA, Timers, EXTI, PVD, GPIO`), sơ đồ chân (`Pinouts & pin definitions`) và điều kiện hoạt động điện học (`Parameter conditions`). Đã loại bỏ các trang bìa trống và phụ lục không chứa văn bản định nghĩa.

### 2. Chuẩn hóa, lỗi và giới hạn
- **Chuẩn hóa văn bản:** Chuẩn hóa Unicode `NFC` qua `unicodedata`, chuẩn hóa ngắt dòng `\r\n` thành `\n`, loại bỏ khoảng trắng dư thừa đầu/cuối mỗi dòng và gộp tối đa 2 dòng trống liên tiếp (`\n\n`) nhằm bảo toàn ranh giới đoạn văn.
- **Lỗi & Giới hạn trích xuất:** File PDF chứa các bảng biểu phức tạp (`Table 2`, `Table 5`) và danh sách mục lục; font Helvetica Type1 sinh cảnh báo `fontTools` nhưng text vẫn trích xuất đầy đủ. Một số bảng có nhiều cột bị ngắt dòng có thể làm xáo trộn thứ tự các cột pinout.

### 3. Embedding model, Vector store và Chi phí
- **Embedding model:** `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` chạy local qua PyTorch/Transformers. Số chiều vector: `384` chiều. Metric: Cosine distance (`<=>`).
- **Vector store:** PostgreSQL 16 kết hợp extension `pgvector 0.8.7`, triển khai qua Docker Compose nội bộ (`day6_lab`).
- **Lệnh chạy:** Đứng từ thư mục `starter/`, chạy lệnh `..\starter\.venv\Scripts\python.exe -m src.run`.
- **Chi phí API:** $0.00 (sử dụng hoàn toàn mô hình mã nguồn mở chạy local).

### 4. Metadata và Trường lọc
- **Metadata bắt buộc:** `document_id` (`stm32f103c8`), `source` (`stm32f103c8.pdf`), `page` (số trang vật lý 1–35).
- **Trường lọc bổ sung trong manifest:** `device` (`STM32F103C8`), `family` (`STM32F1`), `manufacturer` (`STMicroelectronics`).
- **Nguồn giá trị & Lý do chọn:** Trích xuất từ phần giới thiệu trang 1 và trang 9 của Datasheet. Đây là các trường định danh cấp phần cứng đáng tin cậy, giúp hệ thống lọc chính xác tài liệu theo từng dòng vi điều khiển khi corpus mở rộng ra nhiều dòng MCU khác nhau (STM32F4, STM32H7,...).

---

## Cấu hình và benchmark

### 1. Ba cấu hình thí nghiệm (A / B / C)
- **Cấu hình A (Baseline - Fixed-size):** Chia chunk kích thước cố định `size = 500` ký tự, độ gối `overlap = 50` ký tự; gắn metadata `source`, `page`, `start_char`, `end_char`; không áp dụng lọc truy xuất.
- **Cấu hình B (Structure-aware - By paragraph):** Gom cụm theo đoạn văn bản tự nhiên (`\n\n`) với kích thước tối đa `max_size = 500` ký tự; cùng metadata; không áp dụng lọc truy xuất.
- **Cấu hình C (B + Query Filter):** Tái sử dụng 100% chunk và vector embedding của cấu hình B. Khác biệt duy nhất: tại thời điểm query, áp dụng lọc có điều kiện bằng SQL (`WHERE strategy = 'C' AND metadata ->> key = value`) khi câu hỏi có trường `filters`.

### 2. Bộ câu hỏi Benchmark (20 câu)
- **Tập chia trước:** Gồm **20 câu hỏi** chia làm **15 câu dev** (`q01`–`q15`) và **5 câu test** (`q16`–`q20`).
- **Độ bao phủ câu hỏi:** Bao gồm câu hỏi trực tiếp (`truc_tiep`), câu hỏi diễn đạt lại (`dien_dat_lai`), câu hỏi điều kiện/ngoại lệ (`dieu_kien`), và các câu hỏi kiểm tra metadata filter.
- **Câu hỏi Filter:** Gồm 3 câu (`q01`, `q13` thuộc dev và `q16` thuộc test).
- **Kiểm chứng Evidence:** Mỗi câu hỏi đều có `gold_source_id`, `gold_page` và `evidence_quote`. Toàn bộ 20 trích dẫn bằng chứng đã được xác minh tự động và đối soát thủ công tồn tại chính xác 100% trong trang nguồn sau khi chuẩn hóa.

### 3. Tiêu chí chọn chiến lược chốt trước khi xem test
1. **Ưu tiên 1 (Hiệu năng truy xuất):** Tối đa hóa chỉ số `Evidence Hit@3` trên tập dev.
2. **Ưu tiên 2 (Chất lượng dữ liệu):** Điểm tính mạch lạc của chunk (`Chunk Coherence`) cao, hạn chế tối đa việc ngắt giữa câu hoặc đứt nửa từ ngữ.
3. **Ưu tiên 3 (Tối ưu tài nguyên):** Giảm thiểu số lượng chunk dư thừa và thời gian embedding.

---

## Kết quả

### Bảng 1: Hiệu năng truy xuất và Tài nguyên
| Strategy | Split | Hit@1 (n/N) | Evidence Hit@3 (n/N) | Chunk count | Thời gian | Chi phí |
|---|---|---|---|---|---|---|
| **A** (Fixed 500/50) | dev | 9/15 (60.0%) | 9/15 (60.0%) | 175 | 7.27s (embed: 7.16s, ingest: 0.11s) | $0.00 |
| **A** (Fixed 500/50) | test | 3/5 (60.0%) | 4/5 (80.0%) | 175 | - | $0.00 |
| **B** (Paragraph) | dev | 9/15 (60.0%) | 10/15 (66.7%) | 161 | 6.64s (embed: 6.56s, ingest: 0.08s) | $0.00 |
| **B** (Paragraph) | test | 2/5 (40.0%) | 3/5 (60.0%) | 161 | - | $0.00 |
| **C** (Paragraph + Filter) | dev | 9/15 (60.0%) | 10/15 (66.7%) | 161 | 0.10s (embed: 0.0s reuse B, ingest: 0.10s) | $0.00 |
| **C** (Paragraph + Filter) | test | 2/5 (40.0%) | 3/5 (60.0%) | 161 | - | $0.00 |

### Bảng 2: Đánh giá chất lượng 5 khía cạnh
| Strategy | Coherence trung bình /2 (n) | Metadata đủ và đúng (n/N) | Filter tuân thủ (n/N hoặc N/A) | Grounding 0/1/2 (số câu) và trung bình /2 |
|---|---|---|---|---|
| **A** | 1.1 / 2 (n=10) | 15/15 (100%) | N/A (không lọc) | 0: 1 câu, 1: 0 câu, 2: 4 câu (TB: 1.6 / 2) |
| **B** | 1.8 / 2 (n=10) | 15/15 (100%) | N/A (không lọc) | 0: 1 câu, 1: 1 câu, 2: 3 câu (TB: 1.4 / 2) |
| **C** | 1.8 / 2 (n=10) | 15/15 (100%) | 1/1 (100%) | 0: 1 câu, 1: 1 câu, 2: 3 câu (TB: 1.4 / 2) |

- **Đường dẫn vết thực nghiệm (trace):** [starter/results/traces.json](file:///d:/Con_Trai/AIThucChien/K5-L3A-Day06-NguyenDucTrong-2A202603367-DataIngestionEngineering/starter/results/traces.json)
- **Đường dẫn mẫu chấm thủ công:** [starter/results/manual_assessment_template.json](file:///d:/Con_Trai/AIThucChien/K5-L3A-Day06-NguyenDucTrong-2A202603367-DataIngestionEngineering/starter/results/manual_assessment_template.json)
- **Cách chọn mẫu audit:** Chọn 10 trang đầu tiên (trang 1 đến trang 10) để chấm Coherence; lấy toàn bộ 5 câu test $\times$ top-3 (15 hits mỗi chiến lược) để kiểm tra Metadata và Grounding.

---

## Phân tích và kết luận

### 1. So sánh chi tiết A–B và B–C
- **So sánh A–B (Ảnh hưởng của chiến lược Chunking):**
  - *Tài nguyên & Số lượng:* Chiến lược B cắt theo đoạn giảm từ 175 xuống 161 chunks (-8.0%), thời gian embedding giảm từ 7.16s xuống 6.56s.
  - *Độ mạch lạc (Coherence):* B đạt 1.8/2 vượt trội so với A (1.1/2). Cấu hình A thường xuyên cắt ngang giữa từ (ví dụ tại trang 1 chunk 0 bị ngắt `hardwar`, chunk 1 bắt đầu bằng ` access`), làm mất ngữ nghĩa. Cấu hình B giữ trọn vẹn ranh giới đoạn văn.
  - *Hiệu năng truy xuất:* Trên tập dev, B nâng Evidence Hit@3 từ 60.0% lên 66.7% (tìm đúng câu `q02` về tần số 72 MHz mà A bỏ sót). Trên tập test nhỏ (5 câu), Hit@3 của A cao hơn B (80% vs 60%) do cửa sổ fixed-size ngắn kết hợp overlap vô tình bắt trúng một câu đơn lẻ (`q20`), nhưng độ nhiễu chunk của A cao hơn.
- **So sánh B–C (Ảnh hưởng của Metadata Filter):**
  - B và C có cùng số lượng chunk và điểm số truy xuất tương đương vì corpus hiện tại là 1 tài liệu kỹ thuật đồng nhất.
  - Điểm vượt trội của C là tính an toàn: Khi truy vấn có filter (`q16`), C đảm bảo 100% chunk trả về tuân thủ trường `device = STM32F103C8`. Ngoài ra, chi phí embedding của C là 0.0s do tái sử dụng hoàn toàn vector của B.

### 2. Phân tích 2 trường hợp truy xuất thất bại từ `traces.json`
- **Ví dụ lỗi 1 — Câu `q01` (dev):**
  - *Câu hỏi:* "Lõi vi điều khiển của dòng STM32F103x8 và STM32F103xB là gì?" (Gold: trang 1, quote: `Arm®-based 32-bit MCU`).
  - *Thực tế truy xuất:* Cả 3 chiến lược trả về top-1 rơi vào trang 14 (mục "2.3.1 Arm Cortex-M3 core with embedded flash and SRAM", score ~0.76).
  - *Nguyên nhân:* Trang 14 chứa một đoạn văn chuyên sâu mô tả kiến trúc bộ xử lý Cortex-M3, có mật độ từ khóa ngữ nghĩa về CPU cao hơn hẳn so với trang 1 (vốn là trang tóm tắt liệt kê tổng thể). Về mặt nghiệp vụ người dùng, trang 14 trả lời hoàn toàn chính xác, nhưng bị tính là trượt do lệch số trang gold (page 1).
- **Ví dụ lỗi 2 — Câu `q18` (test):**
  - *Câu hỏi:* "Bảng 5 trong tài liệu định nghĩa chân của dòng vi điều khiển nào?" (Gold: trang 28, quote: `Table 5. Medium-density STM32F103xx pin definitions`).
  - *Thực tế truy xuất:* Cả 3 chiến lược đều không tìm thấy trang 28 trong top-3 (Hit@3 = 0). Top-3 trả về các đoạn thuộc trang 5 và trang 6 (score ~0.48 – 0.53).
  - *Nguyên nhân:* Trang 5 và 6 là các trang mục lục bảng biểu (`List of Tables`), tập trung hàng loạt từ khóa "Table 1, Table 2, Table 56...". Mô hình dense embedding bị thiên lệch về trang danh mục thay vì trang nội dung thực sự chứa bảng 5.

### 3. Chiến lược lựa chọn, Đánh đổi và Điều kiện áp dụng
- **Chiến lược lựa chọn:** Chọn **Chiến lược C** (Paragraph chunking kết hợp SQL Metadata Filtering).
- **Đánh đổi:** Chấp nhận tỷ lệ Hit@3 trên tập test nhỏ thấp hơn A một chút để đổi lấy: (1) Tính mạch lạc câu văn nguyên vẹn (1.8/2 vs 1.1/2), giúp LLM phía sau không bị ảo giác do rách ngữ cảnh; (2) Giảm 8% chi phí lưu trữ và tài nguyên tính toán; (3) Khả năng mở rộng đa tài liệu an toàn nhờ bộ lọc metadata.
- **Điều kiện áp dụng:** Rất thích hợp cho tài liệu kỹ thuật, datasheets, chính sách hoặc cẩm nang có cấu trúc phân đoạn rõ ràng bằng tiêu đề và đoạn văn (`\n\n`).

### 4. Hạn chế và Hướng cải tiến
- **Hạn chế:**
  - Tập test gồm 5 câu là mẫu tương đối nhỏ, dễ bị biến động ngẫu nhiên (chỉ cần 1 câu trượt/trúng sẽ làm tỷ lệ nhảy 20%).
  - Các bảng biểu dạng cột (pinout table) chưa được chuyển đổi sang Markdown hoặc JSON trước khi chunk, dẫn đến khó truy xuất thông tin chân tín hiệu.
- **Hướng cải tiến:**
  - Kết hợp **Hybrid Retrieval** (Dense Cosine Similarity + BM25 Sparse Search) để giải quyết triệt để các câu hỏi tìm kiếm định danh chính xác như "Bảng 5" (`q18`).
  - Áp dụng kỹ thuật bóc tách bảng chuyên dụng (Table Extraction) chuyển đổi các bảng số liệu trong PDF thành định dạng bảng có cấu trúc trước khi nhúng.
