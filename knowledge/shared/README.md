# Kho tri thức chung

Nguồn đầu vào: `../MeSH/MESH.ttl`, `../VietHerbs/VHO.owl`,
`../dataset-run/dataset_graph.json`, PDF trong `../../Dataset/` và `uploads/`.
Định nghĩa ontology ứng dụng: `../ontology/core.json` (candidate v1.0.0).

Tạo/cập nhật từ thư mục gốc, không gọi API suy luận cho corpus cũ:

```sh
conda activate bqp
python web/backend/knowledge_store.py
```

`current.json` trỏ vào snapshot SQLite và thư mục Qdrant cùng phiên bản. Chỉ chuyển
pointer sau khi cả hai hoàn tất. Snapshot cũ được giữ để có thể quay về bằng cách
khôi phục manifest cũ; chỉ dùng snapshot nguyên vẹn và ngừng server trước khi đổi.
Không xóa snapshot đang được query sử dụng. Ingestion được tuần tự hóa trong một
tiến trình web; triển khai nhiều worker cần worker ingestion riêng để quản lý jobs.

SQLite lưu khái niệm, nhãn theo ngôn ngữ, quan hệ nguồn, các phát biểu candidate và
đơn vị bằng chứng PDF. ID ontology giữ namespace và URI; entity graph giữ tên có dấu,
type và nguồn. Không gộp các ontology theo label, embedding hay MeSH entry term.
Blank-node restrictions OWL không được trải phẳng thành quan hệ điều trị.

BM25 dùng `Qdrant/bm25` qua FastEmbed và Qdrant memory có `Modifier.IDF`. Sparse
vectors lưu trong `bm25/<snapshot>/evidence.jsonl`, nạp một lần vào query index để
tránh SQLite fsync cho từng điểm của Qdrant local. Thiết lập
tokenizer `english` dùng cho corpus hỗn hợp; chưa có benchmark chất lượng tiếng Việt
cho cấu hình này. Không dùng RDR underscore làm input BM25. `KNOWLEDGE_BM25=0` bật
fallback lexical FTS giữ dấu, không gọi fallback đó là BM25.

PDF mới được lưu theo SHA-256; receipt JSON chứa tiến trình và candidate claims.
Text luôn có thể index dù extraction thiếu khóa API hoặc hết budget. Không tự OCR
hay tự ghép hàng nối trang; trang thiếu text và hàng không rõ được đánh dấu.

MeSH được parse streaming bằng PyOxigraph, ghi chọn lọc nhãn,
định nghĩa, hierarchy và mapping. Cập nhật PDF tái sử dụng ontology đã nhập khi file
nguồn và phiên bản profile không đổi. Các bản SQLite chưa publish do quá trình tạo
bị gián đoạn không được dùng để trả lời.
