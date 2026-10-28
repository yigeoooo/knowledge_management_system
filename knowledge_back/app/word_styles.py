"""Validated editor formatting shared by the DOCX renderer."""

import math
import re

from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor

from .http import ApiError

ALIGNMENTS = {
    "left": WD_ALIGN_PARAGRAPH.LEFT,
    "center": WD_ALIGN_PARAGRAPH.CENTER,
    "right": WD_ALIGN_PARAGRAPH.RIGHT,
    "justify": WD_ALIGN_PARAGRAPH.JUSTIFY,
    "distributed": WD_ALIGN_PARAGRAPH.DISTRIBUTE,
}


def invalid(message="Word 排版参数不正确"):
    raise ApiError(message, 422, 42202)


def number(value, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        invalid()
    try:
        result = float(value)
    except (ValueError, OverflowError):
        invalid()
    if not math.isfinite(result) or not minimum <= result <= maximum:
        invalid()
    return result


def points(value, minimum=0, maximum=500, default_unit="px"):
    if isinstance(value, str):
        match = re.fullmatch(r"\s*(-?\d+(?:\.\d+)?)\s*(px|pt|em|cm|mm|in)?\s*", value)
        if not match:
            invalid()
        amount, unit = match.groups()
    else:
        amount, unit = value, default_unit
    scale = {"px": 0.75, "pt": 1, "em": 12, "cm": 72 / 2.54, "mm": 72 / 25.4, "in": 72}
    result = number(amount, -10000, 10000) * scale[unit or default_unit]
    return number(result, minimum, maximum)


def color(value):
    if not isinstance(value, str):
        invalid()
    value = value.strip().lower()
    if value in {"transparent", "inherit", "initial", ""}:
        return None
    if value in {"black", "white", "red", "blue", "green"}:
        return {
            "black": "000000",
            "white": "FFFFFF",
            "red": "FF0000",
            "blue": "0000FF",
            "green": "008000",
        }[value]
    if re.fullmatch(r"#[0-9a-f]{3}", value):
        return "".join(char * 2 for char in value[1:]).upper()
    if re.fullmatch(r"#[0-9a-f]{6}", value):
        return value[1:].upper()
    rgb = re.fullmatch(r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)(?:\s*,\s*([\d.]+))?\s*\)", value)
    if not rgb or any(int(channel) > 255 for channel in rgb.groups()[:3]):
        invalid("Word 颜色格式不正确")
    alpha = number(rgb[4], 0, 1) if rgb[4] is not None else 1
    return "".join(
        f"{round(int(channel) * alpha + 255 * (1 - alpha)):02X}" for channel in rgb.groups()[:3]
    )


def xml_value(parent, tag, **attributes):
    element = parent.find(qn(f"w:{tag}"))
    if element is None:
        element = OxmlElement(f"w:{tag}")
        parent.append(element)
    for name, value in attributes.items():
        element.set(qn(f"w:{name}"), str(value))


