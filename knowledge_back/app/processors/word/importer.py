"""Read editable DOCX content, retaining a lossless editor snapshot in our exports."""

import hashlib
import json
import re
from io import BytesIO
from zipfile import BadZipFile, ZipFile

from docx import Document
from docx.enum.section import WD_ORIENT
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docx.opc.packuri import PackURI
from docx.opc.part import Part
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.hyperlink import Hyperlink
from lxml import etree

from ...core.http import ApiError
from .styles import ALIGNMENTS

SNAPSHOT = "/customXml/kbs-editor.xml"
HIGHLIGHTS = {
    "yellow": "#ffff00",
    "green": "#00ff00",
    "cyan": "#00ffff",
    "magenta": "#ff00ff",
    "blue": "#0000ff",
    "red": "#ff0000",
    "darkBlue": "#000080",
    "darkCyan": "#008080",
    "darkGreen": "#008000",
    "darkMagenta": "#800080",
    "darkRed": "#800000",
    "darkYellow": "#808000",
    "darkGray": "#808080",
    "lightGray": "#c0c0c0",
    "black": "#000000",
}
LIST_TYPES = {
    "decimal": "decimal",
    "decimalZero": "decimal-leading-zero",
    "lowerLetter": "lower-alpha",
    "upperLetter": "upper-alpha",
    "lowerRoman": "lower-roman",
    "upperRoman": "upper-roman",
    "chineseCounting": "cjk-ideographic",
    "chineseCountingThousand": "trad-chinese-informal",
    "chineseLegalSimplified": "simp-chinese-formal",
}


def unsupported(feature):
    raise ApiError(f"该 Word 含{feature}，暂不能在线编辑；请下载修改后上传新版本", 422, 42202)


def load_word(content):
    try:
        with ZipFile(BytesIO(content)) as archive:
            if (
                len(archive.infolist()) > 3000
                or sum(i.file_size for i in archive.infolist()) > 80_000_000
            ):
                raise ValueError("DOCX too large")
        return Document(BytesIO(content))
    except (BadZipFile, ValueError, KeyError, etree.XMLSyntaxError, OSError) as error:
        raise ApiError("Word 文件无法解析，请确认是有效的 DOCX 文件", 422, 42202) from error


def _fingerprint(document):
    # External Word edits invalidate our snapshot, including style/numbering edits.
    values = [
        document.element.xml,
        document.styles.element.xml,
        document.part.numbering_part.element.xml,
    ]
    return hashlib.sha256("\n".join(values).encode()).hexdigest()


def save_snapshot(document, content):
    root = etree.Element("kbs-editor", version="1", fingerprint=_fingerprint(document))
    root.text = json.dumps(content, ensure_ascii=False, separators=(",", ":"))
    blob = etree.tostring(root, encoding="UTF-8", xml_declaration=True)
    for relation in document.part.rels.values():
        if not relation.is_external and str(relation.target_part.partname) == SNAPSHOT:
            relation.target_part._blob = blob
            return
    document.part.relate_to(
        Part(PackURI(SNAPSHOT), "application/xml", blob, document.part.package), RT.CUSTOM_XML
    )


def _snapshot(document):
    for relation in document.part.rels.values():
        if relation.is_external or str(relation.target_part.partname) != SNAPSHOT:
            continue
        try:
            root = etree.fromstring(
                relation.target_part.blob, etree.XMLParser(resolve_entities=False, no_network=True)
            )
            if root.get("version") == "1" and root.get("fingerprint") == _fingerprint(document):
                return json.loads(root.text)
        except (ValueError, TypeError, etree.XMLSyntaxError):
            pass
    return None


def style_chain(style):
    seen = set()
    while style is not None and style.style_id not in seen:
        seen.add(style.style_id)
        yield style
        style = style.base_style


