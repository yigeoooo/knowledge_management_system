<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { ChatDotRound, Position, Document, ArrowRight, Refresh } from "@element-plus/icons-vue";
import { api, ApiError } from "../lib/session";
import MarkdownContent from "../components/MarkdownContent.vue";
import SourceContent from "../components/SourceContent.vue";

interface Source {
  chunk_id: string;
  source_id?: string;
  document_id: string;
  document_title: string;
  version_id: string;
  version_no: number;
  filename: string;
  modality: "text" | "image" | "video";
  score: number | null;
  heading_path: string | null;
  content: string | null;
  preview_url?: string | null;
}
interface SuggestedQuestion {
  question: string;
  suggestion_token: string;
  source: { chunk_id: string; document_title: string; version_id: string };
}
interface Answer {
  request_id: string;
  knowledge_base_id: string;
  question: string;
  answer: string;
  answer_status: "answered" | "partial" | "sources_only" | "insufficient_evidence";
  sources: Source[];
}
const bases = ref<{ id: string; name: string; status: string }[]>([]);
const basesLoading = ref(true);
const basesError = ref("");
const selected = ref("");
const question = ref("");
const selectedSuggestion = ref<SuggestedQuestion | null>(null);
const suggestions = ref<SuggestedQuestion[]>([]);
const suggestionsLoading = ref(false);
const suggestionsError = ref("");
const searching = ref(false);
const queryError = ref("");
const answer = ref<Answer | null>(null);
const submittedQuestion = ref("");
const sources = computed(() => answer.value?.sources || []);
let suggestionsController: AbortController | null = null;
let queryController: AbortController | null = null;
let suggestionSequence = 0;
let querySequence = 0;
let disposed = false;
let attempt: { signature: string; requestId: string } | null = null;

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : "服务暂不可用，请稍后重试";
}
async function loadBases() {
  basesLoading.value = true;
  basesError.value = "";
  try {
    const result = await api<{ items: { id: string; name: string; status: string }[] }>(
      "/knowledge-bases?status=active&page=1&page_size=100"
    );
    if (disposed) return;
    bases.value = result.items.filter((base) => base.status === "active");
    if (!bases.value.some((base) => base.id === selected.value)) {
      selected.value = bases.value[0]?.id || "";
    }
  } catch (error) {
    if (!disposed) basesError.value = errorMessage(error);
  } finally {
    if (!disposed) basesLoading.value = false;
  }
}
async function loadSuggestions() {
  const sequence = ++suggestionSequence;
  suggestionsController?.abort();
  suggestions.value = [];
  suggestionsError.value = "";
  suggestionsLoading.value = false;
  if (!selected.value) return;
  suggestionsController = new AbortController();
  suggestionsLoading.value = true;
  const baseId = selected.value;
  try {
    const result = await api<{ questions: SuggestedQuestion[] }>("/web/suggested-questions", {
      method: "POST",
      body: JSON.stringify({ knowledge_base_id: baseId }),
      timeoutMs: 120000,
      signal: suggestionsController.signal,
    });
    if (sequence !== suggestionSequence || selected.value !== baseId || disposed) return;
    suggestions.value = result.questions;
  } catch (error) {
    if (sequence === suggestionSequence && !disposed) suggestionsError.value = errorMessage(error);
  } finally {
    if (sequence === suggestionSequence && !disposed) suggestionsLoading.value = false;
  }
}
function requestId() {
  // getRandomValues also works on an HTTP LAN development origin.
  return Array.from(crypto.getRandomValues(new Uint8Array(16)), (n) =>
    n.toString(16).padStart(2, "0")
  ).join("");
}
function useSuggestion(item: SuggestedQuestion) {
  question.value = item.question;
  selectedSuggestion.value = item;
  queryError.value = "";
}
watch(question, (value) => {
  if (value.trim() !== selectedSuggestion.value?.question) selectedSuggestion.value = null;
}, { flush: "sync" });
async function ask() {
  if (!selected.value || !question.value.trim() || searching.value) return;
  const baseId = selected.value;
  const text = question.value.trim();
  const suggestionToken = selectedSuggestion.value?.question === text
    ? selectedSuggestion.value.suggestion_token : undefined;
  const signature = JSON.stringify([baseId, text, suggestionToken]);
  if (attempt?.signature !== signature) attempt = { signature, requestId: requestId() };
  const sequence = ++querySequence;
  queryController?.abort();
  queryController = new AbortController();
  searching.value = true;
  queryError.value = "";
  answer.value = null;
  submittedQuestion.value = text;
  try {
    const result = await api<Answer>("/web/query", {
      method: "POST",
      body: JSON.stringify({ knowledge_base_id: baseId, question: text, request_id: attempt.requestId, suggestion_token: suggestionToken }),
      timeoutMs: 300000,
      signal: queryController.signal,
    });
    if (sequence !== querySequence || selected.value !== baseId || disposed) return;
    answer.value = result;
    // A completed response ends this attempt; an intentional new send may regenerate.
    // Only network/in-flight retries reuse an unfinished request ID.
    attempt = null;
  } catch (error) {
    if (sequence !== querySequence || disposed) return;
    queryError.value = errorMessage(error);
    // Network/provider errors and in-flight retries retain the original request ID.
    if (error instanceof ApiError && [40901, 40903].includes(error.code)) attempt = null;
    if (error instanceof ApiError && error.code === 40903) selectedSuggestion.value = null;
  } finally {
    if (sequence === querySequence && !disposed) searching.value = false;
  }
}
function newQuestion() {
  answer.value = null;
  question.value = "";
  selectedSuggestion.value = null;
  submittedQuestion.value = "";
  queryError.value = "";
  attempt = null;
}
watch(selected, () => {
  querySequence += 1;
  queryController?.abort();
  searching.value = false;
  newQuestion();
  void loadSuggestions();
}, { flush: "sync" });
onMounted(loadBases);
onBeforeUnmount(() => {
  disposed = true;
  suggestionSequence += 1;
  querySequence += 1;
  suggestionsController?.abort();
  queryController?.abort();
});
</script>

