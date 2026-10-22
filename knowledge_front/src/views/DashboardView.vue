<script setup lang="ts">
import { onMounted, ref } from "vue";
import {
  ArrowRight,
  Collection,
  Document,
  Cpu,
  User,
  ChatDotRound,
  Lock,
} from "@element-plus/icons-vue";
import { api, session } from "../lib/session";
const data = ref<Record<string, number>>({}),
  error = ref(""),
  loading = ref(true);
const metrics = [
  { key: "knowledge_base_count", name: "知识库", icon: Collection, path: "/knowledge-bases" },
  { key: "document_count", name: "知识文档", icon: Document, path: "/documents" },
  { key: "robot_count", name: "接入机器人", icon: Cpu, path: "/robots" },
  { key: "user_count", name: "平台用户", icon: User, path: "/users" },
];
async function load() {
  loading.value = true;
  error.value = "";
  try {
    data.value = await api("/dashboard");
  } catch (e) {
    error.value = (e as Error).message;
  } finally {
    loading.value = false;
  }
}
onMounted(load);
</script>
<template>
  <div class="page-heading">
    <div>
      <div class="page-eyebrow">OVERVIEW</div>
      <h1>工作台</h1>
      <p>从这里，连接知识与团队。</p>
    </div>
    <el-tag
      type="info"
      effect="plain"
    >
      {{
        new Date().toLocaleDateString("zh-CN", { year: "numeric", month: "long", day: "numeric" })
      }}
    </el-tag>
  </div>
  <section class="welcome-banner">
    <div>
      <div class="eyebrow">YOUR KNOWLEDGE, CONNECTED</div>
      <h2>欢迎回来，{{ session.user?.display_name }}</h2>
      <p>让积累的每一份经验，都成为下一次创新的起点。</p>
      <el-button
        type="primary"
        @click="$router.push('/qa')"
      >
        前往知识问答
        <el-icon><ArrowRight /></el-icon>
      </el-button>
    </div>
    <div
      class="welcome-art"
      aria-hidden="true"
    >
      <Collection />
    </div>
  </section>
  <el-alert
    v-if="error"
    :title="error"
    type="error"
    show-icon
    :closable="false"
  >
    <el-button
      text
      @click="load"
    >
      重新加载
    </el-button>
  </el-alert>
  <div
    v-loading="loading"
    class="metric-grid"
  >
    <el-card
      v-for="metric in metrics"
      :key="metric.key"
      shadow="never"
      class="metric-card"
    >
      <div>
        <span>{{ metric.name }}</span>
        <el-icon><component :is="metric.icon" /></el-icon>
      </div>
      <strong>{{ data[metric.key] ?? "—" }}</strong>
      <el-button
        text
        @click="$router.push(metric.path)"
      >
        查看详情
        <el-icon><ArrowRight /></el-icon>
      </el-button>
    </el-card>
  </div>
  <div class="dashboard-grid">
    <el-card shadow="never">
      <template #header>
        <div class="card-title">
          快捷入口
          <span>QUICK ACCESS</span>
        </div>
      </template>
      <div class="quick-links">
        <button @click="$router.push('/knowledge-bases')">
          <el-icon><Collection /></el-icon>
          <span>
            知识库管理
            <small>组织与浏览团队知识</small>
          </span>
          <el-icon><ArrowRight /></el-icon>
        </button>
        <button @click="$router.push('/documents')">
          <el-icon><Document /></el-icon>
          <span>
            文档管理
            <small>文档与版本集中管理</small>
          </span>
          <el-icon><ArrowRight /></el-icon>
        </button>
        <button @click="$router.push('/role-permissions')">
          <el-icon><Lock /></el-icon>
          <span>
            角色页面权限
            <small>查看团队的访问范围</small>
          </span>
          <el-icon><ArrowRight /></el-icon>
        </button>
      </div>
    </el-card>
    <el-card shadow="never">
      <template #header>
        <div class="card-title">
          平台建设进度
          <span>GETTING STARTED</span>
        </div>
      </template>
      <el-timeline>
        <el-timeline-item
          type="success"
          timestamp="已就绪"
        >
          品牌首页、账号登录与角色权限
        </el-timeline-item>
        <el-timeline-item
          type="success"
          timestamp="已就绪"
        >
          知识库创建、文档上传与索引管理
        </el-timeline-item>
        <el-timeline-item
          hollow
          timestamp="下一阶段"
        >
          DeepSeek 问答与机器人接口
        </el-timeline-item>
      </el-timeline>
      <div class="development-note">
        <el-icon><ChatDotRound /></el-icon>
        各功能将按页面逐步完善。
      </div>
    </el-card>
  </div>
</template>
