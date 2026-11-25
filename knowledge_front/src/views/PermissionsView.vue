<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from "vue";
import { ElMessage } from "element-plus";
import { Check, Close, Lock, Refresh, Select } from "@element-plus/icons-vue";
import { api } from "../lib/session";

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
  <div class="page-heading">
    <div>
      <div class="page-eyebrow">ACCESS CONTROL</div>
      <h1>角色页面权限</h1>
      <p>为不同角色配置可访问的页面路由，保存后相关用户下次登录即可生效。</p>
    </div>
    <el-button
      :icon="Refresh"
      :loading="loading"
      @click="load"
    >
      刷新
    </el-button>
  </div>

  <el-alert
    class="phase-notice"
    title="权限按页面访问控制；停用页面不会出现在用户登录后的可用页面列表中。"
    type="info"
    :closable="false"
    show-icon
  />
  <el-alert
    v-if="error"
    class="phase-notice"
    :title="error"
    type="error"
    :closable="false"
    show-icon
  />
  <el-card
    v-loading="loading"
    shadow="never"
    class="permission-card"
  >
    <div class="permission-toolbar">
      <span>选择角色</span>
      <el-select
        v-model="selected"
        :disabled="loading || saving"
        @change="changeRole"
      >
        <el-option
          v-for="role in roles"
          :key="role.id"
          :label="`${role.name}${role.status === 'disabled' ? '（已停用）' : ''}`"
          :value="role.id"
        />
      </el-select>
      <el-tag type="success">{{ selectedPageIds.length }} 个已授权页面</el-tag>
      <span class="permission-toolbar-spacer" />
      <el-button
        text
        :icon="Select"
        :disabled="loading || saving || !!error || !pages.length"
        @click="selectAll"
      >
        全选
      </el-button>
      <el-button
        text
        :icon="Close"
        :disabled="loading || saving || !!error || !selectedPageIds.length"
        @click="clearAll"
      >
        清空
      </el-button>
      <el-button
        type="primary"
        :icon="Check"
        :loading="saving"
        :disabled="loading || saving || !!error || !selected"
        @click="save"
      >
        保存权限
      </el-button>
    </div>

    <div
      v-if="selectedRole()?.code === 'super_admin'"
      class="permission-note"
    >
      super_admin 必须保留全部启用页面权限。
    </div>

    <el-checkbox-group
      v-model="selectedPageIds"
      class="permission-grid"
      :disabled="loading || saving || !!error"
    >
      <div
        v-for="page in pages"
        :key="page.id"
        class="permission-item"
        :class="{ granted: selectedPageIds.includes(page.id), disabled: page.status !== 'active' }"
      >
        <el-checkbox :label="page.id">
          <span class="permission-item-content">
            <strong>{{ page.name }}</strong>
            <span>{{ page.route_path }}</span>
            <small>{{ pageTypeLabel(page.page_type) }} · {{ page.status === "active" ? "启用" : "停用" }}</small>
          </span>
        </el-checkbox>
        <el-icon class="permission-item-icon"><Lock /></el-icon>
      </div>
    </el-checkbox-group>
    <el-empty
      v-if="!loading && !pages.length"
      description="暂无页面资源"
    />
  </el-card>
</template>