<template>
  <div class="page-heading">
    <div>
      <div class="page-eyebrow">ASK YOUR KNOWLEDGE</div>
      <h1>知识问答</h1>
      <p>从一个问题开始，发现知识中的答案。</p>
    </div>
  </div>
  <el-alert v-if="basesError" :title="basesError" type="error" :closable="false" class="phase-notice">
    <el-button text @click="loadBases">重新加载知识库</el-button>
  </el-alert>
  <el-alert v-else-if="!basesLoading && !bases.length" title="暂无可用知识库，请联系管理员创建并启用知识库。" type="info" :closable="false" class="phase-notice" />
  <div class="query-layout">
    <el-card shadow="never" class="query-card">
      <div class="query-toolbar">
        <span>当前知识库</span>
        <el-select v-model="selected" placeholder="请选择知识库" :loading="basesLoading" :disabled="!bases.length" aria-label="当前知识库">
          <el-option v-for="base in bases" :key="base.id" :label="base.name" :value="base.id" />
        </el-select>
        <el-button v-if="answer" text :disabled="searching" @click="newQuestion">新问题</el-button>
      </div>
      <div v-if="!answer && !searching" class="query-welcome">
        <div class="query-orb"><el-icon><ChatDotRound /></el-icon></div>
        <h2>你好，有什么想了解的？</h2>
        <p>选择知识库，用自然语言描述你的问题。</p>
        <div v-if="selected" class="question-examples" :aria-busy="suggestionsLoading" aria-live="polite">
          <template v-if="suggestionsLoading">
            <el-skeleton v-for="index in 3" :key="index" animated>
              <template #template><el-skeleton-item variant="rect" class="question-skeleton" /></template>
            </el-skeleton>
            <span class="suggestion-note">正在根据知识库内容整理问题…</span>
          </template>
          <template v-else-if="suggestionsError">
            <span class="suggestion-note">{{ suggestionsError }}，你也可以直接输入问题。</span>
            <el-button text :icon="Refresh" @click="loadSuggestions">重新生成推荐问题</el-button>
          </template>
          <template v-else-if="suggestions.length">
            <span class="suggestion-note">你可能想问</span>
            <button v-for="item in suggestions" :key="item.source.chunk_id" type="button" :title="`来自：${item.source.document_title}`" @click="useSuggestion(item)">
              <span>{{ item.question }}</span><el-icon><ArrowRight /></el-icon>
            </button>
          </template>
          <template v-else>
            <span class="suggestion-note">当前知识库暂无可推荐的问题，你可以直接输入问题。</span>
            <el-button text :icon="Refresh" @click="loadSuggestions">刷新推荐</el-button>
          </template>
        </div>
      </div>
      <section v-if="searching || answer" class="answer-section" aria-live="polite" :aria-busy="searching">
        <div class="asked-question">{{ submittedQuestion }}</div>
        <div v-if="searching" class="answer-loading">
          <el-skeleton :rows="5" animated />
          <p>正在查找资料并生成回答，请稍候…</p>
        </div>
        <template v-else-if="answer">
          <div class="answer-heading">
            <el-icon><ChatDotRound /></el-icon><strong>知识库回答</strong>
            <el-tag v-if="answer.answer_status === 'insufficient_evidence'" type="info" size="small">资料不足</el-tag>
            <el-tag v-else-if="answer.answer_status === 'partial'" type="warning" size="small">部分内容有依据</el-tag>
            <el-tag v-else-if="answer.answer_status === 'sources_only'" type="info" size="small">可查看相关资料</el-tag>
          </div>
          <MarkdownContent class="answer-body" :content="answer.answer" />
          <div v-if="sources.some((source) => source.source_id)" class="answer-citations">
            <a v-for="source in sources.filter((item) => item.source_id)" :key="source.chunk_id" :href="`#qa-source-${source.chunk_id}`">
              [{{ source.source_id }}] {{ source.document_title }}
            </a>
          </div>
        </template>
      </section>
      <div class="query-composer">
        <el-alert v-if="queryError" :title="queryError" type="error" :closable="false" show-icon class="query-error" />
        <el-input v-model="question" type="textarea" :rows="3" placeholder="输入你的问题，探索团队知识…" maxlength="2000" show-word-limit :disabled="!selected || searching" aria-label="你的问题" />
        <div>
          <span>根据当前知识库资料回答，并附上引用来源</span>
          <el-button type="primary" :icon="Position" :loading="searching" :disabled="!selected || !question.trim()" @click="ask">
            {{ queryError ? '重试提问' : '发送问题' }}
          </el-button>
        </div>
      </div>
    </el-card>
    <el-card class="sources-card" shadow="never">
      <template #header><div class="card-title"><span><el-icon><Document /></el-icon>引用与相关来源</span></div></template>
      <div v-if="sources.length" class="source-list">
        <article v-for="source in sources" :id="`qa-source-${source.chunk_id}`" :key="source.chunk_id" class="source-item">
          <div class="source-heading"><strong>{{ source.source_id ? `[${source.source_id}] ` : '' }}{{ source.document_title }}</strong></div>
          <div class="source-meta">v{{ source.version_no }} · {{ source.filename }}</div>
          <div v-if="source.heading_path" class="source-meta">{{ source.heading_path }}</div>
          <video v-if="source.modality === 'video' && source.preview_url" class="source-video" controls :src="source.preview_url" preload="metadata" />
          <img v-else-if="source.modality === 'image' && source.preview_url" class="source-image" :src="source.preview_url" :alt="source.filename" loading="lazy" />
          <SourceContent v-else-if="source.modality === 'text'" class="source-markdown" :content="source.content || ''" :filename="source.filename" />
          <div v-else class="source-unavailable">媒体预览暂不可用，请稍后重新提问。</div>
          <div v-if="source.modality !== 'text'" class="source-meta">相关媒体，未用于推断具体内容</div>
        </article>
      </div>
      <el-empty v-else :description="searching ? '正在查找相关来源' : answer ? '没有可引用的来源' : '提问后，这里将展示引用与相关资料'" :image-size="85" />
    </el-card>
  </div>
