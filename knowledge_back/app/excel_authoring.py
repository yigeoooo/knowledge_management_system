"""Read and write managed Excel workbooks.

The API deliberately exposes a small, stable workbook representation instead
of leaking Univer's internal snapshot format into the backend.  This keeps the
stored file a real XLSX workbook and makes imports from both XLS and XLSX
predictable.
"""

from __future__ import annotations

import zipfile
from io import BytesIO
from pathlib import PurePath
from typing import Any

from .http import ApiError

MAX_ROWS = 10_000
MAX_COLUMNS = 1_000
MAX_CELLS = 100_000
MAX_SHEETS = 100


def _invalid(message: str = "Excel 工作簿格式不正确") -> None:
    raise ApiError(message, 422, 42202)


def _safe_color(color: Any) -> str | None:
    if color is None:
        return None
    try:
        value = getattr(color, "rgb", None)
    except (TypeError, ValueError):
        value = None
    if not value:
        try:
            value = getattr(color, "indexed", None)
        except (TypeError, ValueError):
            value = None
    if value is None:
        return None
    return str(value)


def _style(cell) -> dict[str, Any]:
    font = cell.font
    fill = cell.fill
    alignment = cell.alignment
    border = cell.border
    return {
        "font": {
            "name": font.name,
            "size": font.sz,
            "bold": bool(font.bold),
            "italic": bool(font.italic),
            "underline": font.underline,
            "strike": bool(font.strike),
            "color": _safe_color(font.color),
        },
        "fill": {
            "type": fill.fill_type,
            "color": _safe_color(fill.fgColor),
        },
        "alignment": {
            "horizontal": alignment.horizontal,
            "vertical": alignment.vertical,
            "wrap_text": bool(alignment.wrap_text),
            "text_rotation": alignment.text_rotation,
        },
        "border": {
            side: {
                "style": getattr(getattr(border, side), "style", None),
                "color": _safe_color(getattr(getattr(border, side), "color", None)),
            }
            for side in ("left", "right", "top", "bottom")
        },
        "number_format": cell.number_format,
    }


def _value(value: Any) -> Any:
    # JSON has no representation for Excel's rich Python values.  Keep dates
    # and timedeltas as ISO strings while leaving numbers and booleans intact.
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _cell_payload(cell, cached=None) -> dict[str, Any]:
    raw = cell.value
    formula = raw if cell.data_type == "f" or (isinstance(raw, str) and raw.startswith("=")) else None
    return {
        "value": _value(cached if formula and cached is not None else (None if formula else raw)),
        "formula": formula,
        "style": _style(cell),
        "hyperlink": cell.hyperlink.target if cell.hyperlink else None,
        "comment": cell.comment.text if cell.comment else None,
    }


def _check_limits(sheet_count: int, rows: int, columns: int, cells: int) -> None:
    if sheet_count > MAX_SHEETS:
        _invalid(f"Excel 工作簿最多支持 {MAX_SHEETS} 个工作表")
    if rows > MAX_ROWS or columns > MAX_COLUMNS or cells > MAX_CELLS:
        _invalid(f"Excel 工作簿大小超过限制（最多 {MAX_ROWS} 行、{MAX_COLUMNS} 列、{MAX_CELLS} 个单元格）")


def _reject_mislabeled_text(content: bytes) -> None:
    # A renamed CSV/TSV is readable in desktop Excel but is not an XLS/XLSX
    # workbook. Explain how to fix it instead of reporting file corruption.
    for encoding in ("utf-8-sig", "utf-16", "gb18030"):
        try:
            text = content[:8192].decode(encoding)
        except UnicodeError:
            continue
        if text.strip() and all(char.isprintable() or char in "\t\r\n" for char in text):
            _invalid("文件实际是文本文件，不是 Excel 工作簿。请用 Excel 或 WPS 打开后另存为“Excel 工作簿（.xlsx）”再上传；仅修改扩展名无效。")


