<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { Refresh } from '@element-plus/icons-vue'
import { api } from '../lib/session'
import { answerKindNames, statusText, type Turn } from '../lib/conversations'

interface Run {
  id: string; parent_id?: string | null; name: string; run_type?: string; status: string
  latency_ms?: number | null; started_at?: string | null; input_tokens?: number | null
  output_tokens?: number | null; total_tokens?: number | null; inputs?: unknown; outputs?: unknown
  error?: string | null; children?: Run[]
}
interface Trace {
  source: 'local' | 'langsmith'; question: string; resolved_question: string | null
  status: string; latency_ms: number | null; message: string; truncated: boolean; content_captured: boolean
  runs: Run[]
  local: { run_id?: string; pipeline_version?: string; prompt_version?: string; steps?: Run[]
    token_usage?: { input_tokens: number; output_tokens: number }
    retrieval?: { vector?: unknown[]; lexical?: unknown[]; selected?: string[]; reranker?: string
      embedding_fallback?: boolean; ranked?: { chunk_id: string; document_title: string; score?: number; rerank_score?: number; rerank_fallback?: boolean }[] } }
}
const props = defineProps<{ turn: Turn | null }>()
const emit = defineEmits<{ close: [] }>()
const visible = computed({ get: () => !!props.turn, set: value => { if (!value) emit('close') } })
const trace = ref<Trace | null>(null), loading = ref(false), error = ref(''), selectedId = ref('')
const activeTab = ref('inputs')
let generation = 0, controller: AbortController | null = null
const names: Record<string, string> = {
  'rag.turn': '本轮完整流程', prepare_memory: '整理会话记忆', 'rag.answer': '问答主流程', understand: '理解问题与追问', retrieve: '检索知识库',
  route_interaction: '识别交流意图', direct_answer: '直接交流回复', 'structured.RobotInteraction': '判断意图与生成交流回复', grounded_answer: '生成并核验答案', clarify: '澄清问题', knowledge_retriever: '知识库检索器',
  'rag.retrieval': '混合检索流程', hybrid_recall: '向量与关键词召回', rerank: '候选资料重排',
  expand_context: '扩展上下文', 'structured.ResolvedQuestion': '理解追问',
  'rag.grounding': '生成与核验流程', prepare: '准备回答依据', generate: '生成结构化回答', review: '核验回答与引用', repair: '修复回答', finalize: '整理最终答案',
  'structured.AnswerDraft': '生成回答草稿', 'structured.ReviewResult': '核验回答', 'structured.Summary': '压缩会话摘要', ChatDeepSeek: 'DeepSeek 模型调用', ChatPromptTemplate: '组装提示词',
}
const label = (run: Run) => names[run.name] || run.name
const duration = (value?: number | null) => value == null ? '—' : value < 1000 ? `${value} ms` : `${(value / 1000).toFixed(2)} s`
const runStatus = (value: string) => ({ success: '完成', failed: '失败', running: '处理中' }[value] || value)
const runs = computed(() => {
  const local = (trace.value?.local.steps || []).map((run, i) => ({ ...run, id: run.id || `local-${i}` }))
  const merged = new Map(local.map(run => [run.id, run]))
  for (const run of trace.value?.runs || []) merged.set(run.id, run)
  return [...merged.values()]
})
const tree = computed(() => {
  const entries = new Map(runs.value.map(run => [run.id, { ...run, children: [] as Run[] }]))
  const roots: Run[] = []
  for (const run of entries.values()) {
    const parent = run.parent_id ? entries.get(run.parent_id) : undefined
    if (parent && parent !== run) parent.children.push(run)
    else roots.push(run)
  }
  return roots
})
const selected = computed(() => runs.value.find(run => run.id === selectedId.value) || runs.value[0])
const retrieval = computed(() => trace.value?.local.retrieval)
const tokenUsage = computed(() => {
  const root = trace.value?.runs[0]
  if (root?.total_tokens != null) return root.total_tokens.toLocaleString()
  const usage = trace.value?.local.token_usage
  return usage ? (usage.input_tokens + usage.output_tokens).toLocaleString() : '—'
})
function payload(value: unknown) {
  if (value == null || (typeof value === 'object' && !Object.keys(value).length)) return '未采集此内容。记录时未开启内容采集，或该步骤没有此项数据。'
  return typeof value === 'string' ? value : JSON.stringify(value, null, 2)
}
async function load() {
  const turn = props.turn
  if (!turn) return
  controller?.abort(); controller = new AbortController()
  const current = ++generation
  loading.value = true; error.value = ''
  try {
    const result = await api<Trace>(`/admin/qa-conversations/${turn.conversation_id}/turns/${turn.id}/trace`, { signal: controller.signal, timeoutMs: 30000 })
    if (current !== generation) return
    trace.value = result
    if (!runs.value.some(run => run.id === selectedId.value)) selectedId.value = runs.value[0]?.id || ''
  } catch (e) { if (current === generation) error.value = (e as Error).message }
  finally { if (current === generation) loading.value = false }
}
watch(() => props.turn, turn => {
  generation++; controller?.abort(); trace.value = null; selectedId.value = ''; error.value = ''; activeTab.value = 'inputs'
  if (turn) void load()
}, { immediate: true })
onBeforeUnmount(() => { generation++; controller?.abort() })
</script>