</template>

<style scoped>
.query-layout { grid-template-columns: minmax(0, 1fr) minmax(360px, 36%); align-items: start; }
.query-card, .sources-card { min-width: 0; }
.question-skeleton { width: 100%; height: 54px; border-radius: 6px; }
.suggestion-note { color: #89919c; font-size: 12px; line-height: 1.8; }
.question-examples button { gap: 12px; }
.question-examples button .el-icon { flex-shrink: 0; }
.answer-section { padding: 28px 24px; }
.asked-question { padding: 16px; margin-bottom: 24px; background: #fff5e8; border-radius: 8px; white-space: pre-wrap; overflow-wrap: anywhere; }
.answer-loading p { margin-top: 16px; color: #89919c; font-size: 13px; }
.answer-heading { display: flex; align-items: center; gap: 8px; margin-bottom: 16px; color: #b07427; }
.answer-citations { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 20px; }
.answer-citations a { font-size: 12px; color: #a86e20; padding: 5px 9px; background: #fff5e8; border-radius: 4px; text-decoration: none; }
.query-error { margin-bottom: 14px; }
.source-list { display: grid; grid-template-columns: minmax(0, 1fr); gap: 16px; }
.source-item { scroll-margin-top: 90px; min-width: 0; padding: 18px; border: 1px solid #ebeef2; border-radius: 8px; background: #fff; overflow-wrap: anywhere; }
.source-item:target { border-color: #d8902d; }
.source-heading { font-size: 15px; line-height: 1.6; }
.source-meta { margin: 6px 0 10px; color: #8a8f98; font-size: 12px; }
.source-markdown { padding-top: 16px; border-top: 1px solid #f0f1f3; margin-top: 16px; font-size: 14px; max-height: min(65vh, 720px); overflow: auto; scrollbar-gutter: stable; }
.source-markdown :deep(h1) { font-size: 18px; }
.source-markdown :deep(h2) { font-size: 17px; }
.source-markdown :deep(h3), .source-markdown :deep(h4), .source-markdown :deep(h5), .source-markdown :deep(h6) { font-size: 15px; }
.source-markdown :deep(h1), .source-markdown :deep(h2), .source-markdown :deep(h3), .source-markdown :deep(h4), .source-markdown :deep(h5), .source-markdown :deep(h6) { line-height: 1.5; margin: 20px 0 12px; }
.source-markdown :deep(> :first-child) { margin-top: 0; }
.source-unavailable { color: #8a8f98; font-size: 13px; line-height: 1.7; }
.source-image, .source-video { display: block; max-width: 100%; max-height: 360px; margin-top: 8px; object-fit: contain; }
.source-video { width: 100%; background: #111; }
@media (max-width: 1200px) { .query-layout { grid-template-columns: minmax(0, 1fr); } }
@media (max-width: 600px) { .answer-section { padding: 22px 16px; } }
</style>