def validate_attributes(kind, attrs):
    if not isinstance(attrs, dict):
        invalid()
    for field in ("textAlign",):
        if attrs.get(field) is not None and attrs[field] not in tuple(ALIGNMENTS):
            invalid()
    if attrs.get("lineHeight") is not None:
        number(attrs["lineHeight"], 0.5, 10)
    if attrs.get("lineSpacingPt") is not None:
        number(attrs["lineSpacingPt"], 1, 500)
    if attrs.get("pageBreakBefore") is not None and type(attrs["pageBreakBefore"]) is not bool:
        invalid()
    if attrs.get("indent") is not None:
        number(attrs["indent"], 0, 20)
        if attrs.get("indentUnit") not in (None, "em", "px", "pt", "cm", "mm", "in"):
            invalid()
        points(f"{float(attrs['indent']) * 2}{attrs.get('indentUnit') or 'em'}", maximum=1440)
    for side in ("paragraphLeft", "paragraphRight"):
        if attrs.get(side) is not None:
            number(attrs[side], 0, 5)
    if attrs.get("wordWrap") not in (None, "normal", "break-word", "break-all"):
        invalid()
    if attrs.get("margin") is not None:
        if not isinstance(attrs["margin"], dict):
            invalid()
        for side in ("top", "bottom"):
            if attrs["margin"].get(side) is not None:
                points(attrs["margin"][side])
    for field in ("color", "backgroundColor", "background"):
        if attrs.get(field) is not None:
            color(attrs[field])
    if attrs.get("fontSize"):
        points(attrs["fontSize"], 1, 400)
    if attrs.get("fontFamily") is not None:
        family = attrs["fontFamily"]
        if (
            not isinstance(family, str)
            or len(family) > 200
            or any(
                ord(c) < 32 or 0xD800 <= ord(c) <= 0xDFFF or ord(c) in {0xFFFE, 0xFFFF}
                for c in family
            )
        ):
            invalid()
    if kind == "letterSpacing" and attrs.get("spacing") is not None:
        points(attrs["spacing"], -10, 100)
    if kind in {"tableCell", "tableHeader"}:
        for field, maximum in (("colspan", 20), ("rowspan", 200)):
            value = attrs.get(field, 1)
            if type(value) is not int or not 1 <= value <= maximum:
                invalid("表格合并范围不正确")
        if attrs.get("align") not in (
            None,
            "",
            *ALIGNMENTS,
            *(f"{h}-{v}" for h in ALIGNMENTS for v in ("top", "middle", "bottom")),
        ):
            invalid()
        widths = attrs.get("colwidth")
        if widths is not None:
            if not isinstance(widths, list) or len(widths) != attrs.get("colspan", 1):
                invalid()
            for width in widths:
                if type(width) not in (int, float):
                    invalid()
                number(width, 0, 5000)
    if kind in {"orderedList", "bulletList"} and attrs.get("listType") not in (
        None,
        "decimal",
        "decimal-leading-zero",
        "lower-alpha",
        "lower-latin",
        "upper-latin",
        "trad-chinese-informal",
        "simp-chinese-formal",
        "upper-alpha",
        "lower-roman",
        "upper-roman",
        "cjk-ideographic",
        "disc",
        "circle",
        "square",
        "none",
    ):
        invalid()
    if kind == "taskItem" and type(attrs.get("checked", False)) is not bool:
        invalid()


def paragraph_style(paragraph, attrs):
    fmt = paragraph.paragraph_format
    if attrs.get("textAlign"):
        paragraph.alignment = ALIGNMENTS[attrs["textAlign"]]
    if attrs.get("lineHeight") is not None:
        fmt.line_spacing = number(attrs["lineHeight"], 0.5, 10)
    if attrs.get("lineSpacingPt") is not None:
        fmt.line_spacing = Pt(number(attrs["lineSpacingPt"], 1, 500))
    if attrs.get("pageBreakBefore") is not None:
        fmt.page_break_before = attrs["pageBreakBefore"]
    if attrs.get("indent"):
        fmt.first_line_indent = Pt(
            points(f"{float(attrs['indent']) * 2}{attrs.get('indentUnit') or 'em'}", maximum=1440)
        )
    for side, field in (("left_indent", "paragraphLeft"), ("right_indent", "paragraphRight")):
        if attrs.get(field) is not None:
            setattr(fmt, side, Pt(number(attrs[field], 0, 5) * 72 / 2.54))
    margin = attrs.get("margin") or {}
    if margin.get("top") is not None:
        fmt.space_before = Pt(points(margin["top"]))
    if margin.get("bottom") is not None:
        fmt.space_after = Pt(points(margin["bottom"]))
    if attrs.get("wordWrap"):
        xml_value(
            paragraph._p.get_or_add_pPr(),
            "wordWrap",
            val="1" if attrs["wordWrap"] == "break-all" else "0",
        )


def text_style(run, attrs):
    if attrs.get("fontFamily"):
        family = attrs["fontFamily"].split(",")[0].strip(" \"'")
        run.font.name = family
        run._r.get_or_add_rPr().rFonts.set(qn("w:eastAsia"), family)
    if attrs.get("fontSize"):
        run.font.size = Pt(points(attrs["fontSize"], 1, 400))
    if attrs.get("color") and (value := color(attrs["color"])):
        run.font.color.rgb = RGBColor.from_string(value)
    if attrs.get("backgroundColor") and (value := color(attrs["backgroundColor"])):
        xml_value(run._r.get_or_add_rPr(), "shd", val="clear", fill=value)
