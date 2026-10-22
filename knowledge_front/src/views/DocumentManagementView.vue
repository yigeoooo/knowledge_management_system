<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
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
} from '@element-plus/icons-vue'
import { api, uploadFile } from '../lib/session'

const route = useRoute()

interface KnowledgeBase { id: string; name: string; code: string; status: string }
interface Version {
  id: string; version_no: number; filename: string; content_type: string | null; file_size: number
  status: string; chunk_count: number; error_message: string | null; created_at: string; task: Task | null
}
interface DocumentRow {
  id: string; knowledge_base_id: string; title: string; status: string
  current_version_id: string | null; updated_at: string; current_version: Version | null
}
interface DocumentDetail extends DocumentRow { versions: Version[] }
interface Task { id: string; status: string; task_type: string; error_message: string | null }
interface UploadTicket { version: Version; document: DocumentRow; upload_url: string; required_headers: Record<string, string> }

const bases = ref<KnowledgeBase[]>([])
const selectedBase = ref('')
const rows = ref<DocumentRow[]>([])
const total = ref(0)
const page = ref(1)
const loading = ref(false)
const error = ref('')
const filters = reactive({ q: '', status: '' })
const applied = reactive({ q: '', status: '' })

const uploadOpen = ref(false)
const uploadBusy = ref(false)
const uploadError = ref('')
const selectedFile = ref<File | null>(null)
const fileInput = ref<HTMLInputElement>()
const uploadTitle = ref('')
const replaceOpen = ref(false)
const replaceBusy = ref(false)
const replaceError = ref('')
const replacementFile = ref<File | null>(null)
const replacementInput = ref<HTMLInputElement>()

const drawerOpen = ref(false)
const drawerBusy = ref(false)
const drawerError = ref('')
const detail = ref<DocumentDetail | null>(null)
const selectedVersionId = ref('')
const previewText = ref('')
const previewUrl = ref('')
const previewKind = ref<'text' | 'image' | 'video' | 'pdf' | 'download'>('text')
const editing = ref(false)
const editorText = ref('')
const editorBusy = ref(false)
let indexPollTimer: number | null = null
let indexPollAttempts = 0

const selectedVersion = computed(() => detail.value?.versions.find(version => version.id === selectedVersionId.value) || null)
const isText = computed(() => !!selectedVersion.value && ['.md', '.markdown', '.txt'].includes(extension(selectedVersion.value.filename)))

