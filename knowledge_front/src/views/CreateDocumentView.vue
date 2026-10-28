<script setup lang="ts">
import { computed, defineAsyncComponent, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { onBeforeRouteLeave, useRouter } from "vue-router";
import { ElMessage, ElMessageBox } from "element-plus";
import { Upload, Refresh, Plus, FullScreen } from "@element-plus/icons-vue";
import type { JSONContent } from "@tiptap/core";
const WordEditor = defineAsyncComponent(() => import("../components/WordEditor.vue"));
import MarkdownContent from "../components/MarkdownContent.vue";
import { api, ApiError, session } from "../lib/session";

interface Base { id: string; name: string; status: string }
interface SavedDocument {
  document: { id: string; title: string; knowledge_base_id: string };
  version: { filename: string; status: string; error_message: string | null; task: { status: string; error_message: string | null } | null };
}
const router = useRouter();
const format = ref<"md" | "docx">("md");
const title = ref("");
const markdown = ref("");
const wordContent = ref<JSONContent>({ type: "doc", content: [{ type: "paragraph" }] });
const wordText = ref("");
const selectedBase = ref("");
const bases = ref<Base[]>([]);
const basesLoading = ref(false);
const basesError = ref("");
const saving = ref(false);
const error = ref("");
const draftError = ref("");
const saved = ref<SavedDocument | null>(null);
const statusLoading = ref(false);
const statusError = ref("");
let disposed = false;
let pollTimer: number | undefined;
let pollAttempts = 0;
let statusGeneration = 0;
let attempt: { signature: string; id: string } | null = null;
const draftKey = `kbs-document-draft:${session.user?.id}`;

try {
  const stored = sessionStorage.getItem(draftKey);
  if (stored) {
    const draft = JSON.parse(stored);
    if (draft.format === "md" || draft.format === "docx") format.value = draft.format;
    if (typeof draft.title === "string") title.value = draft.title;
    if (typeof draft.markdown === "string") markdown.value = draft.markdown;
    if (draft.wordContent?.type === "doc") wordContent.value = draft.wordContent;
    if (typeof draft.selectedBase === "string") selectedBase.value = draft.selectedBase;
  }
} catch { draftError.value = "无法恢复浏览器草稿，请重新填写内容。"; }

const wordEditor = ref<{ reset(content: JSONContent): void; fullscreen(): void } | null>(null);
function updateWord(content: JSONContent, text: string) {
  wordContent.value = content;
  wordText.value = text;
}
const contentLength = computed(() => (format.value === "md" ? markdown.value : wordText.value).length);
const hasContent = computed(() => !!(format.value === "md" ? markdown.value : wordText.value).trim());
const dirty = computed(() => !saved.value && (!!title.value.trim() || hasContent.value));
const canSave = computed(() => !!title.value.trim() && hasContent.value && !!selectedBase.value && !saving.value && !saved.value && contentLength.value <= 200000);
const processing = computed(() => !!saved.value && ["UPLOADED", "PROCESSING", "EMBEDDING"].includes(saved.value.version.status) && saved.value.version.task?.status !== "FAILED");
const indexFailed = computed(() => saved.value?.version.status === "FAILED" || saved.value?.version.task?.status === "FAILED");
const documentLink = computed(() => session.pages.some(page => page.route_path === "/documents" && router.hasRoute(`page:${page.code}`)));

watch([format, title, markdown, wordContent, selectedBase], () => {
  if (saved.value) return;
  try {
    sessionStorage.setItem(draftKey, JSON.stringify({ format: format.value, title: title.value, markdown: markdown.value, wordContent: wordContent.value, selectedBase: selectedBase.value }));
    draftError.value = "";
  } catch { draftError.value = "浏览器草稿空间不足，请及时保存到知识库。"; }
}, { deep: true });

async function loadBases() {
  basesLoading.value = true;
  basesError.value = "";
  try {
    const all: Base[] = [];
    let page = 1;
    while (true) {
      const result = await api<{ items: Base[]; total?: number }>(`/knowledge-bases?status=active&page=${page}&page_size=100`);
      if (disposed) return;
      all.push(...result.items.filter(base => base.status === "active"));
      if (result.total == null || page * 100 >= result.total || !result.items.length) break;
      page += 1;
    }
    bases.value = all;
    if (!all.some(base => base.id === selectedBase.value)) selectedBase.value = "";
  } catch (value) { if (!disposed) basesError.value = (value as Error).message; }
  finally { if (!disposed) basesLoading.value = false; }
}
async function changeFormat(value: string | number | boolean | undefined) {
  if (value !== "md" && value !== "docx" || value === format.value || saving.value || saved.value) return;
  if (hasContent.value) {
    try { await ElMessageBox.confirm("切换格式会清空当前正文，标题和知识库选择会保留。", "切换文档格式", { confirmButtonText: "切换格式", cancelButtonText: "继续编辑", type: "warning" }); }
    catch { return; }
  }
  markdown.value = "";
  wordContent.value = { type: "doc", content: [{ type: "paragraph" }] };
  wordText.value = "";
  wordEditor.value?.reset(wordContent.value);
  format.value = value;
  error.value = "";
}
function requestId() {
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6]! & 15) | 64;
  bytes[8] = (bytes[8]! & 63) | 128;
  const hex = Array.from(bytes, byte => byte.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}
