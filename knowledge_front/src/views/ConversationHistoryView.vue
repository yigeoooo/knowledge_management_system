<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Download } from '@element-plus/icons-vue'
import { api } from '../lib/session'
import { type Conversation, type ConversationPage, type Turn, type TurnPage } from '../lib/conversations'
import ConversationTurns from '../components/ConversationTurns.vue'

interface Owner { id: string; name: string; identity: string; status: string; conversation_count: number; turn_count: number }
const source = ref('WEB'), ownerSearch = ref(''), historySearch = ref(''), deleted = ref('')
const owners = ref<Owner[]>([]), selected = ref<Owner | null>(null), history = ref<Conversation[]>([])
const detail = ref<Conversation | null>(null), turns = ref<Turn[]>([])
const cursor = ref<string | null>(null), before = ref<number | null>(null)
const ownerLoading = ref(false), historyLoading = ref(false), detailLoading = ref(false), error = ref('')
const page = ref(1), total = ref(0)
const exporting = ref(false), exportController = new AbortController()
let ownerGeneration = 0, historyGeneration = 0, detailGeneration = 0, disposed = false
function clearDetails() { detailGeneration++; detail.value = null; turns.value = []; before.value = null; detailLoading.value = false }
async function loadOwners() {
  const current = ++ownerGeneration
  owners.value = []; total.value = 0
  historyGeneration++; selected.value = null; history.value = []; cursor.value = null; historyLoading.value = false; clearDetails()
  ownerLoading.value = true; error.value = ''
  try {
    const result = await api<{ items: Owner[]; total: number }>(`/admin/${source.value === 'WEB' ? 'qa-users' : 'qa-robots'}?q=${encodeURIComponent(ownerSearch.value)}&page=${page.value}`)
    if (current !== ownerGeneration || disposed) return
    owners.value = result.items; total.value = result.total
  } catch (e) { if (current === ownerGeneration && !disposed) error.value = (e as Error).message }
  finally { if (current === ownerGeneration && !disposed) ownerLoading.value = false }
}
async function selectOwner(owner: Owner) {
  selected.value = owner; history.value = []; historySearch.value = ''; cursor.value = null; clearDetails()
  await loadHistory()
}
async function loadHistory(more = false) {
  if (!selected.value || (more && !cursor.value)) return
  const current = ++historyGeneration
  if (!more) clearDetails()
  historyLoading.value = true; error.value = ''
  try {
    const params = new URLSearchParams({ source_type: source.value, [source.value === 'WEB' ? 'user_id' : 'robot_id']: selected.value.id, q: historySearch.value, deleted: deleted.value })
    if (more && cursor.value) params.set('cursor', cursor.value)
    const result = await api<ConversationPage>(`/admin/qa-conversations?${params}`)
    if (current !== historyGeneration || disposed) return
    history.value = more ? [...history.value, ...result.items] : result.items; cursor.value = result.next_cursor
  } catch (e) { if (current === historyGeneration && !disposed) error.value = (e as Error).message }
  finally { if (current === historyGeneration && !disposed) historyLoading.value = false }
}
async function selectConversation(item: Conversation, more = false) {
  if (!more) { clearDetails(); detail.value = item }
  const current = ++detailGeneration
  detailLoading.value = true; error.value = ''
  try {
    const result = await api<TurnPage>(`/admin/qa-conversations/${item.id}/turns${more && before.value ? `?before=${before.value}` : ''}`)
    if (current !== detailGeneration || disposed) return
    detail.value = result.conversation; turns.value = more ? [...result.items, ...turns.value] : result.items; before.value = result.next_before
  } catch (e) { if (current === detailGeneration && !disposed) error.value = (e as Error).message }
  finally { if (current === detailGeneration && !disposed) detailLoading.value = false }
}
async function exportConversation() {
  const item = detail.value
  if (!item || exporting.value || detailLoading.value) return
  exporting.value = true
  try {
    const blob = await api<Blob>(`/admin/qa-conversations/${item.id}/export`, {
      responseType: 'blob', timeoutMs: 120000, signal: exportController.signal,
    })
    if (disposed) return
    const url = URL.createObjectURL(blob), link = document.createElement('a')
    const title = item.title.replace(/[\\/:*?"<>|\x00-\x1f]/g, '_').slice(0, 40).trim() || '历史会话'
    link.href = url; link.download = `会话记录_${title}.docx`
    document.body.appendChild(link); link.click(); link.remove()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
    ElMessage.success('已导出完整会话')
  } catch (e) { if (!disposed) ElMessage.error((e as Error).message) }
  finally { if (!disposed) exporting.value = false }
}
watch(source, () => { ownerSearch.value = ''; page.value = 1; void loadOwners() })
onMounted(loadOwners)
onBeforeUnmount(() => { disposed = true; ownerGeneration++; historyGeneration++; detailGeneration++; exportController.abort() })
</script>

<template>
  <div class="page-heading"><div><div class="page-eyebrow">CONVERSATION HISTORY</div><h1>问答日志</h1><p>选择用户或机器人，查看其完整历史对话与回答依据。</p></div><el-radio-group v-model="source"><el-radio-button value="WEB">用户对话</el-radio-button><el-radio-button value="ROBOT">机器人对话</el-radio-button></el-radio-group></div>
  <el-alert v-if="error" :title="error" type="error" show-icon :closable="false" class="history-error" />
  <div class="audit-workspace">
    <aside class="owner-panel" aria-label="选择历史归属">
      <h3>{{ source === 'WEB' ? '选择用户' : '选择机器人' }}</h3>
      <el-input v-model="ownerSearch" :placeholder="source === 'WEB' ? '搜索用户姓名或账号' : '搜索机器人名称或序列号'" clearable @keyup.enter="page = 1; loadOwners()" @clear="page = 1; loadOwners()" />
      <div v-loading="ownerLoading" class="owner-items"><button v-for="owner in owners" :key="owner.id" :class="['owner-item', { selected: selected?.id === owner.id }]" @click="selectOwner(owner)"><strong>{{ owner.name }}</strong><small>{{ owner.identity }} · {{ owner.conversation_count }} 个对话</small><small v-if="owner.status !== 'active'">已停用或删除，历史保留</small></button><el-empty v-if="!owners.length && !ownerLoading" description="暂无问答历史" :image-size="55" /></div>
      <el-pagination v-if="total > 30" v-model:current-page="page" :page-size="30" :total="total" layout="prev, next" @current-change="loadOwners" />
    </aside>
    <section class="history-panel" aria-label="会话列表">
      <h3>{{ selected ? `${selected.name}的对话` : '历史会话' }}</h3>
      <template v-if="selected"><el-input v-model="historySearch" placeholder="搜索会话或问题" clearable @keyup.enter="loadHistory()" @clear="loadHistory()" /><el-select v-model="deleted" aria-label="删除状态" @change="loadHistory()"><el-option label="全部历史（含已删除）" value="" /><el-option label="未删除" value="false" /><el-option label="用户已删除" value="true" /></el-select></template>
      <div v-loading="historyLoading" class="conversation-items"><button v-for="item in history" :key="item.id" :class="['audit-conversation', { selected: detail?.id === item.id }]" @click="selectConversation(item)"><strong>{{ item.title }}</strong><small>{{ item.knowledge_base_name }} · {{ item.turn_count }} 轮</small><small>{{ new Date(item.last_message_at).toLocaleString() }}</small><el-tag v-if="item.deleted_at" size="small" type="info">已删除</el-tag><el-tag v-else-if="item.closed_at" size="small" type="warning">已关闭 · 只读</el-tag></button><el-empty v-if="!history.length && !historyLoading" :description="selected ? '该对象暂无匹配会话' : '请先选择左侧用户或机器人'" :image-size="65" /><el-button v-if="cursor" text @click="loadHistory(true)">更多会话</el-button></div>
    </section>
    <section v-loading="detailLoading" class="detail-panel" aria-label="完整对话详情">
      <template v-if="detail"><div class="detail-heading"><div class="detail-title"><h3>{{ detail.title }}</h3><el-button :icon="Download" :loading="exporting" :disabled="detailLoading" @click="exportConversation">导出会话（Word）</el-button></div><p>{{ detail.owner_name }} · {{ detail.knowledge_base_name }} · {{ detail.turn_count }} 轮</p><el-tag v-if="detail.deleted_at" type="info">已软删除 · 审计保留</el-tag><el-tag v-if="detail.closed_at" type="warning">会话已关闭</el-tag></div><el-button v-if="before" text @click="selectConversation(detail, true)">加载更早消息</el-button><ConversationTurns :turns="turns" readonly /></template>
      <el-empty v-else description="选择一个会话，查看连续问答" :image-size="90" />
    </section>
  </div>
</template>

<style scoped>
.detail-title { display: flex; align-items: flex-start; justify-content: space-between; gap: 14px; flex-wrap: wrap; }
.detail-title h3 { flex: 1; min-width: 120px; overflow-wrap: anywhere; }
.detail-title .el-button { flex-shrink: 0; }
.history-error{margin-bottom:18px}.audit-workspace{display:grid;grid-template-columns:210px 270px minmax(0,1fr);border:1px solid #e6ebf2;border-radius:16px;overflow:hidden;background:white;min-height:600px;height:calc(100dvh - 230px)}.owner-panel,.history-panel{padding:18px 12px;border-right:1px solid #edf0f5;display:flex;flex-direction:column;gap:12px;min-height:0;background:#fafbfd}.history-panel{background:#fff}.audit-workspace h3{font-size:14px;margin:0 0 6px;color:#34435a}.owner-items,.conversation-items{overflow:auto;flex:1;min-height:70px}.owner-item,.audit-conversation{width:100%;border:0;border-radius:10px;background:transparent;text-align:left;display:block;padding:14px 10px;margin-bottom:6px;cursor:pointer;color:#3a4b62}.owner-item:hover,.audit-conversation:hover{background:#f0f4fa}.owner-item.selected,.audit-conversation.selected{background:#eaf1fc}.owner-item strong,.audit-conversation strong{display:block;font-weight:500;font-size:13px;overflow-wrap:anywhere;line-height:1.6}.owner-item small,.audit-conversation small{display:block;color:#8b98aa;font-size:11px;margin-top:5px}.audit-conversation .el-tag{margin-top:8px}.detail-panel{padding:24px clamp(20px,3vw,44px);overflow:auto;min-width:0}.detail-heading{padding-bottom:22px;border-bottom:1px solid #edf1f6;margin-bottom:24px}.detail-heading p{color:#8c99ab;font-size:12px}.detail-heading .el-tag{margin-right:8px}@media(max-width:1100px){.audit-workspace{grid-template-columns:180px 220px minmax(0,1fr)}}@media(max-width:800px){.audit-workspace{grid-template-columns:1fr 1fr;height:auto}.owner-panel,.history-panel{height:330px}.detail-panel{grid-column:1/-1;min-height:350px;border-top:1px solid #edf0f5}}
</style>