def _openpyxl_workbook(content: bytes):
    try:
        from openpyxl import load_workbook

        return load_workbook(BytesIO(content), data_only=False, read_only=False)
    except zipfile.BadZipFile as error:
        _reject_mislabeled_text(content)
        raise RuntimeError("Excel 文件解析失败，请确认文件格式有效且未损坏") from error
    except Exception as error:
        raise RuntimeError("Excel 文件解析失败，请确认文件格式有效且未损坏") from error


def _cached_workbook(content: bytes):
    try:
        from openpyxl import load_workbook

        return load_workbook(BytesIO(content), data_only=True, read_only=False)
    except (OSError, KeyError, ValueError, TypeError, RuntimeError, zipfile.BadZipFile):
        return None


def _parse_xlsx(content: bytes) -> dict[str, Any]:
    workbook = _openpyxl_workbook(content)
    cached = _cached_workbook(content)
    sheets: list[dict[str, Any]] = []
    total_cells = 0
    max_rows = max_columns = 0
    for index, sheet in enumerate(workbook.worksheets):
        cached_sheet = cached.worksheets[index] if cached and index < len(cached.worksheets) else None
        cells: dict[str, dict[str, Any]] = {}
        for row in sheet.iter_rows():
            for cell in row:
                if cell.value is None and not cell.has_style and not cell.hyperlink and not cell.comment:
                    continue
                cached_cell = cached_sheet[cell.coordinate] if cached_sheet else None
                payload = _cell_payload(cell, cached_cell.value if cached_cell else None)
                cells[f"{cell.row - 1},{cell.column - 1}"] = payload
                total_cells += 1
                max_rows = max(max_rows, cell.row)
                max_columns = max(max_columns, cell.column)
        merges = [
            {
                "start_row": item.min_row - 1,
                "start_col": item.min_col - 1,
                "end_row": item.max_row - 1,
                "end_col": item.max_col - 1,
            }
            for item in sheet.merged_cells.ranges
        ]
        row_heights = {
            str(index - 1): dimension.height
            for index, dimension in sheet.row_dimensions.items()
            if dimension.height is not None
        }
        column_widths = {
            key: dimension.width
            for key, dimension in sheet.column_dimensions.items()
            if dimension.width is not None
        }
        sheets.append(
            {
                "id": f"sheet{index + 1}",
                "name": sheet.title,
                "row_count": max(sheet.max_row, 1),
                "column_count": max(sheet.max_column, 1),
                "cells": cells,
                "merges": merges,
                "row_heights": row_heights,
                "column_widths": column_widths,
                "hidden_rows": [str(key - 1) for key, value in sheet.row_dimensions.items() if value.hidden],
                "hidden_columns": [key for key, value in sheet.column_dimensions.items() if value.hidden],
                "freeze_pane": (
                    sheet.freeze_panes.coordinate
                    if getattr(sheet.freeze_panes, "coordinate", None)
                    else str(sheet.freeze_panes) if sheet.freeze_panes else None
                ),
            }
        )
    _check_limits(len(sheets), max_rows, max_columns, total_cells)
    active_index = workbook.index(workbook.active)
    return {"sheets": sheets, "active_sheet": f"sheet{active_index + 1}" if sheets else None}


def _parse_xls(content: bytes) -> dict[str, Any]:
    try:
        import xlrd

        book = xlrd.open_workbook(file_contents=content, formatting_info=False)
    except Exception as error:
        _reject_mislabeled_text(content)
        raise RuntimeError("旧版 Excel 文件解析失败，请确认文件格式有效且未损坏") from error
    sheets: list[dict[str, Any]] = []
    total_cells = max_rows = max_columns = 0
    for index in range(book.nsheets):
        sheet = book.sheet_by_index(index)
        cells = {}
        for row in range(sheet.nrows):
            for col in range(sheet.ncols):
                cell = sheet.cell(row, col)
                if cell.value in (None, ""):
                    continue
                value = cell.value
                if cell.ctype == xlrd.XL_CELL_DATE:
                    value = xlrd.xldate_as_datetime(value, book.datemode).isoformat()
                cells[f"{row},{col}"] = {
                    "value": _value(value),
                    "formula": None,
                    "style": {},
                    "hyperlink": None,
                    "comment": None,
                }
                total_cells += 1
        max_rows = max(max_rows, sheet.nrows)
        max_columns = max(max_columns, sheet.ncols)
        sheets.append(
            {
                "id": f"sheet{index + 1}",
                "name": sheet.name,
                "row_count": max(sheet.nrows, 1),
                "column_count": max(sheet.ncols, 1),
                "cells": cells,
                "merges": [
                    {"start_row": r1, "start_col": c1, "end_row": r2 - 1, "end_col": c2 - 1}
                    for r1, r2, c1, c2 in sheet.merged_cells
                ],
                "row_heights": {},
                "column_widths": {},
                "hidden_rows": [],
                "hidden_columns": [],
                "freeze_pane": None,
            }
        )
    _check_limits(len(sheets), max_rows, max_columns, total_cells)
    return {"sheets": sheets, "active_sheet": "sheet1" if sheets else None}


