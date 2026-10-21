<script setup lang="ts">
import { onMounted, ref } from "vue";
import { ChatDotRound, Position, Document, ArrowRight } from "@element-plus/icons-vue";
import { api } from "../lib/session";
const bases = ref<{ id: string; name: string }[]>([]),
  selected = ref(""),
  question = ref(""),
  error = ref("");
const examples = [
  "如何快速了解产品的主要功能？",
  "设备首次使用需要做哪些准备？",
  "在哪里查找常见问题的处理方法？",
];
async function load() {
  error.value = "";
  try {
    const result = await api<{ items: { id: string; name: string }[] }>("/knowledge-bases");
    bases.value = result.items;
    selected.value = result.items[0]?.id || "";
  } catch (e) {
    error.value = (e as Error).message;
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
    title="问答页面已就绪，文档索引与模型服务接入完成后即可提问。"
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
          <span>回答将结合知识库内容，并附带引用来源</span>
          <el-tooltip content="问答服务接入后开放">
            <span>
              <el-button
                type="primary"
                :icon="Position"
                disabled
              >
                发送问题
              </el-button>
            </span>
          </el-tooltip>
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
      <el-empty
        description="提问后，这里将展示相关文档与引用片段"
        :image-size="85"
      />
    </el-card>
  </div>
</template>
