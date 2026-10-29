"""Bounded visual specs reference answer sections, never executable model code."""
import math
import re
import unicodedata

MAX_SECTIONS = 20
MAX_STEPS = 12
PROCESS_INTENT = re.compile(r"các bước|cac buoc|quy trình|quy trinh|từng bước|tung buoc|"
                            r"\b(?:steps?|procedure|process|step.by.step)\b", re.I)
STEP_MARKER = re.compile(r"(?<!\w)(?:\*{1,2})?(?:Bước|Step)\s+(\d{1,2})\s*[:.)-](?:\*{1,2})?\s*", re.I)
NOTE_MARKER = re.compile(r"(?:\s|^)(?:\*{1,2})?(?:Chú ý|Lưu ý|Notes?|Caution)\s*:", re.I)


def is_process_question(question):
    return bool(PROCESS_INTENT.search(unicodedata.normalize("NFC", question)))


def normalize_step_draft(result, question, visual_enabled=False):
    """Split an explicit ordered series before verification, without rewriting it.

    Preserve the introduction, qualifiers, trailing notes and citation IDs. Never
    guess a sequence from unnumbered prose, missing numbers, or alternative runs.
    """
    if not is_process_question(question) or not isinstance(result.get("sections"), list):
        return result
    runs, separate = [], []
    for index, section in enumerate(result["sections"]):
        if not isinstance(section, dict) or not isinstance(section.get("text"), str):
            return result
        matches = list(STEP_MARKER.finditer(section["text"]))
        if len(matches) == 1 and not section["text"][:matches[0].start()].strip():
            separate.append((index, int(matches[0][1])))
        if len(matches) >= 2:
            if not 2 <= len(matches) <= MAX_STEPS or [int(m[1]) for m in matches] != list(range(1, len(matches) + 1)):
                return result
            runs.append((index, matches))
    if not runs and visual_enabled and 2 <= len(separate) <= MAX_STEPS:
        refs = [index for index, number in separate]
        if ([number for index, number in separate] == list(range(1, len(separate) + 1))
                and refs == list(range(refs[0], refs[-1] + 1))):
            spec = {"kind": "steps", "sections": refs}
            return result if result.get("visualization") == spec else {**result, "visualization": spec}
    if len(runs) != 1:
        return result
    source_index, matches = runs[0]
    original = result["sections"][source_index]
    text = original["text"]
    sections, refs = list(result["sections"][:source_index]), []
    if prefix := text[:matches[0].start()].strip():
        sections.append({**original, "text": prefix})
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        fragment = text[match.start():end].strip()
        note = NOTE_MARKER.search(fragment) if index == len(matches) - 1 else None
        if note:
            fragment, tail = fragment[:note.start()].strip(), fragment[note.start():].strip()
        if not STEP_MARKER.sub("", fragment, count=1).strip():
            return result
        refs.append(len(sections))
        sections.append({**original, "text": fragment})
        if note:
            sections.append({**original, "text": tail})
    sections.extend(result["sections"][source_index + 1:])
    if len(sections) > MAX_SECTIONS:
        return result
    updated = {**result, "sections": sections}
    if visual_enabled:
        updated["visualization"] = {"kind": "steps", "sections": refs}
    return updated


def answer_markdown(sections, visual=None):
    """Keep text readable even if a visual is absent or independently rejected."""
    refs = visual["sections"] if visual and visual["kind"] == "steps" else []
    paragraphs = []
    for index, section in enumerate(sections):
        text = section["text"].strip()
        matches = list(STEP_MARKER.finditer(text))
        # Legacy/model-packed steps still get paragraph breaks without changing
        # their claims or inventing a new sequence.
        if len(matches) >= 2:
            for match in reversed(matches):
                text = text[:match.start()].rstrip() + "\n\n" + text[match.start():]
            text = text.strip()
        if index in refs and not STEP_MARKER.match(text):
            text = f"{refs.index(index) + 1}. {text}"
        citations = " ".join(f"[{n}](#cite-{n})" for n in dict.fromkeys(section["citations"]))
        paragraphs.append(text + " " + citations)
    return "\n\n".join(paragraphs)

