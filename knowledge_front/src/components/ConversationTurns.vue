<script setup lang="ts">
import MarkdownContent from "./MarkdownContent.vue";
import SourceContent from "./SourceContent.vue";
import { pending, statusText, type Turn } from "../lib/conversations";
defineProps<{
  turns: Turn[];
  readonly?: boolean;
  plain?: boolean;
  retryDisabled?: boolean;
  showTrace?: boolean;
}>();
defineEmits<{ retry: [turn: Turn]; trace: [turn: Turn] }>();
</script>

<template>
  <div
    class="conversation-turns"
    aria-live="polite"
  >
    <article
      v-for="(turn, index) in turns"
      :key="turn.id"
      class="conversation-turn"
      :data-turn-id="turn.id"
    >
      <div class="user-message">
        <span class="message-label">提问</span>
        <div>{{ turn.question }}</div>
      </div>
      <section
        class="assistant-message"
        :aria-busy="pending(turn)"
      >
        <div class="message-heading">
          <strong>{{ plain ? "机器人回答" : "知识库回答" }}</strong>
          <span>{{ statusText(turn.status) }}</span>
        </div>
        <div
          v-if="pending(turn)"
          class="thinking"
        >
          <span class="thinking-dot" />
          正在整理资料，离开页面后仍会继续处理…
        </div>
        <div
          v-if="plain && turn.answer"
          class="conversation-answer plain-answer"
        >
          {{ turn.answer }}
        </div>
        <MarkdownContent
          v-else-if="turn.answer"
          :content="turn.answer"
          class="conversation-answer"
        />
        <el-alert
          v-if="turn.error_message"
          :title="turn.error_message"
          :type="turn.status === 'FAILED' ? 'error' : 'info'"
          :closable="false"
          show-icon
        />
        <p
          v-if="turn.context_notice"
          class="context-notice"
        >
          {{ turn.context_notice }}
        </p>
        <el-button
          v-if="showTrace"
          class="trace-button"
          size="small"
          @click="$emit('trace', turn)"
        >
          查看处理流程
        </el-button>
        <el-button
          v-if="!readonly && turn.status === 'FAILED' && index === turns.length - 1"
          size="small"
          :disabled="retryDisabled"
          @click="$emit('retry', turn)"
        >
          重试回答
        </el-button>
        <details
          v-if="turn.sources.length"
          class="turn-sources"
        >
          <summary>引用与相关资料 · {{ turn.sources.length }}</summary>
          <article
            v-for="(source, i) in turn.sources"
            :key="source.chunk_id || i"
            class="turn-source"
          >
            <strong>
              {{ source.source_id ? `[${source.source_id}] ` : "" }}{{ source.document_title }}
            </strong>
            <small>
              {{ source.filename }}
              <template v-if="source.version_no">· v{{ source.version_no }}</template>
            </small>
            <small v-if="source.heading_path">{{ source.heading_path }}</small>
            <video
              v-if="source.modality === 'video' && source.preview_url"
              :src="source.preview_url"
              controls
              preload="metadata"
            />
            <img
              v-else-if="source.modality === 'image' && source.preview_url"
              :src="source.preview_url"
              :alt="source.filename"
              loading="lazy"
            />
            <SourceContent
              v-else-if="source.content"
              :content="source.content"
              :filename="source.filename"
              :content-html="source.content_html"
            />
            <p v-else>原文件预览暂不可用。</p>
          </article>
        </details>
        <details
          v-if="readonly"
          class="turn-metadata"
        >
          <summary>本轮详情</summary>
          <div>请求编号：{{ turn.request_id }}</div>
          <div>
            模型：{{ turn.model_name || "—" }} · 耗时：{{ turn.latency_ms ?? "—" }} ms · 召回：{{
              turn.retrieval_count ?? "—"
            }}
          </div>
          <div>{{ new Date(turn.created_at).toLocaleString() }}</div>
        </details>
      </section>
    </article>
  </div>
</template>

<style scoped>
.trace-button {
  margin-top: 16px;
}
.plain-answer {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
.conversation-turns {
  display: grid;
  gap: 32px;
  min-width: 0;
}
.conversation-turn {
  min-width: 0;
}
.user-message {
  margin-left: auto;
  max-width: 85%;
  width: fit-content;
  background: #f4f4f2;
  border-radius: 18px 18px 4px 18px;
  padding: 14px 20px;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  color: #30302c;
  line-height: 1.7;
}
.message-label {
  display: block;
  font-size: 11px;
  color: #7c8798;
  margin-bottom: 4px;
}
.assistant-message {
  padding: 20px 0 6px;
  min-width: 0;
}
.message-heading {
  display: flex;
  gap: 12px;
  align-items: center;
  margin-bottom: 16px;
  font-size: 13px;
}
.message-heading > span {
  color: #8b96a5;
  font-size: 12px;
}
.conversation-answer {
  font-size: 15px;
  line-height: 1.85;
}
.thinking {
  display: flex;
  gap: 10px;
  align-items: center;
  color: #738095;
  font-size: 13px;
  padding: 15px 0;
}
.thinking-dot {
  width: 8px;
  height: 8px;
  background: var(--brand-orange);
  border-radius: 50%;
  animation: pulse 1.4s infinite;
}
.turn-sources,
.turn-metadata {
  margin-top: 16px;
  font-size: 12px;
  color: #68768a;
}
.turn-sources > summary,
.turn-metadata > summary {
  cursor: pointer;
  padding: 10px 0;
}
.turn-source {
  margin: 10px 0;
  padding: 16px;
  border: 1px solid #e8edf4;
  border-radius: 12px;
  background: #fafbfd;
  color: #334155;
  overflow-wrap: anywhere;
}
.turn-source strong,
.turn-source small {
  display: block;
  margin-bottom: 6px;
}
.turn-source small {
  color: #8190a3;
}
.turn-source img,
.turn-source video {
  max-width: 100%;
  max-height: 320px;
}
.turn-metadata > div {
  padding: 5px 0;
  overflow-wrap: anywhere;
}
.context-notice {
  font-size: 12px;
  color: #927133;
}
@keyframes pulse {
  50% {
    opacity: 0.3;
  }
}
</style>
