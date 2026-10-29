<script setup lang="ts">
import {
  computed,
  defineAsyncComponent,
  onBeforeUnmount,
  onMounted,
  reactive,
  ref,
  watch,
} from "vue";
import { onBeforeRouteLeave, useRoute } from "vue-router";
import type { JSONContent } from "@tiptap/core";
const WordEditor = defineAsyncComponent(() => import("../components/WordEditor.vue"));
const ExcelEditor = defineAsyncComponent(() => import("../components/ExcelEditor.vue"));
import type { ExcelWorkbook } from "../components/ExcelEditor.vue";
import { ElMessage, ElMessageBox } from "element-plus";
import {
  Download,
  Edit,
  FolderOpened,
  Plus,
  Refresh,
  Search,
  View,
  Delete,
  RefreshRight,
} from "@element-plus/icons-vue";
import { api, uploadFile } from "../lib/session";
import { queryParams } from "../lib/query";
import WordContent from "../components/WordContent.vue";
import { renderMarkdown } from "../lib/markdown";

const route = useRoute();
interface KnowledgeBase {
  id: string;
  name: string;
  code: string;
  status: string;
}
interface Version {
  id: string;
  version_no: number;
  filename: string;
  content_type: string | null;
  file_size: number;
  status: string;
  chunk_count: number;
  error_message: string | null;
  created_at: string;
  task: Task | null;
}
interface DocumentRow {
  created_by_name: string;
  updated_by_name: string;
  id: string;
  knowledge_base_id: string;
  title: string;
  status: string;
  current_version_id: string | null;
  updated_at: string;
  current_version: Version | null;
}
interface DocumentDetail extends DocumentRow {
  versions: Version[];
}
interface Task {
  id: string;
  status: string;
  task_type: string;
  error_message: string | null;
}
interface UploadTicket {
  version: Version;
  document: DocumentRow;
  upload_url: string;
  required_headers: Record<string, string>;
}

const maxFileSize = ref(200 * 1024 * 1024);
const bases = ref<KnowledgeBase[]>([]);
const selectedBase = ref("");
const rows = ref<DocumentRow[]>([]);
const total = ref(0);
const page = ref(1);
const loading = ref(false);
const error = ref("");
const filters = reactive({ q: "", status: "" });
const applied = reactive({ q: "", status: "" });

const uploadOpen = ref(false);
const uploadBusy = ref(false);
const uploadError = ref("");
const selectedFile = ref<File | null>(null);
const fileInput = ref<HTMLInputElement>();
const uploadTitle = ref("");

const replaceOpen = ref(false);
const replaceBusy = ref(false);
const replaceError = ref("");
const replacementFile = ref<File | null>(null);
const replacementInput = ref<HTMLInputElement>();

const detailOpen = ref(false);
const detailBusy = ref(false);
const detailError = ref("");
const detail = ref<DocumentDetail | null>(null);
const selectedVersionId = ref("");
const previewText = ref("");
const previewHtml = ref("");
const previewUrl = ref("");
const previewKind = ref<"text" | "image" | "video" | "pdf" | "excel" | "download">("text");
const editing = ref(false);
const editorText = ref("");
const editorBusy = ref(false);
const wordContent = ref<JSONContent>({ type: "doc", content: [] });
const emptyWorkbook = (): ExcelWorkbook => ({
  sheets: [{ id: "sheet1", name: "Sheet1", row_count: 100, column_count: 26, cells: {} }],
  active_sheet: "sheet1",
});
const excelWorkbook = ref<ExcelWorkbook>(emptyWorkbook());
const excelLatest = ref<ExcelWorkbook>(excelWorkbook.value);
const excelEditor = ref<{ snapshot(): ExcelWorkbook } | null>(null);
const editBaseId = ref("");
const editBaseline = ref("");
const wordReady = ref(false);
const excelReady = ref(false);
let saveAttempt: { payload: string; id: string } | null = null;
const isWord = computed(() => extension(selectedVersion.value?.filename || "") === ".docx");
const isExcel = computed(() =>
  [".xls", ".xlsx"].includes(extension(selectedVersion.value?.filename || ""))
);
const canEdit = computed(() => isText.value || isWord.value || isExcel.value);
function excelEditSignature(workbook: ExcelWorkbook) {
  // Formula results are derived data. Recalculation after loading a workbook
  // must not mark an otherwise untouched document as edited.
  return JSON.stringify(workbook, function (key, value) {
    return key === "value" && this.formula ? null : value;
  });
}
const dirty = computed(
  () =>
    editing.value &&
    (isWord.value
      ? JSON.stringify(wordContent.value) !== editBaseline.value
      : isExcel.value
        ? excelEditSignature(excelLatest.value) !== editBaseline.value
        : editorText.value !== previewText.value)
);
function updateWord(content: JSONContent) {
  wordContent.value = content;
  if (!wordReady.value) {
    editBaseline.value = JSON.stringify(content);
    wordReady.value = true;
  }
}
function updateExcel(workbook: ExcelWorkbook) {
  excelLatest.value = workbook;
  if (!excelReady.value) {
    editBaseline.value = excelEditSignature(workbook);
    excelReady.value = true;
  }
}
async function discardEdits() {
  if (editorBusy.value) return false;
  if (editing.value && isExcel.value && excelEditor.value)
    excelLatest.value = excelEditor.value.snapshot();
  if (dirty.value) {
    try {
      await ElMessageBox.confirm("放弃尚未保存的修改？", "未保存的文档", {
        confirmButtonText: "放弃修改",
        cancelButtonText: "继续编辑",
        type: "warning",
      });
    } catch {
      return false;
    }
  }
  editing.value = false;
  return true;
}
async function closeDetail(done: () => void) {
  if (await discardEdits()) done();
}
function beforeUnload(event: BeforeUnloadEvent) {
  if (dirty.value || editorBusy.value) {
    event.preventDefault();
    event.returnValue = "";
  }
}
onBeforeRouteLeave(discardEdits);
onMounted(() => window.addEventListener("beforeunload", beforeUnload));
onBeforeUnmount(() => window.removeEventListener("beforeunload", beforeUnload));

