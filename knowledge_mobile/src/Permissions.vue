<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from "vue";
import { ElMessage } from "element-plus";
import ChoiceSheet from './ChoiceSheet.vue'
import { api } from "@web/lib/session";

interface Role {
  id: string;
  name: string;
  code: string;
  status: "active" | "disabled";
}

interface Page {
  id: string;
  code: string;
  name: string;
  route_path: string;
  page_type: string;
  sort_order: number;
  status: "active" | "disabled";
  is_visible: boolean;
}

interface RoleList {
  items: Role[];
}

interface PageList {
  items: Page[];
}

interface PermissionResult {
  page_ids: string[];
}

const roles = ref<Role[]>([]);
const pages = ref<Page[]>([]);
const selectedPageIds = ref<string[]>([]);
const selected = ref("");
const loading = ref(false);
const saving = ref(false);
const error = ref("");
let requestGeneration = 0;

const selectedRole = () => roles.value.find((role) => role.id === selected.value);

function errorText(value: unknown) {
  return value instanceof Error ? value.message : "操作失败，请稍后重试";
}

async function loadPermissions() {
  if (!selected.value) {
    selectedPageIds.value = [];
    return;
  }
  const current = ++requestGeneration;
  loading.value = true;
  error.value = "";
  selectedPageIds.value = [];
  try {
    const data = await api<PermissionResult>(`/roles/${selected.value}/pages`);
    if (current === requestGeneration) selectedPageIds.value = data.page_ids;
  } catch (value) {
    if (current === requestGeneration) error.value = errorText(value);
  } finally {
    if (current === requestGeneration) loading.value = false;
  }
}

async function load() {
  const current = ++requestGeneration;
  loading.value = true;
  error.value = "";
  try {
    const [roleResult, pageResult] = await Promise.all([
      api<RoleList>("/roles?page_size=100"),
      api<PageList>("/pages?page_size=100"),
    ]);
    if (current !== requestGeneration) return;
    roles.value = roleResult.items;
    pages.value = [...pageResult.items].sort(
      (left, right) => left.sort_order - right.sort_order || left.name.localeCompare(right.name),
    );
    if (!roles.value.some((role) => role.id === selected.value)) {
      selected.value =
        roles.value.find((role) => role.code === "super_admin")?.id || roles.value[0]?.id || "";
    }
    if (!selected.value) {
      selectedPageIds.value = [];
      return;
    }
    const permissions = await api<PermissionResult>(`/roles/${selected.value}/pages`);
    if (current === requestGeneration) selectedPageIds.value = permissions.page_ids;
  } catch (value) {
    if (current === requestGeneration) {
      error.value = errorText(value);
      selectedPageIds.value = [];
    }
  } finally {
    if (current === requestGeneration) loading.value = false;
  }
}

function changeRole() {
  void loadPermissions();
}

function selectAll() {
  selectedPageIds.value = pages.value.map((page) => page.id);
}

function clearAll() {
  selectedPageIds.value = [];
}

async function save() {
  if (!selected.value || loading.value || saving.value || error.value) return;
  saving.value = true;
  error.value = "";
  try {
    const data = await api<PermissionResult>(`/roles/${selected.value}/pages`, {
      method: "PUT",
      body: JSON.stringify({ page_ids: selectedPageIds.value }),
    });
    selectedPageIds.value = data.page_ids;
    ElMessage.success("页面权限已保存");
  } catch (value) {
    error.value = errorText(value);
    ElMessage.error(error.value);
  } finally {
    saving.value = false;
  }
}

function pageTypeLabel(pageType: string) {
  return { menu: "菜单", page: "页面", button: "按钮", hidden: "隐藏" }[pageType] || pageType;
}

onMounted(load);
onBeforeUnmount(() => {
  ++requestGeneration;
});
</script>

<template>
  <header class="record-page-title"><h1>角色页面权限</h1><van-button icon="replay" size="small" aria-label="刷新权限" :loading="loading" :disabled="saving" @click="load" /></header>
  <ChoiceSheet :model-value="selected" label="选择角色" placeholder="选择角色" searchable :disabled="loading || saving"
    :options="roles.map(role => ({value:role.id,text:role.name + (role.status === 'disabled' ? '（已停用）' : '')}))" @update:model-value="selected = $event; changeRole()" />
  <p v-if="error" role="alert" class="form-error">{{ error }}</p>
  <p v-if="selectedRole()?.code === 'super_admin'" class="record-note">超级管理员必须保留全部启用页面权限。</p>
  <div class="record-section-title"><h2>已授权 <span>{{ selectedPageIds.length }}</span></h2>
    <div><van-button size="small" :disabled="loading || saving || !!error || !pages.length" @click="selectAll">全选</van-button>
    <van-button size="small" :disabled="loading || saving || !!error || !selectedPageIds.length" @click="clearAll">清空</van-button></div>
  </div>
  <van-checkbox-group class="mobile-grants" v-model="selectedPageIds" :disabled="loading || saving || !!error">
    <van-checkbox v-for="page in pages" :key="page.id" :name="page.id" label-position="left">
      <strong>{{ page.name }}</strong><small>{{ page.route_path }} · {{ pageTypeLabel(page.page_type) }} · {{ page.status === 'active' ? '启用' : '停用' }}</small>
    </van-checkbox>
  </van-checkbox-group>
  <van-empty v-if="!loading && !pages.length" description="暂无页面资源" />
  <van-button block type="primary" :loading="saving" :disabled="loading || saving || !!error || !selected" @click="save">保存权限</van-button>
</template>
