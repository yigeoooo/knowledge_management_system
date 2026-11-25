<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import type { Component } from "vue";
import { useRouter } from "vue-router";
import {
  ArrowRight,
  Collection,
  Document,
  Cpu,
  User,
  ChatDotRound,
  Lock,
  Setting,
  List,
  DataAnalysis,
} from "@element-plus/icons-vue";
import { api, session } from "../lib/session";
const router = useRouter();
const data = ref<Record<string, number>>({}),
  error = ref(""),
  loading = ref(true);
const availablePages = computed(() => session.pages.filter((page) =>
  page.is_visible && !["button", "hidden"].includes(page.page_type) &&
  router.hasRoute(`page:${page.code}`),
));
const canOpen = (path: string) => availablePages.value.some((page) => page.route_path === path);
const metrics = computed(() => [
  { key: "knowledge_base_count", name: "知识库", icon: Collection, path: "/knowledge-bases" },
  { key: "document_count", name: "知识文档", icon: Document, path: "/documents" },
  { key: "robot_count", name: "接入机器人", icon: Cpu, path: "/robots" },
  { key: "user_count", name: "平台用户", icon: User, path: "/users" },
].filter((metric) => canOpen(metric.path)));
const shortcutInfo: Record<string, { icon: Component; description: string }> = {
  KnowledgeQA: { icon: ChatDotRound, description: "从知识库中查找答案" },
  KnowledgeBaseManagement: { icon: Collection, description: "组织与浏览团队知识" },
  DocumentManagement: { icon: Document, description: "文档与版本集中管理" },
  DocumentCreate: { icon: Document, description: "编写 Word 或 Markdown 文档" },
  RobotManagement: { icon: Cpu, description: "管理设备与调用状态" },
  UserManagement: { icon: User, description: "管理平台成员" },
  RoleManagement: { icon: Setting, description: "管理团队角色" },
  PageManagement: { icon: List, description: "查看平台页面与路由" },
  RolePermissions: { icon: Lock, description: "配置团队的访问范围" },
  QALogs: { icon: DataAnalysis, description: "查看历史问答与引用资料" },
  AuditLogs: { icon: Document, description: "查看平台操作记录" },
  Profile: { icon: User, description: "查看个人信息与页面权限" },
};
const shortcuts = computed(() => availablePages.value
  .filter((page) => page.route_path !== "/dashboard")
  .sort((left, right) => left.sort_order - right.sort_order)
  .map((page) => ({ ...page, ...shortcutInfo[page.component_key] })),
);
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
        v-if="canOpen('/qa')"
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
    v-if="metrics.length"
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
  <div v-if="shortcuts.length" class="dashboard-grid">
    <el-card shadow="never">
      <template #header>
        <div class="card-title">
          快捷入口
          <span>QUICK ACCESS</span>
        </div>
      </template>
      <div class="quick-links">
        <button v-for="page in shortcuts" :key="page.code" @click="$router.push(page.route_path)">
          <el-icon><component :is="page.icon || Document" /></el-icon>
          <span>
            {{ page.name }}
            <small>{{ page.description || "进入页面" }}</small>
          </span>
          <el-icon><ArrowRight /></el-icon>
        </button>
      </div>
    </el-card>
  </div>
</template>