let indexPollTimer: number | null = null;
let indexPollAttempts = 0;

const renderedPreviewHtml = computed(() => {
  if (!previewText.value) return "";
  return renderMarkdown(previewText.value);
});
const renderedEditorPreviewHtml = computed(() => {
  if (!editorText.value) return "";
  return renderMarkdown(editorText.value);
});

const selectedVersion = computed(
  () => detail.value?.versions.find((v) => v.id === selectedVersionId.value) || null
);
const isText = computed(
  () =>
    !!selectedVersion.value &&
    [".md", ".markdown", ".txt"].includes(extension(selectedVersion.value.filename))
);

function extension(filename: string) {
  return filename.slice(filename.lastIndexOf(".")).toLowerCase();
}

function formatTime(value: string) {
  return new Date(value).toLocaleString("zh-CN", { hour12: false });
}

function formatSize(value: number) {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}

function statusLabel(status: string) {
  const map: Record<string, string> = {
    active: "启用",
    archived: "已归档",
    PENDING_UPLOAD: "等待上传",
    UPLOADED: "等待索引",
    PENDING: "排队索引",
    RUNNING: "索引中",
    PROCESSING: "处理中",
    EMBEDDING: "生成向量",
    INDEXED: "已就绪",
    SUCCESS: "已完成",
    FAILED: "失败",
    ARCHIVED: "已归档",
  };
  return map[status] ?? status;
}

function statusType(status: string) {
  if (["active", "INDEXED"].includes(status)) return "success";
  if (["FAILED", "archived", "ARCHIVED"].includes(status)) return "danger";
  if (
    ["PENDING", "RUNNING", "PROCESSING", "EMBEDDING", "UPLOADED", "PENDING_UPLOAD"].includes(status)
  )
    return "warning";
  return "info";
}

function versionDisplayStatus(version: Version | null) {
  if (!version) return "";
  if (version.task?.status === "FAILED") return "FAILED";
  if (version.task?.status === "RUNNING")
    return version.status === "EMBEDDING" ? "EMBEDDING" : "RUNNING";
  if (version.task?.status === "PENDING" && version.status === "UPLOADED") return "PENDING";
  return version.status;
}

function needsIndexPolling(row: DocumentRow) {
  const version = row.current_version;
  if (!version) return false;
  return (
    ["PENDING", "RUNNING"].includes(version.task?.status || "") ||
    ["UPLOADED", "PROCESSING", "EMBEDDING"].includes(version.status)
  );
}

function stopIndexPolling() {
  if (indexPollTimer !== null) window.clearTimeout(indexPollTimer);
  indexPollTimer = null;
  indexPollAttempts = 0;
}

function startIndexPolling() {
  stopIndexPolling();
  const poll = async () => {
    indexPollTimer = null;
    indexPollAttempts += 1;
    await loadDocuments();
    if (rows.value.some(needsIndexPolling) && indexPollAttempts < 60) {
      indexPollTimer = window.setTimeout(() => {
        void poll();
      }, 2000);
    } else {
      indexPollAttempts = 0;
    }
  };
  indexPollTimer = window.setTimeout(() => {
    void poll();
  }, 300);
}

async function loadBases() {
  const result = await api<{ items: KnowledgeBase[] }>(
    "/knowledge-bases?status=active&page=1&page_size=100"
  );
  bases.value = result.items.filter((base) => base.status === "active");
  const requested =
    typeof route.query.knowledge_base_id === "string" ? route.query.knowledge_base_id : "";
  if (requested && bases.value.some((b) => b.id === requested)) {
    selectedBase.value = requested;
  } else if (!selectedBase.value || !bases.value.some((b) => b.id === selectedBase.value)) {
    selectedBase.value = bases.value[0]?.id || "";
  }
}