def _rprops(run, paragraph):
    props = [run._r.rPr]
    props.extend(s.element.rPr for s in style_chain(run.style))
    props.extend(s.element.rPr for s in style_chain(paragraph.style))
    defaults = paragraph.part.document.styles.element.find(qn("w:docDefaults"))
    if defaults is not None:
        defaults = defaults.find(qn("w:rPrDefault"))
        if defaults is not None:
            props.append(defaults.find(qn("w:rPr")))
    return [p for p in props if p is not None]


def _property(props, tag, attribute="val"):
    for prop in props:
        node = prop.find(qn(f"w:{tag}"))
        if node is not None:
            return node.get(qn(f"w:{attribute}"), "1")
    return None


def run_marks(run, paragraph):
    props = _rprops(run, paragraph)
    marks = []
    for tag, mark in [("b", "bold"), ("i", "italic"), ("u", "underline"), ("strike", "strike")]:
        value = _property(props, tag)
        if value is not None and value not in ("0", "false", "off", "none"):
            marks.append({"type": mark})
    vertical = _property(props, "vertAlign")
    if vertical in ("subscript", "superscript"):
        marks.append({"type": vertical})
    attrs = {}
    for prop in props:
        fonts = prop.find(qn("w:rFonts"))
        if fonts is not None:
            family = fonts.get(qn("w:eastAsia")) or fonts.get(qn("w:ascii"))
            if family:
                attrs["fontFamily"] = family
                break
    if size := _property(props, "sz"):
        attrs["fontSize"] = f"{float(size) / 2:g}pt"
    rgb = _property(props, "color")
    if rgb and re.fullmatch("[0-9a-fA-F]{6}", rgb):
        attrs["color"] = f"#{rgb}"
    fill = _property(props, "shd", "fill")
    if fill and re.fullmatch("[0-9a-fA-F]{6}", fill):
        attrs["backgroundColor"] = f"#{fill}"
    elif highlight := HIGHLIGHTS.get(_property(props, "highlight")):
        attrs["backgroundColor"] = highlight
    if attrs:
        marks.append({"type": "textStyle", "attrs": attrs})
    if spacing := _property(props, "spacing"):
        marks.append({"type": "letterSpacing", "attrs": {"spacing": f"{int(spacing) / 20:g}pt"}})
    return marks


def paragraph_attrs(paragraph):
    formats = [paragraph.paragraph_format]
    formats.extend(s.paragraph_format for s in style_chain(paragraph.style))

    def get(name):
        return next((v for fmt in formats if (v := getattr(fmt, name)) is not None), None)

    attrs = {"textAlign": {v: k for k, v in ALIGNMENTS.items()}.get(get("alignment"), "left")}
    line = get("line_spacing")
    if line is not None:
        if hasattr(line, "pt"):
            attrs["lineSpacingPt"] = line.pt
        else:
            attrs["lineHeight"] = line
    for name, field in [("left_indent", "paragraphLeft"), ("right_indent", "paragraphRight")]:
        if (value := get(name)) is not None:
            attrs[field] = round(value.cm, 6)
    if (indent := get("first_line_indent")) is not None:
        attrs.update(indent=indent.pt / 2, indentUnit="pt")
    attrs["margin"] = {}
    for name, field in [("space_before", "top"), ("space_after", "bottom")]:
        if (value := get(name)) is not None:
            attrs["margin"][field] = f"{value.pt / 0.75:g}"
    if get("page_break_before"):
        attrs["pageBreakBefore"] = True
    return attrs