function extension(filename: string) { return filename.slice(filename.lastIndexOf('.')).toLowerCase() }
function formatTime(value: string) { return new Date(value).toLocaleString('zh-CN', { hour12: false }) }
function formatSize(value: number) {
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`
  return `${(value / 1024 / 1024).toFixed(1)} MB`
}
function statusLabel(status: string) {
  return ({ active: '启用', archived: '已归档', PENDING_UPLOAD: '等待上传', UPLOADED: '等待索引', PENDING: '排队索引', RUNNING: '索引中', PROCESSING: '处理中', EMBEDDING: '生成向量', INDEXED: '已就绪', SUCCESS: '已完成', FAILED: '失败', ARCHIVED: '已归档' } as Record<string, string>)[status] || status
}
function statusType(status: string) {
  if (['active', 'INDEXED'].includes(status)) return 'success'
  if (['FAILED', 'archived', 'ARCHIVED'].includes(status)) return 'danger'
  if (['PENDING', 'RUNNING', 'PROCESSING', 'EMBEDDING', 'UPLOADED', 'PENDING_UPLOAD'].includes(status)) return 'warning'
  return 'info'
}
function versionDisplayStatus(version: Version | null) {
  if (!version) return ''
  if (version.task?.status === 'FAILED') return 'FAILED'
  if (version.task?.status === 'RUNNING') return version.status === 'EMBEDDING' ? 'EMBEDDING' : 'RUNNING'
  if (version.task?.status === 'PENDING' && version.status === 'UPLOADED') return 'PENDING'
  return version.status
}
function needsIndexPolling(row: DocumentRow) {
  const version = row.current_version
  if (!version) return false
  return ['PENDING', 'RUNNING'].includes(version.task?.status || '')
    || ['UPLOADED', 'PROCESSING', 'EMBEDDING'].includes(version.status)
}
function stopIndexPolling() {
  if (indexPollTimer !== null) window.clearTimeout(indexPollTimer)
  indexPollTimer = null
  indexPollAttempts = 0
}
function startIndexPolling() {
  stopIndexPolling()
  const poll = async () => {
    indexPollTimer = null
    indexPollAttempts += 1
    await loadDocuments()
    if (rows.value.some(needsIndexPolling) && indexPollAttempts < 60) {
      indexPollTimer = window.setTimeout(() => { void poll() }, 2000)
    } else {
      indexPollAttempts = 0
    }
  }
  indexPollTimer = window.setTimeout(() => { void poll() }, 300)
}
function escapeHtml(value: string) {
  return value.replace(/[&<>'"]/g, character => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[character] || character))
}
function renderInline(value: string) {
  const escaped = escapeHtml(value)
  const protectedValues: string[] = []
  const protect = (character: string) => `\uE000${protectedValues.push(character) - 1}\uE001`
  let html = escaped.replace(/\\([\\`*_\[\]{}()#+.!>~|-])/gu, (_, character: string) => protect(character))
  const codeValues: string[] = []
  html = html.replace(/`([^`\n]+)`/gu, (_, code: string) => {
    codeValues.push(code)
    return `\uE010${codeValues.length - 1}\uE011`
  })
  html = html
    .replace(/!\[([^\]]*)\]\((https?:\/\/[^\s)]+)(?:\s+["'][^"']*["'])?\)/gu, '<img class="markdown-inline-image" src="$2" alt="$1">')
    .replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)(?:\s+["'][^"']*["'])?\)/gu, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>')
    .replace(/\*\*([^*\n]+)\*\*/gu, '<strong>$1</strong>')
    .replace(/__([^_\n]+)__/gu, '<strong>$1</strong>')
    .replace(/~~([^~\n]+)~~/gu, '<del>$1</del>')
    .replace(/(^|[^\w])\*([^*\n]+)\*(?!\*)/gu, '$1<em>$2</em>')
    .replace(/(^|[^\w])_([^_\n]+)_(?!\w)/gu, '$1<em>$2</em>')
    .replace(/ {2,}\n/gu, '<br>')
    .replace(/\n/gu, '<br>')
  html = html.replace(/\uE010(\d+)\uE011/gu, (_, index: string) => `<code>${codeValues[Number(index)]}</code>`)
  return html.replace(/\uE000(\d+)\uE001/gu, (_, index: string) => protectedValues[Number(index)])
}
function splitTableRow(line: string) {
  const protectedPipe = '\uE100'
  const normalized = line.trim().replace(/^\|/u, '').replace(/\|$/u, '').replace(/\\\|/gu, protectedPipe)
  return normalized.split('|').map(cell => cell.trim().replaceAll(protectedPipe, '|'))
}
function isTableDivider(line: string) {
  return splitTableRow(line).length > 0 && splitTableRow(line).every(cell => /^:?-{3,}:?$/u.test(cell))
}
function renderMarkdown(value: string) {
  const lines = value.replace(/\r\n?/gu, '\n').split('\n')
  let html = ''
  let paragraph: string[] = []
  const flushParagraph = () => {
    if (paragraph.length) {
      html += `<p>${renderInline(paragraph.join('\n'))}</p>`
      paragraph = []
    }
  }
  let index = 0
  while (index < lines.length) {
    const line = lines[index]
    const fence = line.match(/^\s{0,3}(```+|~~~+)\s*.*$/u)
    if (fence) {
      flushParagraph()
      const marker = fence[1][0]
      const code: string[] = []
      index += 1
      while (index < lines.length && !new RegExp(`^\\s{0,3}${marker}{3,}\\s*$`, 'u').test(lines[index])) {
        code.push(lines[index]); index += 1
      }
      if (index < lines.length) index += 1
      html += `<pre class="markdown-code"><code>${escapeHtml(code.join('\n'))}</code></pre>`
      continue
    }
    const heading = line.match(/^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$/u)
    if (heading) {
      flushParagraph(); html += `<h${heading[1].length}>${renderInline(heading[2])}</h${heading[1].length}>`; index += 1; continue
    }
    if (index + 1 < lines.length && line.includes('|') && isTableDivider(lines[index + 1])) {
      flushParagraph()
      const headers = splitTableRow(line)
      const dividers = splitTableRow(lines[index + 1])
      html += '<table><thead><tr>'
      headers.forEach((header, cellIndex) => {
        const divider = dividers[cellIndex] || ''
        const align = divider.startsWith(':') ? 'left' : divider.endsWith(':') ? 'right' : ''
        html += `<th${align ? ` style="text-align:${align}"` : ''}>${renderInline(header)}</th>`
      })
      html += '</tr></thead><tbody>'; index += 2
      while (index < lines.length && lines[index].includes('|') && lines[index].trim()) {
        const cells = splitTableRow(lines[index]); html += '<tr>'
        headers.forEach((_, cellIndex) => { html += `<td>${renderInline(cells[cellIndex] || '')}</td>` })
        html += '</tr>'; index += 1
      }
      html += '</tbody></table>'; continue
    }
    const unordered = line.match(/^\s*[-+*]\s+(.+)$/u)
    if (unordered) {
      flushParagraph(); html += '<ul>'
      while (index < lines.length) {
        const item = lines[index].match(/^\s*[-+*]\s+(.+)$/u)
        if (!item) break
        html += `<li>${renderInline(item[1])}</li>`; index += 1
      }
      html += '</ul>'; continue
    }
    const ordered = line.match(/^\s*\d+[.)]\s+(.+)$/u)
    if (ordered) {
      flushParagraph(); html += '<ol>'
      while (index < lines.length) {
        const item = lines[index].match(/^\s*\d+[.)]\s+(.+)$/u)
        if (!item) break
        html += `<li>${renderInline(item[1])}</li>`; index += 1
      }
      html += '</ol>'; continue
    }
    if (/^\s*>\s?/u.test(line)) {
      flushParagraph(); const quote: string[] = []
      while (index < lines.length && /^\s*>\s?/u.test(lines[index])) { quote.push(lines[index].replace(/^\s*>\s?/u, '')); index += 1 }
      html += `<blockquote>${renderMarkdown(quote.join('\n'))}</blockquote>`; continue
    }
    if (/^\s{0,3}([-*_])(?:\s*\1){2,}\s*$/u.test(line)) { flushParagraph(); html += '<hr>'; index += 1; continue }
    if (!line.trim()) { flushParagraph(); index += 1; continue }
    paragraph.push(line); index += 1
  }
  flushParagraph()
  return html
}

