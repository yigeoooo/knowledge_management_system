import { computed, onBeforeUnmount, ref, type Ref } from 'vue'
import { api, ApiError } from './session'
import { pending, requestId, type Conversation, type Turn, type TurnPage } from './conversations'

export interface RobotOption {
  id: string; name: string | null; serial_no: string; status: string
  knowledge_base_id: string | null; knowledge_base_name: string | null; knowledge_base_status: string | null
}
interface Attempt {
  path: string; body: Record<string, unknown>; serial: string; turn: Turn; previous?: Turn
}

export function useRobotConversation(robot: Ref<RobotOption | undefined>) {
  const conversation = ref<Conversation | null>(null), turns = ref<Turn[]>([])
  const loading = ref(false), sending = ref(false), error = ref(''), nextBefore = ref<number | null>(null)
  const attempt = ref<Attempt | null>(null)
  const awaitingAnswer = computed(() => !!attempt.value || turns.value.some(pending))
  const busy = computed(() => sending.value || awaitingAnswer.value)
  let generation = 0, controller = new AbortController()

  function reset() {
    generation++; controller.abort(); controller = new AbortController()
    conversation.value = null; turns.value = []; nextBefore.value = null; attempt.value = null
    loading.value = false; sending.value = false; error.value = ''
  }
  async function open(cid: string) {
    reset()
    if (!robot.value) return
    const current = generation; loading.value = true
    try {
      const result = await api<TurnPage>(`/admin/robot-chat/robots/${robot.value.id}/conversations/${cid}/turns`, { signal: controller.signal })
      if (current !== generation) return
      conversation.value = result.conversation; turns.value = result.items; nextBefore.value = result.next_before
    } catch (e) { if (current === generation) error.value = (e as Error).message }
    finally { if (current === generation) loading.value = false }
  }
  async function older() {
    if (!robot.value || !conversation.value || !nextBefore.value || loading.value) return
    const current = generation; loading.value = true
    try {
      const result = await api<TurnPage>(`/admin/robot-chat/robots/${robot.value.id}/conversations/${conversation.value.id}/turns?before=${nextBefore.value}`, { signal: controller.signal })
      if (current !== generation) return
      turns.value = [...result.items, ...turns.value]; nextBefore.value = result.next_before
    } catch (e) { if (current === generation) error.value = (e as Error).message }
    finally { if (current === generation) loading.value = false }
  }
  async function execute(candidate: Attempt) {
    if (sending.value) return null
    const current = generation
    attempt.value = candidate; sending.value = true; error.value = ''
    if (!turns.value.some(t => t.id === candidate.turn.id)) turns.value.push(candidate.turn)
    else turns.value = turns.value.map(t => t.id === candidate.turn.id ? { ...t, status: 'PROCESSING', error_message: null } : t)
    try {
      const result = await api<Turn & { conversation: Conversation }>(candidate.path, {
        method: 'POST', body: JSON.stringify(candidate.body), headers: { 'X-Robot-Serial': candidate.serial },
        timeoutMs: 210000, signal: controller.signal,
      })
      if (current !== generation) return null
      conversation.value = result.conversation
      turns.value = [...turns.value.filter(t => t.id !== candidate.turn.id && t.id !== result.id), result]
      attempt.value = null
      return result.conversation
    } catch (e) {
      if (current !== generation) return null
      error.value = (e as Error).message
      // A rejected request can be edited. An interrupted request retains its exact ID and payload.
      if (e instanceof ApiError && e.status >= 400 && e.status < 500) {
        attempt.value = null
        turns.value = candidate.previous
          ? turns.value.map(t => t.id === candidate.turn.id ? candidate.previous! : t)
          : turns.value.filter(t => t.id !== candidate.turn.id)
      }
      return null
    } finally { if (current === generation) sending.value = false }
  }
  async function send(question: string) {
    if (!robot.value || busy.value || loading.value || !question.trim()) return null
    const cid = conversation.value?.id, id = requestId()
    const body: Record<string, unknown> = { serial_no: robot.value.serial_no, question: question.trim(), request_id: id }
    if (cid) { body.conversation_id = cid; body.expected_last_turn_no = conversation.value!.last_turn_no }
    return execute({
      path: cid ? '/robot/conversations/query' : '/robot/query', body, serial: robot.value.serial_no,
      turn: { id: `local-${id}`, turn_id: '', conversation_id: cid || '', turn_no: (conversation.value?.last_turn_no || 0) + 1,
        request_id: id, question: question.trim(), answer: null, status: 'PROCESSING', answer_kind: 'knowledge',
        sources: [], error_message: null, created_at: new Date().toISOString() },
    })
  }
  async function resume() {
    if (attempt.value) return execute(attempt.value)
    const turn = turns.value.find(pending)
    if (!turn || !robot.value || !conversation.value) return null
    return execute({ path: '/robot/conversations/query', serial: robot.value.serial_no, turn, previous: turn,
      body: { serial_no: robot.value.serial_no, conversation_id: conversation.value.id, request_id: turn.request_id, question: turn.question } })
  }
  async function retry(turn: Turn) {
    if (!conversation.value || !robot.value || busy.value) return null
    return execute({ path: `/robot/conversations/${conversation.value.id}/turns/${turn.id}/retry`,
      body: {}, serial: robot.value.serial_no, turn, previous: turn })
  }
  onBeforeUnmount(reset)
  return { conversation, turns, loading, sending, error, nextBefore, busy, awaitingAnswer, reset, open, older, send, resume, retry }
}
