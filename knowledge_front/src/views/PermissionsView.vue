<script setup lang="ts">
import { onMounted, ref } from "vue";
import { Lock, Refresh } from "@element-plus/icons-vue";
import { api } from "../lib/session";
interface Role {
  id: string;
  name: string;
  code: string;
}
interface Page {
  id: string;
  name: string;
  route_path: string;
}
const roles = ref<Role[]>([]),
  pages = ref<Page[]>([]),
  allowed = ref<string[]>([]),
  selected = ref(""),
  loading = ref(false),
  error = ref("");
let generation = 0;
async function permissions() {
  const current = ++generation;
  loading.value = true;
  error.value = "";
  allowed.value = [];
  try {
    const data = await api<{ page_ids: string[] }>(`/roles/${selected.value}/pages`);
    if (current === generation) allowed.value = data.page_ids;
  } catch (e) {
    if (current === generation) error.value = (e as Error).message;
  } finally {
    if (current === generation) loading.value = false;
  }
}
async function load() {
  loading.value = true;
  error.value = "";
  try {
    const [r, p] = await Promise.all([
      api<{ items: Role[] }>("/roles?page_size=100"),
      api<{ items: Page[] }>("/pages?page_size=100"),
    ]);
    roles.value = r.items;
    pages.value = p.items;
    selected.value =
      r.items.find((role) => role.code === "super_admin")?.id || r.items[0]?.id || "";
    if (selected.value) await permissions();
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
      <div class="page-eyebrow">ACCESS CONTROL</div>
      <h1>角色页面权限</h1>
      <p>查看不同角色可以访问的页面与功能。</p>
    </div>
    <el-button
      :icon="Refresh"
      @click="load"
    >
      刷新
    </el-button>
  </div>
  <el-alert
    class="phase-notice"
    title="当前展示数据库中的实际授权，权限编辑功能将在后续开放。"
    type="info"
    :closable="false"
    show-icon
  />
  <el-alert
    v-if="error"
    :title="error"
    type="error"
    :closable="false"
  />
  <el-card
    v-loading="loading"
    shadow="never"
  >
    <div class="permission-toolbar">
      <span>选择角色</span>
      <el-select
        v-model="selected"
        @change="permissions"
      >
        <el-option
          v-for="role in roles"
          :key="role.id"
          :label="role.name"
          :value="role.id"
        />
      </el-select>
      <el-tag>{{ allowed.length }} 个已授权页面</el-tag>
    </div>
    <div class="permission-grid">
      <div
        v-for="page in pages"
        :key="page.id"
        class="permission-item"
        :class="{ granted: allowed.includes(page.id) }"
      >
        <el-icon><Lock /></el-icon>
        <div>
          <strong>{{ page.name }}</strong>
          <span>{{ page.route_path }}</span>
        </div>
        <el-tag :type="allowed.includes(page.id) ? 'success' : 'info'">
          {{ allowed.includes(page.id) ? "已授权" : "未授权" }}
        </el-tag>
      </div>
    </div>
  </el-card>
</template>