async function loadBases() {
  const result = await api<{ items: KnowledgeBase[] }>('/knowledge-bases?status=active&page=1&page_size=100')
  // 文档只能在 active 知识库下管理；管理员列表接口还会返回停用和归档项。
  bases.value = result.items.filter(base => base.status === 'active')
  const requested = typeof route.query.knowledge_base_id === 'string' ? route.query.knowledge_base_id : ''
  if (requested && bases.value.some(base => base.id === requested)) selectedBase.value = requested
  else if (!selectedBase.value || !bases.value.some(base => base.id === selectedBase.value)) selectedBase.value = bases.value[0]?.id || ''
}
async function loadDocuments() {
  if (!selectedBase.value) { rows.value = []; total.value = 0; return }
  loading.value = true; error.value = ''
  try {
    const params = new URLSearchParams({ page: String(page.value), page_size: '20', q: applied.q, status: applied.status })
    const result = await api<{ items: DocumentRow[]; total: number }>(`/knowledge-bases/${selectedBase.value}/documents?${params}`)
    rows.value = result.items; total.value = result.total
  } catch (e) { error.value = (e as Error).message; rows.value = [] } finally { loading.value = false }
}
function search() { applied.q = filters.q.trim(); applied.status = filters.status; page.value = 1; void loadDocuments() }
function chooseFile(event: Event) {
  const file = (event.target as HTMLInputElement).files?.[0]
  selectedFile.value = file || null
  uploadTitle.value = file?.name.replace(/\.[^.]+$/u, '') || ''
  uploadError.value = ''
}
function openUpload() { selectedFile.value = null; uploadTitle.value = ''; uploadError.value = ''; uploadOpen.value = true; if (fileInput.value) fileInput.value.value = '' }
function chooseReplacementFile(event: Event) {
  replacementFile.value = (event.target as HTMLInputElement).files?.[0] || null
  replaceError.value = ''
}
function openReplace() {
  replacementFile.value = null
  replaceError.value = ''
  replaceOpen.value = true
  if (replacementInput.value) replacementInput.value.value = ''
}

