<script setup lang="ts">
import { computed, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ElMessage, ElMessageBox } from "element-plus";
import {
  House,
  ChatDotRound,
  Document,
  Cpu,
  User,
  Setting,
  Collection,
  List,
  Lock,
  SwitchButton,
  ArrowRight,
  Menu,
  DataAnalysis,
} from "@element-plus/icons-vue";
import BrandLogo from "./BrandLogo.vue";
import { logout, session } from "../lib/session";
import { installPages } from "../router";
const route = useRoute(),
  router = useRouter(),
  mobileOpen = ref(false),
  leaving = ref(false);
const icons: Record<string, unknown> = {
  dashboard: House,
  knowledge_qa: ChatDotRound,
  knowledge_bases: Collection,
  documents: Document,
  document_create: Document,
  robots: Cpu,
  users: User,
  roles: Setting,
  pages: List,
  role_permissions: Lock,
  qa_logs: DataAnalysis,
  audit_logs: Document,
  profile: User,
};
const menu = computed(() => session.pages.filter((p) => p.is_visible && p.page_type !== "button"));
async function signOut() {
  try {
    await ElMessageBox.confirm("退出后需要重新登录才能访问知识平台。", "退出登录", {
      confirmButtonText: "退出登录",
      cancelButtonText: "取消",
      type: "info",
    });
  } catch {
    return;
  }
  leaving.value = true;
  try {
    await logout();
    installPages();
    await router.replace("/");
  } catch (e) {
    ElMessage.error((e as Error).message);
  } finally {
    leaving.value = false;
  }
}
</script>
<template>
  <div class="workspace">
    <button
      v-if="mobileOpen"
      class="sidebar-backdrop"
      aria-label="关闭菜单"
      @click="mobileOpen = false"
    />
    <aside
      class="workspace-sidebar"
      :class="{ 'is-open': mobileOpen }"
    >
      <BrandLogo compact />
      <div class="sidebar-product">
        KNOWLEDGE HUB
        <span>知识平台</span>
      </div>
      <div class="sidebar-caption">工作空间</div>
      <el-menu
        :default-active="route.path"
        class="workspace-menu"
        @select="
          (path: string) => {
            router.push(path);
            mobileOpen = false;
          }
        "
      >
        <el-menu-item
          v-for="page in menu"
          :key="page.code"
          :index="page.route_path"
        >
          <el-icon><component :is="icons[page.code] || Document" /></el-icon>
          <span>{{ page.name }}</span>
        </el-menu-item>
      </el-menu>
      <div class="sidebar-footer">
        <span class="live-dot" />
        知识连接，无限可能
        <RouterLink
          to="/"
          aria-label="返回官网首页"
        >
          <el-icon><ArrowRight /></el-icon>
        </RouterLink>
      </div>
    </aside>
    <div class="workspace-body">
      <header class="workspace-header">
        <div class="workspace-breadcrumb">
          <el-button
            class="workspace-menu-toggle"
            text
            aria-label="打开菜单"
            @click="mobileOpen = true"
          >
            <el-icon><Menu /></el-icon>
          </el-button>
          <span>知识平台</span>
          <span>/</span>
          <strong>{{ route.meta.title }}</strong>
        </div>
        <div class="workspace-account">
          <el-tag
            effect="plain"
            type="info"
          >
            {{ session.user?.role_name }}
          </el-tag>
          <el-avatar :size="32">
            {{ session.user?.display_name.slice(0, 1).toUpperCase() }}
          </el-avatar>
          <span>{{ session.user?.display_name }}</span>
          <el-button
            text
            :loading="leaving"
            aria-label="退出登录"
            @click="signOut"
          >
            <el-icon><SwitchButton /></el-icon>
          </el-button>
        </div>
      </header>
      <main class="workspace-content"><RouterView /></main>
      <footer class="workspace-footer">
        DEXFORCE KNOWLEDGE HUB
        <span>跨维智能 · 知识平台</span>
      </footer>
    </div>
  </div>
</template>
