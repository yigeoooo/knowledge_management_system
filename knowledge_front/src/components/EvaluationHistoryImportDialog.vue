<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { api } from '../lib/session'
import { statusText } from '../lib/conversations'
import MarkdownContent from './MarkdownContent.vue'

export interface ImportedHistory {
  context: { summary: string; turns: { question: string; answer: string; [key: string]: unknown }[] }
  conversation: HistoryConversation
  skipped_count: number
  start_turn_no: number
  end_turn_no: number
}
interface Owner { id: string; name: string; identity: string; conversation_count: number }
interface HistoryConversation { id: string; title: string; last_turn_no: number; last_message_at: string }
interface HistoryTurn { id: string; turn_no: number; question: string; answer: string | null; status: string; answer_kind: string; importable: boolean }
interface List<T> { items: T[]; total: number }
const props = defineProps<{ datasetId: string; robot: boolean; task: 'answer' | 'summary'; hasHistory: boolean }>()
const emit = defineEmits<{ close: []; import: [ImportedHistory] }>()
const source = props.robot ? 'ROBOT' : 'WEB'
const owners = ref<Owner[]>([]), ownerId = ref(''), ownerPage = ref(1), ownerTotal = ref(0), ownerQuery = ref('')
const conversations = ref<HistoryConversation[]>([]), conversation = ref<HistoryConversation | null>(null)
const conversationPage = ref(1), conversationTotal = ref(0), query = ref('')
const turns = ref<HistoryTurn[]>([]), turnPage = ref(1), turnTotal = ref(0)
const start = ref(1), end = ref(1), snapshot = ref<ImportedHistory | null>(null)
const error = ref(''), ownerLoading = ref(false), conversationLoading = ref(false), turnLoading = ref(false), copying = ref(false)
const busy = computed(() => ownerLoading.value || conversationLoading.value || turnLoading.value || copying.value)
const rangeValid = computed(() => !!conversation.value && start.value >= 1 && end.value >= start.value && end.value <= conversation.value.last_turn_no && end.value - start.value < 30)
const requests = new Map<string, AbortController>()
let disposed = false
function cancel(...names: string[]) { for (const name of names) { requests.get(name)?.abort(); requests.delete(name) } }
function begin(name: string) { cancel(name); const controller = new AbortController(); requests.set(name, controller); return controller }
function current(name: string, controller: AbortController) { return !disposed && requests.get(name) === controller && !controller.signal.aborted }
function url(path: string, values: Record<string, string | number> = {}) {
  const params = new URLSearchParams({ source_type: source })
  Object.entries(values).forEach(([key, value]) => params.set(key, String(value)))
  return `/evaluations/datasets/${props.datasetId}/history/${path}?${params}`
}
function clearConversation() {
  cancel('turns', 'copy'); conversation.value = null; turns.value = []; turnTotal.value = 0
  turnLoading.value = false; copying.value = false; snapshot.value = null
}
async function searchOwners(value = '', more = false) {
  const request = begin('owners')
  if (!more) {
    owners.value = []
    ownerQuery.value = value; ownerPage.value = 1; ownerTotal.value = 0
  }
  const page = more ? ownerPage.value + 1 : 1
  ownerLoading.value = true; error.value = ''
  try {
    const result = await api<List<Owner>>(url('owners', { q: ownerQuery.value, page }), { signal: request.signal })
    if (!current('owners', request)) return
    owners.value = more ? [...owners.value, ...result.items] : result.items
    ownerTotal.value = result.total; ownerPage.value = page
  } catch (e) { if (current('owners', request)) error.value = (e as Error).message }
  finally { if (current('owners', request)) ownerLoading.value = false }
}
async function selectOwner() { query.value = ''; conversationPage.value = 1; await loadConversations() }
async function loadConversations() {
  clearConversation(); conversations.value = []; conversationTotal.value = 0
  const request = begin('conversations')
  if (!ownerId.value) return
  conversationLoading.value = true; error.value = ''
  try {
    const result = await api<List<HistoryConversation>>(url('conversations', { owner_id: ownerId.value, q: query.value, page: conversationPage.value }), { signal: request.signal })
    if (current('conversations', request)) { conversations.value = result.items; conversationTotal.value = result.total }
  } catch (e) { if (current('conversations', request)) error.value = (e as Error).message }
  finally { if (current('conversations', request)) conversationLoading.value = false }
}
async function selectConversation(row: HistoryConversation) {
  clearConversation(); conversation.value = row; turnPage.value = 1; start.value = 1; end.value = 1
  await loadTurns()
}
async function loadTurns() {
  const row = conversation.value
  if (!row) return
  const request = begin('turns'); turns.value = []; turnLoading.value = true; error.value = ''
  try {
    const result = await api<List<HistoryTurn> & { conversation: HistoryConversation }>(url(`conversations/${row.id}/turns`, { page: turnPage.value }), { signal: request.signal })
    if (current('turns', request)) { turns.value = result.items; turnTotal.value = result.total; conversation.value = result.conversation }
  } catch (e) { if (current('turns', request)) error.value = (e as Error).message }
  finally { if (current('turns', request)) turnLoading.value = false }
}
function setStart(no: number) { start.value = no; if (end.value < no) end.value = no }
function setEnd(no: number) { end.value = no; if (start.value > no) start.value = no }
async function previewSelection() {
  if (!conversation.value || !rangeValid.value || busy.value) return
  const request = begin('copy'); copying.value = true; error.value = ''
  try {
    const result = await api<ImportedHistory>(url(`conversations/${conversation.value.id}/context`, { start: start.value, end: end.value, task: props.task }), { signal: request.signal })
    if (current('copy', request)) snapshot.value = result
  } catch (e) { if (current('copy', request)) error.value = (e as Error).message }
  finally { if (current('copy', request)) copying.value = false }
}
onMounted(() => searchOwners())
watch([start, end], () => { cancel('copy'); copying.value = false; snapshot.value = null })
onBeforeUnmount(() => { disposed = true; for (const request of requests.values()) request.abort() })
</script>