async function loadDocuments() {
  if (!selectedBase.value) {
    rows.value = [];
    total.value = 0;
    return;
  }
  loading.value = true;
  error.value = "";
  try {
    const params = queryParams({
      page: String(page.value),
      page_size: "20",
      q: applied.q,
      status: applied.status,
    });
    const res = await api<{ items: DocumentRow[]; total: number; max_file_size?: number }>(
      `/knowledge-bases/${selectedBase.value}/documents?${params}`
    );
    if (res.max_file_size && res.max_file_size > 0) maxFileSize.value = res.max_file_size;
    rows.value = res.items;
    total.value = res.total;
  } catch (e) {
    error.value = (e as Error).message;
    rows.value = [];
  } finally {
    loading.value = false;
  }
}

function search() {
  applied.q = filters.q.trim();
  applied.status = filters.status;
  page.value = 1;
  void loadDocuments();
}

function chooseFile(event: Event) {
  const file = (event.target as HTMLInputElement).files?.[0];
  if (file && (file.size === 0 || file.size > maxFileSize.value)) {
    selectedFile.value = null;
    uploadError.value = `文件需非空，且不超过 ${formatSize(maxFileSize.value)}`;
    return;
  }
  selectedFile.value = file || null;
  uploadTitle.value = file?.name.replace(/\.[^.]+$/u, "") || "";
  uploadError.value = "";
}

function openUpload() {
  selectedFile.value = null;
  uploadTitle.value = "";
  uploadError.value = "";
  uploadOpen.value = true;
  if (fileInput.value) fileInput.value.value = "";
}

function chooseReplacementFile(event: Event) {
  const file = (event.target as HTMLInputElement).files?.[0] || null;
  replacementFile.value = file;
  replaceError.value = "";
  if (file && (file.size === 0 || file.size > maxFileSize.value)) {
    replacementFile.value = null;
    replaceError.value = `文件需非空，且不超过 ${formatSize(maxFileSize.value)}`;
  }
}

function openReplace() {
  replacementFile.value = null;
  replaceError.value = "";
  replaceOpen.value = true;
  if (replacementInput.value) replacementInput.value.value = "";
}

async function putToMinio(ticket: UploadTicket, file: Blob) {
  const resp = await fetch(ticket.upload_url, {
    method: "PUT",
    headers: ticket.required_headers,
    body: file,
    credentials: "omit",
  });
  if (!resp.ok) throw new Error(`对象存储上传失败（HTTP ${resp.status}）`);
}

async function completeUpload(ticket: UploadTicket, file: File) {
  try {
    await putToMinio(ticket, file);
  } catch {
    await uploadFile(
      `/documents/versions/${ticket.version.id}/upload`,
      file,
      file.type || ticket.required_headers["Content-Type"]
    );
    return;
  }
  await api(`/documents/complete`, {
    method: "POST",
    body: JSON.stringify({ version_id: ticket.version.id }),
  });
}

async function upload() {
  if (!selectedFile.value || !selectedBase.value || uploadBusy.value) return;
  uploadBusy.value = true;
  uploadError.value = "";
  try {
    const file = selectedFile.value;
    const ticket = await api<UploadTicket>("/documents/presign-upload", {
      method: "POST",
      body: JSON.stringify({
        knowledge_base_id: selectedBase.value,
        filename: file.name,
        title: uploadTitle.value.trim() || undefined,
        file_size: file.size,
        content_type: file.type || undefined,
      }),
    });
    await completeUpload(ticket, file);
    uploadOpen.value = false;
    ElMessage.success("文档已上传，等待索引任务处理");
    await loadDocuments();
    startIndexPolling();
  } catch (e) {
    uploadError.value = (e as Error).message;
  } finally {
    uploadBusy.value = false;
  }
}

async function openDocument(row: DocumentRow, startEditing = false) {
  detailOpen.value = true;
  detailBusy.value = true;
  detailError.value = "";
  editing.value = false;
  detail.value = null;
  try {
    detail.value = await api<DocumentDetail>(`/documents/${row.id}`);
    selectedVersionId.value = detail.value.current_version_id || detail.value.versions[0]?.id || "";
    await loadVersionContent();
    if (startEditing && canEdit.value) await beginEdit();
  } catch (e) {
    detailError.value = (e as Error).message;
  } finally {
    detailBusy.value = false;
  }
}