def numbering(paragraph):
    props = [paragraph._p.pPr, *(s.element.pPr for s in style_chain(paragraph.style))]
    numpr = next((p.numPr for p in props if p is not None and p.numPr is not None), None)
    if numpr is None or numpr.numId is None or numpr.numId.val == 0:
        return None
    num_id, level = numpr.numId.val, numpr.ilvl.val if numpr.ilvl is not None else 0
    root = paragraph.part.numbering_part.element
    nums = root.xpath(f'w:num[@w:numId="{num_id}"]')
    if not nums:
        unsupported("无法识别的编号")
    aid = nums[0].find(qn("w:abstractNumId")).get(qn("w:val"))
    levels = root.xpath(f'w:abstractNum[@w:abstractNumId="{aid}"]/w:lvl[@w:ilvl="{level}"]')
    overrides = nums[0].xpath(f'w:lvlOverride[@w:ilvl="{level}"]')
    if overrides and overrides[0].find(qn("w:lvl")) is not None:
        levels = [overrides[0].find(qn("w:lvl"))]
    if not levels:
        unsupported("无法识别的多级编号")
    lvl = levels[0]
    fmt = lvl.find(qn("w:numFmt")).get(qn("w:val"))
    if fmt not in LIST_TYPES and fmt != "bullet":
        unsupported("特殊编号样式")
    start = lvl.find(qn("w:start"))
    start = int(start.get(qn("w:val"))) if start is not None else 1
    if overrides and (override := overrides[0].find(qn("w:startOverride"))) is not None:
        start = int(override.get(qn("w:val")))
    # Standard nested lists are supported; compound labels such as 1.2. need a
    # numbering engine, so do not silently flatten them to simple numbers.
    label = lvl.find(qn("w:lvlText"))
    if label is not None and len(re.findall(r"%\d", label.get(qn("w:val"), ""))) > 1:
        unsupported("复合多级编号")
    bullet = label.get(qn("w:val"), "") if label is not None else ""
    return (
        num_id,
        level,
        "bulletList" if fmt == "bullet" else "orderedList",
        {
            "start": start,
            "listType": LIST_TYPES.get(fmt, {"○": "circle", "▪": "square"}.get(bullet, "disc")),
        },
    )


def _paragraph(paragraph):
    attrs = paragraph_attrs(paragraph)
    name = paragraph.style.name if paragraph.style else ""
    heading = re.fullmatch(r"Heading ([1-6])", name, flags=re.IGNORECASE)
    kind = "heading" if heading else "paragraph"
    if heading:
        attrs["level"] = int(heading[1])
    blocks, inline = [], []

    def flush():
        nonlocal inline
        blocks.append({"type": kind, "attrs": dict(attrs), "content": inline})
        inline = []

    for item in paragraph.iter_inner_content():
        link = []
        runs = item.runs if isinstance(item, Hyperlink) else [item]
        if isinstance(item, Hyperlink):
            href = item.url
            if not re.match(r"^(https?://|mailto:)", href, flags=re.IGNORECASE):
                unsupported("内部书签或特殊链接")
            link = [{"type": "link", "attrs": {"href": href}}]
        for run in runs:
            marks = run_marks(run, paragraph) + link
            for child in run._r:
                if child.tag == qn("w:t") and child.text:
                    inline.append({"type": "text", "text": child.text, "marks": marks})
                elif child.tag == qn("w:tab"):
                    inline.append({"type": "text", "text": "\t", "marks": marks})
                elif child.tag in (qn("w:br"), qn("w:cr")):
                    if child.get(qn("w:type")) == "page":
                        if inline:
                            flush()
                        blocks.append({"type": "pageBreak"})
                    elif child.get(qn("w:type")) == "column":
                        unsupported("分栏符")
                    else:
                        inline.append({"type": "hardBreak"})
    if inline or not blocks:
        flush()
    borders = paragraph._p.pPr.find(qn("w:pBdr")) if paragraph._p.pPr is not None else None
    if borders is not None:
        if paragraph.text:
            unsupported("带边框的段落")
        return [{"type": "horizontalRule"}]
    return blocks