async function refreshStatus() {
  if (!saved.value || disposed || statusLoading.value) return;
  window.clearTimeout(pollTimer);
  const generation = statusGeneration;
  statusLoading.value = true;
  statusError.value = "";
  try {
    const result = await api<SavedDocument>(`/documents/created/${saved.value.document.id}`);
    if (!disposed && generation === statusGeneration) saved.value = result;
  } catch (value) { if (!disposed && generation === statusGeneration) statusError.value = (value as Error).message; }
  finally {
    if (!disposed && generation === statusGeneration) {
      statusLoading.value = false;
      if (processing.value && !statusError.value && ++pollAttempts < 60) pollTimer = window.setTimeout(refreshStatus, 2000);
    }
  }
}
async function save() {
  if (!canSave.value) {
    if (!saved.value && !saving.value) error.value = "请填写文档标题和正文，并选择知识库。";
    return false;
  }
  const body = { knowledge_base_id: selectedBase.value, title: title.value.trim(), format: format.value, content: format.value === "md" ? markdown.value : wordContent.value };
  const signature = JSON.stringify(body);
  if (attempt?.signature !== signature) attempt = { signature, id: requestId() };
  saving.value = true;
  error.value = "";
  try {
    const result = await api<SavedDocument>("/documents/create", { method: "POST", body: JSON.stringify({ ...body, request_id: attempt.id }), timeoutMs: 120000 });
    if (disposed) return false;
    saved.value = result;
    try { sessionStorage.removeItem(draftKey); } catch { /* The document is already saved. */ }
    ElMessage.success("文档已保存到知识库");
    pollAttempts = 0;
    pollTimer = window.setTimeout(refreshStatus, 2000);
    return true;
  } catch (value) {
    if (!disposed) error.value = (value as Error).message;
    if (value instanceof ApiError && value.code === 40901) attempt = null;
    return false;
  }
  finally { if (!disposed) saving.value = false; }
}
async function newDocument() {
  if (saving.value) return;
  if (dirty.value) {
    try { await ElMessageBox.confirm("当前草稿尚未保存，确定清空并新建文档？", "新建文档", { type: "warning", confirmButtonText: "新建文档", cancelButtonText: "继续编辑" }); }
    catch { return; }
  }
  window.clearTimeout(pollTimer);
  ++statusGeneration;
  statusLoading.value = false;
  saved.value = null;
  title.value = "";
  markdown.value = "";
  wordContent.value = { type: "doc", content: [{ type: "paragraph" }] };
  wordText.value = "";
  wordEditor.value?.reset(wordContent.value);
  error.value = "";
  statusError.value = "";
  attempt = null;
}
function beforeUnload(event: BeforeUnloadEvent) {
  if (dirty.value || saving.value) { event.preventDefault(); event.returnValue = ""; }
}
onBeforeRouteLeave(async () => {
  if (saving.value) { ElMessage.warning("正在保存，请稍候再离开"); return false; }
  if (!dirty.value) return true;
  try { await ElMessageBox.confirm("文档尚未保存到知识库，确定离开？草稿会保留在当前浏览器标签页。", "离开编辑页面", { confirmButtonText: "离开", cancelButtonText: "继续编辑" }); return true; }
  catch { return false; }
});
onMounted(() => { void loadBases(); window.addEventListener("beforeunload", beforeUnload); });
onBeforeUnmount(() => { disposed = true; window.clearTimeout(pollTimer); window.removeEventListener("beforeunload", beforeUnload); });
</script>