async function putToMinio(ticket: UploadTicket, file: Blob) {
  const response = await fetch(ticket.upload_url, { method: 'PUT', headers: ticket.required_headers, body: file, credentials: 'omit' })
  if (!response.ok) throw new Error(`对象存储上传失败（HTTP ${response.status}）`)
}
async function completeUpload(ticket: UploadTicket, file: File) {
  try { await putToMinio(ticket, file) } catch {
    await uploadFile(`/documents/versions/${ticket.version.id}/upload`, file, file.type || ticket.required_headers['Content-Type'])
    return
  }
  await api(`/documents/complete`, { method: 'POST', body: JSON.stringify({ version_id: ticket.version.id }) })
}
async function upload() {
  if (!selectedFile.value || !selectedBase.value || uploadBusy.value) return
  uploadBusy.value = true; uploadError.value = ''
  try {
    const file = selectedFile.value
    const ticket = await api<UploadTicket>('/documents/presign-upload', { method: 'POST', body: JSON.stringify({ knowledge_base_id: selectedBase.value, filename: file.name, title: uploadTitle.value.trim() || undefined, file_size: file.size, content_type: file.type || undefined }) })
    await completeUpload(ticket, file)
    uploadOpen.value = false
    ElMessage.success('文档已上传，等待索引任务处理')
    await loadDocuments()
    startIndexPolling()
  } catch (e) { uploadError.value = (e as Error).message } finally { uploadBusy.value = false }
}

