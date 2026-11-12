<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Delete, Position, ChatDotRound, Refresh, Fold, Expand, ArrowDown } from '@element-plus/icons-vue'
import { api } from '../lib/session'
import { type Conversation, type ConversationPage } from '../lib/conversations'
import { useConversation } from '../lib/useConversation'
import ConversationTurns from '../components/ConversationTurns.vue'
import ConversationLengthNotice from '../components/ConversationLengthNotice.vue'

const route = useRoute(), router = useRouter()
const { conversation, turns, loading, sending, error, nextBefore, busy, reset, open, older, send, retry } = useConversation()
const history = ref<Conversation[]>([]), historyLoading = ref(false), historyError = ref('')
const cursor = ref<string | null>(null), historySearch = ref('')
const bases = ref<{ id: string; name: string }[]>([]), baseId = ref(''), question = ref('')
const suggestions = ref<{ question: string; suggestion_token: string }[]>([]), suggestionsLoading = ref(false)
const suggestionsError = ref(''), selectedSuggestion = ref<{ question: string; suggestion_token: string } | null>(null)
const messagePanel = ref<HTMLElement>()
const historyExpanded = ref(window.innerWidth > 720), pinned = ref(true)
function trackScroll() { const panel = messagePanel.value; if (panel) pinned.value = panel.scrollHeight - panel.scrollTop - panel.clientHeight < 120 }
function scrollToLatest() { pinned.value = true; messagePanel.value?.scrollTo({ top: messagePanel.value.scrollHeight, behavior: 'smooth' }) }
watch(turns, async () => { if (pinned.value) { await nextTick(); scrollToLatest() } }, { deep: true })
const canSend = computed(() => !loading.value && !!baseId.value && !busy.value && (!route.query.conversation_id || !!conversation.value) && !conversation.value?.closed_at && (!conversation.value || conversation.value.knowledge_base_status === 'active'))
let historyGeneration = 0, suggestionGeneration = 0, disposed = false
let suggestionsController = new AbortController()

