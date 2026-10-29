<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import {
  createUniver, defaultTheme, LocaleType,
  HorizontalAlign, VerticalAlign, WrapStrategy, BorderStyleTypes, TextDecoration,
} from "@univerjs/presets";
import { UniverSheetsCorePreset } from "@univerjs/preset-sheets-core";
import zhCN from "@univerjs/preset-sheets-core/locales/zh-CN";
import "@univerjs/preset-sheets-core/lib/index.css";

export interface ExcelCell {
  value: string | number | boolean | null;
  formula?: string | null;
  style?: Record<string, unknown>;
  hyperlink?: string | null;
  comment?: string | null;
}
export interface ExcelSheet {
  id: string;
  name: string;
  row_count: number;
  column_count: number;
  cells: Record<string, ExcelCell>;
  merges?: Array<{ start_row: number; start_col: number; end_row: number; end_col: number }>;
  row_heights?: Record<string, number>;
  column_widths?: Record<string, number>;
  hidden_rows?: string[];
  hidden_columns?: string[];
  freeze_pane?: string | null;
}
export interface ExcelWorkbook {
  sheets: ExcelSheet[];
  active_sheet?: string | null;
}

const props = withDefaults(
  defineProps<{
    workbook: ExcelWorkbook;
    title?: string;
    readonly?: boolean;
    disabled?: boolean;
    saveDocument?: () => Promise<boolean>;
  }>(),
  { title: "Excel 表格", readonly: false, disabled: false }
);
const emit = defineEmits<{ change: [workbook: ExcelWorkbook] }>();
const container = ref<HTMLElement | null>(null);
let univer: any = null;
let univerAPI: any = null;
let workbookApi: any = null;
let commandSubscription: { dispose?: () => void } | null = null;
let changeTimer: number | undefined;
let initTimer: number | undefined;
let initialized = false;

// The API uses Excel names; Univer stores numeric enums. Keep both directions
// explicit, including numeric values in drafts saved by older editor versions.
const horizontalAlignments: Record<string, number> = {
  left: HorizontalAlign.LEFT, center: HorizontalAlign.CENTER, right: HorizontalAlign.RIGHT,
  justify: HorizontalAlign.JUSTIFIED, distributed: HorizontalAlign.DISTRIBUTED,
};
const verticalAlignments: Record<string, number> = {
  top: VerticalAlign.TOP, center: VerticalAlign.MIDDLE, bottom: VerticalAlign.BOTTOM,
};
const borderStyles: Record<string, number> = {
  thin: BorderStyleTypes.THIN, hair: BorderStyleTypes.HAIR, dotted: BorderStyleTypes.DOTTED,
  dashed: BorderStyleTypes.DASHED, dashDot: BorderStyleTypes.DASH_DOT,
  dashDotDot: BorderStyleTypes.DASH_DOT_DOT, double: BorderStyleTypes.DOUBLE,
  medium: BorderStyleTypes.MEDIUM, mediumDashed: BorderStyleTypes.MEDIUM_DASHED,
  mediumDashDot: BorderStyleTypes.MEDIUM_DASH_DOT, mediumDashDotDot: BorderStyleTypes.MEDIUM_DASH_DOT_DOT,
  slantDashDot: BorderStyleTypes.SLANT_DASH_DOT, thick: BorderStyleTypes.THICK,
};
const underlineStyles: Record<string, number> = {
  single: TextDecoration.SINGLE, double: TextDecoration.DOUBLE,
  singleAccounting: TextDecoration.SINGLE_ACCOUNTING, doubleAccounting: TextDecoration.DOUBLE_ACCOUNTING,
};
function enumValue(values: Record<string, number>, value: unknown) {
  if (typeof value === "number") return Object.values(values).includes(value) ? value : undefined;
  return typeof value === "string" ? values[value] : undefined;
}
function enumName(values: Record<string, number>, value: unknown) {
  if (typeof value === "string" && value in values) return value;
  return Object.entries(values).find(([, number]) => number === value)?.[0] || null;
}

