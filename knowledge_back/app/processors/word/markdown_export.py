"""Render answer Markdown into editable Word paragraphs and tables, without fetching assets."""

from urllib.parse import urlparse

from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor
from markdown_it import MarkdownIt

_MARKDOWN = MarkdownIt("commonmark", {"html": False}).enable(["table", "strikethrough"])


def clean_text(value):
    return "".join(
        char
        for char in str(value or "")
        if char in "\n\r\t"
        or 0x20 <= ord(char) <= 0xD7FF
        or 0xE000 <= ord(char) <= 0xFFFD
        or 0x10000 <= ord(char) <= 0x10FFFF
    )


def shade(element, fill):
    node = OxmlElement("w:shd")
    node.set(qn("w:fill"), fill)
    element.append(node)


def _inline(paragraph, tokens):
    marks, links = set(), []
    for token in tokens or []:
        if token.type in {"strong_open", "em_open", "s_open"}:
            marks.add(token.type.split("_")[0])
        elif token.type in {"strong_close", "em_close", "s_close"}:
            marks.discard(token.type.split("_")[0])
        elif token.type == "link_open":
            links.append(token.attrGet("href") or "")
        elif token.type == "link_close":
            url = links.pop() if links else ""
            try:
                scheme = urlparse(url).scheme.lower()
            except ValueError:
                scheme = ""
            if scheme in {"http", "https", "mailto"}:
                paragraph.add_run(f"（{clean_text(url)}）")
        elif token.type in {"softbreak", "hardbreak"}:
            paragraph.add_run().add_break()
        elif token.type == "image":
            paragraph.add_run(f"[图片：{clean_text(token.content) or '见原会话'}]")
        elif token.type in {"text", "code_inline", "html_inline"}:
            run = paragraph.add_run(clean_text(token.content))
            run.bold, run.italic, run.font.strike = "strong" in marks, "em" in marks, "s" in marks
            if token.type == "code_inline":
                run.font.name = "Consolas"
                run.font.size = Pt(10)
                shade(run._r.get_or_add_rPr(), "F1F3F5")


def _table(document, tokens):
    rows, row = [], None
    for token in tokens:
        if token.type == "tr_open":
            row = []
            rows.append(row)
        elif token.type == "inline" and row is not None:
            row.append(token.children or [])
    if not rows:
        return
    table = document.add_table(rows=0, cols=max(len(row) for row in rows))
    table.style = "Table Grid"
    for index, cells in enumerate(rows):
        target = table.add_row()
        if index == 0:
            repeat = OxmlElement("w:tblHeader")
            target._tr.get_or_add_trPr().append(repeat)
        for cell, content in zip(target.cells, cells, strict=False):
            paragraph = cell.paragraphs[0]
            paragraph.paragraph_format.space_after = Pt(5)
            _inline(paragraph, content)
            for run in paragraph.runs:
                run.font.size = Pt(9)
                if index == 0:
                    run.bold = True
            if index == 0:
                shade(cell._tc.get_or_add_tcPr(), "EDF2F7")


def append_markdown(document, text):
    tokens = _MARKDOWN.parse(clean_text(text))
    lists, quote_depth, marker, paragraph = [], 0, None, None
    index = 0
    while index < len(tokens):
        token = tokens[index]
        kind = token.type
        if kind == "table_open":
            end = next(i for i in range(index + 1, len(tokens)) if tokens[i].type == "table_close")
            _table(document, tokens[index + 1 : end])
            index = end
        elif kind in {"bullet_list_open", "ordered_list_open"}:
            lists.append(int(token.attrGet("start") or 1) if kind == "ordered_list_open" else None)
        elif kind in {"bullet_list_close", "ordered_list_close"}:
            lists.pop()
        elif kind == "list_item_open":
            marker = f"{lists[-1]}. " if lists[-1] is not None else "• "
            if lists[-1] is not None:
                lists[-1] += 1
        elif kind == "list_item_close":
            marker = None
        elif kind == "blockquote_open":
            quote_depth += 1
        elif kind == "blockquote_close":
            quote_depth -= 1
        elif kind in {"paragraph_open", "heading_open"}:
            style = (
                f"Heading {min(6, int(token.tag[1:]) + 2)}" if kind == "heading_open" else "Normal"
            )
            paragraph = document.add_paragraph(style=style)
            paragraph.paragraph_format.left_indent = Cm(0.45 * (len(lists) + quote_depth))
            if marker:
                paragraph.add_run(marker)
                marker = None
            if quote_depth:
                shade(paragraph._p.get_or_add_pPr(), "F5F7FA")
        elif kind == "inline" and paragraph is not None:
            _inline(paragraph, token.children)
        elif kind in {"fence", "code_block"}:
            paragraph = document.add_paragraph()
            paragraph.paragraph_format.line_spacing = 1
            paragraph.paragraph_format.left_indent = Cm(0.4)
            shade(paragraph._p.get_or_add_pPr(), "F4F5F7")
            run = paragraph.add_run(clean_text(token.content).rstrip("\n"))
            run.font.name, run.font.size = "Consolas", Pt(9)
        elif kind == "hr":
            run = document.add_paragraph().add_run("────────────────────────")
            run.font.color.rgb = RGBColor.from_string("CBD5E1")
        index += 1
