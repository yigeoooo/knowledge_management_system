<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { api, session } from '../lib/session'
import { answerKindNames } from '../lib/conversations'
import type { Dataset, EvaluationDocument, Example } from '../lib/evaluations'
import EvaluationDocumentPreview from './EvaluationDocumentPreview.vue'
import EvaluationHistoryImportDialog, { type ImportedHistory } from './EvaluationHistoryImportDialog.vue'

const props = defineProps<{ open: boolean; dataset: Dataset | undefined; example: Example | null }>()
const emit = defineEmits<{ close: []; saved: [] }>()
interface HistoryTurn { question: string; answer: string; [key: string]: unknown }
const form = reactive({ task: 'answer', name: '', question: '', robot: false, expected_document_ids: [] as string[], answer_points: '', forbidden_points: '', expected_status: '', expected_answer_kind: '', reference_answer: '', source_notes: '', summary: '', turns: [] as HistoryTurn[] })
const documents = ref<EvaluationDocument[]>([]), documentsLoading = ref(false), documentError = ref(''), saving = ref(false)
const showSources = ref(true), expanded = ref(false), mobilePane = ref('question'), narrow = ref(false)
const importingHistory = ref(false)
const canReadLogs = computed(() => session.pages.some(page => page.route_path === '/qa-logs'))
let contextExtra: Record<string, unknown> = {}, documentSequence = 0, controller: AbortController | undefined
let media: MediaQueryList | undefined
const historyNeeded = computed(() => ['followup', 'summary'].includes(form.task))
const referenceVisible = computed(() => narrow.value ? mobilePane.value === 'reference' : showSources.value)
const formVisible = computed(() => narrow.value ? mobilePane.value === 'question' : !expanded.value || !showSources.value)
const canSave = computed(() => !saving.value && !!form.name.trim() && !!form.question.trim() && !documentsLoading.value && !documentError.value)
const documentOptions = computed(() => [...documents.value, ...form.expected_document_ids.filter(id => !documents.value.some(d => d.id === id)).map(id => ({ id, title: '文档已失效，请移除后重新选择', filename: id, indexed: false }))])
function updateScreen() { narrow.value = !!media?.matches }
onMounted(() => { media = window.matchMedia('(max-width: 1023px)'); updateScreen(); media.addEventListener('change', updateScreen) })
watch(() => props.open, open => {
  importingHistory.value = false
  if (!open) { ++documentSequence; controller?.abort(); return }
  const row = props.example, context = row?.inputs.context || {}
  const turns = Array.isArray(context.turns) ? context.turns : []
  contextExtra = Object.fromEntries(Object.entries(context).filter(([key]) => !['turns', 'summary'].includes(key)))
  Object.assign(form, {
    task: row?.inputs.task && row.inputs.task !== 'answer' ? row.inputs.task : turns.length || context.summary ? 'followup' : 'answer',
    name: row?.name || '', question: row?.inputs.question || '', robot: row?.inputs.robot || false,
    expected_document_ids: [...(row?.reference.expected_document_ids || [])],
    answer_points: row?.reference.answer_points.join('\n') || '', forbidden_points: row?.reference.forbidden_points?.join('\n') || '',
    expected_status: row?.reference.expected_status || '', expected_answer_kind: row?.reference.expected_answer_kind || '', reference_answer: row?.reference.reference_answer || '', source_notes: row?.reference.source_notes || '',
    summary: typeof context.summary === 'string' ? context.summary : '',
    turns: turns.map(t => t && typeof t === 'object' ? ({ ...t, question: String(t.question || ''), answer: String(t.answer || '') }) : ({ question: String(t || ''), answer: '' })),
  })
  showSources.value = true; expanded.value = false; mobilePane.value = 'question'
  documents.value = []; void searchDocuments()
}, { immediate: true })
watch(() => form.task, task => { if (['followup', 'summary'].includes(task) && !form.turns.length && !form.summary) form.turns.push({ question: '', answer: '' }) })
async function searchDocuments(query = '') {
  const sequence = ++documentSequence
  controller?.abort(); controller = new AbortController()
  documentError.value = ''; documentsLoading.value = true
  const params = new URLSearchParams({ q: query })
  form.expected_document_ids.forEach(value => params.append('selected', value))
  try {
    const result = await api<{ items: EvaluationDocument[] }>(`/evaluations/datasets/${props.dataset?.id}/documents?${params}`, { signal: controller.signal })
    if (sequence === documentSequence) documents.value = result.items
  } catch (e) { if (sequence === documentSequence) documentError.value = (e as Error).message }
  finally { if (sequence === documentSequence) documentsLoading.value = false }
}
function addSource(doc: EvaluationDocument) {
  if (saving.value || form.expected_document_ids.includes(doc.id)) return
  if (form.expected_document_ids.length >= 30) { ElMessage.warning('最多选择 30 份预期文档'); return }
  if (!documents.value.some(d => d.id === doc.id)) documents.value.push(doc)
  form.expected_document_ids.push(doc.id)
  ElMessage.success('已加入预期文档')
}
function expandSource() {
  if (narrow.value) mobilePane.value = 'question'
  else expanded.value = !expanded.value
}
function lines(value: string) { return value.split('\n').map(v => v.trim()).filter(Boolean) }
function importHistory(value: ImportedHistory) {
  form.turns = value.context.turns.map(turn => ({ ...turn }))
  form.summary = ''; contextExtra = {}; importingHistory.value = false
  ElMessage.success(`已导入 ${form.turns.length} 轮历史问答，可继续编辑后保存题目`)
}
async function save(status: 'draft' | 'enabled') {
  if (!canSave.value || !props.dataset) return
  if (status === 'enabled' && historyNeeded.value) {
    if ((!form.turns.length && !form.summary.trim()) || form.turns.some(t => !t.question.trim() || !t.answer.trim())) {
      ElMessage.warning('请补全历史问题和回答；尚未完成时可保存草稿'); return
    }
  }
  saving.value = true
  try {
    const context = historyNeeded.value ? { ...contextExtra, summary: form.summary, turns: form.turns } : {}
    const payload = { status, name: form.name, inputs: { task: form.task === 'followup' ? 'answer' : form.task, question: form.question, robot: form.robot, context }, reference: { expected_document_ids: form.expected_document_ids, answer_points: lines(form.answer_points), forbidden_points: lines(form.forbidden_points), expected_status: form.expected_status || null, expected_answer_kind: form.robot && ['answer', 'followup'].includes(form.task) ? form.expected_answer_kind || null : null, reference_answer: form.reference_answer, source_notes: form.source_notes }, expected_revision: props.example?.revision }
    await api(props.example ? `/evaluations/examples/${props.example.id}` : `/evaluations/datasets/${props.dataset.id}/examples`, { method: props.example ? 'PUT' : 'POST', body: JSON.stringify(payload) })
    ElMessage.success(status === 'enabled' ? '测试题已保存并启用，可直接用于正式评测' : '已保存草稿，不参与发布验收')
    emit('saved')
  } catch (e) { ElMessage.error((e as Error).message) }
  finally { saving.value = false }
}
function close() { if (!saving.value) emit('close') }
onBeforeUnmount(() => { ++documentSequence; controller?.abort(); media?.removeEventListener('change', updateScreen) })
</script>

