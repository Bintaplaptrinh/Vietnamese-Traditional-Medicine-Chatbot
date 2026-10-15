# Medical research skills cho Bloop

Đã clone [AIPOCH Medical Research Skills](https://github.com/aipoch/medical-research-skills)
vào `medical-research-skills/`, giữ nguyên `SKILL.md`, modules tham chiếu, assets
và giấy phép MIT của upstream. Commit và SHA-256 của các skill được chọn nằm trong
[`medical-research-skills.lock.json`](medical-research-skills.lock.json).

Đây là nguồn tham khảo để xây profile cho chatbot; backend chưa tự nạp các skill.
Clone local được ignore để không thêm một repository Git lồng vào repository chính.
Các liên kết skill dưới đây trỏ tới đúng commit đã clone.

## Nhóm skill phù hợp

| Tác vụ trong Bloop | Skill upstream | Phần cần áp dụng khi tích hợp |
| --- | --- | --- |
| Lập kế hoạch tìm tài liệu | [biomedical-search-strategy-builder](https://github.com/aipoch/medical-research-skills/blob/686e09dfdb45d9fa1a08664f06bb93769b3c9d91/awesome-med-research-skills/Evidence%20Insight/biomedical-search-strategy-builder/SKILL.md) | Tách khái niệm, đề xuất MeSH/free-text và truy vấn theo cơ sở dữ liệu; skill xây query, không tự tải bài báo |
| Đọc và phân loại nghiên cứu | [study-design-identifier](https://github.com/aipoch/medical-research-skills/blob/686e09dfdb45d9fa1a08664f06bb93769b3c9d91/awesome-med-research-skills/Evidence%20Insight/study-design-identifier/SKILL.md) | Xác định thiết kế từ phương pháp thực tế, giữ population, model và validation scope |
| Kiểm tra phát biểu | [paper-to-claim-verifier](https://github.com/aipoch/medical-research-skills/blob/686e09dfdb45d9fa1a08664f06bb93769b3c9d91/awesome-med-research-skills/Evidence%20Insight/paper-to-claim-verifier/SKILL.md) | Đối chiếu từng phần của claim với nghiên cứu gốc và phát hiện citation drift |
| Đọc các kết quả khác nhau | [contradictory-findings-resolver](https://github.com/aipoch/medical-research-skills/blob/686e09dfdb45d9fa1a08664f06bb93769b3c9d91/awesome-med-research-skills/Evidence%20Insight/contradictory-findings-resolver/SKILL.md) | Kiểm tra khác biệt về quần thể, endpoint, thiết kế và phương pháp trước khi kết luận mâu thuẫn |
| Điều chỉnh mức khẳng định | [claim-strength-calibrator](https://github.com/aipoch/medical-research-skills/blob/686e09dfdb45d9fa1a08664f06bb93769b3c9d91/awesome-med-research-skills/Academic%20Writing/claim-strength-calibrator/SKILL.md) | Chọn cách diễn đạt phù hợp mức bằng chứng; giữ khác biệt giữa tương quan, cơ chế và ứng dụng lâm sàng |
| Kiểm tra trích dẫn | [reference-integrity-checker](https://github.com/aipoch/medical-research-skills/blob/686e09dfdb45d9fa1a08664f06bb93769b3c9d91/awesome-med-research-skills/Academic%20Writing/reference-integrity-checker/SKILL.md) | Kiểm tra claim–citation và phạm vi nguồn; không chỉ định dạng danh mục tài liệu |
| Biên tập tiếng Anh y khoa | [medical-english-precision-editor](https://github.com/aipoch/medical-research-skills/blob/686e09dfdb45d9fa1a08664f06bb93769b3c9d91/awesome-med-research-skills/Academic%20Writing/medical-english-precision-editor/SKILL.md) | Cải thiện thuật ngữ và câu văn, bảo toàn ý nghĩa và mức bằng chứng |
| Giải thích dễ hiểu | [lay-summary-for-cross-disciplinary-teams](https://github.com/aipoch/medical-research-skills/blob/686e09dfdb45d9fa1a08664f06bb93769b3c9d91/awesome-med-research-skills/Academic%20Writing/lay-summary-for-cross-disciplinary-teams/SKILL.md) | Giải thích viết tắt, mục tiêu, kết quả và giới hạn cho người đọc khác chuyên môn; cần điều chỉnh template cho hội thoại |

Tên/path chính xác, permalink và SHA-256 của từng `SKILL.md` được ghi trong lock
file. Khi triển khai, cần đọc cả modules/assets mà skill yêu cầu; không chỉ lấy
frontmatter hoặc chép riêng đoạn giới thiệu vào prompt.

## Nội dung và cách hiển thị

Skill định hướng cách lập kế hoạch, dùng bằng chứng và viết câu trả lời. Với Bloop,
profile cần giữ tiếng Việt hoặc tiếng Anh theo câu hỏi; tên dược liệu và thuật ngữ
có dấu được bảo toàn. Cần chỉnh các template viết manuscript sang câu trả lời
ngắn phù hợp hội thoại trước khi đưa vào runtime.

Cách phát text qua mạng và hiệu ứng tạo chữ nằm ở code:

| Phần | Code hiện tại |
| --- | --- |
| Chốt đáp án trước khi gửi SSE | [`main.py`](../backend/main.py), hàm `chat` / `stream` |
| Tích lũy SSE, render Markdown và hiện chữ | [`app.js`](../frontend/app.js), `consume` / `revealReply` |
| Giới hạn bằng chứng, budget và kiểm chứng | [`harness.py`](../backend/harness.py) |

Hiện server gửi đáp án hoàn chỉnh sau answer gate; frontend tạo hiệu ứng hiện
từng grapheme hoặc word sau event `done`. Clone thư viện skill chưa thay đổi hành
vi này. Phần hướng dẫn viết cần chạy trước verification, để JEV kiểm tra chính
nội dung cuối cùng sẽ được hiển thị.

## Khôi phục clone theo phiên bản đã chọn

Chạy từ thư mục gốc dự án khi clone local chưa tồn tại:

```sh
git clone --no-checkout --depth 1 https://github.com/aipoch/medical-research-skills.git web/references/medical-research-skills
git -C web/references/medical-research-skills fetch --depth 1 origin 686e09dfdb45d9fa1a08664f06bb93769b3c9d91
git -C web/references/medical-research-skills checkout --detach 686e09dfdb45d9fa1a08664f06bb93769b3c9d91
```

Clone chỉ tải nguồn. Chưa cài dependency, chạy script nghiên cứu hay gọi dịch vụ
ngoài từ repo này.
