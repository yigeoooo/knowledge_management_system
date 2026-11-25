import { computed, type Ref } from 'vue'
import { Lexer, type Tokens } from 'marked'
import type { Source, Turn } from '@web/lib/conversations'

interface Cell { column: number; value: string }

function columnLabel(column: number) {
  let label = ''
  while (column > 0) {
    column -= 1
    label = String.fromCharCode(65 + column % 26) + label
    column = Math.floor(column / 26)
  }
  return label
}

// excel_documents emits "key: value" in column order. Only split before
// another known label or numbered column. A pipe by itself is cell content.
function readCells(text: string, headers: Cell[] = []): Cell[] | null {
  const byLabel = new Map(headers.map(cell => [cell.value, cell.column]))
  if (byLabel.size !== headers.length || headers.some(cell => cell.value.includes(' | '))) return null
  const labels = [...byLabel.keys()].sort((a, b) => b.length - a.length)
  const cells: Cell[] = []
  for (const part of text.split(' | ')) {
    const label = labels.find(key => part.startsWith(key + ': '))
    const numbered = /^列([1-9]\d*): /.exec(part)
    const column = label === undefined ? Number(numbered?.[1]) : byLabel.get(label)!
    const previous = cells.at(-1)
    if (label === undefined && !numbered) {
      if (!previous) return null
      previous.value += ' | ' + part
      continue
    }
    if (column > 16384 || column <= (previous?.column ?? 0)) return null
    const prefix = label === undefined ? numbered![0] : label + ': '
    cells.push({ column, value: part.slice(prefix.length) })
  }
  return cells
}

// Convert the row-based index excerpt into the coordinate notation used by
// ExcelSourceContent. Unrecognized or ambiguous excerpts keep their original text.
function excelCoordinates(content: string) {
  const text = content.replace(/\r\n?/g, '\n')
  const sheet = /^# 工作表[：:]([^\n]+)\n\n/.exec(text)
  if (!sheet) return content
  const sections = text.slice(sheet[0].length).split(/(?:^|\n\n)表头\/首个数据行（第([1-9]\d*)行）[：:]/)
  if (sections.length !== 3) return content
  const [title, headerRow, body] = sections
  const rows = body.split(/\n\n第([1-9]\d*)行[：:]/)
  if (rows.length > 3 || Number(headerRow) > 1048576) return content
  const headers = readCells(rows[0])
  if (!headers) return content
  // The optional merged title has no saved row number.
  const notes = title.replace(/^列[1-9]\d*: /, '')
  const lines = ['工作表：' + sheet[1]]
  if (notes) lines.push(notes)
  function addRow(number: string, cells: Cell[]) {
    for (const { column, value } of cells) lines.push(columnLabel(column) + number + '：' + value)
  }
  const coordinateLine = /(?:^|\n)(?:工作表|[A-Z]{1,3}[1-9]\d{0,6})[：:]/
  // A continuation line resembling a coordinate cannot be represented losslessly.
  const ambiguousCell = (cell: Cell) => /\n(?:工作表|[A-Z]{1,3}[1-9]\d{0,6})[：:]/.test(cell.value)
  if (coordinateLine.test(notes) || headers.some(ambiguousCell)) return content
  addRow(headerRow, headers)
  if (rows.length === 3) {
    const [, number, values] = rows
    const cells = readCells(values, headers)
    if (!cells || Number(number) <= Number(headerRow) || Number(number) > 1048576 ||
      cells.some(ambiguousCell)) return content
    addRow(number, cells)
  }
  return lines.join('\n')
}

function textHtml(value: string) {
  return value.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/\n/g, '<br>')
}

function tableRow(cells: string[], tag: 'th' | 'td') {
  return '<tr>' + cells.map(cell => `<${tag}>${textHtml(cell)}</${tag}>`).join('') + '</tr>'
}

// The Word indexer writes headings with # and separates table rows with
// blank lines. Only infer a table from consecutive rows of the same width.
function wordFragment(content: string) {
  const blocks = content.replace(/\r\n?/g, '\n').split(/\n\n+/)
  const html: string[] = []
  let structured = false
  let rows: string[][] = []
  function flushRows() {
    if (rows.length > 1) {
      const table = rows.map(row => tableRow(row, 'td'))
      html.push('<table><tbody>' + table.join('') + '</tbody></table>')
      structured = true
    } else if (rows.length) {
      html.push('<p>' + textHtml(rows[0].join(' | ')) + '</p>')
    }
    rows = []
  }
  for (const block of blocks) {
    const heading = /^(#{1,6}) ([^\n]+)$/.exec(block)
    const cells = block.split(' | ')
    if (!heading && !block.includes('\n') && cells.length > 1) {
      if (rows.length && rows[0].length !== cells.length) flushRows()
      rows.push(cells)
      continue
    }
    flushRows()
    if (heading) {
      const tag = 'h' + heading[1].length
      html.push('<' + tag + '>' + textHtml(heading[2]) + '</' + tag + '>')
      structured = true
      continue
    }
    if (block.includes('|') && block.includes('\n') && block.includes('---')) {
      const tokens = Lexer.lex(block)
      if (tokens.length === 1 && tokens[0]?.type === 'table') {
        const table = tokens[0] as Tokens.Table
        const head = tableRow(table.header.map(cell => cell.text), 'th')
        const body = table.rows.map(row => tableRow(row.map(cell => cell.text), 'td')).join('')
        html.push('<table><thead>' + head + '</thead><tbody>' + body + '</tbody></table>')
        structured = true
        continue
      }
    }
    html.push('<p>' + textHtml(block) + '</p>')
  }
  flushRows()
  return structured ? html.join('') : null
}

function displaySource(source: Source) {
  if (!source.content) return source
  if (/\.xlsx?$/i.test(source.filename)) {
    const content = excelCoordinates(source.content)
    if (content !== source.content) return { ...source, content }
  } else if (/\.docx$/i.test(source.filename) && !source.content_html) {
    const html = wordFragment(source.content)
    if (html) return { ...source, content_html: html }
  }
  return source
}

export function useCitationTurns(turns: Ref<Turn[]>) {
  return computed(() => turns.value.map(turn => ({ ...turn, sources: turn.sources.map(displaySource) })))
}