async function loadHistory(more = false) {
  if (more && !cursor.value) return
  const current = ++historyGeneration
  historyLoading.value = true; historyError.value = ''
  try {
    const params = new URLSearchParams({ q: historySearch.value.trim() })
    if (more && cursor.value) params.set('cursor', cursor.value)
    const result = await api<ConversationPage>(`/web/conversations?${params}`)
    if (current !== historyGeneration || disposed) return
    history.value = more ? [...history.value, ...result.items.filter(item => !history.value.some(old => old.id === item.id))] : result.items
    cursor.value = result.next_cursor
  } catch (e) { if (current === historyGeneration && !disposed) historyError.value = (e as Error).message }
  finally { if (current === historyGeneration && !disposed) historyLoading.value = false }
}
async function loadSuggestions() {
  const current = ++suggestionGeneration
  suggestionsController.abort(); suggestionsController = new AbortController()
  suggestions.value = []; suggestionsError.value = ''; suggestionsLoading.value = false
  if (!baseId.value || conversation.value || route.query.conversation_id) return
  suggestionsLoading.value = true
  try {
    const result = await api<{ questions: typeof suggestions.value }>('/web/suggested-questions', {
      method: 'POST', body: JSON.stringify({ knowledge_base_id: baseId.value }), timeoutMs: 120000, signal: suggestionsController.signal,
    })
    if (current === suggestionGeneration && !disposed) suggestions.value = result.questions
  } catch (e) { if (current === suggestionGeneration && !disposed) suggestionsError.value = (e as Error).message }
  finally { if (current === suggestionGeneration && !disposed) suggestionsLoading.value = false }
}
async function navigate(id?: string) {
  question.value = ''; selectedSuggestion.value = null
  if (window.innerWidth <= 720) historyExpanded.value = false
  if (id) {
    if (route.query.conversation_id === id && !conversation.value) await openFromRoute()
    else await router.replace({ path: '/qa', query: { conversation_id: id } })
  }
  else {
    reset(); await router.replace({ path: '/qa' })
    if (!bases.value.some(b => b.id === baseId.value)) baseId.value = bases.value[0]?.id || ''
    void loadSuggestions()
  }
}
async function openFromRoute() {
  const id = typeof route.query.conversation_id === 'string' ? route.query.conversation_id : ''
  if (!id) { reset(); return }
  if (conversation.value?.id === id) return
  pinned.value = true
  suggestionsController.abort(); suggestionGeneration++
  await open(id)
  if (conversation.value?.id === id) baseId.value = conversation.value.knowledge_base_id
}
async function ask() {
  if (!canSend.value || !question.value.trim()) return
  const result = await send(question.value, baseId.value,
    selectedSuggestion.value?.question === question.value.trim() ? selectedSuggestion.value.suggestion_token : undefined)
  if (result) {
    question.value = ''; selectedSuggestion.value = null
    await router.replace({ path: '/qa', query: { conversation_id: result.id } })
    void loadHistory()
    await nextTick(); messagePanel.value?.scrollTo({ top: messagePanel.value.scrollHeight, behavior: 'smooth' })
  }
}
async function remove(item: Conversation) {
  try { await ElMessageBox.confirm('删除后将从你的历史中移除，管理员仍可审计查看。', '删除对话', { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' }) } catch { return }
  try {
    await api(`/web/conversations/${item.id}`, { method: 'DELETE' })
    if (conversation.value?.id === item.id) await navigate()
    await loadHistory()
  } catch (e) { ElMessage.error((e as Error).message) }
}
watch(() => route.query.conversation_id, openFromRoute)
watch(baseId, () => { selectedSuggestion.value = null; if (!conversation.value) void loadSuggestions() })
watch(question, () => { if (selectedSuggestion.value?.question !== question.value.trim()) selectedSuggestion.value = null })
onMounted(async () => {
  void loadHistory(); void openFromRoute()
  try {
    const result: typeof bases.value = []
    for (let page = 1; ; page++) {
      const batch = await api<{ items: typeof bases.value; total: number }>(`/knowledge-bases?status=active&page_size=100&page=${page}`)
      if (disposed) return
      result.push(...batch.items)
      if (result.length >= batch.total || batch.items.length < 100) break
    }
    bases.value = result
    if (!baseId.value) baseId.value = result[0]?.id || ''
  } catch (e) { if (!disposed) error.value = (e as Error).message }
})
onBeforeUnmount(() => { disposed = true; historyGeneration++; suggestionGeneration++; suggestionsController.abort() })
</script>

<template>
  <div :class="['chat-workspace', { 'history-collapsed': !historyExpanded }]">
    <button v-if="historyExpanded" class="chat-history-backdrop" aria-label="关闭历史侧栏" @click="historyExpanded = false" />
    <aside class="chat-history" aria-label="我的历史对话">
      <el-button type="primary" :icon="Plus" class="new-chat" @click="navigate()">新对话</el-button>
      <div class="history-title"><span>我的对话</span><el-button text :icon="Refresh" aria-label="刷新历史" @click="loadHistory()" /></div>
      <el-input v-model="historySearch" placeholder="搜索历史对话" clearable @keyup.enter="loadHistory()" @clear="loadHistory()" />
      <el-alert v-if="historyError" :title="historyError" type="error" :closable="false" />
      <div v-loading="historyLoading" class="history-items">
        <div v-for="item in history" :key="item.id" :class="['history-item', { selected: conversation?.id === item.id }]">
          <button class="history-open" @click="navigate(item.id)"><strong>{{ item.title }}</strong><small>{{ item.knowledge_base_name }} · {{ new Date(item.last_message_at).toLocaleDateString() }}</small></button>
          <el-button text :icon="Delete" :aria-label="`删除对话 ${item.title}`" @click="remove(item)" />
        </div>
        <p v-if="!history.length && !historyLoading" class="muted">还没有对话，发送第一个问题吧。</p>
        <el-button v-if="cursor" text :loading="historyLoading" @click="loadHistory(true)">更多历史</el-button>
      </div>
    </aside>
    <main class="chat-main">
      <header class="chat-header"><div class="chat-title"><el-button text :icon="historyExpanded ? Fold : Expand" :aria-label="historyExpanded ? '收起历史侧栏' : '展开历史侧栏'" @click="historyExpanded = !historyExpanded" /><div><h1>{{ conversation?.title || '知识问答' }}</h1><small v-if="conversation">{{ conversation.knowledge_base_name }} · {{ conversation.turn_count }} 轮对话</small></div></div>
        <el-select v-if="!conversation" v-model="baseId" placeholder="选择知识库" aria-label="选择知识库" :disabled="sending" filterable><el-option v-for="base in bases" :key="base.id" :value="base.id" :label="base.name" /></el-select>
        <el-button v-else text @click="navigate()">换知识库 / 新对话</el-button>
      </header>
      <div ref="messagePanel" v-loading="loading" class="chat-messages" @scroll="trackScroll"><div class="message-column">
        <el-button v-if="nextBefore" text :loading="loading" @click="older">加载更早消息</el-button>
        <div v-if="!turns.length && !loading" class="chat-welcome"><el-icon :size="38"><ChatDotRound /></el-icon><h2>今天想了解什么？</h2><p>本次对话会记住上下文，每个新对话独立开始。</p>
          <div class="suggestion-list"><span v-if="suggestionsLoading">正在准备推荐问题…</span><button v-for="item in suggestions" :key="item.question" @click="question = item.question; selectedSuggestion = item">{{ item.question }}</button><p v-if="suggestionsError">推荐问题暂不可用，你仍可以直接提问。</p><el-button v-if="baseId && !suggestionsLoading" text @click="loadSuggestions">刷新推荐</el-button></div>
        </div>
        <ConversationTurns :turns="turns" :readonly="!!conversation?.closed_at" @retry="retry" />
      </div></div>
      <footer class="chat-composer"><el-button v-if="!pinned && turns.length" circle :icon="ArrowDown" class="scroll-latest" aria-label="滚动到最新消息" @click="scrollToLatest" /><div class="composer-box">
        <ConversationLengthNotice v-if="conversation" :turn-count="conversation.turn_count" :disabled="busy || loading" @new-conversation="navigate()" />
        <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />
        <el-button v-if="error && route.query.conversation_id" text @click="open(String(route.query.conversation_id))">刷新当前对话</el-button>
        <el-alert v-if="conversation?.closed_at || (conversation && conversation.knowledge_base_status !== 'active')" title="此会话目前只读，可查看已有历史。" type="info" :closable="false" />
        <el-input v-model="question" type="textarea" :rows="3" maxlength="2000" show-word-limit aria-label="你的问题" placeholder="输入问题，或接着上文继续问…" :disabled="!canSend" @keydown.ctrl.enter.prevent="ask" />
        <div class="composer-actions"><small>依据知识库资料回答 · Ctrl + Enter 发送</small><el-button type="primary" :icon="Position" :loading="sending" :disabled="!canSend || !question.trim()" @click="ask">{{ busy ? '回答中' : '发送问题' }}</el-button></div>
      </div><p class="answer-disclaimer">回答基于知识库资料，请结合原文核对重要信息</p></footer>
    </main>
  </div>
</template>

<style scoped src="../styles/chat-workspace.css"></style>