async function loadVersionContent() {
  if (!detail.value || !selectedVersionId.value) return;
  previewText.value = "";
  previewHtml.value = "";
  previewUrl.value = "";
  previewKind.value = "text";
  const version = selectedVersion.value;
  if (!version) return;
  try {
    if ([".md", ".markdown", ".txt"].includes(extension(version.filename))) {
      const res = await api<{ content: string }>(
        `/documents/${detail.value.id}/content?version_id=${version.id}`
      );
      previewText.value = res.content;
      editorText.value = res.content;
    } else if (extension(version.filename) === ".docx") {
      const res = await api<{ content: string; html?: string }>(
        `/documents/${detail.value.id}/text-preview?version_id=${version.id}`
      );
      previewText.value = res.content;
      previewHtml.value = res.html || "";
      previewKind.value = "text";
    } else if ([".xls", ".xlsx"].includes(extension(version.filename))) {
      const res = await api<{ workbook: ExcelWorkbook }>(
        `/documents/${detail.value.id}/excel-content?version_id=${version.id}`
      );
      excelWorkbook.value = res.workbook;
      excelLatest.value = res.workbook;
      previewKind.value = "excel";
    } else if (
      [".pdf", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".mp4", ".webm", ".mov"].includes(
        extension(version.filename)
      )
    ) {
      const res = await api<{ preview_url: string }>(
        `/documents/${detail.value.id}/preview-url?version_id=${version.id}`
      );
      previewUrl.value = res.preview_url;
      const ext = extension(version.filename);
      if ([".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"].includes(ext))
        previewKind.value = "image";
      else if ([".mp4", ".webm", ".mov"].includes(ext)) previewKind.value = "video";
      else if (ext === ".pdf") previewKind.value = "pdf";
      else previewKind.value = "download";
    } else {
      previewKind.value = "download";
    }
  } catch (e) {
    detailError.value = (e as Error).message;
  }
}

function changeVersion() {
  editing.value = false;
  void loadVersionContent();
}

async function downloadVersion(version?: Version | null) {
  const targetVersion = version ?? selectedVersion.value;
  if (!detail.value || !targetVersion) return;
  try {
    const params = new URLSearchParams({ version_id: targetVersion.id });
    const res = await api<{ download_url: string }>(
      `/documents/${detail.value.id}/download-url?${params}`
    );
    const link = document.createElement("a");
    link.href = res.download_url;
    link.download = targetVersion.filename;
    link.target = "_blank";
    link.click();
  } catch (e) {
    ElMessage.error((e as Error).message);
  }
}

async function beginEdit() {
  if (!detail.value || !selectedVersion.value || !canEdit.value || editorBusy.value) return;
  detailError.value = "";
  editorBusy.value = true;
  try {
    editBaseId.value = selectedVersion.value.id;
    saveAttempt = null;
    if (isWord.value) {
      const result = await api<{ content: JSONContent }>(
        `/documents/${detail.value.id}/word-content?version_id=${editBaseId.value}`
      );
      wordContent.value = result.content;
      editBaseline.value = JSON.stringify(result.content);
      wordReady.value = false;
    } else if (isExcel.value) {
      const result = await api<{ workbook: ExcelWorkbook }>(
        `/documents/${detail.value.id}/excel-content?version_id=${editBaseId.value}`
      );
      excelWorkbook.value = result.workbook;
      excelLatest.value = result.workbook;
      editBaseline.value = excelEditSignature(result.workbook);
      excelReady.value = false;
    } else {
      editorText.value = previewText.value;
    }
    editing.value = true;
  } catch (error) {
    detailError.value = (error as Error).message;
  } finally {
    editorBusy.value = false;
  }
}

async function saveEdit(): Promise<boolean> {
  if (!detail.value || !selectedVersion.value || editorBusy.value) return false;
  editorBusy.value = true;
  detailError.value = "";
  try {
    let versionId: string;
    if (isWord.value) {
      const body = { base_version_id: editBaseId.value, content: wordContent.value };
      const payload = JSON.stringify(body);
      if (!saveAttempt || saveAttempt.payload !== payload)
        saveAttempt = { payload, id: crypto.randomUUID() };
      const result = await api<{ version: Version }>(`/documents/${detail.value.id}/word-content`, {
        method: "POST",
        body: JSON.stringify({ ...body, request_id: saveAttempt.id }),
        timeoutMs: 120000,
      });
      versionId = result.version.id;
    } else if (isExcel.value) {
      excelLatest.value = excelEditor.value?.snapshot() || excelLatest.value;
      const body = { base_version_id: editBaseId.value, workbook: excelLatest.value };
      const payload = JSON.stringify(body);
      if (!saveAttempt || saveAttempt.payload !== payload)
        saveAttempt = { payload, id: crypto.randomUUID() };
      const result = await api<{ version: Version }>(
        `/documents/${detail.value.id}/excel-content`,
        {
          method: "POST",
          body: JSON.stringify({ ...body, request_id: saveAttempt.id }),
          timeoutMs: 120000,
        }
      );
      versionId = result.version.id;
    } else {
      const filename = selectedVersion.value.filename;
      const file = new File([editorText.value], filename, {
        type: selectedVersion.value.content_type || "text/markdown;charset=utf-8",
      });
      const ticket = await api<UploadTicket>("/documents/presign-upload", {
        method: "POST",
        body: JSON.stringify({
          knowledge_base_id: detail.value.knowledge_base_id,
          document_id: detail.value.id,
          base_version_id: editBaseId.value,
          filename,
          title: detail.value.title,
          file_size: file.size,
          content_type: file.type,
        }),
      });
      await completeUpload(ticket, file);
      versionId = ticket.version.id;
    }
    ElMessage.success("新版本已提交，等待索引完成");
    editing.value = false;
    await openDocument(detail.value, false);
    if (detail.value?.versions.some((v) => v.id === versionId)) {
      selectedVersionId.value = versionId;
      await loadVersionContent();
    }
    await loadDocuments();
    startIndexPolling();
    return true;
  } catch (e) {
    detailError.value = (e as Error).message;
    return false;
  } finally {
    editorBusy.value = false;
  }
}

