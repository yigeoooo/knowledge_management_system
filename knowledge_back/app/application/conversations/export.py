"""Export an entire conversation snapshot as a readable, editable Word document."""

import re
from datetime import UTC, datetime
from io import BytesIO
from zoneinfo import ZoneInfo

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor
from lxml import etree

from ...core.extensions import db
from ...entities import QALog, now
from ...processors.pdf import readable_answer
from ...processors.word.markdown_export import append_markdown, clean_text, shade
from . import service as svc

DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
WORD_2013_NS = "http://schemas.microsoft.com/office/word/2012/wordml"
COMPATIBILITY_NS = "http://schemas.openxmlformats.org/markup-compatibility/2006"
STATUSES = {
    "PENDING": "等待回答",
    "PROCESSING": "回答中",
    "SUCCESS": "已回答",
    "PARTIAL": "部分回答",
    "NO_EVIDENCE": "资料不足",
    "SOURCES_ONLY": "仅有相关资料",
    "FAILED": "回答失败",
    "CANCELLED": "已取消",
}


def _time(value):
    if not value:
        return "—"
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M:%S")


def _document():
    document = Document()
    # Word's saved heading-collapse state is a Word 2013 extension. Older readers
    # may ignore it while keeping all citation content readable.
    root = document.element
    etree.cleanup_namespaces(
        root,
        top_nsmap={"w15": WORD_2013_NS},
        keep_ns_prefixes=[prefix for prefix in root.nsmap if prefix] + ["w15"],
    )
    ignorable = root.get(f"{{{COMPATIBILITY_NS}}}Ignorable", "").split()
    if "w15" not in ignorable:
        ignorable.append("w15")
    root.set(f"{{{COMPATIBILITY_NS}}}Ignorable", " ".join(ignorable))
    compat = document.settings.element.find(qn("w:compat"))
    if compat is None:
        compat = OxmlElement("w:compat")
        document.settings.element.append(compat)
    mode = next(
        (
            item
            for item in compat.findall(qn("w:compatSetting"))
            if item.get(qn("w:name")) == "compatibilityMode"
        ),
        None,
    )
    if mode is None:
        mode = OxmlElement("w:compatSetting")
        compat.append(mode)
    mode.set(qn("w:name"), "compatibilityMode")
    mode.set(qn("w:uri"), "http://schemas.microsoft.com/office/word")
    mode.set(qn("w:val"), "15")
    section = document.sections[0]
    section.page_width, section.page_height = Cm(21), Cm(29.7)
    section.top_margin = section.bottom_margin = Cm(2)
    section.left_margin = section.right_margin = Cm(2.2)
    normal = document.styles["Normal"]
    normal.font.name, normal.font.size = "Calibri", Pt(11)
    normal.element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"), "宋体")
    normal.paragraph_format.line_spacing = 1.3
    normal.paragraph_format.space_after = Pt(7)
    for name, size in [
        ("Title", 24),
        ("Subtitle", 11),
        ("Heading 1", 16),
        ("Heading 2", 12),
        ("Heading 3", 11),
        ("Heading 4", 11),
        ("Heading 5", 11),
        ("Heading 6", 11),
    ]:
        style = document.styles[name]
        style.font.name, style.font.size = "Calibri", Pt(size)
        style.font.color.rgb = RGBColor.from_string("233044")
        style.element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"), "微软雅黑")
        style.paragraph_format.keep_with_next = True
    header = section.header.paragraphs[0]
    run = header.add_run("DEXFORCE  /  知识问答记录")
    run.font.size, run.font.color.rgb = Pt(9), RGBColor.from_string("8391A3")
    footer = section.footer.paragraphs[0]
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    footer.add_run("会话导出 · 第 ")
    for field, suffix in [("PAGE", " 页 / 共 "), ("NUMPAGES", " 页")]:
        node = OxmlElement("w:fldSimple")
        node.set(qn("w:instr"), field)
        footer._p.append(node)
        footer.add_run(suffix)
    for run in footer.runs:
        run.font.size, run.font.color.rgb = Pt(9), RGBColor.from_string("8391A3")
    document.core_properties.author = "DEXFORCE 知识平台"
    return document