def parse_workbook(filename: str, content: bytes) -> dict[str, Any]:
    extension = PurePath(filename).suffix.lower()
    if extension == ".xlsx":
        return _parse_xlsx(content)
    if extension == ".xls":
        return _parse_xls(content)
    _invalid("只支持 XLS 或 XLSX 文件")


def _number(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _apply_color(target, value: Any) -> None:
    if not value:
        return
    from openpyxl.styles import Color

    text = str(value).strip().removeprefix("#")
    if len(text) in {6, 8} and all(char in "0123456789abcdefABCDEF" for char in text):
        target.color = Color(rgb=text if len(text) == 8 else f"FF{text}")


def _apply_style(cell, style: Any) -> None:
    if style is None:
        return
    if not isinstance(style, dict):
        raise TypeError("Style must be an object")
    for field in ("font", "fill", "alignment", "border"):
        if style.get(field) is not None and not isinstance(style[field], dict):
            raise TypeError(f"Style {field} must be an object")
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

    font = style.get("font") or {}
    font_color = font.get("color")
    if isinstance(font_color, str):
        font_color = font_color.strip().removeprefix("#")
    if not isinstance(font_color, str) or len(font_color) not in {6, 8} or not all(
        char in "0123456789abcdefABCDEF" for char in font_color
    ):
        font_color = None
    cell.font = Font(
        name=font.get("name"), sz=font.get("size"), bold=bool(font.get("bold")),
        italic=bool(font.get("italic")), underline=font.get("underline"), strike=bool(font.get("strike")),
        color=(f"FF{font_color}" if font_color and len(font_color) == 6 else font_color),
    )
    fill = style.get("fill") or {}
    if fill.get("type"):
        fill_color = fill.get("color")
        if isinstance(fill_color, str):
            fill_color = fill_color.strip().removeprefix("#")
            if len(fill_color) == 6:
                fill_color = f"FF{fill_color}"
        cell.fill = PatternFill(fill_type=fill.get("type"), fgColor=fill_color or "00000000")
    alignment = style.get("alignment") or {}
    cell.alignment = Alignment(
        horizontal=alignment.get("horizontal"), vertical=alignment.get("vertical"),
        wrap_text=alignment.get("wrap_text"), text_rotation=alignment.get("text_rotation", 0) or 0,
    )
    border = style.get("border") or {}
    sides = {}
    for side_name in ("left", "right", "top", "bottom"):
        side = border.get(side_name) or {}
        border_side = Side(style=side.get("style"))
        _apply_color(border_side, side.get("color"))
        sides[side_name] = border_side
    cell.border = Border(**sides)
    if style.get("number_format"):
        cell.number_format = style["number_format"]


def _validated_workbook(workbook: Any) -> list[dict[str, Any]]:
    if not isinstance(workbook, dict) or not isinstance(workbook.get("sheets"), list) or not workbook["sheets"]:
        _invalid("工作簿至少需要一个工作表")
    sheets = workbook["sheets"]
    if len(sheets) > MAX_SHEETS:
        _invalid(f"Excel 工作簿最多支持 {MAX_SHEETS} 个工作表")
    total_cells = 0
    for index, sheet in enumerate(sheets):
        if not isinstance(sheet, dict):
            _invalid(f"第 {index + 1} 个工作表格式不正确")
        name = sheet.get("name")
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 31:
            _invalid("工作表名称需为 1–31 个字符")
        cells = sheet.get("cells") or {}
        if not isinstance(cells, dict):
            _invalid("工作表单元格格式不正确")
        total_cells += len(cells)
        if total_cells > MAX_CELLS:
            _invalid(f"Excel 工作簿最多支持 {MAX_CELLS} 个单元格")
        for key, cell in cells.items():
            try:
                row, column = (int(value) for value in str(key).split(",", 1))
            except (ValueError, TypeError):
                _invalid("单元格坐标格式不正确")
            if row < 0 or column < 0 or row >= MAX_ROWS or column >= MAX_COLUMNS or not isinstance(cell, dict):
                _invalid("单元格超出允许范围")
    return sheets


def workbook_bytes(workbook: dict[str, Any]) -> bytes:
    """Create a real XLSX file from the stable API representation."""
    sheets = _validated_workbook(workbook)
    from openpyxl import Workbook

    output = Workbook()
    output.remove(output.active)
    names: set[str] = set()
    for index, source in enumerate(sheets):
        name = source["name"].strip()
        if name in names:
            _invalid("工作表名称不能重复")
        names.add(name)
        sheet = output.create_sheet(name)
        for key, payload in (source.get("cells") or {}).items():
            row, column = (int(value) for value in str(key).split(",", 1))
            cell = sheet.cell(row=row + 1, column=column + 1)
            formula = payload.get("formula")
            cell.value = formula if formula else _number(payload.get("value"))
            try:
                _apply_style(cell, payload.get("style"))
            except (ValueError, TypeError, AttributeError) as error:
                raise ApiError(f"工作表“{name}”的 {cell.coordinate} 单元格样式格式不正确", 422, 42202) from error
            if payload.get("hyperlink"):
                cell.hyperlink = payload["hyperlink"]
            if payload.get("comment"):
                from openpyxl.comments import Comment

                cell.comment = Comment(str(payload["comment"]), "knowledge-system")
        for merge in source.get("merges") or []:
            try:
                sheet.merge_cells(
                    start_row=int(merge["start_row"]) + 1,
                    start_column=int(merge["start_col"]) + 1,
                    end_row=int(merge["end_row"]) + 1,
                    end_column=int(merge["end_col"]) + 1,
                )
            except (KeyError, TypeError, ValueError):
                _invalid("合并单元格范围不正确")
        for row, height in (source.get("row_heights") or {}).items():
            sheet.row_dimensions[int(row) + 1].height = float(height)
        for column, width in (source.get("column_widths") or {}).items():
            sheet.column_dimensions[str(column)].width = float(width)
        for row in source.get("hidden_rows") or []:
            sheet.row_dimensions[int(row) + 1].hidden = True
        for column in source.get("hidden_columns") or []:
            sheet.column_dimensions[str(column)].hidden = True
        freeze = source.get("freeze_pane")
        if freeze:
            sheet.freeze_panes = str(freeze)
    active = workbook.get("active_sheet")
    if isinstance(active, str):
        for index, source in enumerate(sheets):
            if source.get("id") == active:
                output.active = index
                break
    stream = BytesIO()
    output.save(stream)
    return stream.getvalue()


def workbook_text(workbook: dict[str, Any]) -> str:
    """Return deterministic, coordinate-aware text for retrieval and QA."""
    lines: list[str] = []
    for sheet in workbook.get("sheets", []):
        lines.append(f"工作表：{sheet.get('name', '')}")
        for coordinate, payload in sorted(
            (sheet.get("cells") or {}).items(),
            key=lambda item: tuple(int(part) for part in item[0].split(",", 1)),
        ):
            if not isinstance(payload, dict):
                continue
            value = payload.get("value")
            formula = payload.get("formula")
            if value in (None, "") and not formula:
                continue
            row, column = (int(part) for part in coordinate.split(",", 1))
            # Convert zero-based coordinates to a familiar A1 label.
            letters = ""
            number = column + 1
            while number:
                number, remainder = divmod(number - 1, 26)
                letters = chr(65 + remainder) + letters
            lines.append(f"{letters}{row + 1}：{formula or value}")
    return "\n".join(lines)