def _table(table):
    if len(table.columns) > 20 or len(table.rows) > 200:
        unsupported("超过 200 行或 20 列的表格")
    rows, anchors = [], {}
    grid = [column.width.pt / 0.75 if column.width else 0 for column in table.columns]
    for row_index, row in enumerate(table.rows):
        cells = []
        if row.grid_cols_before or row.grid_cols_after:
            unsupported("不规则表格")
        for col, cell in enumerate(row.cells):
            if cell._tc in anchors:
                node, first_row = anchors[cell._tc]
                if row_index > first_row:
                    node["attrs"]["rowspan"] = row_index - first_row + 1
                continue
            span = cell._tc.grid_span
            attrs = {"colspan": span, "rowspan": 1, "colwidth": grid[col : col + span]}
            prop = cell._tc.tcPr
            shade = prop.find(qn("w:shd")) if prop is not None else None
            if shade is not None and re.fullmatch("[0-9A-Fa-f]{6}", shade.get(qn("w:fill"), "")):
                attrs["background"] = "#" + shade.get(qn("w:fill"))
            attrs["align"] = "left-" + {0: "top", 1: "middle", 3: "bottom"}.get(
                cell.vertical_alignment, "top"
            )
            if cell.tables:
                unsupported("嵌套表格")
            node = {"type": "tableCell", "attrs": attrs, "content": _blocks(cell)}
            anchors[cell._tc] = (node, row_index)
            cells.append(node)
        rows.append({"type": "tableRow", "content": cells})
    return {"type": "table", "content": rows}


def _blocks(container):
    output, stack, counters = [], [], {}
    for block in container.iter_inner_content():
        if isinstance(block, Table):
            stack = []
            output.append(_table(block))
            continue
        info = numbering(block)
        nodes = _paragraph(block)
        if not info:
            stack = []
            output.extend(nodes)
            continue
        num_id, level, kind, attrs = info
        if level > len(stack):
            unsupported("缺少父级的列表")
        stack = stack[: level + 1]
        if len(stack) <= level or stack[level][0] != num_id:
            stack = stack[:level]
            parent = output if not stack else stack[-1][1]["content"][-1]["content"]
            attrs = {**attrs, "start": counters.get((num_id, level), attrs["start"])}
            node = {"type": kind, "attrs": attrs, "content": []}
            parent.append(node)
            stack.append((num_id, node))
        # List marker indentation is represented by the list wrapper itself.
        for node in nodes:
            if node["type"] in ("paragraph", "heading"):
                node["attrs"].pop("paragraphLeft", None)
                node["attrs"].pop("indent", None)
                node["type"] = "paragraph"
        stack[-1][1]["content"].append({"type": "listItem", "content": nodes})
        counters[(num_id, level)] = counters.get((num_id, level), attrs["start"]) + 1
    return output


def word_content(content):
    from .authoring import _validate_word

    document = load_word(content)
    if snapshot := _snapshot(document):
        _validate_word(snapshot, allow_empty=True)
        return snapshot
    for tags, label in [
        (("drawing", "pict", "object"), "图片、形状或嵌入对象"),
        (("ins", "del", "moveFrom", "moveTo"), "修订记录"),
        (
            ("fldChar", "fldSimple", "instrText", "footnoteReference", "endnoteReference"),
            "域或脚注",
        ),
        (("sdt", "altChunk", "commentRangeStart"), "内容控件或批注"),
    ]:
        if any(document.element.findall(".//" + qn("w:" + tag)) for tag in tags):
            unsupported(label)
    if document.element.xpath(".//m:oMath | .//m:oMathPara"):
        unsupported("公式")
    if len(document.sections) != 1:
        unsupported("多个分节")
    section = document.sections[0]
    cols = section._sectPr.find(qn("w:cols"))
    if cols is not None and int(cols.get(qn("w:num"), "1")) != 1:
        unsupported("分栏排版")
    landscape = section.orientation == WD_ORIENT.LANDSCAPE
    width, height = section.page_width.cm, section.page_height.cm
    page = {
        "size": {"width": height if landscape else width, "height": width if landscape else height},
        "orientation": "landscape" if landscape else "portrait",
        "margin": {
            edge: getattr(section, f"{edge}_margin").cm
            for edge in ("left", "right", "top", "bottom")
        },
    }
    result = {"type": "doc", "attrs": {"page": page}, "content": _blocks(document)}
    try:
        _validate_word(result, allow_empty=True)
    except ApiError as error:
        raise ApiError("该 Word 的排版超出在线编辑范围：" + error.message, 422, 42202) from error
    return result
