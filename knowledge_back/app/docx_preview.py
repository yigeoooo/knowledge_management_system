"""Render DOCX paragraphs as escaped HTML; optionally clip to a cited text range."""

import re
from html import escape

from docx.oxml.ns import qn
from docx.table import Table
from docx.text.hyperlink import Hyperlink
from lxml import etree, html

from .http import ApiError
from .word_import import load_word, numbering, paragraph_attrs, run_marks


def _css(styles):
    return escape(';'.join(f'{key}:{value}' for key, value in styles.items()), quote=True)


def _run_html(run, paragraph):
    styles = {}
    for mark in run_marks(run, paragraph):
        kind, attrs = mark['type'], mark.get('attrs', {})
        if kind == 'textStyle':
            for name, css in [('fontFamily', 'font-family'), ('fontSize', 'font-size'),
                              ('color', 'color'), ('backgroundColor', 'background-color')]:
                if name in attrs:
                    value = attrs[name]
                    if name == 'fontFamily':
                        value = '"' + re.sub(r'[;{}<>"\\]', '', value) + '"'
                    styles[css] = value
        elif kind == 'bold':
            styles['font-weight'] = '700'
        elif kind == 'italic':
            styles['font-style'] = 'italic'
        elif kind in ('underline', 'strike'):
            styles['text-decoration'] = (styles.get('text-decoration', '') + ' ' +
                                         ('underline' if kind == 'underline' else 'line-through')).strip()
        elif kind in ('subscript', 'superscript'):
            styles.update({'vertical-align': 'sub' if kind == 'subscript' else 'super', 'font-size': 'smaller'})
        elif kind == 'letterSpacing':
            styles['letter-spacing'] = attrs['spacing']
    text = escape(run.text or '').replace('\n', '<br>').replace('\r', '')
    if run._r.xpath('.//w:br[@w:type="page"]'):
        text += '<hr class="docx-page-break">'
    return f'<span style="{_css(styles)}">{text}</span>' if styles else text


def _paragraph_inner(paragraph):
    parts = []
    for item in paragraph.iter_inner_content():
        if isinstance(item, Hyperlink):
            text = ''.join(_run_html(run, paragraph) for run in item.runs)
            if re.match(r'^(https?://|mailto:)', item.url, flags=re.IGNORECASE):
                text = f'<a href="{escape(item.url, quote=True)}">{text}</a>'
            parts.append(text)
        else:
            parts.append(_run_html(item, paragraph))
    return ''.join(parts) or '<br>'


def _paragraph_html(paragraph):
    attrs = paragraph_attrs(paragraph)
    styles = {'text-align': attrs['textAlign'], 'white-space': 'pre-wrap'}
    for field, css in [('paragraphLeft', 'margin-left'), ('paragraphRight', 'margin-right')]:
        if field in attrs:
            styles[css] = f'{attrs[field]}cm'
    if 'indent' in attrs:
        styles['text-indent'] = f"{attrs['indent'] * 2:g}pt"
    for side, value in attrs.get('margin', {}).items():
        styles['margin-' + side] = f'{float(value):g}px'
    if 'lineHeight' in attrs:
        styles['line-height'] = attrs['lineHeight']
    if 'lineSpacingPt' in attrs:
        styles['line-height'] = f"{attrs['lineSpacingPt']:g}pt"
    if attrs.get('pageBreakBefore'):
        styles['break-before'] = 'page'
    name = paragraph.style.name if paragraph.style else ''
    heading = re.fullmatch(r'Heading ([1-6])', name, flags=re.IGNORECASE)
    tag = 'h' + heading[1] if heading else 'p'
    borders = paragraph._p.pPr.find(qn('w:pBdr')) if paragraph._p.pPr is not None else None
    return (f'<{tag} style="{_css(styles)}">{_paragraph_inner(paragraph)}</{tag}>' +
            ('<hr>' if borders is not None else ''))


