# Medical research skills cho Bloop

Đã clone [AIPOCH Medical Research Skills](https://github.com/aipoch/medical-research-skills)
vào `medical-research-skills/`, giữ nguyên `SKILL.md`, modules tham chiếu, assets
và giấy phép MIT của upstream. Commit và SHA-256 của các skill được chọn nằm trong
[`medical-research-skills.lock.json`](medical-research-skills.lock.json).

Backend đã nạp tám profile hội thoại được điều chỉnh từ các skill này trong
[`backend/skills`](../backend/skills/NOTICE.md). Package chứa profile, bản Markdown
gốc, modules Markdown và giấy phép; chạy ứng dụng không cần clone tham khảo.
Clone local được ignore. Các liên kết dưới đây trỏ tới đúng commit đã chọn.

## Nhóm skill phù hợp

| Tác vụ trong Bloop | Skill upstream | Hướng dẫn được điều chỉnh cho Bloop |
| --- | --- | --- |
| Lập kế hoạch tìm tài liệu | [biomedical-search-strategy-builder](https://github.com/aipoch/medical-research-skills/blob/686e09dfdb45d9fa1a08664f06bb93769b3c9d91/awesome-med-research-skills/Evidence%20Insight/biomedical-search-strategy-builder/SKILL.md) | Tách nhu cầu bằng chứng, tạo truy vấn VI/EN giữ tên gốc và giới hạn nguồn; dùng free-text phù hợp retrieval hiện tại |
| Đọc và phân loại nghiên cứu | [study-design-identifier](https://github.com/aipoch/medical-research-skills/blob/686e09dfdb45d9fa1a08664f06bb93769b3c9d91/awesome-med-research-skills/Evidence%20Insight/study-design-identifier/SKILL.md) | Xác định thiết kế từ phương pháp thực tế, giữ population, model và validation scope |
| Kiểm tra phát biểu | [paper-to-claim-verifier](https://github.com/aipoch/medical-research-skills/blob/686e09dfdb45d9fa1a08664f06bb93769b3c9d91/awesome-med-research-skills/Evidence%20Insight/paper-to-claim-verifier/SKILL.md) | Đối chiếu từng phần của claim với nghiên cứu gốc và phát hiện citation drift |
| Đọc các kết quả khác nhau | [contradictory-findings-resolver](https://github.com/aipoch/medical-research-skills/blob/686e09dfdb45d9fa1a08664f06bb93769b3c9d91/awesome-med-research-skills/Evidence%20Insight/contradictory-findings-resolver/SKILL.md) | Kiểm tra khác biệt về quần thể, endpoint, thiết kế và phương pháp trước khi kết luận mâu thuẫn |
| Điều chỉnh mức khẳng định | [claim-strength-calibrator](https://github.com/aipoch/medical-research-skills/blob/686e09dfdb45d9fa1a08664f06bb93769b3c9d91/awesome-med-research-skills/Academic%20Writing/claim-strength-calibrator/SKILL.md) | Chọn cách diễn đạt phù hợp mức bằng chứng; giữ khác biệt giữa tương quan, cơ chế và ứng dụng lâm sàng |
| Kiểm tra trích dẫn | [reference-integrity-checker](https://github.com/aipoch/medical-research-skills/blob/686e09dfdb45d9fa1a08664f06bb93769b3c9d91/awesome-med-research-skills/Academic%20Writing/reference-integrity-checker/SKILL.md) | Kiểm tra claim–citation và phạm vi nguồn; không chỉ định dạng danh mục tài liệu |
| Biên tập tiếng Anh y khoa | [medical-english-precision-editor](https://github.com/aipoch/medical-research-skills/blob/686e09dfdb45d9fa1a08664f06bb93769b3c9d91/awesome-med-research-skills/Academic%20Writing/medical-english-precision-editor/SKILL.md) | Cải thiện thuật ngữ và câu văn, bảo toàn ý nghĩa và mức bằng chứng |
| Giải thích dễ hiểu | [lay-summary-for-cross-disciplinary-teams](https://github.com/aipoch/medical-research-skills/blob/686e09dfdb45d9fa1a08664f06bb93769b3c9d91/awesome-med-research-skills/Academic%20Writing/lay-summary-for-cross-disciplinary-teams/SKILL.md) | Trả lời trực tiếp bằng ngôn ngữ người dùng; giải thích thuật ngữ có nguồn, giữ tên có dấu và không ép template báo cáo |

Tên/path chính xác, permalink và SHA-256 của upstream được ghi trong lock file.
Manifest của package runtime lưu riêng các file Markdown đã vendoring và hash.
Profile hội thoại tự chứa; bản upstream đầy đủ được giữ để đối chiếu.

## Nội dung và cách hiển thị

Planner luôn dùng skill tìm tài liệu. Mỗi draft dùng kiểm tra claim, mức khẳng định
và trích dẫn; thêm study design khi câu hỏi/bằng chứng liên quan nghiên cứu, thêm
conflict resolver khi có dấu hiệu mâu thuẫn. Tiếng Anh dùng precision editor;
tiếng Việt dùng plain language profile. Tên dược liệu và thuật ngữ có dấu được giữ.

[`medical_skills.py`](../backend/medical_skills.py) chọn profile bằng quy tắc local,
không thêm API call. Hướng dẫn được tính vào input budget; không mở rộng source
masks hoặc quyền truy cập. Health trả `skill_profile`; kết quả chat và trace lưu
`skills` gồm phiên bản, fingerprint và IDs theo từng bước/vòng.

Cách phát text qua mạng và hiệu ứng tạo chữ nằm ở code:

| Phần | Code hiện tại |
| --- | --- |
| Chốt đáp án trước khi gửi SSE | [`main.py`](../backend/main.py), hàm `chat` / `stream` |
| Tích lũy SSE, render Markdown và hiện chữ | [`app.js`](../frontend/app.js), `consume` / `revealReply` |
| Giới hạn bằng chứng, budget và kiểm chứng | [`harness.py`](../backend/harness.py) |

Server gửi đáp án hoàn chỉnh sau answer gate; frontend tạo hiệu ứng hiện từng
grapheme hoặc word sau event `done`. Hướng dẫn viết chạy trước verification,
để JEV kiểm tra chính nội dung cuối cùng sẽ được hiển thị.

## Khôi phục clone tham khảo theo phiên bản đã chọn

Chạy từ thư mục gốc dự án khi clone local chưa tồn tại:

```sh
git clone --no-checkout --depth 1 https://github.com/aipoch/medical-research-skills.git web/references/medical-research-skills
git -C web/references/medical-research-skills fetch --depth 1 origin 686e09dfdb45d9fa1a08664f06bb93769b3c9d91
git -C web/references/medical-research-skills checkout --detach 686e09dfdb45d9fa1a08664f06bb93769b3c9d91
```

Clone chỉ tải nguồn để nghiên cứu hoặc cập nhật profile; runtime dùng package
trong backend. Package không chạy script hoặc cài dependency của upstream.