function colorStyle(value: unknown) {
  if (typeof value !== "string") return undefined;
  const normalized = value.trim().replace(/^#/, "");
  if (!/^(?:[0-9a-f]{6}|[0-9a-f]{8})$/i.test(normalized)) return undefined;
  // Excel uses ARGB; Univer's renderer expects a CSS color.
  return { rgb: `#${normalized.slice(-6)}` };
}

function toUniverStyle(style: Record<string, any> | undefined) {
  if (!style) return undefined;
  const font = style.font || {};
  const fill = style.fill || {};
  const alignment = style.alignment || {};
  const border = style.border || {};
  const result: Record<string, any> = {
    ff: font.name || undefined,
    fs: typeof font.size === "number" ? font.size : undefined,
    bl: font.bold ? 1 : 0,
    it: font.italic ? 1 : 0,
    ul: { s: font.underline ? 1 : 0, t: underlineStyles[font.underline] ?? TextDecoration.SINGLE },
    st: { s: font.strike ? 1 : 0 },
    cl: colorStyle(font.color),
    bg: fill.type ? colorStyle(fill.color) : undefined,
    ht: enumValue(horizontalAlignments, alignment.horizontal),
    vt: enumValue(verticalAlignments, alignment.vertical),
    tb: alignment.wrap_text ? WrapStrategy.WRAP : WrapStrategy.OVERFLOW,
    tr: {
      a: alignment.text_rotation === 255 ? 0 : alignment.text_rotation > 90 ? 90 - alignment.text_rotation : alignment.text_rotation || 0,
      v: alignment.text_rotation === 255 ? 1 : 0,
    },
    n: style.number_format ? { pattern: style.number_format } : undefined,
  };
  const sides: Record<string, string> = { top: "t", right: "r", bottom: "b", left: "l" };
  const borderData: Record<string, any> = {};
  for (const [name, key] of Object.entries(sides)) {
    const side = border[name] || {};
    const borderStyle = enumValue(borderStyles, side.style);
    if (borderStyle !== undefined) borderData[key] = { s: borderStyle, cl: colorStyle(side.color) || { rgb: "#000000" } };
  }
  if (Object.keys(borderData).length) result.bd = borderData;
  return Object.fromEntries(Object.entries(result).filter(([, value]) => value !== undefined));
}

function columnLabel(index: number) {
  let result = "";
  let current = index + 1;
  while (current) {
    current -= 1;
    result = String.fromCharCode(65 + (current % 26)) + result;
    current = Math.floor(current / 26);
  }
  return result;
}

function parseFreeze(value: string | null | undefined) {
  if (!value) return { xSplit: 0, ySplit: 0, startRow: -1, startColumn: -1 };
  const match = /^([A-Z]+)(\d+)$/i.exec(value);
  if (!match) return { xSplit: 0, ySplit: 0, startRow: -1, startColumn: -1 };
  let column = 0;
  for (const char of match[1]!.toUpperCase()) column = column * 26 + char.charCodeAt(0) - 64;
  const row = Number(match[2]);
  return {
    xSplit: Math.max(0, column - 1),
    ySplit: Math.max(0, row - 1),
    startRow: Math.max(0, row - 1),
    startColumn: Math.max(0, column - 1),
  };
}

function toUniverWorkbook(source: ExcelWorkbook) {
  const sheets: Record<string, any> = {};
  const sheetOrder = source.sheets.map((sheet, index) => {
    const id = sheet.id || `sheet${index + 1}`;
    const cellData: Record<string, Record<string, any>> = {};
    for (const [coordinate, payload] of Object.entries(sheet.cells || {})) {
      const [row, column] = coordinate.split(",").map(Number);
      if (!Number.isInteger(row) || !Number.isInteger(column) || !payload) continue;
      cellData[row] ||= {};
      cellData[row][column] = {
        // XLSX files saved by openpyxl keep formulas without cached results.
        // Univer recalculates empty caches on load; a synthetic zero skips it.
        v: payload.value,
        f: payload.formula || undefined,
        s: toUniverStyle(payload.style),
      };
    }
    const rowData: Record<string, any> = {};
    for (const [row, height] of Object.entries(sheet.row_heights || {}))
      rowData[row] = { h: height };
    const columnData: Record<string, any> = {};
    for (const [column, width] of Object.entries(sheet.column_widths || {})) {
      let columnIndex = 0;
      for (const char of column.toUpperCase())
        columnIndex = columnIndex * 26 + char.charCodeAt(0) - 64;
      columnData[Math.max(0, columnIndex - 1)] = { w: width };
    }
    for (const row of sheet.hidden_rows || []) rowData[row] = { ...(rowData[row] || {}), hd: 1 };
    for (const column of sheet.hidden_columns || []) {
      let columnIndex = 0;
      for (const char of column.toUpperCase())
        columnIndex = columnIndex * 26 + char.charCodeAt(0) - 64;
      columnData[Math.max(0, columnIndex - 1)] = {
        ...(columnData[Math.max(0, columnIndex - 1)] || {}),
        hd: 1,
      };
    }
    sheets[id] = {
      id,
      name: sheet.name,
      tabColor: "",
      hidden: 0,
      freeze: parseFreeze(sheet.freeze_pane),
      rowCount: Math.max(100, sheet.row_count || 1),
      columnCount: Math.max(26, sheet.column_count || 1),
      zoomRatio: 1,
      scrollTop: 0,
      scrollLeft: 0,
      defaultColumnWidth: 100,
      defaultRowHeight: 20,
      mergeData: (sheet.merges || []).map((merge) => ({
        startRow: merge.start_row,
        startColumn: merge.start_col,
        endRow: merge.end_row,
        endColumn: merge.end_col,
      })),
      cellData,
      rowData,
      columnData,
      rowHeader: { width: 46 },
      columnHeader: { height: 20 },
      showGridlines: 1,
      rightToLeft: 0,
    };
    return id;
  });
  return {
    id: `workbook-${crypto.randomUUID()}`,
    name: props.title || "Excel 表格",
    appVersion: "1.0.0",
    locale: LocaleType.ZH_CN,
    styles: {},
    sheetOrder,
    sheets,
  };
}

function fromUniverStyle(style: any) {
  if (!style || typeof style !== "object") return {};
  const color = (value: any) => value?.rgb || value?.color || undefined;
  return {
    font: {
      name: style.ff || null,
      size: style.fs || null,
      bold: !!style.bl,
      italic: !!style.it,
      underline: style.ul?.s ? enumName(underlineStyles, style.ul.t) || "single" : null,
      strike: !!style.st?.s,
      color: color(style.cl),
    },
    fill: { type: style.bg ? "solid" : null, color: color(style.bg) },
    alignment: {
      horizontal: style.ht === HorizontalAlign.BOTH ? "justify" : enumName(horizontalAlignments, style.ht),
      vertical: enumName(verticalAlignments, style.vt),
      wrap_text: style.tb === WrapStrategy.WRAP,
      text_rotation: style.tr?.v ? 255 : style.tr?.a < 0 ? 90 - style.tr.a : style.tr?.a || 0,
    },
    border: Object.fromEntries(
      Object.entries({ left: "l", right: "r", top: "t", bottom: "b" }).map(([name, key]) => [
        name,
        { style: enumName(borderStyles, style.bd?.[key]?.s), color: color(style.bd?.[key]?.cl) },
      ])
    ),
    number_format: style.n?.pattern || "General",
  };
}

function fromUniverWorkbook(snapshot: any): ExcelWorkbook {
  const sheets = (snapshot.sheetOrder || []).map((id: string) => {
    const sheet = snapshot.sheets[id] || {};
    const cells: Record<string, ExcelCell> = {};
    for (const [row, columns] of Object.entries(sheet.cellData || {})) {
      for (const [column, payload] of Object.entries((columns || {}) as Record<string, any>)) {
        const cell = payload as any;
        if (cell.v == null && !cell.f && !cell.s) continue;
        cells[`${row},${column}`] = {
          value: cell.v ?? null,
          formula: cell.f || null,
          style: fromUniverStyle(typeof cell.s === "string" ? snapshot.styles?.[cell.s] : cell.s),
        };
      }
    }
    const merges = (sheet.mergeData || []).map((merge: any) => ({
      start_row: merge.startRow,
      start_col: merge.startColumn,
      end_row: merge.endRow,
      end_col: merge.endColumn,
    }));
    const rowHeights: Record<string, number> = {};
    for (const [row, data] of Object.entries(sheet.rowData || {}))
      if ((data as any).h) rowHeights[row] = (data as any).h;
    const columnWidths: Record<string, number> = {};
    for (const [column, data] of Object.entries(sheet.columnData || {}))
      if ((data as any).w) columnWidths[columnLabel(Number(column))] = (data as any).w;
    const freeze =
      sheet.freeze?.xSplit || sheet.freeze?.ySplit
        ? `${columnLabel(sheet.freeze.xSplit || 0)}${(sheet.freeze.ySplit || 0) + 1}`
        : null;
    return {
      id,
      name: sheet.name || id,
      row_count: sheet.rowCount || 1,
      column_count: sheet.columnCount || 1,
      cells,
      merges,
      row_heights: rowHeights,
      column_widths: columnWidths,
      hidden_rows: Object.entries(sheet.rowData || {})
        .filter(([, data]) => (data as any).hd)
        .map(([row]) => row),
      hidden_columns: Object.entries(sheet.columnData || {})
        .filter(([, data]) => (data as any).hd)
        .map(([column]) => columnLabel(Number(column))),
      freeze_pane: freeze,
    };
  });
  return { sheets, active_sheet: snapshot.sheetOrder?.[0] || null };
}

function emitChange() {
  if (!initialized || props.readonly || props.disabled || !workbookApi) return;
  window.clearTimeout(changeTimer);
  changeTimer = window.setTimeout(
    () => emit("change", fromUniverWorkbook(workbookApi.save())),
    100
  );
}

function initialize() {
  if (!container.value) return;
  destroy();
  const containerId = `univer-container-${crypto.randomUUID()}`;
  container.value.id = containerId;
  const result = createUniver({
    locale: LocaleType.ZH_CN,
    locales: { [LocaleType.ZH_CN]: zhCN },
    theme: defaultTheme,
    presets: [
      UniverSheetsCorePreset({
        container: containerId,
        header: true,
        toolbar: true,
        contextMenu: true,
        footer: {},
      }),
    ],
  });
  univer = result.univer;
  univerAPI = result.univerAPI;
  const workbookData = toUniverWorkbook(props.workbook);
  initTimer = window.setTimeout(() => {
    if (!univerAPI) return;
    workbookApi = univerAPI.createWorkbook({ ...workbookData, dateSystem: "date1900", resources: [] }, { makeCurrent: true });
    if (props.readonly) {
      void Promise.all(
        workbookApi.getSheets().map((sheet: any) => sheet.getWorksheetPermission()?.setMode("readOnly"))
      ).catch(() => undefined);
    }
    commandSubscription = workbookApi.onCommandExecuted(() => emitChange());
    initialized = true;
    nextTick(() => {
      if (!props.readonly && !props.disabled && workbookApi) {
        emit("change", fromUniverWorkbook(workbookApi.save()));
      }
    });
  }, 400);
}

function snapshot() {
  return workbookApi ? fromUniverWorkbook(workbookApi.save()) : props.workbook;
}
function fullscreen() {
  container.value?.requestFullscreen?.();
}
function destroy() {
  initialized = false;
  window.clearTimeout(initTimer);
  window.clearTimeout(changeTimer);
  commandSubscription?.dispose?.();
  commandSubscription = null;
  if (workbookApi && univerAPI) univerAPI.disposeUnit(workbookApi.getId());
  univer?.dispose?.();
  workbookApi = null;
  univerAPI = null;
  univer = null;
}
defineExpose({ snapshot, fullscreen });
watch(() => props.workbook, initialize, { deep: false });
onMounted(initialize);
onBeforeUnmount(destroy);
</script>

<template>
  <div
    ref="container"
    class="excel-editor"
    :class="{ 'excel-editor-readonly': readonly || disabled }"
    aria-label="Excel 表格编辑器"
    @keydown="emitChange"
    @paste="emitChange"
  ></div>
</template>

<style scoped>
.excel-editor {
  min-height: 560px;
  height: min(72vh, 760px);
  width: 100%;
  overflow: hidden;
  background: #fff;
}
.excel-editor-readonly {
  user-select: text;
}
</style>