async function replaceVersion() {
  if (!detail.value || !replacementFile.value || replaceBusy.value) return;
  const baseVersionId = detail.value.current_version_id || detail.value.versions[0]?.id;
  if (!baseVersionId) {
    replaceError.value = "文档没有可替换的基础版本";
    return;
  }
  replaceBusy.value = true;
  replaceError.value = "";
  try {
    const file = replacementFile.value;
    const ticket = await api<UploadTicket>("/documents/presign-upload", {
      method: "POST",
      body: JSON.stringify({
        knowledge_base_id: detail.value.knowledge_base_id,
        document_id: detail.value.id,
        base_version_id: baseVersionId,
        filename: file.name,
        title: detail.value.title,
        file_size: file.size,
        content_type: file.type || undefined,
      }),
    });
    await completeUpload(ticket, file);
    replaceOpen.value = false;
    ElMessage.success("新版本已提交，等待索引完成");
    await openDocument(detail.value, false);
    if (detail.value?.versions.some((v) => v.id === ticket.version.id)) {
      selectedVersionId.value = ticket.version.id;
      await loadVersionContent();
    }
    await loadDocuments();
    startIndexPolling();
  } catch (e) {
    replaceError.value = (e as Error).message;
  } finally {
    replaceBusy.value = false;
  }
}

async function reindex(row: DocumentRow) {
  try {
    await ElMessageBox.confirm("将重新处理当前版本，确认继续吗？", "重新索引", { type: "warning" });
    const res = await api<{ task: Task }>(`/documents/${row.id}/reindex`, {
      method: "POST",
      body: "{}",
    });
    ElMessage.success(`任务已创建：${res.task.id.slice(0, 8)}`);
    await loadDocuments();
    startIndexPolling();
  } catch (e) {
    if (e !== "cancel") ElMessage.error((e as Error).message);
  }
}

async function archive(row: DocumentRow) {
  try {
    await ElMessageBox.confirm(
      "归档后文档不再作为当前内容使用，历史版本会保留。确认归档吗？",
      "归档文档",
      { type: "warning" }
    );
    await api(`/documents/${row.id}`, { method: "DELETE" });
    ElMessage.success("文档已归档，清理任务已创建");
    await loadDocuments();
  } catch (e) {
    if (e !== "cancel") ElMessage.error((e as Error).message);
  }
}

watch(selectedBase, () => {
  page.value = 1;
  stopIndexPolling();
  void loadDocuments();
});

onMounted(async () => {
  try {
    await loadBases();
    await loadDocuments();
  } catch (e) {
    error.value = (e as Error).message;
  }
});

onBeforeUnmount(stopIndexPolling);
</script>