def render_conversation(metadata, turns, exported_at):
    document = _document()
    title = clean_text(metadata["title"])
    document.core_properties.title = title
    document.add_heading(title, level=0)
    document.add_paragraph("知识问答 · 完整会话记录", style="Subtitle")
    state = "已软删除（审计保留）" if metadata["deleted_at"] else "正常"
    if metadata["closed_at"]:
        state += " / 已关闭"
    table = document.add_table(rows=0, cols=2)
    table.style = "Light Shading Accent 1"
    for label, value in [
        ("用户 / 机器人", metadata["owner_name"]),
        ("来源", "机器人" if metadata["source_type"] == "ROBOT" else "网页用户"),
        ("知识库", metadata["knowledge_base_name"]),
        ("会话状态", state),
        ("创建时间", _time(metadata["created_at"])),
        ("最后提问", _time(metadata["last_message_at"])),
        ("导出时间", _time(exported_at)),
        ("问答轮数", str(len(turns))),
    ]:
        cells = table.add_row().cells
        cells[0].text, cells[1].text = label, clean_text(value)
        cells[0].width, cells[1].width = Cm(3), Cm(13.6)
    note = document.add_paragraph(
        f"会话编号：{metadata['id']}\n时间统一为北京时间。内容为导出时的历史快照。"
    )
    for run in note.runs:
        run.font.size, run.font.color.rgb = Pt(9), RGBColor.from_string("64748B")
    if not turns:
        document.add_paragraph("该会话暂无问答记录。")
    for turn in turns:
        document.add_heading(f"第 {turn['turn_no']} 轮", level=1)
        status = STATUSES.get(turn["status"], turn["status"])
        if turn.get("answer_kind") == "clarification":
            status += " · 澄清提问"
        paragraph = document.add_paragraph(f"{_time(turn['created_at'])}  ·  {status}")
        for run in paragraph.runs:
            run.font.size, run.font.color.rgb = Pt(9), RGBColor.from_string("64748B")
        document.add_heading("提问", level=2)
        question = document.add_paragraph(clean_text(turn["question"]))
        shade(question._p.get_or_add_pPr(), "F4F6F8")
        document.add_heading("回答", level=2)
        if turn.get("answer"):
            append_markdown(document, turn["answer"])
        elif turn["status"] in svc.INFLIGHT:
            document.add_paragraph("本轮回答尚未完成，导出的是当前状态。")
        else:
            document.add_paragraph("本轮暂无答案。")
        for label, text in [
            ("处理说明", turn.get("error_message")),
            ("上下文提示", turn.get("context_notice")),
        ]:
            if text:
                document.add_paragraph(f"{label}：{clean_text(text)}")
        audit = document.add_paragraph(f"请求编号：{turn['request_id']}")
        for run in audit.runs:
            run.font.size, run.font.color.rgb = Pt(8), RGBColor.from_string("8391A3")
        sources = turn.get("sources") or []
        if sources:
            heading = document.add_heading("引用资料", level=2)
            properties = heading._p.get_or_add_pPr()
            outline = OxmlElement("w:outlineLvl")
            outline.set(qn("w:val"), "1")  # Level 2; the next turn's level 1 ends this section.
            properties.append(outline)
            properties.append(etree.Element(f"{{{WORD_2013_NS}}}collapsed"))
            for index, source in enumerate(sources, start=1):
                label = source.get("source_id") or str(index)
                heading = document.add_paragraph()
                heading.paragraph_format.keep_with_next = True
                heading.add_run(
                    f"[{label}] {clean_text(source.get('document_title') or source.get('filename') or '引用资料')}"
                ).bold = True
                location = " · ".join(
                    clean_text(value)
                    for value in [
                        source.get("filename"),
                        f"v{source['version_no']}" if source.get("version_no") else None,
                        source.get("heading_path"),
                    ]
                    if value
                )
                if location:
                    document.add_paragraph(location)
                if source.get("content"):
                    paragraph = document.add_paragraph(clean_text(source["content"]))
                    for run in paragraph.runs:
                        run.font.size, run.font.color.rgb = Pt(9), RGBColor.from_string("475569")
                elif source.get("modality") in {"image", "video"}:
                    document.add_paragraph("图片 / 视频来源，请在系统中查看原文件。")
    output = BytesIO()
    document.save(output)
    return output.getvalue()


def export_conversation(conversation_id):
    conversation = svc.get_conversation(conversation_id, admin=True)
    metadata = svc.conversation_data(conversation)
    turns = []
    # Capture all submitted turns, independent of the frontend's message pagination.
    for log in db.session.scalars(
        db.select(QALog)
        .where(
            QALog.conversation_id == conversation.id,
            QALog.turn_no < conversation.next_turn_no,
        )
        .order_by(QALog.turn_no)
    ):
        turns.append(
            {
                "turn_no": log.turn_no,
                "question": log.question,
                "answer": readable_answer(log.answer, log.sources or []) if log.answer else None,
                "status": log.status,
                "answer_kind": log.answer_kind,
                "sources": log.sources or [],
                "error_message": log.error_message,
                "context_notice": (log.context_snapshot or {}).get("notice"),
                "request_id": log.request_id,
                "created_at": log.created_at,
            }
        )
    db.session.rollback()
    exported_at = now()
    safe_title = (
        re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", clean_text(metadata["title"]))[:40].strip(" .")
        or "历史会话"
    )
    filename = f"会话记录_{safe_title}_{exported_at.astimezone(ZoneInfo('Asia/Shanghai')):%Y%m%d_%H%M}.docx"
    return render_conversation(metadata, turns, exported_at), filename