async function openDocument(row: DocumentRow, startEditing = false) {
  drawerOpen.value = true; drawerBusy.value = true; drawerError.value = ''; editing.value = false; detail.value = null
  try {
    detail.value = await api<DocumentDetail>(`/documents/${row.id}`)
    selectedVersionId.value = detail.value.current_version_id || detail.value.versions[0]?.id || ''
    await loadVersionContent()
    if (startEditing && isText.value) editing.value = true
  } catch (e) { drawerError.value = (e as Error).message } finally { drawerBusy.value = false }
}
async function loadVersionContent() {
  if (!detail.value || !selectedVersionId.value) return
  previewText.value = ''; previewUrl.value = ''; previewKind.value = 'text'
  const version = selectedVersion.value
  if (!version) return
  try {
    if (['.md', '.markdown', '.txt'].includes(extension(version.filename))) {
      const result = await api<{ content: string }>(`/documents/${detail.value.id}/content?version_id=${version.id}`)
      previewText.value = result.content; editorText.value = result.content
    } else if (extension(version.filename) === '.docx') {
      const result = await api<{ content: string }>(`/documents/${detail.value.id}/text-preview?version_id=${version.id}`)
      previewText.value = result.content; previewKind.value = 'text'
    } else if (['.pdf', '.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg', '.mp4', '.webm', '.mov'].includes(extension(version.filename))) {
      const result = await api<{ preview_url: string }>(`/documents/${detail.value.id}/preview-url?version_id=${version.id}`)
      previewUrl.value = result.preview_url
      const ext = extension(version.filename)
      previewKind.value = ['.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg'].includes(ext) ? 'image' : ['.mp4', '.webm', '.mov'].includes(ext) ? 'video' : ext === '.pdf' ? 'pdf' : 'download'
    } else {
      previewKind.value = 'download'
    }
  } catch (e) { drawerError.value = (e as Error).message }
}
function changeVersion() { editing.value = false; void loadVersionContent() }
async function downloadVersion(version = selectedVersion.value) {
  if (!detail.value || !version) return
  try {
    const result = await api<{ download_url: string }>(`/documents/${detail.value.id}/download-url?version_id=${version.id}`)
    const link = document.createElement('a'); link.href = result.download_url; link.download = version.filename; link.target = '_blank'; link.click()
  } catch (e) { ElMessage.error((e as Error).message) }
}
function beginEdit() {
  if (!isText.value) { ElMessage.info('图片、视频、PDF 和 Word 文件请上传新版本进行修改'); return }
  editorText.value = previewText.value; editing.value = true
}
async function saveEdit() {
  if (!detail.value || !selectedVersion.value || editorBusy.value) return
  editorBusy.value = true; drawerError.value = ''
  try {
    const filename = selectedVersion.value.filename
    const file = new File([editorText.value], filename, { type: selectedVersion.value.content_type || 'text/markdown;charset=utf-8' })
    const ticket = await api<UploadTicket>('/documents/presign-upload', { method: 'POST', body: JSON.stringify({ knowledge_base_id: detail.value.knowledge_base_id, document_id: detail.value.id, base_version_id: selectedVersion.value.id, filename, title: detail.value.title, file_size: file.size, content_type: file.type }) })
    await completeUpload(ticket, file)
    ElMessage.success('新版本已提交，等待索引完成')
    editing.value = false
    await openDocument(detail.value, false)
    if (detail.value?.versions.some(version => version.id === ticket.version.id)) {
      selectedVersionId.value = ticket.version.id
      await loadVersionContent()
    }
    await loadDocuments()
    startIndexPolling()
  } catch (e) { drawerError.value = (e as Error).message } finally { editorBusy.value = false }
}
async function replaceVersion() {
  if (!detail.value || !replacementFile.value || replaceBusy.value) return
  const baseVersionId = detail.value.current_version_id || detail.value.versions[0]?.id
  if (!baseVersionId) { replaceError.value = '文档没有可替换的基础版本'; return }
  replaceBusy.value = true; replaceError.value = ''
  try {
    const file = replacementFile.value
    const ticket = await api<UploadTicket>('/documents/presign-upload', { method: 'POST', body: JSON.stringify({ knowledge_base_id: detail.value.knowledge_base_id, document_id: detail.value.id, base_version_id: baseVersionId, filename: file.name, title: detail.value.title, file_size: file.size, content_type: file.type || undefined }) })
    await completeUpload(ticket, file)
    replaceOpen.value = false
    ElMessage.success('新版本已提交，等待索引完成')
    await openDocument(detail.value, false)
    if (detail.value?.versions.some(version => version.id === ticket.version.id)) {
      selectedVersionId.value = ticket.version.id
      await loadVersionContent()
    }
    await loadDocuments()
    startIndexPolling()
  } catch (e) { replaceError.value = (e as Error).message } finally { replaceBusy.value = false }
}
async function reindex(row: DocumentRow) {
  try { await ElMessageBox.confirm('将重新处理当前版本，确认继续吗？', '重新索引', { type: 'warning' }); const result = await api<{ task: Task }>(`/documents/${row.id}/reindex`, { method: 'POST', body: '{}' }); ElMessage.success(`任务已创建：${result.task.id.slice(0, 8)}`); await loadDocuments(); startIndexPolling() } catch (e) { if (e !== 'cancel') ElMessage.error((e as Error).message) }
}
async function archive(row: DocumentRow) {
  try { await ElMessageBox.confirm('归档后文档不再作为当前内容使用，历史版本会保留。确认归档吗？', '归档文档', { type: 'warning' }); await api(`/documents/${row.id}`, { method: 'DELETE' }); ElMessage.success('文档已归档，清理任务已创建'); await loadDocuments() } catch (e) { if (e !== 'cancel') ElMessage.error((e as Error).message) }
}
watch(selectedBase, () => { page.value = 1; stopIndexPolling(); void loadDocuments() })
onMounted(async () => { try { await loadBases(); await loadDocuments() } catch (e) { error.value = (e as Error).message } })
onBeforeUnmount(stopIndexPolling)
</script>

