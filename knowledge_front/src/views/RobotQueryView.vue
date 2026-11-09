<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Delete, Position, Cpu, Refresh, Fold, Expand, ArrowDown } from '@element-plus/icons-vue'
import { api } from '../lib/session'
import { type Conversation, type ConversationPage, type Turn } from '../lib/conversations'
import { useRobotConversation, type RobotOption } from '../lib/useRobotConversation'
import ConversationTurns from '../components/ConversationTurns.vue'

const route = useRoute(), router = useRouter()
const robots = ref<RobotOption[]>([]), robotId = ref(''), robotsLoading = ref(true), robotsError = ref('')
const robot = computed(() => robots.value.find(r => r.id === robotId.value))
const { conversation, turns, loading, sending, error, nextBefore, busy, awaitingAnswer, reset, open, older, send, resume, retry } = useRobotConversation(robot)
const history = ref<Conversation[]>([]), historyLoading = ref(false), historyError = ref(''), cursor = ref<string | null>(null), historySearch = ref('')
const question = ref(''), messagePanel = ref<HTMLElement>(), historyExpanded = ref(window.innerWidth > 720), pinned = ref(true)
const robotReady = computed(() => robot.value?.status === 'active' && !!robot.value.knowledge_base_id && robot.value.knowledge_base_status === 'active')
const readonly = computed(() => !robotReady.value || !!conversation.value?.closed_at || (!!conversation.value && conversation.value.knowledge_base_status !== 'active'))
const canSend = computed(() => !robotsLoading.value && !loading.value && !busy.value && !readonly.value && (!route.query.conversation_id || !!conversation.value))
let historyGeneration = 0, disposed = false, initialized = false
function trackScroll() { const panel = messagePanel.value; if (panel) pinned.value = panel.scrollHeight - panel.scrollTop - panel.clientHeight < 120 }
function scrollToLatest() { pinned.value = true; messagePanel.value?.scrollTo({ top: messagePanel.value.scrollHeight, behavior: 'smooth' }) }
watch(turns, async () => { if (pinned.value) { await nextTick(); scrollToLatest() } }, { deep: true })