<template>
  <el-dialog :model-value="open" :title="example ? '查看 / 编辑测试题' : '添加测试题'" :width="referenceVisible && !narrow ? 'min(1920px, 96vw)' : 'min(1000px, 94vw)'" top="3vh" destroy-on-close class="example-dialog" :close-on-click-modal="false" :close-on-press-escape="!saving && !importingHistory" :show-close="!saving" @close="close">
    <div class="editor-toolbar"><span>评测集：{{ dataset?.name }}</span><el-radio-group v-if="narrow" v-model="mobilePane" size="small"><el-radio-button value="question">题目编辑</el-radio-button><el-radio-button value="reference">资料预览</el-radio-button></el-radio-group><el-button v-else link type="primary" @click="showSources = !showSources; expanded = false">{{ showSources ? '收起资料' : '查看知识库资料' }}</el-button></div>
    <div class="example-workspace" :class="{ split: referenceVisible && formVisible && !narrow }">
      <el-form v-show="formVisible" label-position="top" class="example-editor" :disabled="saving">
        <div class="form-columns"><el-form-item label="样本名称"><el-input v-model="form.name" maxlength="200" /></el-form-item><el-form-item label="回答渠道"><el-switch v-model="form.robot" active-text="机器人简洁回答" inactive-text="网页回答" /></el-form-item></div>
        <el-form-item label="测试任务"><el-select v-model="form.task" aria-label="测试任务"><el-option label="知识问答（单轮问题）" value="answer" /><el-option label="连续追问（带历史问答）" value="followup" /><el-option label="会话摘要" value="summary" /><el-option label="推荐问题" value="suggestions" /></el-select></el-form-item>
        <el-form-item :label="form.task === 'summary' ? '摘要任务说明' : form.task === 'suggestions' ? '资料检索主题' : '测试问题'"><el-input v-model="form.question" type="textarea" :rows="2" maxlength="2000" /></el-form-item>
        <div class="form-columns"><el-form-item label="预期命中的文档（从当前知识库选择）">
          <el-select v-model="form.expected_document_ids" multiple filterable remote :remote-method="searchDocuments" :loading="documentsLoading" :multiple-limit="30" placeholder="搜索并选择知识库文档" aria-label="预期命中的文档" @visible-change="(open: boolean) => open && searchDocuments()">
            <el-option v-for="doc in documentOptions" :key="doc.id" :value="doc.id" :label="`${doc.title} · ${doc.id.slice(0, 8)}`" :disabled="!doc.indexed">{{ doc.title }} <small>{{ doc.filename }} · {{ doc.id.slice(0, 8) }}{{ doc.indexed ? '' : ' · 尚未完成索引' }}</small></el-option>
          </el-select><p class="help-text">可多选，也可在资料预览中点击“加入预期文档”。</p>
          <el-alert v-if="example?.document_issue" :title="`${example.document_issue}。原标注：${example.reference.expected_documents.join('、')}`" type="warning" :closable="false" /><el-alert v-if="documentError" :title="documentError" type="error" :closable="false"><el-button link @click="searchDocuments()">重试</el-button></el-alert>
        </el-form-item><el-form-item label="答案必需的事实要点（每行一条）"><el-input v-model="form.answer_points" type="textarea" :rows="3" placeholder="填写关键事实，自动指标仅检查字面覆盖" /></el-form-item></div>
        <el-form-item v-if="form.robot && ['answer', 'followup'].includes(form.task)" label="预期回答类型"><el-select v-model="form.expected_answer_kind" clearable placeholder="可选，用于检查机器人是否正确分流" aria-label="预期回答类型"><el-option v-for="(name, kind) in answerKindNames" :key="kind" :value="kind" :label="name" /></el-select><p class="help-text">闲聊、通识和实时信息说明可以不选预期文档，填写参考答案或关键要点即可。</p></el-form-item><el-form-item label="参考答案（供人工对照）"><el-input v-model="form.reference_answer" type="textarea" :rows="3" maxlength="5000" /></el-form-item>
        <el-form-item label="核对依据（文档章节、表格行及适用条件）"><el-input v-model="form.source_notes" type="textarea" :rows="2" maxlength="5000" /></el-form-item>
        <div class="form-columns"><el-form-item label="预期状态"><el-select v-model="form.expected_status" clearable placeholder="可选"><el-option label="完整回答" value="SUCCESS" /><el-option label="部分回答" value="PARTIAL" /><el-option label="资料不足" value="NO_EVIDENCE" /><el-option label="需要澄清" value="CLARIFICATION" /><el-option label="仅提供资料" value="SOURCES_ONLY" /></el-select></el-form-item><el-form-item label="不应出现的错误内容（每行一条）"><el-input v-model="form.forbidden_points" type="textarea" :rows="2" /></el-form-item></div>
        <section v-if="historyNeeded" class="history-editor" aria-label="历史问答">
          <div class="history-heading"><h3>{{ form.task === 'summary' ? '需要生成摘要的历史问答' : '本次追问之前的历史问答' }}</h3><el-button v-if="canReadLogs" type="primary" plain @click="importingHistory = true">从问答日志导入</el-button></div><p class="help-text">可手动填写，或预览问答日志后导入。每道题独立保存历史内容，不随原会话变化。</p><p v-if="!canReadLogs" class="help-text">从日志导入需要问答日志查看权限。</p>
          <div v-for="(turn, index) in form.turns" :key="index" class="history-turn"><div class="turn-heading"><strong>第 {{ index + 1 }} 轮</strong><el-button link type="danger" @click="form.turns.splice(index, 1)">移除此轮</el-button></div><el-form-item :label="`第 ${index + 1} 轮问题`"><el-input v-model="turn.question" type="textarea" :rows="2" maxlength="2000" /></el-form-item><el-form-item :label="`第 ${index + 1} 轮回答`"><el-input v-model="turn.answer" type="textarea" :rows="2" maxlength="5000" /></el-form-item></div>
          <el-button :disabled="form.turns.length >= 30" @click="form.turns.push({ question: '', answer: '' })">添加历史问答</el-button>
          <el-form-item label="更早的对话摘要（可选）" class="summary-field"><el-input v-model="form.summary" type="textarea" :rows="2" maxlength="10000" /></el-form-item>
        </section>
      </el-form>
      <EvaluationDocumentPreview v-if="open && dataset && referenceVisible" :dataset-id="dataset.id" :initial-document-id="example?.reference.expected_document_ids?.[0]" :expected-document-ids="form.expected_document_ids" :expanded="expanded || narrow" @select="addSource" @expand="expandSource" />
    </div>
    <template #footer><div class="example-footer"><p>核对资料后可直接保存并启用，未完成的题目可先存草稿。</p><div><el-button :disabled="saving" @click="close">关闭</el-button><el-button :loading="saving" :disabled="!canSave" @click="save('draft')">保存草稿</el-button><el-button type="primary" :loading="saving" :disabled="!canSave" @click="save('enabled')">保存并启用</el-button></div></div></template>
  </el-dialog>
  <EvaluationHistoryImportDialog v-if="open && dataset && importingHistory" :dataset-id="dataset.id" :robot="form.robot" :task="form.task === 'summary' ? 'summary' : 'answer'" :has-history="!!form.summary.trim() || form.turns.some(turn => !!turn.question.trim() || !!turn.answer.trim())" @close="importingHistory = false" @import="importHistory" />
