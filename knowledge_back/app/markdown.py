"""Small deterministic Markdown chunker used by the indexing worker."""

from dataclasses import dataclass


@dataclass(frozen=True)
class MarkdownChunk:
    content: str
    heading_path: str
    line_start: int
    line_end: int


def _blocks(text: str):
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    blocks = []
    current = []
    start = 1
    in_code = False

    def flush(end):
        nonlocal current, start
        if any(line.strip() for line in current):
            blocks.append(("\n".join(current).strip(), start, end))
        current = []

    for index, line in enumerate(lines, 1):
        fence = line.strip().startswith("```") or line.strip().startswith("~~~")
        if fence:
            if not current:
                start = index
            current.append(line)
            in_code = not in_code
            if not in_code:
                flush(index)
            continue
        if not in_code and not line.strip():
            flush(index - 1)
            start = index + 1
            continue
        if not current:
            start = index
        current.append(line)
    flush(len(lines))
    return blocks


def _heading_path(line: str, headings: list[str | None]) -> str:
    stripped = line.strip()
    if not stripped.startswith("#"):
        return " > ".join(value for value in headings if value)
    prefix, _, title = stripped.partition(" ")
    if not title or set(prefix) != {"#"}:
        return " > ".join(value for value in headings if value)
    level = min(len(prefix), 6)
    headings[level - 1] = title.strip().rstrip("#").strip()
    for index in range(level, len(headings)):
        headings[index] = None
    return " > ".join(value for value in headings if value)


def chunk_markdown(text: str, *, max_chars: int = 3200, overlap_chars: int = 300) -> list[MarkdownChunk]:
    """Group Markdown blocks while retaining heading and source line metadata."""

    if max_chars < 256 or overlap_chars < 0 or overlap_chars >= max_chars:
        raise ValueError("invalid chunk configuration")
    headings: list[str | None] = [None] * 6
    grouped: list[tuple[str, str, int, int]] = []
    for block, start, end in _blocks(text):
        path = ""
        for line in block.splitlines():
            path = _heading_path(line, headings)
        grouped.append((block, path, start, end))

    chunks: list[MarkdownChunk] = []
    current: list[tuple[str, str, int, int]] = []
    current_size = 0
    for block, path, start, end in grouped:
        if len(block) > max_chars:
            if current:
                chunks.append(_make_chunk(current))
                current, current_size = [], 0
            step = max_chars - overlap_chars
            for offset in range(0, len(block), step):
                part = block[offset : offset + max_chars].strip()
                if part:
                    chunks.append(MarkdownChunk(part, path, start, end))
            continue
        if current and current_size + len(block) + 2 > max_chars:
            chunks.append(_make_chunk(current))
            current = []
            current_size = 0
        current.append((block, path, start, end))
        current_size += len(block) + (2 if current_size else 0)
    if current:
        chunks.append(_make_chunk(current))
    return chunks


def _make_chunk(parts: list[tuple[str, str, int, int]]) -> MarkdownChunk:
    return MarkdownChunk(
        "\n\n".join(part[0] for part in parts).strip(),
        next((part[1] for part in reversed(parts) if part[1]), ""),
        parts[0][2],
        parts[-1][3],
    )