<template>
  <div class="page-heading">
    <div><div class="page-eyebrow">DOCUMENT LIBRARY</div><h1>文档管理</h1><p>按知识库管理原始文件、版本和索引状态。</p></div>
    <el-button type="primary" :icon="Plus" :disabled="!selectedBase" @click="openUpload">上传文件</el-button>
  </div>
  <el-alert class="phase-notice" title="支持 Markdown、TXT、PDF、Word、图片和视频；文本文件可在线编辑，其他文件可预览、下载并上传新版本。" type="info" :closable="false" show-icon />
  <el-alert v-if="!loading && !bases.length" class="phase-notice" title="当前没有可用知识库，请先在知识库管理中创建并启用知识库。" type="warning" :closable="false" show-icon />
  <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />
  <el-card shadow="never" class="resource-card">
    <div class="table-toolbar">
      <el-select v-model="selectedBase" placeholder="选择知识库" style="min-width: 220px"><el-option v-for="base in bases" :key="base.id" :label="`${base.name}（${base.code}）`" :value="base.id" /></el-select>
      <el-input v-model="filters.q" :prefix-icon="Search" placeholder="搜索文档标题" clearable @keyup.enter="search" @clear="search" />
      <el-select v-model="filters.status" placeholder="全部状态" clearable @change="search"><el-option label="有效" value="active" /><el-option label="已归档" value="archived" /></el-select>
      <el-button type="primary" plain @click="search">搜索</el-button><el-button :icon="Refresh" :loading="loading" @click="loadDocuments">刷新</el-button>
    </div>
    <el-table v-loading="loading" :data="rows" style="width: 100%" :min-height="360">
      <el-table-column prop="title" label="文档标题" min-width="220" show-overflow-tooltip />
      <el-table-column label="当前版本" width="120"><template #default="{ row }">{{ row.current_version ? `v${row.current_version.version_no}` : '—' }}</template></el-table-column>
      <el-table-column label="文件类型" width="120"><template #default="{ row }">{{ row.current_version?.filename?.split('.').pop()?.toUpperCase() || '—' }}</template></el-table-column>
      <el-table-column label="索引状态" width="130"><template #default="{ row }"><el-tag :type="statusType(versionDisplayStatus(row.current_version) || row.status)">{{ statusLabel(versionDisplayStatus(row.current_version) || row.status) }}</el-tag></template></el-table-column>
      <el-table-column label="更新时间" width="180"><template #default="{ row }">{{ formatTime(row.updated_at) }}</template></el-table-column>
      <el-table-column label="操作" fixed="right" width="270"><template #default="{ row }"><el-button link type="primary" :icon="View" @click="openDocument(row)">预览</el-button><el-button link type="primary" :icon="Edit" @click="openDocument(row, true)">编辑</el-button><el-button link :icon="RefreshRight" @click="reindex(row)">重索引</el-button><el-button link type="danger" :icon="Delete" @click="archive(row)">归档</el-button></template></el-table-column>
      <template #empty><el-empty :description="selectedBase ? '暂无文档' : '请先选择知识库'" :image-size="80"><template #image><el-icon :size="70" color="#c6c8ce"><FolderOpened /></el-icon></template></el-empty></template>
    </el-table>
    <div class="table-pagination"><span>共 {{ total }} 条记录</span><el-pagination v-model:current-page="page" :page-size="20" :total="total" layout="prev, pager, next" @current-change="loadDocuments" /></div>
  </el-card>

  <el-dialog v-model="uploadOpen" title="上传知识库文件" width="520px" align-center>
    <el-alert v-if="uploadError" :title="uploadError" type="error" :closable="false" show-icon />
    <el-form label-position="top"><el-form-item label="所属知识库"><el-input :model-value="bases.find(base => base.id === selectedBase)?.name || ''" disabled /></el-form-item><el-form-item label="文档标题"><el-input v-model="uploadTitle" maxlength="255" placeholder="默认使用文件名" /></el-form-item><el-form-item label="文件"><input ref="fileInput" type="file" accept=".md,.markdown,.txt,.pdf,.doc,.docx,.png,.jpg,.jpeg,.gif,.webp,.svg,.mp4,.webm,.mov,.avi" @change="chooseFile" /><div class="form-tip">单文件最大 {{ Math.round(20 * 1024 / 1024) }} MB，文件上传后进入索引任务。</div></el-form-item></el-form>
    <template #footer><el-button @click="uploadOpen = false">取消</el-button><el-button type="primary" :loading="uploadBusy" :disabled="!selectedFile" @click="upload">开始上传</el-button></template>
  </el-dialog>

  <el-dialog v-model="replaceOpen" title="上传文档新版本" width="520px" align-center>
    <el-alert v-if="replaceError" :title="replaceError" type="error" :closable="false" show-icon />
    <el-alert title="新文件会保留为新版本，当前版本在索引成功前不会切换。" type="info" :closable="false" show-icon />
    <el-form label-position="top"><el-form-item label="文档"><el-input :model-value="detail?.title || ''" disabled /></el-form-item><el-form-item label="新文件"><input ref="replacementInput" type="file" accept=".md,.markdown,.txt,.pdf,.doc,.docx,.png,.jpg,.jpeg,.gif,.webp,.svg,.mp4,.webm,.mov,.avi" @change="chooseReplacementFile" /><div class="form-tip">支持 Markdown、TXT、PDF、Word、图片和视频，单文件最大 20 MB。</div></el-form-item></el-form>
    <template #footer><el-button @click="replaceOpen = false">取消</el-button><el-button type="primary" :loading="replaceBusy" :disabled="!replacementFile" @click="replaceVersion">上传新版本</el-button></template>
  </el-dialog>

  <el-drawer v-model="drawerOpen" title="文档详情" size="min(920px, 92vw)" destroy-on-close>
    <el-alert v-if="drawerError" :title="drawerError" type="error" :closable="false" show-icon />
    <div v-loading="drawerBusy" class="document-drawer" v-if="detail">
      <div class="document-meta"><div><h2>{{ detail.title }}</h2><p>{{ detail.knowledge_base_id }} · {{ detail.status === 'active' ? '有效' : '已归档' }}</p></div><div class="document-actions"><el-select v-model="selectedVersionId" placeholder="选择版本" @change="changeVersion"><el-option v-for="version in detail.versions" :key="version.id" :label="`v${version.version_no} · ${statusLabel(version.status)} · ${formatSize(version.file_size)}`" :value="version.id" /></el-select><el-button v-if="detail.status === 'active'" :icon="Plus" @click="openReplace">上传新版本</el-button><el-button :icon="Download" @click="downloadVersion">下载</el-button><el-button v-if="isText && !editing && detail.status === 'active'" type="primary" :icon="Edit" @click="beginEdit">在线编辑</el-button></div></div>
      <div v-if="editing" class="editor-layout"><el-input v-model="editorText" type="textarea" :rows="24" resize="none" /><div class="markdown-preview"><div class="preview-label">实时预览</div><div class="markdown-body" v-html="renderMarkdown(editorText)" /></div></div>
      <div v-else-if="previewKind === 'text'" class="markdown-body document-preview" v-html="renderMarkdown(previewText)" />
      <img v-else-if="previewKind === 'image'" class="file-preview-image" :src="previewUrl" alt="文档预览" />
      <video v-else-if="previewKind === 'video'" class="file-preview-video" controls :src="previewUrl" />
      <iframe v-else-if="previewKind === 'pdf'" class="file-preview-frame" :src="previewUrl" title="PDF 预览" />
      <el-empty v-else description="该类型暂不支持在线预览，请下载后查看" />
      <el-divider /><h3>版本历史</h3><el-table :data="detail.versions" size="small"><el-table-column label="版本" width="90"><template #default="{ row }">v{{ row.version_no }}</template></el-table-column><el-table-column prop="filename" label="文件名" min-width="180" show-overflow-tooltip /><el-table-column label="状态" width="110"><template #default="{ row }"><el-tag :type="statusType(row.status)">{{ statusLabel(row.status) }}</el-tag></template></el-table-column><el-table-column label="大小" width="100"><template #default="{ row }">{{ formatSize(row.file_size) }}</template></el-table-column><el-table-column label="创建时间" width="170"><template #default="{ row }">{{ formatTime(row.created_at) }}</template></el-table-column><el-table-column label="操作" width="100"><template #default="{ row }"><el-button link :icon="Download" @click="downloadVersion(row)">下载</el-button></template></el-table-column></el-table>
    </div>
    <template #footer><div v-if="editing"><el-button @click="editing = false">取消编辑</el-button><el-button type="primary" :loading="editorBusy" @click="saveEdit">保存为新版本</el-button></div></template>
  </el-drawer>