<template>
  <div class="page-heading">
    <div>
      <div class="page-eyebrow">DOCUMENT LIBRARY</div>
      <h1>文档管理</h1>
      <p>按知识库管理原始文件、版本和索引状态。</p>
    </div>
    <el-button
      type="primary"
      :icon="Plus"
      :disabled="!selectedBase"
      @click="openUpload"
    >
      上传文件
    </el-button>
  </div>

  <el-alert
    class="phase-notice"
    title="支持 Markdown、TXT、DOCX 和 Excel 在线编辑，保存后生成新版本；其他文件可预览、下载并上传新版本。"
    type="info"
    :closable="false"
    show-icon
  />
  <el-alert
    v-if="!loading && !bases.length"
    class="phase-notice"
    title="当前没有可用知识库，请先在知识库管理中创建并启用知识库。"
    type="warning"
    :closable="false"
    show-icon
  />
  <el-alert
    v-if="error"
    :title="error"
    type="error"
    :closable="false"
    show-icon
  />

  <el-card
    shadow="never"
    class="resource-card"
  >
    <div class="table-toolbar">
      <el-select
        v-model="selectedBase"
        placeholder="选择知识库"
        style="min-width: 220px"
      >
        <el-option
          v-for="base in bases"
          :key="base.id"
          :label="`${base.name}（${base.code}）`"
          :value="base.id"
        />
      </el-select>
      <el-input
        v-model="filters.q"
        :prefix-icon="Search"
        placeholder="搜索文档标题"
        clearable
        @keyup.enter="search"
        @clear="search"
      />
      <el-select
        v-model="filters.status"
        placeholder="全部状态"
        clearable
        value-on-clear=""
        @change="search"
      >
        <el-option
          label="有效"
          value="active"
        />
        <el-option
          label="已归档"
          value="archived"
        />
      </el-select>
      <el-button
        type="primary"
        plain
        @click="search"
      >
        搜索
      </el-button>
      <el-button
        :icon="Refresh"
        :loading="loading"
        @click="loadDocuments"
      >
        刷新
      </el-button>
    </div>

    <el-table
      v-loading="loading"
      :data="rows"
      style="width: 100%"
      :min-height="360"
    >
      <el-table-column
        prop="title"
        label="文档标题"
        min-width="220"
        show-overflow-tooltip
      />
      <el-table-column
        label="当前版本"
        width="120"
      >
        <template #default="{ row }">
          {{ row.current_version ? `v${row.current_version.version_no}` : "—" }}
        </template>
      </el-table-column>
      <el-table-column
        label="文件类型"
        width="120"
      >
        <template #default="{ row }">
          {{ row.current_version?.filename?.split(".").pop()?.toUpperCase() || "—" }}
        </template>
      </el-table-column>
      <el-table-column
        label="索引状态"
        width="130"
      >
        <template #default="{ row }">
          <el-tag :type="statusType(versionDisplayStatus(row.current_version) || row.status)">
            {{ statusLabel(versionDisplayStatus(row.current_version) || row.status) }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column
        label="创建人"
        min-width="130"
        show-overflow-tooltip
      >
        <template #default="{ row }">{{ row.created_by_name || "—" }}</template>
      </el-table-column>
      <el-table-column
        label="最后修改人"
        min-width="130"
        show-overflow-tooltip
      >
        <template #default="{ row }">{{ row.updated_by_name || "—" }}</template>
      </el-table-column>
      <el-table-column
        label="更新时间"
        width="180"
      >
        <template #default="{ row }">{{ formatTime(row.updated_at) }}</template>
      </el-table-column>
      <el-table-column
        label="操作"
        fixed="right"
        width="270"
      >
        <template #default="{ row }">
          <el-button
            link
            type="primary"
            :icon="View"
            @click="openDocument(row)"
          >
            预览
          </el-button>
          <el-button
            link
            type="primary"
            :icon="Edit"
            @click="openDocument(row, true)"
          >
            编辑
          </el-button>
          <el-button
            link
            :icon="RefreshRight"
            @click="reindex(row)"
          >
            重索引
          </el-button>
          <el-button
            link
            type="danger"
            :icon="Delete"
            @click="archive(row)"
          >
            归档
          </el-button>
        </template>
      </el-table-column>
      <template #empty>
        <el-empty
          :description="selectedBase ? '暂无文档' : '请先选择知识库'"
          :image-size="80"
        >
          <template #image>
            <el-icon
              :size="70"
              color="#c6c8ce"
            >
              <FolderOpened />
            </el-icon>
          </template>
        </el-empty>
      </template>
    </el-table>

    <div class="table-pagination">
      <span>共 {{ total }} 条记录</span>
      <el-pagination
        v-model:current-page="page"
        :page-size="20"
        :total="total"
        layout="prev, pager, next"
        @current-change="loadDocuments"
      />
    </div>
  </el-card>

  <el-dialog
    v-model="uploadOpen"
    title="上传知识库文件"
    width="520px"
    align-center
  >
    <el-alert
      v-if="uploadError"
      :title="uploadError"
      type="error"
      :closable="false"
      show-icon
    />
    <el-form label-position="top">
      <el-form-item label="所属知识库">
        <el-input
          :model-value="bases.find((base) => base.id === selectedBase)?.name || ''"
          disabled
        />
      </el-form-item>
      <el-form-item label="文档标题">
        <el-input
          v-model="uploadTitle"
          maxlength="255"
          placeholder="默认使用文件名"
        />
      </el-form-item>
      <el-form-item label="文件">
        <input
          ref="fileInput"
          type="file"
          accept=".md,.markdown,.txt,.pdf,.doc,.docx,.xls,.xlsx,.png,.jpg,.jpeg,.gif,.webp,.svg,.mp4,.webm,.mov,.avi"
          @change="chooseFile"
        />
        <div class="form-tip">
          单文件最大 {{ formatSize(maxFileSize) }}，文件上传后进入索引任务。
        </div>
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="uploadOpen = false">取消</el-button>
      <el-button
        type="primary"
        :loading="uploadBusy"
        :disabled="!selectedFile"
        @click="upload"
      >
        开始上传
      </el-button>
    </template>
  </el-dialog>

  <el-dialog
    v-model="replaceOpen"
    title="上传文档新版本"
    width="520px"
    align-center
  >
    <el-alert
      v-if="replaceError"
      :title="replaceError"
      type="error"
      :closable="false"
      show-icon
    />
    <el-alert
      title="新文件会保留为新版本，当前版本在索引成功前不会切换。"
      type="info"
      :closable="false"
      show-icon
    />
    <el-form label-position="top">
      <el-form-item label="文档">
        <el-input
          :model-value="detail?.title || ''"
          disabled
        />
      </el-form-item>
      <el-form-item label="新文件">
        <input
          ref="replacementInput"
          type="file"
          accept=".md,.markdown,.txt,.pdf,.doc,.docx,.xls,.xlsx,.png,.jpg,.jpeg,.gif,.webp,.svg,.mp4,.webm,.mov,.avi"
          @change="chooseReplacementFile"
        />
        <div class="form-tip">
          支持 Markdown、TXT、PDF、Word、Excel、图片和视频，单文件最大
          {{ formatSize(maxFileSize) }}。
        </div>
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="replaceOpen = false">取消</el-button>
      <el-button
        type="primary"
        :loading="replaceBusy"
        :disabled="!replacementFile"
        @click="replaceVersion"
      >
        上传新版本
      </el-button>
    </template>
  </el-dialog>

  <el-dialog
    v-model="detailOpen"
    title="文档详情"
    :before-close="closeDetail"
    :close-on-press-escape="!editing"
    fullscreen
    destroy-on-close
  >
    <el-alert
      v-if="detailError"
      :title="detailError"
      type="error"
      :closable="false"
      show-icon
    />
    <div
      v-loading="detailBusy"
      class="document-dialog"
      v-if="detail"
    >
      <div class="document-meta">
        <div>
          <h2>{{ detail.title }}</h2>
          <p>
            {{ detail.status === "active" ? "有效" : "已归档" }} · 创建人：{{
              detail.created_by_name || "—"
            }}
            · 最后修改人：{{ detail.updated_by_name || "—" }}
          </p>
        </div>
        <div class="document-actions">
          <el-select
            v-model="selectedVersionId"
            :disabled="editing || editorBusy"
            placeholder="选择版本"
            @change="changeVersion"
          >
            <el-option
              v-for="version in detail.versions"
              :key="version.id"
              :label="`v${version.version_no} · ${statusLabel(version.status)} · ${formatSize(version.file_size)}`"
              :value="version.id"
            />
          </el-select>
          <el-button
            v-if="detail.status === 'active'"
            :icon="Plus"
            :disabled="editing || editorBusy"
            @click="openReplace"
          >
            上传新版本
          </el-button>
          <el-button
            :icon="Download"
            @click="downloadVersion()"
          >
            下载
          </el-button>
          <el-button
            v-if="canEdit && !editing && detail.status === 'active'"
            :loading="editorBusy"
            type="primary"
            :icon="Edit"
            @click="beginEdit"
          >
            在线编辑
          </el-button>
        </div>
      </div>

      <section
        v-if="editing && isWord"
        class="word-edit-panel"
      >
        <p>编辑 DOCX 正文，保存为新版本。原版本可在版本历史中下载。</p>
        <WordEditor
          :key="editBaseId"
          :content="wordContent"
          :title="detail.title"
          :disabled="editorBusy"
          :save-document="saveEdit"
          @change="updateWord"
        />
      </section>
      <section
        v-else-if="editing && isExcel"
        class="excel-edit-panel"
      >
        <p>编辑 Excel 工作簿，保存为新版本。原版本可在版本历史中下载。</p>
        <ExcelEditor
          ref="excelEditor"
          :key="editBaseId"
          :workbook="excelWorkbook"
          :title="detail.title"
          :disabled="editorBusy"
          @change="updateExcel"
        />
        <!-- <div class="excel-edit-actions">
          <el-button
            type="primary"
            :loading="editorBusy"
            @click="saveEdit"
          >
            保存 Excel 新版本
          </el-button>
        </div> -->
      </section>
      <div
        v-else-if="editing"
        class="editor-layout"
      >
        <el-input
          v-model="editorText"
          type="textarea"
          :rows="20"
          resize="none"
        />
        <div class="markdown-preview">
          <div class="preview-label">实时预览</div>
          <div
            class="markdown-body"
            v-html="renderedEditorPreviewHtml"
          ></div>
        </div>
      </div>

      <WordContent
        v-else-if="previewKind === 'text' && previewHtml"
        class="document-preview"
        :html="previewHtml"
      />
      <div
        v-else-if="previewKind === 'text'"
        class="markdown-body document-preview"
        v-html="renderedPreviewHtml"
      ></div>
      <section
        v-else-if="previewKind === 'excel'"
        class="excel-preview"
      >
        <ExcelEditor
          :workbook="excelWorkbook"
          :title="detail.title"
          readonly
        />
      </section>
      <img
        v-else-if="previewKind === 'image'"
        class="file-preview-image"
        :src="previewUrl"
        alt="文档预览"
      />
      <video
        v-else-if="previewKind === 'video'"
        class="file-preview-video"
        controls
        :src="previewUrl"
      ></video>
      <iframe
        v-else-if="previewKind === 'pdf'"
        class="file-preview-frame"
        :src="previewUrl"
        title="PDF预览"
      ></iframe>
      <el-empty
        v-else
        description="该类型暂不支持在线预览，请下载后查看"
      />

      <el-divider />
      <h3>版本历史</h3>
      <el-table
        :data="detail.versions"
        size="small"
      >
        <el-table-column
          label="版本"
          width="90"
        >
          <template #default="{ row }">v{{ row.version_no }}</template>
        </el-table-column>
        <el-table-column
          prop="filename"
          label="文件名"
          min-width="180"
          show-overflow-tooltip
        />
        <el-table-column
          label="状态"
          width="110"
        >
          <template #default="{ row }">
            <el-tag :type="statusType(row.status)">{{ statusLabel(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column
          label="大小"
          width="100"
        >
          <template #default="{ row }">{{ formatSize(row.file_size) }}</template>
        </el-table-column>
        <el-table-column
          label="创建时间"
          width="170"
        >
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column
          label="操作"
          width="100"
        >
          <template #default="{ row }">
            <el-button
              link
              :icon="Download"
              @click="downloadVersion(row)"
            >
              下载
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>
    <template #footer>
      <div v-if="editing">
        <el-button
          :disabled="editorBusy"
          @click="discardEdits"
        >
          取消编辑
        </el-button>
        <el-button
          type="primary"
          :loading="editorBusy"
          @click="saveEdit"
        >
          保存为新版本
        </el-button>
      </div>
    </template>
  </el-dialog>
</template>

<style scoped>
.document-dialog {
  min-height: calc(100vh - 140px);
}
.document-meta {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 18px;
}
.document-meta h2 {
  margin: 0 0 6px;
}
.document-meta p {
  margin: 0;
  color: #8a8f98;
  font-size: 13px;
}
.document-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.document-actions .el-select {
  width: 320px;
}
.document-preview {
  min-height: 320px;
  padding: 24px;
  background: #fafafa;
  border: 1px solid #ebeef2;
  border-radius: 8px;
}

/* ========== 编辑布局核心修复：解决textarea高度只有一点点 ========== */
.editor-layout {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  height: calc(100vh - 340px);
  min-height: 520px;
}
.editor-layout :deep(.el-textarea) {
  height: 100% !important;
}
.editor-layout :deep(.el-input__wrapper) {
  height: 100% !important;
}
.editor-layout :deep(.el-textarea__inner) {
  height: 100% !important;
  min-height: unset !important;
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  line-height: 1.7;
  box-sizing: border-box;
}

.markdown-preview {
  min-height: 100%;
  padding: 24px 28px;
  overflow: auto;
  border: 1px solid #ebeef2;
  border-radius: 8px;
  background: #fff;
}
.preview-label {
  margin-bottom: 12px;
  color: #9a9da3;
  font-size: 12px;
  letter-spacing: 0.08em;
}
.markdown-body {
  color: #30343b;
  line-height: 1.8;
}
.markdown-body :deep(h1),
.markdown-body :deep(h2),
.markdown-body :deep(h3),
.markdown-body :deep(h4) {
  margin: 18px 0 8px;
  color: #16181c;
}
.markdown-body :deep(p) {
  margin: 0 0 12px;
}
.markdown-body :deep(code) {
  padding: 2px 5px;
  border-radius: 4px;
}
.markdown-body :deep(pre) {
  padding: 14px;
  overflow-x: auto;
  border-radius: 6px;
}
.markdown-body :deep(table) {
  border-collapse: collapse;
  width: 100%;
  margin-bottom: 16px;
}
.markdown-body :deep(th),
.markdown-body :deep(td) {
  border: 1px solid #ddd;
  padding: 6px 10px;
}
.markdown-body :deep(th) {
  background-color: #f5f7fa;
}

.file-preview-image {
  display: block;
  max-width: 100%;
  max-height: calc(100vh - 300px);
  margin: auto;
  object-fit: contain;
}
.file-preview-video {
  display: block;
  width: 100%;
  max-height: calc(100vh - 300px);
  background-color: #111;
}
.file-preview-frame {
  width: 100%;
  height: calc(100vh - 280px);
  border: 0;
}
.form-tip {
  margin-top: 8px;
  color: #8a8f98;
  font-size: 12px;
}

/* 小屏幕：改为上下堆叠，取消百分比高度 */
@media (max-width: 900px) {
  .document-meta {
    display: block;
  }
  .document-actions {
    margin-top: 14px;
  }
  .document-actions .el-select {
    width: 100%;
  }
  .editor-layout {
    grid-template-columns: 1fr;
    height: auto;
  }
  .editor-layout :deep(.el-textarea__inner) {
    min-height: 420px !important;
    height: auto !important;
  }
}
</style>
