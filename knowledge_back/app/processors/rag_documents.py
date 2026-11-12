"""Structure-aware LangChain Documents for the existing versioned SQL index."""
import re
from hashlib import sha256

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter, TextSplitter

from .markdown import markdown_blocks

CHUNK_SIZE = 1600
CHUNK_OVERLAP = 160


class KnowledgeTextSplitter(TextSplitter):
    def __init__(self):
        super().__init__(chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP)
        self.prose = RecursiveCharacterTextSplitter(
            chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP,
            separators=["\n\n", "\n", "。", "；", ". ", " ", ""],
        )

    def split_text(self, text):
        return [d.page_content for d in self.create_documents([text])]

    def create_documents(self, texts, metadatas=None):
        result = []
        for index, text in enumerate(texts):
            metadata = dict(metadatas[index]) if metadatas else {}
            sections, lines, start, heading, fence = [], [], 1, [], None
            for number, line in enumerate(text.splitlines(), 1):
                marker = re.match(r"^\s*(`{3,}|~{3,})", line)
                if marker:
                    token = marker.group(1)
                    if fence is None:
                        fence = token
                    elif token[0] == fence[0] and len(token) >= len(fence):
                        fence = None
                title = re.match(r"^(#{1,6})\s+(.+)", line) if fence is None else None
                if title:
                    if any(part.strip() for part in lines):
                        sections.append(("\n".join(lines), start, " > ".join(h for h in heading if h)))
                    lines, start = [], number
                    level = len(title.group(1))
                    heading = (heading + [""] * (level - 1))[:level - 1] + [title.group(2).strip()]
                lines.append(line)
            if any(part.strip() for part in lines):
                sections.append(("\n".join(lines), start, " > ".join(h for h in heading if h)))
            for ordinal, (section, line_start, path) in enumerate(sections):
                section_id = sha256(f"{metadata.get('version_id', '')}:{ordinal}:{path}".encode()).hexdigest()[:24]
                pieces = []
                for block, first, last in markdown_blocks(section):
                    if block.lstrip().startswith(("```", "~~~")):
                        # A command block is atomic. Oversized blocks fail explicitly;
                        # indexing must never silently corrupt or omit commands.
                        if len(block) > 16000:
                            raise ValueError("代码块超过 16000 字符，请按完整操作拆分文档")
                        parts = [block]
                    elif "|" in block and re.search(r"\|?\s*:?-{3,}", block):
                        rows = block.splitlines()
                        head, buffer, parts = rows[:2], rows[:2], []
                        for row in rows[2:]:
                            if len("\n".join(buffer + [row])) > CHUNK_SIZE and len(buffer) > 2:
                                parts.append("\n".join(buffer))
                                buffer = head.copy()
                            buffer.append(row)
                        if len(buffer) > 2:
                            parts.append("\n".join(buffer))
                        if not parts:
                            parts = [block]
                    else:
                        parts = self.prose.split_text(block)
                    for part in parts:
                        # Keep adjacent short paragraph/FAQ blocks together.
                        if pieces and len(pieces[-1][0]) + len(part) + 2 <= CHUNK_SIZE:
                            prior, begin, _ = pieces[-1]
                            pieces[-1] = (prior + "\n\n" + part, begin, last)
                        else:
                            pieces.append((part, first, last))
                for part, first, last in pieces:
                    result.append(Document(page_content=part, metadata={**metadata,
                        "heading_path": path, "section_id": section_id,
                        "line_start": line_start + first - 1, "line_end": line_start + last - 1}))
        return result


def excel_documents(workbook, *, version_id):
    """Keep worksheet identity, first populated row and each data row together."""
    result = []
    for sheet in workbook.get("sheets", []):
        rows = {}
        for coordinate, cell in (sheet.get("cells") or {}).items():
            row, column = map(int, coordinate.split(","))
            value = cell.get("formula") or cell.get("value")
            if value is not None and value != "":
                rows.setdefault(row, []).append((column, str(value)))
        if not rows:
            continue
        def row_text(row, values=rows):
            return " | ".join(f"列{col + 1}: {val}" for col, val in sorted(values[row]))
        ordered = sorted(rows)
        first = ordered[0]
        header_row = first
        # A single merged title commonly precedes a multi-column header.
        if len(ordered) >= 3 and len(rows[first]) == 1:
            candidate = ordered[1]
            if len(rows[candidate]) >= 2 and all(len(value) < 80 and not re.fullmatch(r"[\d.,]+", value) for _, value in rows[candidate]):
                header_row = candidate
        labels = dict(rows[header_row])
        title = "\n\n".join(row_text(r) for r in ordered if r < header_row)
        header = f"# 工作表：{sheet['name']}\n\n" + (title + "\n\n" if title else "") + f"表头/首个数据行（第{header_row + 1}行）：{row_text(header_row)}"
        for row in [header_row] + [r for r in ordered if r > header_row]:
            values = " | ".join(f"{labels.get(col, f'列{col + 1}')}: {val}" for col, val in sorted(rows[row]))
            text = header if row == header_row else header + f"\n\n第{row + 1}行：{values}"
            if len(text) > 16000:
                raise ValueError("Excel 单行内容过长，请拆分为可检索的数据区域")
            result.append(Document(page_content=text, metadata={"version_id": str(version_id),
                "heading_path": sheet['name'], "sheet": sheet['name'], "row_start": first + 1 if row == header_row else row + 1,
                "row_end": row + 1, "header_row": header_row + 1, "section_id": f"sheet:{sheet['id']}",
                "modality": "text"}))
    return result
