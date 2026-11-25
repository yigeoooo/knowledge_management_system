"""Plain answer text for robot clients, preserving code and meaningful numbers."""

import re
from html.parser import HTMLParser

from markdown_it import MarkdownIt

_MARKDOWN = MarkdownIt("commonmark").enable(["table", "strikethrough"])
_CITATIONS = re.compile(r"\[\d+\](?:\s+\[\d+\])*")


class _Text(HTMLParser):
    def __init__(self, *, compact=False):
        super().__init__(convert_charrefs=True)
        self.compact = compact
        self.parts = []
        self.lists = []
        self.hidden = 0
        self.in_table = 0
        self.in_cell = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden += 1
        if self.hidden:
            return
        if tag == "table":
            self.in_table += 1
        elif tag in {"td", "th"}:
            self.in_cell += 1
        if tag in {"p", "div", "blockquote", "pre", "tr", "br", "hr"} or re.fullmatch(
            r"h[1-6]", tag
        ):
            self.parts.append("\n")
        if tag in {"ol", "ul"}:
            start = dict(attrs).get("start", "1")
            self.lists.append(int(start) if tag == "ol" and str(start).isdigit() else None)
        elif tag == "li":
            number = self.lists[-1] if self.lists else None
            self.parts.append(
                "\n" if self.compact else (f"\n{number}、" if number is not None else "\n• ")
            )
            if number is not None:
                self.lists[-1] += 1
        elif tag == "img":
            self.parts.append(dict(attrs).get("alt") or "")

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.hidden = max(0, self.hidden - 1)
            return
        if self.hidden:
            return
        if tag in {"p", "div", "blockquote", "pre", "tr", "li"} or re.fullmatch(r"h[1-6]", tag):
            self.parts.append("\n")
        elif tag in {"td", "th"}:
            self.parts.append("\t")
            self.in_cell = max(0, self.in_cell - 1)
        elif tag == "table":
            self.in_table = max(0, self.in_table - 1)
        elif tag in {"ol", "ul"} and self.lists:
            self.lists.pop()

    def handle_data(self, data):
        if not self.hidden and not (self.in_table and not self.in_cell and not data.strip()):
            self.parts.append(data)


def _answer_text(answer, sources, *, compact=False, require_paragraphs=False):
    source_ids = {str(source["source_id"]) for source in sources if "source_id" in source}
    tokens = _MARKDOWN.parse(answer or "")
    if require_paragraphs and any(
        token.type not in {"paragraph_open", "inline", "paragraph_close"} for token in tokens
    ):
        raise ValueError("请改写为简短的自然语言段落，不要标题、列表、表格、代码块或 HTML。")
    for index, token in enumerate(tokens):
        if (
            token.type == "inline"
            and token.level == 1
            and index > 0
            and tokens[index - 1].type == "paragraph_open"
            and _CITATIONS.fullmatch(token.content.strip())
            and set(re.findall(r"\[(\d+)\]", token.content)) <= source_ids
        ):
            token.children = []
    parser = _Text(compact=compact)
    parser.feed(_MARKDOWN.renderer.render(tokens, _MARKDOWN.options, {}))
    parser.close()
    text = "".join(parser.parts)
    if compact:
        return " ".join(text.split())
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def answer_text(answer, sources):
    """Remove actual citation paragraphs, preserving code, numbers and line breaks."""
    return _answer_text(answer, sources)


def robot_answer_text(answer, sources, *, require_paragraphs=False):
    """One plain paragraph; generated drafts must use prose before evidence review."""
    return _answer_text(answer, sources, compact=True, require_paragraphs=require_paragraphs)