<template>
  <div class="page-heading">
    <div><div class="page-eyebrow">CREATE A DOCUMENT</div><h1>创建文档</h1><p>从空白开始记录知识，编写完成后保存到知识库。</p></div>
    <div class="authoring-actions">
      <el-button v-if="format === 'docx'" :icon="FullScreen" @click="wordEditor?.fullscreen()">全屏编辑</el-button>
      <el-button :icon="Plus" :disabled="saving" @click="newDocument">新建文档</el-button>
    </div>
  </div>
  <el-alert v-if="draftError" :title="draftError" type="warning" :closable="false" class="phase-notice" />
  <el-alert v-if="saved" :type="indexFailed ? 'warning' : 'success'" :closable="false" class="phase-notice" show-icon>
    <template #title>{{ saved.version.filename }} 已保存{{ saved.version.status === 'INDEXED' ? '，可用于知识问答' : indexFailed ? '，内容处理失败' : '，正在处理内容' }}</template>
    <p v-if="indexFailed">{{ saved.version.error_message || saved.version.task?.error_message }}</p>
    <p v-else-if="processing">处理完成后，知识库问答即可引用这份文档。</p>
    <el-button text :icon="Refresh" :loading="statusLoading" @click="refreshStatus">刷新状态</el-button>
    <el-button v-if="documentLink" text @click="router.push({ path: '/documents', query: { knowledge_base_id: saved.document.knowledge_base_id } })">查看知识库文档</el-button>
    <el-button text @click="newDocument">继续创建下一篇</el-button>
  </el-alert>
  <el-alert v-if="statusError" :title="statusError" type="error" :closable="false" class="phase-notice" />
  <el-card shadow="never" class="authoring-card">
    <div class="authoring-settings">
      <el-form label-position="top" class="authoring-form" @submit.prevent="save">
        <el-form-item label="文档标题" required><el-input v-model="title" aria-label="文档标题" placeholder="为文档起一个清晰的标题" maxlength="200" show-word-limit :disabled="saving || !!saved" /></el-form-item>
        <el-form-item label="保存到知识库" required>
          <el-select v-model="selectedBase" aria-label="保存到知识库" placeholder="选择知识库" filterable :loading="basesLoading" :disabled="saving || !!saved" no-data-text="暂无可用知识库">
            <el-option v-for="base in bases" :key="base.id" :value="base.id" :label="base.name" />
          </el-select>
        </el-form-item>
        <el-form-item label="文档格式"><el-radio-group :model-value="format" :disabled="saving || !!saved" @change="changeFormat"><el-radio-button value="md">Markdown</el-radio-button><el-radio-button value="docx">Word</el-radio-button></el-radio-group></el-form-item>
      </el-form>
      <el-alert v-if="basesError || (!basesLoading && !bases.length)" :title="basesError || '暂无可用知识库，请联系管理员创建并启用知识库。'" :type="basesError ? 'error' : 'info'" :closable="false"><el-button text @click="loadBases">重新加载</el-button></el-alert>
    </div>
    <div v-if="format === 'md'" class="markdown-editor-grid">
      <section><div class="editor-caption">Markdown 正文</div><el-input v-model="markdown" class="markdown-input" type="textarea" aria-label="Markdown 文档正文" :rows="22" placeholder="# 文档标题&#10;&#10;开始编写你的内容…" :disabled="saving || !!saved" resize="vertical" /></section>
      <section class="authoring-preview"><div class="editor-caption">实时预览</div><MarkdownContent v-if="markdown.trim()" :content="markdown" /><el-empty v-else description="编写内容后，在这里预览排版" :image-size="80" /></section>
    </div>
    <section v-else class="word-editor-section">
      <div class="word-save-note">草稿自动保留在当前标签页；点击“保存到知识库”后上传并入库。</div>
      <WordEditor ref="wordEditor" :content="wordContent" :title="title" :disabled="saving || !!saved" :save-document="save" @change="updateWord" />
    </section>
    <div class="authoring-footer"><span>{{ contentLength.toLocaleString() }} / 200,000 字符 · {{ saved ? '已保存' : '草稿保留在当前标签页' }}</span><el-button type="primary" :icon="Upload" :loading="saving" :disabled="!canSave" @click="save">保存到知识库</el-button></div>
    <el-alert v-if="error" :title="error" type="error" show-icon :closable="false" />
  </el-card>
</template>

<style scoped>
.authoring-card :deep(.el-card__body) { padding: 0; }
.authoring-settings { padding: 24px; border-bottom: 1px solid #edf0f3; }
.authoring-form { display: grid; grid-template-columns: minmax(220px, 1.5fr) minmax(180px, 1fr) auto; gap: 20px; }
.authoring-form .el-form-item { margin-bottom: 0; }
.authoring-form .el-select { width: 100%; }
.authoring-settings .el-alert { margin-top: 16px; }
.markdown-editor-grid { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); }
.markdown-editor-grid > section { min-width: 0; padding: 20px 24px; }
.markdown-editor-grid > section + section { border-left: 1px solid #edf0f3; }
.editor-caption { color: #8a909b; font-size: 12px; margin-bottom: 16px; }
.markdown-input :deep(textarea) { font-family: ui-monospace, monospace; line-height: 1.8; min-height: 480px; }
.authoring-preview { max-height: 720px; overflow: auto; }
.authoring-actions { display: flex; gap: 8px; flex-wrap: wrap; }
.authoring-actions .el-button { margin-left: 0; }
.word-save-note { padding: 10px 24px; font-size: 12px; color: #777f8b; background: #fafbfc; border-bottom: 1px solid #edf0f3; }
.word-editor-section { min-width: 0; }
.authoring-footer { display: flex; align-items: center; justify-content: space-between; gap: 16px; border-top: 1px solid #edf0f3; padding: 18px 24px; }
.authoring-footer span { font-size: 12px; color: #9097a1; }
@media (max-width: 1100px) { .authoring-form { grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); } .markdown-editor-grid { grid-template-columns: minmax(0, 1fr); } .markdown-editor-grid > section + section { border-left: 0; border-top: 1px solid #edf0f3; } }
@media (max-width: 600px) { .authoring-form { grid-template-columns: minmax(0, 1fr); } .authoring-footer { align-items: stretch; flex-direction: column; } }
</style>