<template>
  <el-dialog :model-value="true" title="从问答日志导入" width="min(1320px, 94vw)" top="4vh" append-to-body class="history-import-dialog" :close-on-click-modal="false" @close="emit('close')">
    <p class="import-intro">从当前知识库的{{ robot ? '机器人' : '用户' }}会话中选择历史问答，导入后可继续编辑。<template v-if="task === 'answer'">请只选测试问题之前的内容，避免把待测问题的答案放入上下文。</template></p>
    <el-alert v-if="error" :title="error" type="error" :closable="false" class="import-error" />
    <div v-if="!snapshot" class="import-workspace">
      <aside class="conversation-browser">
        <label>{{ robot ? '选择机器人' : '选择用户' }}</label>
        <el-select v-model="ownerId" filterable remote :remote-method="searchOwners" :loading="ownerLoading" :aria-label="robot ? '选择机器人' : '选择用户'" :placeholder="robot ? '搜索名称或序列号' : '搜索姓名或账号'" @change="selectOwner">
          <el-option v-for="owner in owners" :key="owner.id" :value="owner.id" :label="`${owner.name} · ${owner.identity}`" />
          <template #footer><el-button v-if="owners.length < ownerTotal" link :loading="ownerLoading" @click.stop="searchOwners(ownerQuery, true)">加载更多</el-button><el-button v-else-if="!owners.length" link @click.stop="searchOwners()">重新加载</el-button></template>
        </el-select>
        <el-input v-model="query" placeholder="搜索会话标题或问题" clearable :disabled="!ownerId" @keyup.enter="conversationPage = 1; loadConversations()" @clear="conversationPage = 1; loadConversations()"><template #append><el-button :disabled="!ownerId" @click="conversationPage = 1; loadConversations()">搜索</el-button></template></el-input>
        <div v-loading="conversationLoading" class="conversation-options">
          <button v-for="row in conversations" :key="row.id" :class="['conversation-option', { selected: row.id === conversation?.id }]" @click="selectConversation(row)"><strong>{{ row.title }}</strong><span>{{ row.last_turn_no }} 轮 · {{ new Date(row.last_message_at).toLocaleString('zh-CN') }}</span></button>
          <el-empty v-if="!conversationLoading && !conversations.length" :description="ownerId ? '当前知识库暂无匹配会话' : '先选择用户或机器人'" :image-size="55" />
        </div>
        <el-pagination v-if="conversationTotal > 20" v-model:current-page="conversationPage" :page-size="20" :total="conversationTotal" small layout="prev, pager, next" :pager-count="5" @current-change="loadConversations" />
      </aside>
      <section v-loading="turnLoading" class="conversation-preview" aria-label="会话问答预览">
        <template v-if="conversation">
          <header><h3>{{ conversation.title }}</h3><p>阅读完整问题和回答后，在卡片上选择起点、终点。失败、取消和未完成的问答不会导入。</p></header>
          <div class="range-picker"><span>导入范围</span><el-input-number v-model="start" :min="1" :max="conversation.last_turn_no || 1" controls-position="right" aria-label="起始轮次" /><span>至</span><el-input-number v-model="end" :min="1" :max="conversation.last_turn_no || 1" controls-position="right" aria-label="结束轮次" /><span>轮，最多 30 轮</span></div>
          <p v-if="!rangeValid" class="range-warning">请调整起止顺序，并将范围控制在 30 轮以内。</p>
          <div class="turn-options">
            <article v-for="turn in turns" :key="turn.id" :class="['import-turn', { included: turn.importable && turn.turn_no >= start && turn.turn_no <= end }]">
              <div class="import-turn-heading"><strong>第 {{ turn.turn_no }} 轮</strong><span>{{ turn.answer_kind === 'clarification' ? '需要澄清' : statusText(turn.status) }}</span><el-tag v-if="turn.importable && turn.turn_no >= start && turn.turn_no <= end" size="small">已选入范围</el-tag></div>
              <p class="import-question">{{ turn.question }}</p>
              <MarkdownContent v-if="turn.answer" :content="turn.answer" class="import-answer" /><p v-else class="empty-answer">暂无回答</p>
              <div class="turn-actions"><template v-if="turn.importable"><el-button size="small" :type="start === turn.turn_no ? 'primary' : 'default'" plain @click="setStart(turn.turn_no)">从此问答开始</el-button><el-button size="small" :type="end === turn.turn_no ? 'primary' : 'default'" plain @click="setEnd(turn.turn_no)">到此问答结束</el-button></template><span v-else>此轮不可导入</span></div>
            </article>
            <el-empty v-if="!turnLoading && !turns.length" description="会话暂无问答" :image-size="55" />
          </div>
          <el-pagination v-if="turnTotal > 10" v-model:current-page="turnPage" :page-size="10" :total="turnTotal" small layout="prev, pager, next" :pager-count="5" @current-change="loadTurns" />
        </template>
        <el-empty v-else description="选择会话后，在这里预览并选择问题和回答" :image-size="75" />
      </section>
    </div>
    <section v-else class="import-confirmation" aria-label="待导入问答预览">
      <div class="confirmation-heading"><div><h3>{{ snapshot.conversation.title }}</h3><p>选中第 {{ snapshot.start_turn_no }}–{{ snapshot.end_turn_no }} 轮，将导入 {{ snapshot.context.turns.length }} 组问答<template v-if="snapshot.skipped_count">，已跳过 {{ snapshot.skipped_count }} 轮未完成或无回答的记录</template>。</p></div><el-button @click="snapshot = null">返回选择</el-button></div>
      <div class="selected-turns"><article v-for="(turn, index) in snapshot.context.turns" :key="index" class="import-turn"><strong>原会话第 {{ turn.turn_no }} 轮</strong><p class="import-question">{{ turn.question }}</p><MarkdownContent :content="turn.answer" class="import-answer" /></article></div>
    </section>
    <template #footer><div class="import-footer"><p>{{ hasHistory ? '确认后替换当前历史问答及旧摘要；测试问题和参考答案保留。' : '导入内容仅用作历史上下文，参考答案需另行核对资料填写。' }}</p><div><el-button @click="emit('close')">取消</el-button><el-button v-if="!snapshot" type="primary" :disabled="!rangeValid || busy" :loading="copying" @click="previewSelection">预览待导入问答</el-button><el-button v-else type="primary" @click="emit('import', snapshot)">{{ hasHistory ? '替换并导入' : '确认导入' }}</el-button></div></div></template>
  </el-dialog>