def _table_html(table):
    anchors, rows = {}, []
    for row_index, row in enumerate(table.rows):
        cells = []
        for cell in row.cells:
            if cell._tc in anchors:
                element, first = anchors[cell._tc]
                if row_index > first:
                    element.set('rowspan', str(row_index - first + 1))
                continue
            td = html.Element('td', colspan=str(cell._tc.grid_span), rowspan='1')
            anchors[cell._tc] = (td, row_index)
            styles = {}
            shade = cell._tc.tcPr.find(qn('w:shd')) if cell._tc.tcPr is not None else None
            if shade is not None and re.fullmatch('[0-9A-Fa-f]{6}', shade.get(qn('w:fill'), '')):
                styles['background-color'] = '#' + shade.get(qn('w:fill'))
            if cell.width:
                styles['width'] = f'{cell.width.pt:g}pt'
            styles['vertical-align'] = {0: 'top', 1: 'middle', 3: 'bottom'}.get(cell.vertical_alignment, 'top')
            td.set('style', ';'.join(f'{k}:{v}' for k, v in styles.items()))
            fragment = html.fragment_fromstring(_render(cell), create_parent='div')
            td.extend(fragment)
            cells.append(td)
        tr = html.Element('tr')
        tr.extend(cells)
        rows.append(tr)
    table_element = html.Element('table', {'class': 'docx-preview-table'})
    tbody = etree.SubElement(table_element, 'tbody')
    tbody.extend(rows)
    return html.tostring(table_element, encoding='unicode')


def _render(container):
    blocks, stack, counters = [], [], {}
    for block in container.iter_inner_content():
        if isinstance(block, Table):
            stack = []
            blocks.append(html.fragment_fromstring(_table_html(block)))
            continue
        paragraph = html.fragment_fromstring(_paragraph_html(block), create_parent='div')
        try:
            info = numbering(block)
        except ApiError:
            info = None
        if not info:
            stack = []
            blocks.extend(paragraph)
            continue
        num_id, level, kind, attrs = info
        level = min(level, len(stack))
        stack = stack[:level + 1]
        if len(stack) <= level or stack[level][0] != num_id:
            stack = stack[:level]
            tag = 'ol' if kind == 'orderedList' else 'ul'
            lst = html.Element(tag)
            if tag == 'ol':
                lst.set('start', str(counters.get((num_id, level), attrs['start'])))
            lst.set('style', f"list-style-type:{attrs['listType']}")
            if stack and len(stack[-1][1]):
                stack[-1][1][-1].append(lst)
            else:
                blocks.append(lst)
            stack.append((num_id, lst))
        li = etree.SubElement(stack[-1][1], 'li')
        li.extend(paragraph)
        counters[(num_id, level)] = counters.get((num_id, level), attrs['start']) + 1
    return ''.join(html.tostring(block, encoding='unicode') for block in blocks)


def docx_html(content):
    return _render(load_word(content))


def _normalized(text):
    # The legacy indexer represents table cells with pipe delimiters.
    return re.sub(r'[\s|]+', '', text)


def citation_html(rendered, content):
    """Preserve styles while removing text outside the exact cited substring.

    Never replace an old citation with an entire/latest document. If a range
    cannot be located in its saved version, the caller retains its plain text.
    """
    root = html.fragment_fromstring(rendered, create_parent='div')
    slots = [(item.getparent(), 'tail' if item.is_tail else 'text', str(item))
             for item in root.xpath('.//text()')]
    full = ''.join(_normalized(text) for _, _, text in slots)
    needle = _normalized(content)
    start = full.find(needle) if needle else -1
    if start < 0:
        return None
    end, cursor = start + len(needle), 0
    for node, field, value in slots:
        kept = []
        for character in value:
            width = len(_normalized(character))
            if start <= cursor < end:
                kept.append(character)
            cursor += width
        setattr(node, field, ''.join(kept))
    for listing in root.iter('ol'):
        skipped = 0
        for item in listing:
            if ''.join(item.itertext()).strip():
                break
            skipped += 1
        listing.set('start', str(int(listing.get('start', '1')) + skipped))
    for node in reversed(list(root.iterdescendants())):
        if node.tag in ('td', 'th') and ''.join(node.getparent().itertext()).strip():
            continue
        if not ''.join(node.itertext()).strip() and not (node.tail or '').strip() and node.getparent() is not None:
            node.getparent().remove(node)
    return ''.join(html.tostring(node, encoding='unicode') for node in root)
