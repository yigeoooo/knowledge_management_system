<script setup lang="ts">
import { computed } from "vue";

interface Cell {
  coordinate: string;
  row: number;
  column: number;
  value: string;
}
interface Sheet {
  name: string;
  notes: string[];
  cells: Map<string, Cell>;
}

const props = defineProps<{ content: string }>();

function columnLabel(column: number) {
  let label = "";
  while (column > 0) {
    column -= 1;
    label = String.fromCharCode(65 + column % 26) + label;
    column = Math.floor(column / 26);
  }
  return label;
}

// workbook_text emits one coordinate/value per line. Work with the saved
// citation itself so historical answers keep the exact evidence they cited.
const sheets = computed(() => {
  const sections: Sheet[] = [];
  let section: Sheet = { name: "", notes: [], cells: new Map() };
  let previous: Cell | null = null;
  for (const line of props.content.replace(/\r\n?/g, "\n").split("\n")) {
    const heading = /^工作表[：:](.*)$/.exec(line);
    if (heading) {
      if (section.name || section.notes.length || section.cells.size) sections.push(section);
      section = { name: heading[1]!.trim(), notes: [], cells: new Map() };
      previous = null;
      continue;
    }
    const match = /^([A-Z]{1,3})([1-9]\d{0,6})[：:](.*)$/.exec(line);
    if (match) {
      const column = [...match[1]!].reduce((value, char) => value * 26 + char.charCodeAt(0) - 64, 0);
      const row = Number(match[2]);
      if (column <= 16384 && row <= 1048576) {
        const coordinate = `${match[1]}${row}`;
        // Ambiguous or overlapping fragments must not silently overwrite data.
        if (section.cells.has(coordinate)) return [];
        previous = { coordinate, row, column, value: match[3]! };
        section.cells.set(coordinate, previous);
        continue;
      }
    }
    // A chunk may begin inside a cell, or contain a multiline cell value.
    if (previous) previous.value += `\n${line}`;
    else section.notes.push(line);
  }
  if (section.name || section.notes.length || section.cells.size) sections.push(section);
  if (!sections.some(item => item.cells.size)) return [];

  const result = [];
  for (const item of sections) {
    const cells = [...item.cells.values()];
    const rows = [...new Set(cells.map(cell => cell.row))].sort((a, b) => a - b);
    let columns = [...new Set(cells.map(cell => cell.column))].sort((a, b) => a - b);
    if (columns.length) {
      const first = columns[0]!;
      const span = columns[columns.length - 1]! - first + 1;
      // Keep nearby empty columns in place; retain explicit column labels for
      // sparse excerpts instead of allocating a full worksheet-sized grid.
      if (span <= 32) columns = Array.from({ length: span }, (_, index) => first + index);
    }
    if (rows.length * columns.length > 5000) return [];
    const label = item.name ? `工作表：${item.name}` : "工作表片段";
    result.push({
      label,
      notes: (!rows.length && item.name ? [label, ...item.notes] : item.notes).join("\n"),
      columns: columns.map(column => columnLabel(column)),
      rows: rows.map(row => ({
        number: row,
        cells: columns.map(column => {
          const coordinate = `${columnLabel(column)}${row}`;
          return { coordinate, value: item.cells.get(coordinate)?.value ?? "" };
        }),
      })),
    });
  }
  return result;
});

function numeric(value: string) {
  return /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?%?$/i.test(value.trim());
}
</script>

<template>
  <div class="excel-source">
    <template v-if="sheets.length">
      <section v-for="(sheet, index) in sheets" :key="index" class="excel-source-sheet">
        <div v-if="sheet.notes" class="excel-source-text">{{ sheet.notes }}</div>
        <div v-if="sheet.rows.length" class="excel-source-scroll" tabindex="0" :aria-label="`${sheet.label}引用表格`">
          <table :aria-label="sheet.label">
            <caption>{{ sheet.label }}</caption>
            <thead>
              <tr><th scope="col">行</th><th v-for="column in sheet.columns" :key="column" scope="col">{{ column }}</th></tr>
            </thead>
            <tbody>
              <tr v-for="row in sheet.rows" :key="row.number" :class="{ 'excel-source-header-row': row.number === 1 }">
                <th scope="row">{{ row.number }}</th>
                <td v-for="cell in row.cells" :key="cell.coordinate" :data-cell="cell.coordinate" :title="cell.coordinate"
                  :class="{ 'excel-source-number': numeric(cell.value), 'excel-source-formula': cell.value.startsWith('=') }">{{ cell.value }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </template>
    <div v-else class="excel-source-text">{{ content }}</div>
  </div>
</template>

<style scoped>
.excel-source { min-width: 0; max-width: 100%; box-sizing: border-box; }
.excel-source-sheet + .excel-source-sheet { margin-top: 18px; }
.excel-source-text { white-space: pre-wrap; overflow-wrap: anywhere; line-height: 1.8; }
.excel-source-text + .excel-source-scroll { margin-top: 12px; }
.excel-source-scroll { max-width: 100%; max-height: 420px; overflow: auto; border: 1px solid #e4e7ed; border-radius: 6px; }
.excel-source-scroll:focus-visible { outline: 2px solid #f39800; outline-offset: 2px; }
table { width: max-content; min-width: 100%; border-collapse: separate; border-spacing: 0; font-size: 13px; line-height: 1.6; }
caption { padding: 10px 12px; text-align: left; font-weight: 600; background: #fff8ee; color: #806039; }
th, td { padding: 7px 10px; border-right: 1px solid #e4e7ed; border-bottom: 1px solid #e4e7ed; }
th { min-width: 32px; background: #f6f8fa; color: #727b88; text-align: center; font-weight: 500; }
thead th { position: sticky; top: 0; z-index: 1; }
th:first-child { position: sticky; left: 0; z-index: 1; }
thead th:first-child { z-index: 2; }
td { min-width: 88px; max-width: 260px; white-space: pre-wrap; overflow-wrap: anywhere; vertical-align: top; color: #30343b; }
tr > :last-child { border-right: 0; }
tbody tr:last-child > * { border-bottom: 0; }
.excel-source-header-row td { font-weight: 600; background: #fafbfc; }
.excel-source-number { text-align: right; font-variant-numeric: tabular-nums; }
.excel-source-formula { font-family: ui-monospace, monospace; }
</style>