</template>

<style scoped>
.import-intro{margin:0 0 16px;font-size:13px;line-height:1.8;color:#7c899b}.import-error{margin-bottom:12px}.import-workspace{display:grid;grid-template-columns:285px minmax(0,1fr);gap:22px;height:calc(84vh - 155px);min-height:300px}.conversation-browser,.conversation-preview{display:flex;flex-direction:column;gap:12px;min-width:0;min-height:0}.conversation-browser{border-right:1px solid #e5eaf1;padding-right:20px}.conversation-browser>label{font-size:13px;font-weight:600}.conversation-options,.turn-options,.selected-turns{min-height:0;flex:1;overflow:auto}.conversation-option{display:block;width:100%;border:1px solid transparent;border-radius:9px;background:#f7f9fc;padding:12px;text-align:left;margin-bottom:9px;cursor:pointer;color:#465569}.conversation-option.selected{background:#fff6e8;border-color:#efab56}.conversation-option strong{display:block;overflow-wrap:anywhere;line-height:1.6}.conversation-option span{display:block;color:#8995a5;font-size:11px;margin-top:6px}.conversation-preview h3,.confirmation-heading h3{font-size:15px;margin:0 0 6px}.conversation-preview header p,.confirmation-heading p{margin:0;color:#8390a2;font-size:12px;line-height:1.7}.range-picker{display:flex;gap:10px;flex-wrap:wrap;align-items:center;font-size:12px;color:#738196}.range-picker .el-input-number{width:100px}.range-warning{font-size:12px;color:#be702b;margin:0}.import-turn{border:1px solid #e3e9f1;border-radius:10px;padding:16px;margin-bottom:12px;overflow-wrap:anywhere}.import-turn.included{border-color:#edab56;background:#fffcf6}.import-turn-heading{display:flex;align-items:center;gap:10px;font-size:13px;flex-wrap:wrap}.import-turn-heading>span{color:#8591a1;font-size:12px}.import-question{font-weight:600;white-space:pre-wrap;font-size:14px;line-height:1.8;margin:12px 0}.import-answer{font-size:13px;line-height:1.8}.empty-answer,.turn-actions>span{font-size:12px;color:#9aa4b1}.turn-actions{display:flex;justify-content:flex-end;gap:8px;flex-wrap:wrap;margin-top:14px}.turn-actions .el-button+.el-button{margin-left:0}.import-confirmation{display:flex;flex-direction:column;gap:16px;height:calc(84vh - 155px);min-height:300px}.confirmation-heading{display:flex;align-items:flex-start;gap:16px;justify-content:space-between}.selected-turns{padding-right:8px}.import-footer{display:flex;align-items:center;justify-content:space-between;gap:16px}.import-footer p{font-size:12px;line-height:1.7;color:#8390a2;text-align:left;margin:0}.import-footer>div{display:flex;flex-shrink:0}@media(max-width:800px){.import-workspace{grid-template-columns:minmax(0,1fr);grid-template-rows:205px minmax(0,1fr);gap:14px;height:calc(88vh - 235px);min-height:360px}.conversation-browser{padding:0 0 12px;border-right:0;border-bottom:1px solid #e5eaf1;gap:7px}.conversation-browser>label{display:none}.conversation-option{padding:8px}.conversation-option span{display:none}.conversation-preview header p{display:none}.range-picker{gap:5px}.range-picker .el-input-number{width:80px}.range-picker>span:last-child{display:none}.import-footer{flex-wrap:wrap;gap:8px}.import-footer>div{margin-left:auto}.import-confirmation{height:calc(85vh - 205px)}.import-intro{font-size:12px;margin-bottom:10px}.import-turn{padding:12px}}
</style>