VISUAL_INSTRUCTIONS = """VISUAL RESPONSE CONTRACT (visualise skill selected):
The user asked for or benefits from a visual. Include the visualization field in your JSON.
For comparisons, make ONE separate atomic section for EACH item/group: do not combine all groups in one section.
For a bar chart, section i must describe ONLY the group represented by value i, stating that group's own value and unit.
Do not use a combined summary, a computed difference, a total, or an arithmetic comparison as an individual group's section.
For a process, make one section per supported step, preserving order. Use 2–12 steps when evidence allows; never truncate a protocol to six steps.
Choose bar for directly comparable source numbers, cards for qualitative comparisons, steps for an ordered process.
Choose checklist for practical measures, tips or options that can be numbered for reading but have no required order.
For a checklist, create 2–6 separate sections, ONE action per section; never put a numbered list inside one section.
Never invent arrows, causality or a required sequence between independent prevention measures.
Reference each visual item exactly once by its zero-based section index. Cards and bars include all sections.
Steps/checklists may leave general context or notes outside the referenced items; the host displays these separately.
Keep the referenced actions contiguous, with context before them and general notes after them.
A bar needs values in that same order and a unit. Use at most 20 answer sections including notes.
For example, two qualitative sections allow visualization={"kind":"cards","sections":[0,1]}.
For bars, take every value from its corresponding group's actual source evidence, never from schema examples.
Set visualization=null only if evidence is insufficient, there is just one supported item, or the formats do not fit.
Với câu hỏi về CÁC BƯỚC hay QUY TRÌNH: dùng kind="steps", mỗi bước một section, không dùng checklist.
Không tóm tắt cả quy trình trong một section. Không trộn thời điểm/chỉ định thực hiện với các thao tác.
Giữ nguyên thứ tự, điều kiện và mọi bước cần thiết của MỘT quy trình trong nguồn, không trộn các phiên bản khác nhau.
Ghi chú chung có section riêng và không nằm trong visualization.sections; không lặp lại ghi chú.
Giữ riêng từng nhóm trong sections; khi đủ dữ liệu, bắt buộc thêm visualization đúng schema, không chỉ kể lại số liệu.
Với câu hỏi về các biện pháp/cách thực hiện: chọn 2–6 hành động được nguồn nêu rõ.
Mỗi phần tử sections chỉ viết MỘT hành động ngắn cùng citations; KHÔNG gộp cả danh sách vào một đoạn.
Sau đó thêm visualization={"kind":"checklist","sections":[0,1]} nếu có hai hành động;
nếu có nhiều hơn thì điền đủ chỉ số tương ứng. Không chép ví dụ này làm nội dung trả lời.
Không dẫn nhập bằng tên cơ quan, tên bài viết hay URL. Không biến khuyến cáo cũ hoặc quảng cáo sản phẩm thành hướng dẫn hiện hành.
Với biểu đồ cột: mỗi section chỉ nêu số liệu của MỘT nhóm. Không gộp hai nhóm vào một section;
không thêm section tính chênh lệch, tổng hay phép trừ. Mỗi giá trị cột phải khớp đúng nhóm trong section tương ứng.
Viết đơn vị bằng ngôn ngữ trả lời và giữ đúng ý nghĩa, không chép đơn vị tiếng Anh từ ví dụ khi trả lời tiếng Việt.
"""


VISUAL_SCHEMA = {"anyOf": [{"type": "null"}, {"type": "object", "properties": {
    "kind": {"type": "string", "enum": ["cards", "steps", "bar", "checklist"]},
    "sections": {"type": "array", "minItems": 2, "maxItems": MAX_STEPS,
                 "items": {"type": "integer", "minimum": 0, "maximum": MAX_SECTIONS - 1}},
    "values": {"type": "array", "minItems": 2, "maxItems": 6,
               "items": {"type": "number", "minimum": 0}},
    "unit": {"type": "string"}}, "required": ["kind", "sections"], "additionalProperties": False}]}


def normalize_visual(value, sections):
    if (not isinstance(value, dict) or not isinstance(value.get("kind"), str)
            or value["kind"] not in {"cards", "steps", "bar", "checklist"}):
        return None
    refs = value.get("sections")
    process = value["kind"] in {"steps", "checklist"}
    if (not isinstance(refs, list) or not 2 <= len(sections) <= MAX_SECTIONS
            or not 2 <= len(refs) <= (MAX_STEPS if process else 6)
            or any(type(ref) is not int or not 0 <= ref < len(sections) for ref in refs)
            or len(set(refs)) != len(refs)
            or (not process and set(refs) != set(range(len(sections))))
            or (process and refs != list(range(refs[0], refs[-1] + 1)))):
        return None
    result = {"kind": value["kind"], "sections": refs}
    if value["kind"] == "bar":
        values, unit = value.get("values"), value.get("unit")
        if (not isinstance(values, list) or len(values) != len(refs)
                or any(type(number) not in (int, float) or not math.isfinite(number) or number < 0 for number in values)
                or not isinstance(unit, str) or len(unit) > 60):
            return None
        result.update(values=values, unit=unit)
    return result


def public_visual(spec, sections, language):
    if spec is None:
        return None
    # All wording and citations come from verified sections; model-supplied
    # markup, titles, labels and other unverified fields are never exposed.
    items = [{"text": sections[index]["text"], "citations": sections[index]["citations"]}
             for index in spec["sections"]]
    result = {"kind": spec["kind"], "items": items, "language": language}
    unused = [i for i in range(len(sections)) if i not in spec["sections"]]
    if unused:
        clean = lambda i: {"text": sections[i]["text"], "citations": sections[i]["citations"]}
        result["context"] = [clean(i) for i in unused if i < spec["sections"][0]]
        result["notes"] = [clean(i) for i in unused if i >= spec["sections"][0]]
    if spec["kind"] == "bar":
        result.update(values=spec["values"], unit=spec["unit"])
    return result
