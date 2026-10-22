<script setup lang="ts">
import { onMounted, ref } from "vue";
import { ChatDotRound, Position, Document, ArrowRight } from "@element-plus/icons-vue";
import { api } from "../lib/session";
const bases = ref<{ id: string; name: string; status?: string }[]>([]),
  selected = ref(""),
  question = ref(""),
  error = ref(""),
  searching = ref(false),
  sources = ref<Source[]>([]);
interface Source {
  document_id: string;
  document_title: string;
  version_id: string;
  version_no: number;
  filename: string;
  modality: "text" | "image" | "video";
  score: number;
  heading_path: string | null;
  content: string | null;
  preview_url?: string | null;
}
const examples = [
  "如何快速了解产品的主要功能？",
  "设备首次使用需要做哪些准备？",
  "在哪里查找常见问题的处理方法？",
];
async function load() {
  error.value = "";
  try {
    const result = await api<{ items: { id: string; name: string; status?: string }[] }>("/knowledge-bases?status=active&page=1&page_size=100");
    bases.value = result.items.filter((base) => !base.status || base.status === "active");
    selected.value = bases.value[0]?.id || "";
  } catch (e) {
    error.value = (e as Error).message;
  }
}
async function search() {
  if (!selected.value || !question.value.trim() || searching.value) return;
  searching.value = true;
  error.value = "";
  try {
    const result = await api<{ sources: Source[] }>("/web/search", {
      method: "POST",
      body: JSON.stringify({ knowledge_base_id: selected.value, question: question.value.trim() }),
    });
    sources.value = result.sources;
  } catch (e) {
    error.value = (e as Error).message;
    sources.value = [];
  } finally {
    searching.value = false;
  }
}
onMounted(load);
</script>
<template>
  <div class="page-heading">
    <div>
      <div class="page-eyebrow">ASK YOUR KNOWLEDGE</div>
      <h1>知识问答</h1>
      <p>从一个问题开始，发现知识中的答案。</p>
    </div>
  </div>
  <el-alert
    class="phase-notice"
    title="输入文字后将使用同一多模态 Embedding 空间检索文本、图片和视频来源。"
    type="info"
    :closable="false"
    show-icon
  />
  <el-alert
    v-if="error"
    :title="error"
    type="error"
    :closable="false"
  >
    <el-button
      text
      @click="load"
    >
      重试
    </el-button>
  </el-alert>
  <div class="query-layout">
    <el-card
      shadow="never"
      class="query-card"
    >
      <div class="query-toolbar">
        <span>当前知识库</span>
        <el-select
          v-model="selected"
          placeholder="请选择知识库"
        >
          <el-option
            v-for="base in bases"
            :key="base.id"
            :label="base.name"
            :value="base.id"
          />
        </el-select>
      </div>
      <div class="query-welcome">
        <div class="query-orb">
          <el-icon><ChatDotRound /></el-icon>
        </div>
        <h2>你好，有什么想了解的？</h2>
        <p>选择知识库，用自然语言描述你的问题。</p>
        <div class="question-examples">
          <button
            v-for="example in examples"
            :key="example"
            @click="question = example"
          >
            {{ example }}
            <el-icon><ArrowRight /></el-icon>
          </button>
        </div>
      </div>
      <div class="query-composer">
        <el-input
          v-model="question"
          type="textarea"
          :rows="3"
          placeholder="输入你的问题，探索团队知识…"
          maxlength="2000"
          show-word-limit
        />
        <div>
          <span>将返回最相关的文本、图片和视频来源</span>
          <el-button
            type="primary"
            :icon="Position"
            :loading="searching"
            :disabled="!selected || !question.trim()"
            @click="search"
          >
            检索来源
          </el-button>
        </div>
      </div>
    </el-card>
    <el-card
      class="sources-card"
      shadow="never"
    >
      <template #header>
        <div class="card-title">
          <span>
            <el-icon><Document /></el-icon>
            引用来源
          </span>
        </div>
      </template>
      <div v-if="sources.length" class="source-list">
        <article
          v-for="source in sources"
          :key="`${source.version_id}-${source.modality}`"
          class="source-item"
        >
          <div class="source-heading">
            <strong>{{ source.document_title }}</strong>
            <el-tag size="small">相似度 {{ source.score.toFixed(3) }}</el-tag>
          </div>
          <div class="source-meta">v{{ source.version_no }} · {{ source.filename }} · {{ source.modality }}</div>
          <video
            v-if="source.modality === 'video' && source.preview_url"
            class="source-video"
            controls
            :src="source.preview_url"
          />
          <img
            v-else-if="source.modality === 'image' && source.preview_url"
            class="source-image"
            :src="source.preview_url"
            :alt="source.filename"
          />
          <div v-else class="source-content">{{ source.content || "该媒体来源已命中，可打开文档预览。" }}</div>
        </article>
      </div>
      <el-empty
        v-else
        description="提问后，这里将展示相关文档、图片和视频来源"
        :image-size="85"
      />
    </el-card>
  </div>
</template>

<style scoped>
.source-list { display: grid; gap: 12px; }
.source-item { padding: 14px; border: 1px solid #ebeef2; border-radius: 8px; background: #fff; }
.source-heading { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.source-meta { margin: 6px 0 10px; color: #8a8f98; font-size: 12px; }
.source-content { white-space: pre-wrap; color: #4a4f57; line-height: 1.6; }
.source-image, .source-video { display: block; max-width: 100%; max-height: 220px; margin-top: 8px; object-fit: contain; }
.source-video { width: 100%; background: #111; }
</style>
