"""Plain answer text for robot clients, preserving code and meaningful numbers."""

import re
from html.parser import HTMLParser

from markdown_it import MarkdownIt

_MARKDOWN = MarkdownIt("commonmark").enable(["table", "strikethrough"])
_CITATIONS = re.compile(r"\[\d+\](?:\s+\[\d+\])*")


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
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
            self.parts.append(f"\n{number}、" if number is not None else "\n• ")
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


def answer_text(answer, sources):
    """Remove server-added citation paragraphs, then render Markdown as text.

    Only numbered paragraphs matching actual sources are citations; array
    indices, inline code and fenced code must retain their brackets/operators.
    """
    source_ids = {str(source["source_id"]) for source in sources if "source_id" in source}
    tokens = _MARKDOWN.parse(answer or "")
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
    parser = _Text()
    parser.feed(_MARKDOWN.renderer.render(tokens, _MARKDOWN.options, {}))
    parser.close()
    return re.sub(r"\n{3,}", "\n\n", "".join(parser.parts)).strip()