async function loadHistory(more = false) {
  if (!robotId.value || (more && !cursor.value)) return
  const current = ++historyGeneration; historyLoading.value = true; historyError.value = ''
  try {
    const params = new URLSearchParams({ q: historySearch.value.trim() })
    if (more && cursor.value) params.set('cursor', cursor.value)
    const result = await api<ConversationPage>(`/admin/robot-chat/robots/${robotId.value}/conversations?${params}`)
    if (current !== historyGeneration || disposed) return
    history.value = more ? [...history.value, ...result.items.filter(item => !history.value.some(old => old.id === item.id))] : result.items
    cursor.value = result.next_cursor
  } catch (e) { if (current === historyGeneration && !disposed) historyError.value = (e as Error).message }
  finally { if (current === historyGeneration && !disposed) historyLoading.value = false }
}
async function openFromRoute() {
  if (!initialized) return
  const rid = typeof route.query.robot_id === 'string' ? route.query.robot_id : robots.value.find(r => r.status === 'active' && r.knowledge_base_status === 'active')?.id || robots.value[0]?.id || ''
  const cid = typeof route.query.conversation_id === 'string' ? route.query.conversation_id : ''
  if (robotId.value !== rid) {
    reset(); robotId.value = rid; question.value = ''; history.value = []; cursor.value = null; historySearch.value = ''; historyGeneration++
    historyLoading.value = false; historyError.value = ''
    if (robot.value) void loadHistory()
  }
  if (!robot.value) { reset(); error.value = rid ? '机器人不存在，请重新选择。' : ''; return }
  if (cid && conversation.value?.id !== cid) { question.value = ''; pinned.value = true; await open(cid) }
  else if (!cid && (conversation.value || turns.value.length)) reset()
}
async function navigate(cid?: string, rid = robotId.value) {
  const unchanged = route.query.robot_id === rid && (route.query.conversation_id || undefined) === cid
  reset(); question.value = ''; pinned.value = true
  if (window.innerWidth <= 720) historyExpanded.value = false
  await router.replace({ path: '/robot-qa', query: { robot_id: rid || undefined, conversation_id: cid } })
  if (unchanged) await openFromRoute()
}
async function accepted(result: Conversation | null) {
  if (!result) return
  question.value = ''
  await router.replace({ path: '/robot-qa', query: { robot_id: robotId.value, conversation_id: result.id } })
  void loadHistory(); await nextTick(); scrollToLatest()
}
async function ask() { if (canSend.value && question.value.trim()) await accepted(await send(question.value)) }
async function retryAnswer(turn: Turn) { if (!readonly.value) await accepted(await retry(turn)) }
async function resumeAnswer() { if (!readonly.value) await accepted(await resume()) }
async function remove(item: Conversation) {
  const selected = robot.value
  if (!selected) return
  try { await ElMessageBox.confirm('删除后将从机器人的历史中移除，管理员仍可在问答日志查看。', '删除对话', { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' }) } catch { return }
  try {
    await api(`/robot/conversations/${item.id}`, { method: 'DELETE', headers: { 'X-Robot-Serial': selected.serial_no } })
    if (robotId.value !== selected.id || disposed) return
    if (conversation.value?.id === item.id) await navigate()
    await loadHistory()
  } catch (e) { ElMessage.error((e as Error).message) }
}
async function loadRobots() {
  robotsLoading.value = true; robotsError.value = ''
  try {
    const result: RobotOption[] = []
    for (let page = 1; ; page++) {
      const batch = await api<{ items: RobotOption[]; total: number }>(`/admin/robot-chat/robots?page_size=100&page=${page}`)
      if (disposed) return
      result.push(...batch.items)
      if (result.length >= batch.total || batch.items.length < 100) break
    }
    robots.value = result; initialized = true; await openFromRoute()
  } catch (e) { if (!disposed) robotsError.value = (e as Error).message }
  finally { if (!disposed) robotsLoading.value = false }
}
watch(() => [route.query.robot_id, route.query.conversation_id], openFromRoute)
onMounted(loadRobots)
onBeforeUnmount(() => { disposed = true; historyGeneration++ })
</script>

<template>
  <div :class="['chat-workspace', { 'history-collapsed': !historyExpanded }]">
    <button v-if="historyExpanded" class="chat-history-backdrop" aria-label="关闭历史侧栏" @click="historyExpanded = false" />
    <aside class="chat-history" aria-label="机器人历史对话">
      <el-button type="primary" :icon="Plus" class="new-chat" :disabled="!robot" @click="navigate()">新对话</el-button>
      <div class="history-title"><span>机器人的对话</span><el-button text :icon="Refresh" :disabled="!robot" aria-label="刷新历史" @click="loadHistory()" /></div>
      <el-input v-model="historySearch" placeholder="搜索历史对话" :disabled="!robot" clearable @keyup.enter="loadHistory()" @clear="loadHistory()" />
      <el-alert v-if="historyError" :title="historyError" type="error" :closable="false" />
      <div v-loading="historyLoading" class="history-items">
        <div v-for="item in history" :key="item.id" :class="['history-item', { selected: conversation?.id === item.id }]">
          <button class="history-open" @click="navigate(item.id)"><strong>{{ item.title }}</strong><small>{{ item.knowledge_base_name }} · {{ item.closed_at ? '已关闭' : new Date(item.last_message_at).toLocaleDateString() }}</small></button>
          <el-button text :icon="Delete" :disabled="robot?.status !== 'active'" :aria-label="`删除对话 ${item.title}`" @click="remove(item)" />
        </div>
        <p v-if="!history.length && !historyLoading" class="muted">{{ robot ? '还没有对话，发送第一个问题吧。' : '选择机器人后查看历史对话。' }}</p>
        <el-button v-if="cursor" text :loading="historyLoading" @click="loadHistory(true)">更多历史</el-button>
      </div>
    </aside>
    <main class="chat-main">
      <header class="chat-header"><div class="chat-title"><el-button text :icon="historyExpanded ? Fold : Expand" :aria-label="historyExpanded ? '收起历史侧栏' : '展开历史侧栏'" @click="historyExpanded = !historyExpanded" /><div><h1>机器人问答</h1><small v-if="robot">{{ conversation?.knowledge_base_name || robot.knowledge_base_name || '未绑定知识库' }}<template v-if="conversation"> · {{ conversation.turn_count }} 轮对话</template></small></div></div>
        <el-select :model-value="robotId" placeholder="选择机器人" aria-label="选择机器人" :loading="robotsLoading" filterable @update:model-value="navigate(undefined, $event)"><el-option v-for="item in robots" :key="item.id" :value="item.id" :label="`${item.name || item.serial_no}${item.status === 'active' ? '' : '（已停用）'}`" /></el-select>
      </header>
      <div ref="messagePanel" v-loading="loading || robotsLoading" class="chat-messages" @scroll="trackScroll"><div class="message-column">
        <el-button v-if="nextBefore" text :loading="loading" @click="older">加载更早消息</el-button>
        <div v-if="!turns.length && !loading" class="chat-welcome"><el-icon :size="38"><Cpu /></el-icon><h2>像机器人一样，开始提问</h2><p>选择机器人，即可使用它绑定的知识库测试问答。<br>同一对话记住上下文，新对话独立开始。</p>
          <p v-if="robot" class="robot-identity">{{ robot.name || '机器人' }} · {{ robot.serial_no }}</p>
          <p v-else-if="!robotsLoading && !robotsError">暂无机器人，请先在机器人管理中创建并绑定知识库。</p>
        </div>
        <ConversationTurns :turns="turns" :readonly="readonly" :retry-disabled="busy" plain @retry="retryAnswer" />
      </div></div>
      <footer class="chat-composer"><el-button v-if="!pinned && turns.length" circle :icon="ArrowDown" class="scroll-latest" aria-label="滚动到最新消息" @click="scrollToLatest" /><div class="composer-box">
        <el-alert v-if="robotsError || error" :title="robotsError || error" type="error" :closable="false" show-icon />
        <el-button v-if="robotsError" text @click="loadRobots">重新加载机器人</el-button>
        <el-button v-if="error && route.query.conversation_id && !sending" text @click="open(String(route.query.conversation_id))">刷新当前对话</el-button>
        <el-alert v-if="robot && readonly" :title="conversation?.closed_at ? '机器人绑定已变更，此会话只读，请开启新对话。' : '机器人或知识库不可用，请检查启用状态和知识库绑定。'" type="info" :closable="false" />
        <el-button v-if="awaitingAnswer && !sending && !readonly" type="primary" plain @click="resumeAnswer">继续等待回答</el-button>
        <el-input v-model="question" type="textarea" :rows="3" maxlength="2000" show-word-limit aria-label="你的问题" placeholder="输入问题，测试机器人的回答…" :disabled="!canSend" @keydown.ctrl.enter.prevent="ask" />
        <div class="composer-actions"><small>简洁文本回答 · Ctrl + Enter 发送</small><el-button type="primary" :icon="Position" :loading="sending" :disabled="!canSend || !question.trim()" @click="ask">{{ busy ? '回答中' : '发送问题' }}</el-button></div>
      </div><p class="answer-disclaimer">测试对话保存在所选机器人的历史中，可在问答日志查看</p></footer>
    </main>
  </div>
</template>

<style scoped src="../styles/chat-workspace.css"></style>
<style scoped>
.robot-identity { margin-top: 20px; }
</style>