<template>
  <el-dialog v-model="visible" title="问答处理流程" width="min(1440px, 94vw)" align-center destroy-on-close append-to-body class="trace-detail-dialog">
    <div class="trace-page" v-loading="loading">
      <header class="trace-header">
        <div><div class="trace-eyebrow">{{ trace?.source === 'langsmith' ? 'LANGSMITH TRACE' : 'EXECUTION TRACE' }}</div><h2>{{ turn?.question }}</h2><p v-if="turn">第 {{ turn.turn_no }} 轮 · {{ statusText(trace?.status || turn.status) }}<template v-if="turn.answer_kind"> · {{ answerKindNames[turn.answer_kind] || turn.answer_kind }}</template></p></div>
        <el-button :icon="Refresh" :disabled="loading" @click="load">刷新流程</el-button>
      </header>
      <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />
      <template v-if="trace">
        <el-alert :title="trace.message" :type="trace.source === 'langsmith' ? 'success' : 'info'" :closable="false" show-icon />
        <el-alert v-if="trace.truncated" title="步骤数量较多，此处最多展示 200 个步骤。" type="warning" :closable="false" show-icon />
        <div class="trace-stats">
          <div><small>回答总耗时</small><strong>{{ duration(trace.latency_ms) }}</strong></div>
          <div><small>处理步骤</small><strong>{{ runs.length }}</strong></div>
          <div><small>模型 Token 用量</small><strong>{{ tokenUsage }}</strong></div>
          <div><small>进入回答的资料片段</small><strong>{{ retrieval?.selected?.length ?? '—' }}</strong></div>
        </div>
        <p v-if="trace.resolved_question && trace.resolved_question !== trace.question" class="resolved-question"><strong>结合上下文理解的问题：</strong>{{ trace.resolved_question }}</p>
        <div v-if="runs.length" class="trace-workspace">
          <section class="trace-tree-panel" aria-label="流程步骤"><h3>执行步骤</h3><p class="trace-hint">选择步骤查看详情。父步骤耗时包含子步骤。</p>
            <div class="trace-tree-scroll" tabindex="0" aria-label="执行步骤滚动区域"><el-tree :data="tree" :indent="14" node-key="id" default-expand-all highlight-current :expand-on-click-node="false" :current-node-key="selected?.id" :props="{ label: 'name' }" @node-click="(run: Run) => selectedId = run.id">
              <template #default="{ data }"><div class="trace-node"><span :class="['trace-dot', data.status]" /><span class="trace-node-name" :title="data.name">{{ label(data) }}</span><small>{{ duration(data.latency_ms) }}</small></div></template>
            </el-tree></div>
          </section>
          <section v-if="selected" class="trace-node-panel" aria-label="步骤详情">
            <div class="trace-node-heading"><div><h3>{{ label(selected) }}</h3><p>{{ selected.name }} · {{ selected.run_type || 'chain' }}</p></div><el-tag :type="selected.status === 'failed' ? 'danger' : selected.status === 'running' ? 'warning' : 'success'">{{ runStatus(selected.status) }}</el-tag></div>
            <div class="trace-node-metrics"><span>耗时：{{ duration(selected.latency_ms) }}</span><span>输入 Token：{{ selected.input_tokens ?? '—' }}</span><span>输出 Token：{{ selected.output_tokens ?? '—' }}</span></div>
            <p v-if="selected.started_at" class="trace-hint">开始于 {{ new Date(selected.started_at).toLocaleString() }}</p>
            <el-alert v-if="selected.error" :title="selected.error" type="error" :closable="false" class="trace-run-error" />
            <el-tabs v-model="activeTab"><el-tab-pane label="输入数据" name="inputs"><pre class="trace-payload">{{ payload(selected.inputs) }}</pre></el-tab-pane><el-tab-pane label="输出数据" name="outputs"><pre class="trace-payload">{{ payload(selected.outputs) }}</pre></el-tab-pane></el-tabs>
          </section>
        </div>
        <el-empty v-else description="本轮暂无可展示的流程步骤" :image-size="80" />
        <section v-if="retrieval && Object.keys(retrieval).length" class="trace-retrieval"><h3>检索与重排</h3><p class="trace-hint">向量召回 {{ retrieval.vector?.length ?? 0 }} 条 · 关键词召回 {{ retrieval.lexical?.length ?? 0 }} 条 · 重排方式 {{ retrieval.reranker || '—' }}</p>
          <el-alert v-if="retrieval.embedding_fallback" title="本轮向量服务不可用，已使用关键词召回。" type="warning" :closable="false" />
          <el-table :data="retrieval.ranked || []" max-height="320"><el-table-column prop="document_title" label="资料名称" min-width="200" /><el-table-column label="向量相似度" width="130"><template #default="{ row }">{{ row.score == null ? '—' : Number(row.score).toFixed(4) }}</template></el-table-column><el-table-column label="重排得分" width="120"><template #default="{ row }">{{ row.rerank_score == null ? '—' : Number(row.rerank_score).toFixed(4) }}</template></el-table-column><el-table-column label="状态" width="180"><template #default="{ row }"><el-tag v-if="retrieval.selected?.includes(row.chunk_id)" size="small">用于回答</el-tag><el-tag v-if="row.rerank_fallback" size="small" type="warning">重排降级</el-tag></template></el-table-column></el-table>
        </section>
        <footer class="trace-footer">运行编号：{{ trace.local.run_id || '—' }} · 流程版本：{{ trace.local.pipeline_version || '—' }} · 提示词版本：{{ trace.local.prompt_version || '—' }}</footer>
      </template>
    </div>
  </el-dialog>