</template>

<style scoped>
.editor-toolbar{display:flex;justify-content:space-between;align-items:center;gap:16px;margin:0 0 16px}.editor-toolbar>span{font-size:12px;color:#8793a4;overflow-wrap:anywhere}.example-workspace{height:calc(94vh - 165px);max-height:1150px;display:grid;grid-template-columns:minmax(0,1fr);grid-template-rows:minmax(0,1fr);gap:22px;min-width:0}.example-workspace.split{grid-template-columns:minmax(0,0.9fr) minmax(0,1.1fr)}.example-editor{height:100%;overflow:auto;padding:0 10px 0 0;min-width:0;box-sizing:border-box}.form-columns{display:grid;grid-template-columns:1fr 1fr;gap:20px}.example-editor :deep(.el-select){width:100%}.help-text{font-size:12px;line-height:1.7;color:#8b97a7;margin:8px 0}.example-editor small{margin-left:10px;color:#8b97a7;font-size:11px}.example-footer{display:flex;align-items:center;justify-content:space-between;gap:14px}.example-footer p{color:#8793a4;font-size:12px;text-align:left;margin:0}.example-footer>div{display:flex;flex-shrink:0}.history-editor{border-top:1px solid #e6ebf2;padding-top:18px}.history-heading{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}.history-editor h3{font-size:14px;margin:0 0 8px}.history-turn{background:#f7f9fc;padding:14px;border-radius:8px;margin:14px 0}.turn-heading{display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;font-size:12px}.summary-field{margin-top:18px}@media(max-width:1200px) and (min-width:1024px){.split .form-columns{grid-template-columns:1fr;gap:0}}@media(max-width:1023px){.example-workspace{height:65vh}.editor-toolbar{flex-wrap:wrap}.example-footer{flex-wrap:wrap}.example-footer>div{margin-left:auto}}@media(max-width:600px){.form-columns{grid-template-columns:1fr;gap:0}.example-footer p{display:none}.example-editor{padding-right:4px}.example-workspace{height:62vh}}
</style>
