import { computed, onBeforeUnmount, ref } from 'vue'
import { api, ApiError } from './session'
import { pending, requestId, type Conversation, type Turn, type TurnPage } from './conversations'

export function useConversation() {
  const conversation = ref<Conversation | null>(null), turns = ref<Turn[]>([])
  const loading = ref(false), sending = ref(false), error = ref(''), nextBefore = ref<number | null>(null)
  let generation = 0, timer: ReturnType<typeof setTimeout> | undefined
  let controller = new AbortController(), attempt: { signature: string; id: string } | null = null
  const busy = computed(() => sending.value || turns.value.some(pending))
  function reset() {
    generation++; controller.abort(); controller = new AbortController(); clearTimeout(timer)
    conversation.value = null; turns.value = []; nextBefore.value = null
    loading.value = false; sending.value = false; error.value = ''; attempt = null
  }
  function schedulePoll() {
    clearTimeout(timer)
    const turn = turns.value.find(pending)
    if (!turn || !conversation.value) return
    const current = generation, cid = conversation.value.id
    timer = setTimeout(async () => {
      try {
        const updated = await api<Turn>(`/web/conversations/${cid}/turns/${turn.id}`, { signal: controller.signal })
        if (current !== generation) return
        turns.value = turns.value.map(item => item.id === updated.id ? updated : item)
        error.value = ''; schedulePoll()
      } catch (e) {
        if (current !== generation) return
        error.value = (e as Error).message
        if (e instanceof ApiError && [401, 403, 404].includes(e.status)) return
        timer = setTimeout(schedulePoll, 3000)
      }
    }, 1200)
  }
  async function open(id: string) {
    reset(); const current = generation; loading.value = true
    try {
      const result = await api<TurnPage>(`/web/conversations/${id}/turns`, { signal: controller.signal })
      if (current !== generation) return
      conversation.value = result.conversation; turns.value = result.items; nextBefore.value = result.next_before; schedulePoll()
    } catch (e) { if (current === generation) error.value = (e as Error).message }
    finally { if (current === generation) loading.value = false }
  }
  async function older() {
    if (!nextBefore.value || !conversation.value || loading.value) return
    const current = generation; loading.value = true
    try {
      const result = await api<TurnPage>(`/web/conversations/${conversation.value.id}/turns?before=${nextBefore.value}`, { signal: controller.signal })
      if (current !== generation) return
      turns.value = [...result.items, ...turns.value]; nextBefore.value = result.next_before
    } catch (e) { if (current === generation) error.value = (e as Error).message }
    finally { if (current === generation) loading.value = false }
  }
  async function send(question: string, baseId: string, suggestionToken?: string) {
    if (busy.value || loading.value || !question.trim()) return null
    const current = generation, cid = conversation.value?.id
    const signature = JSON.stringify([cid, baseId, question.trim(), suggestionToken])
    if (attempt?.signature !== signature) attempt = { signature, id: requestId() }
    const payload = cid ? { question: question.trim(), request_id: attempt.id, expected_last_turn_no: conversation.value!.last_turn_no }
      : { question: question.trim(), request_id: attempt.id, knowledge_base_id: baseId, suggestion_token: suggestionToken }
    sending.value = true; error.value = ''
    try {
      const result = await api<Turn & { conversation: Conversation }>(cid ? `/web/conversations/${cid}/turns` : '/web/conversations', {
        method: 'POST', body: JSON.stringify(payload), signal: controller.signal,
      })
      if (current !== generation) return null
      conversation.value = result.conversation
      if (!turns.value.some(item => item.id === result.id)) turns.value.push(result)
      attempt = null; schedulePoll(); return result.conversation
    } catch (e) {
      if (current === generation) {
        error.value = (e as Error).message
        if (e instanceof ApiError && [40901, 40903, 40913].includes(e.code)) attempt = null
      }
      return null
    } finally { if (current === generation) sending.value = false }
  }
  async function retry(turn: Turn) {
    if (!conversation.value || busy.value) return
    const current = generation; sending.value = true
    try {
      const updated = await api<Turn>(`/web/conversations/${conversation.value.id}/turns/${turn.id}/retry`, { method: 'POST', body: '{}', signal: controller.signal })
      if (current !== generation) return
      turns.value = turns.value.map(item => item.id === updated.id ? updated : item); error.value = ''; schedulePoll()
    } catch (e) { if (current === generation) error.value = (e as Error).message }
    finally { if (current === generation) sending.value = false }
  }
  onBeforeUnmount(reset)
  return { conversation, turns, loading, sending, error, nextBefore, busy, reset, open, older, send, retry }
}