</template>

<style scoped>
.document-drawer { min-height: 480px; }
.document-meta { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; margin-bottom: 18px; }
.document-meta h2 { margin: 0 0 6px; }
.document-meta p { margin: 0; color: #8a8f98; font-size: 13px; }
.document-actions { display: flex; align-items: center; gap: 8px; }
.document-actions .el-select { width: 280px; }
.document-preview { min-height: 260px; padding: 24px; background: #fafafa; border: 1px solid #ebeef2; border-radius: 8px; }
.editor-layout { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.editor-layout :deep(.el-textarea__inner) { min-height: 560px !important; font-family: ui-monospace, SFMono-Regular, Consolas, monospace; line-height: 1.6; }
.markdown-preview { min-height: 560px; padding: 12px 18px; overflow: auto; border: 1px solid #ebeef2; border-radius: 8px; background: #fff; }
.preview-label { margin-bottom: 12px; color: #9a9da3; font-size: 12px; letter-spacing: .08em; }
.markdown-body { color: #30343b; line-height: 1.8; }
.markdown-body :deep(h1), .markdown-body :deep(h2), .markdown-body :deep(h3), .markdown-body :deep(h4) { margin: 18px 0 8px; color: #16181c; }
.markdown-body :deep(p) { margin: 0 0 12px; }
.markdown-body :deep(code) { padding: 2px 5px; background: #f0f1f3; border-radius: 4px; }
.markdown-body :deep(.markdown-code) { padding: 14px; overflow: auto; background: #1f2329; color: #f6f7f8; border-radius: 6px; }
.file-preview-image { display: block; max-width: 100%; max-height: 620px; margin: auto; object-fit: contain; }
.file-preview-video { display: block; width: 100%; max-height: 620px; background: #111; }
.file-preview-frame { width: 100%; height: 680px; border: 0; }
.form-tip { margin-top: 8px; color: #8a8f98; font-size: 12px; }
@media (max-width: 800px) { .document-meta { display: block; } .document-actions { margin-top: 14px; flex-wrap: wrap; } .document-actions .el-select { width: 100%; } .editor-layout { grid-template-columns: 1fr; } }
</style>
