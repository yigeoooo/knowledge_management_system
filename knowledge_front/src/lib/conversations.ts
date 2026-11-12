export interface Conversation {
  id: string; title: string; source_type: 'WEB' | 'ROBOT'; owner_name: string
  knowledge_base_id: string; knowledge_base_name: string; knowledge_base_status: string
  last_turn_no: number; turn_count: number; created_at: string; last_message_at: string
  deleted_at: string | null; closed_at: string | null; closed_reason: string | null
}
export interface Source {
  source_id?: string; chunk_id: string; document_title: string; filename: string
  version_no?: number; heading_path?: string; content?: string; content_html?: string
  modality?: string; preview_url?: string | null
}
export interface Turn {
  id: string; turn_id: string; conversation_id: string; turn_no: number; request_id: string
  question: string; answer: string | null; status: string; answer_kind: string
  sources: Source[]; error_message: string | null; created_at: string
  model_name?: string; latency_ms?: number; retrieval_count?: number; context_notice?: string
}
export interface TurnPage { items: Turn[]; next_before: number | null; conversation: Conversation }
export interface ConversationPage { items: Conversation[]; next_cursor: string | null }
export function requestId() {
  return Array.from(crypto.getRandomValues(new Uint8Array(16)), n => n.toString(16).padStart(2, '0')).join('')
}
export const pending = (turn: Turn) => ['PENDING', 'PROCESSING'].includes(turn.status)
export const statusText = (status: string) => ({
  PENDING: '等待回答', PROCESSING: '正在查找资料并核实回答', SUCCESS: '已回答', PARTIAL: '部分内容有依据',
  NO_EVIDENCE: '资料不足', SOURCES_ONLY: '可查看相关资料', FAILED: '回答失败', CANCELLED: '已取消',
}[status] || status)

export const answerKindNames: Record<string, string> = { knowledge: '知识库回答', chat: '自然交流', general: '通识回答', realtime: '实时信息说明', clarification: '澄清问题' }