</template>

<style scoped>
.trace-page { margin: 0 auto; padding: 6px 4px 24px; min-height: 300px; color: #34435a; }
.trace-header,.trace-node-heading { display: flex; justify-content: space-between; align-items: flex-start; gap: 20px; }
.trace-header h2 { font-size: 20px; margin: 10px 0; overflow-wrap: anywhere; }
.trace-eyebrow { color: #a37031; font-size: 11px; letter-spacing: 2px; }
.trace-header p,.trace-hint,.trace-node-heading p { color: #8290a1; font-size: 12px; line-height: 1.6; }
.trace-page > .el-alert { margin: 12px 0; }
.trace-stats { display: grid; grid-template-columns: repeat(4,1fr); gap: 16px; margin: 18px 0; }
.trace-stats > div { border: 1px solid #e7ebf1; padding: 15px 18px; border-radius: 12px; background: #fafbfd; }
.trace-stats small,.trace-stats strong { display: block; }
.trace-stats small { font-size: 12px; color: #7e8b9c; }
.trace-stats strong { margin-top: 10px; font-size: 22px; font-weight: 600; }
.trace-workspace { display: grid; grid-template-columns: minmax(340px, 39%) minmax(0,1fr); height: clamp(540px, 58dvh, 760px); border: 1px solid #e5eaf1; border-radius: 12px; overflow: hidden; }
.trace-tree-panel,.trace-node-panel { display: flex; flex-direction: column; padding: 20px; min-width: 0; min-height: 0; }
.trace-tree-panel { border-right: 1px solid #e5eaf1; background: #fcfcfd; }
.trace-tree-scroll { flex: 1; min-height: 0; overflow: auto; padding-bottom: 8px; overscroll-behavior: contain; }
.trace-tree-scroll .el-tree { width: max-content; min-width: 100%; background: transparent; }
h3 { font-size: 15px; margin: 0 0 10px; }
.trace-node { display: flex; align-items: center; gap: 10px; flex: 1; min-width: max-content; padding-right: 14px; font-size: 13px; }
.trace-node-name { flex: 1; white-space: nowrap; }
.trace-node small { margin-left: 12px; color: #8c97a5; white-space: nowrap; flex-shrink: 0; }
.trace-tree-panel :deep(.el-tree-node__content) { height: 38px; }
.trace-dot { width: 6px; height: 6px; border-radius: 50%; background: #d1a14b; flex-shrink: 0; }
.trace-dot.success { background: #5d9d83; }.trace-dot.failed { background: #db6868; }
.trace-node-heading > div { min-width: 0; }
.trace-node-heading h3 { overflow-wrap: anywhere; }
.trace-node-metrics { display: flex; flex-wrap: wrap; gap: 20px; font-size: 13px; margin: 16px 0; }
.trace-node-heading p { margin: 0; overflow-wrap: anywhere; }
.trace-node-panel > :not(.el-tabs) { flex-shrink: 0; }
.trace-node-panel > .el-tabs { display: flex; flex-direction: column; flex: 1; min-height: 0; }
.trace-node-panel :deep(.el-tabs__header) { flex-shrink: 0; }
.trace-node-panel :deep(.el-tabs__content) { flex: 1; min-height: 0; }
.trace-node-panel :deep(.el-tab-pane) { height: 100%; }
.trace-payload { box-sizing: border-box; height: 100%; white-space: pre-wrap; overflow-wrap: anywhere; background: #f7f9fc; padding: 20px; border-radius: 8px; font: 14px/1.8 ui-monospace, monospace; overflow: auto; margin: 0; overscroll-behavior: contain; }
.trace-run-error { overflow-wrap: anywhere; max-height: 90px; overflow-y: auto; }
.trace-retrieval { margin-top: 26px; }
.trace-footer { margin-top: 22px; color: #8994a3; font-size: 11px; overflow-wrap: anywhere; }
.resolved-question { line-height: 1.8; font-size: 13px; }
@media (max-width: 800px) {
  .trace-page { padding: 4px 0 20px; }
  .trace-stats { grid-template-columns: repeat(2,1fr); gap: 10px; }
  .trace-workspace { grid-template-columns: minmax(0,1fr); height: auto; }
  .trace-tree-panel { height: 320px; box-sizing: border-box; border-right: 0; border-bottom: 1px solid #e5eaf1; }
  .trace-node-panel { height: 520px; box-sizing: border-box; }
  .trace-header h2 { font-size: 18px; }
  .trace-payload { padding: 14px; font-size: 13px; }
}
</style>

<style>
.el-dialog.trace-detail-dialog { border-radius: 18px; padding: 0; overflow: hidden; box-shadow: 0 24px 80px #14203233; }
.trace-detail-dialog .el-dialog__header { padding: 23px 28px 20px; margin: 0; border-bottom: 1px solid #edf0f5; background: linear-gradient(110deg, #fffaf3, #fff 60%); }
.trace-detail-dialog .el-dialog__title { font-size: 17px; font-weight: 600; color: #34435a; }
.trace-detail-dialog .el-dialog__headerbtn { top: 11px; right: 12px; }
.trace-detail-dialog .el-dialog__body { padding: 20px 26px 0; max-height: min(80dvh, 1020px); overflow-y: auto; overscroll-behavior: contain; }
@media (max-width: 600px) {
  .trace-detail-dialog .el-dialog__header { padding: 20px; }
  .trace-detail-dialog .el-dialog__body { padding: 16px 14px 0; max-height: 80dvh; }
}
</style>
