<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { showSuccessToast, showFailToast } from "vant";
import PageHeader from './PageHeader.vue'
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

const savedIds = ref<string[]>([]);
const selectedRole = computed(() => roles.value.find(role => role.id === selected.value));
const protectedIds = computed(() => new Set(selectedRole.value?.code === "super_admin"
  ? pages.value.filter(page => page.status === "active").map(page => page.id) : []));
const checked = computed(() => new Set(selectedPageIds.value));
const dirty = computed(() => savedIds.value.length !== checked.value.size || savedIds.value.some(id => !checked.value.has(id)));
const blocked = computed(() => loading.value || saving.value || !!error.value || !selected.value);
const sections = [
  { name: "工作台与问答", icon: "chat-o", codes: ["dashboard", "knowledge_qa", "robot_qa", "profile"] },
  { name: "知识与内容", icon: "description-o", codes: ["knowledge_bases", "document_create", "documents", "prompts", "evaluations"] },
  { name: "设备与系统管理", icon: "setting-o", codes: ["robots", "users", "roles", "pages", "role_permissions"] },
  { name: "日志与审计", icon: "notes-o", codes: ["qa_logs", "audit_logs"] },
  { name: "其他页面", icon: "apps-o", codes: [] },
];
const groups = computed(() => {
  const buckets = sections.map(section => ({ ...section, pages: [] as Page[] }));
  for (const page of pages.value) {
    const group = buckets.find(section => section.codes.includes(page.code)) ?? buckets[buckets.length - 1];
    group.pages.push(page);
  }
  return buckets.filter(group => group.pages.length);
});

async function listAll<T>(resource: string) {
  const items: T[] = [];
  for (let page = 1; ; page++) {
    const batch = await api<{items:T[]; total:number}>(`/${resource}?page_size=100&page=${page}`);
    items.push(...batch.items);
    if (items.length >= batch.total || batch.items.length < 100) return items;
  }
}

function accept(ids: string[]) {
  savedIds.value = [...ids];
  selectedPageIds.value = [...new Set([...ids, ...protectedIds.value])];
}

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
    if (current === requestGeneration) accept(data.page_ids);
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
      listAll<Role>("roles"),
      listAll<Page>("pages"),
    ]);
    if (current !== requestGeneration) return;
    roles.value = roleResult;
    pages.value = [...pageResult].sort(
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
    if (current === requestGeneration) accept(permissions.page_ids);
  } catch (value) {
    if (current === requestGeneration) {
      error.value = errorText(value);
      selectedPageIds.value = [];
    }
  } finally {
    if (current === requestGeneration) loading.value = false;
  }
}

function changeRole(id: string) {
  selected.value = id;
  void loadPermissions();
}

function selectAll() {
  selectedPageIds.value = pages.value.map((page) => page.id);
}

function clearAll() {
  selectedPageIds.value = [...protectedIds.value];
}

async function save() {
  if (blocked.value || !dirty.value) return;
  saving.value = true;
  error.value = "";
  try {
    const data = await api<PermissionResult>(`/roles/${selected.value}/pages`, {
      method: "PUT",
      body: JSON.stringify({ page_ids: selectedPageIds.value }),
    });
    accept(data.page_ids);
    showSuccessToast("页面权限已保存");
  } catch (value) {
    showFailToast(errorText(value));
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
  <PageHeader title="角色页面权限">
    <van-button icon="replay" size="small" aria-label="刷新权限" :loading="loading" :disabled="saving" @click="load" />
    <van-button class="grant-save" size="small" :loading="saving" :disabled="blocked || !dirty" @click="save">保存</van-button>
  </PageHeader>
  <section class="grants">
    <div class="grant-role">
      <ChoiceSheet :model-value="selected" label="选择角色" placeholder="选择角色" searchable :disabled="loading || saving || !roles.length"
        :options="roles.map(role => ({ value: role.id, text: role.name + (role.status === 'disabled' ? '（已停用）' : '') }))" @update:model-value="changeRole">
        <template #value="{ text }">
          <van-icon class="role-symbol" name="shield-o" />
          <span class="role-name"><small>当前角色</small><strong>{{ text }}</strong></span>
        </template>
      </ChoiceSheet>
      <p v-if="selectedRole?.code === 'super_admin'"><van-icon name="lock" /> 已启用的页面始终授权给超级管理员</p>
    </div>
    <p v-if="error" role="alert" class="form-error">{{ error }}</p>
    <p v-else-if="loading" class="records-loading" role="status">正在加载权限…</p>
    <van-empty v-else-if="!roles.length || !pages.length" :description="roles.length ? '暂无页面资源' : '暂无角色'" />
    <template v-else>
      <header class="grant-summary">
        <h2>页面权限</h2>
        <span aria-live="polite">已选 {{ checked.size }} / {{ pages.length }}</span>
        <div v-if="protectedIds.size < pages.length" class="grant-actions">
          <button type="button" :disabled="blocked || checked.size === pages.length" @click="selectAll">全选</button>
          <button type="button" :disabled="blocked || checked.size === protectedIds.size" @click="clearAll">清空</button>
        </div>
      </header>
      <van-checkbox-group v-model="selectedPageIds" :disabled="blocked">
        <details v-for="(group, index) in groups" :key="group.name" class="grant-group" :open="index === 0">
          <summary>
            <van-icon class="group-icon" :name="group.icon" />
            <strong>{{ group.name }}</strong>
            <small>{{ group.pages.filter(page => checked.has(page.id)).length }} / {{ group.pages.length }}</small>
            <van-icon name="arrow-down" class="group-chevron" />
          </summary>
          <van-checkbox v-for="page in group.pages" :key="page.id" :name="page.id" label-position="left"
            :disabled="protectedIds.has(page.id)" :aria-disabled="blocked || protectedIds.has(page.id)">
            <span class="grant-name">{{ page.name }}</span>
            <small class="grant-path">{{ page.route_path }}<template v-if="page.page_type !== 'menu'"> · {{ pageTypeLabel(page.page_type) }}</template><template v-if="page.status !== 'active'"> · 已停用</template></small>
            <template v-if="protectedIds.has(page.id)" #icon><van-icon name="lock" aria-label="必须保留" /></template>
          </van-checkbox>
        </details>
      </van-checkbox-group>
    </template>
  </section>
</template>

<style scoped>
.grants { padding-bottom: 12px; }
.grant-role { background: var(--canvas); border-radius: 10px; padding: 4px 14px; }
.grant-role :deep(.choice-trigger) { display: flex; width: 100%; min-height: 64px; padding: 8px 0; border: 0; background: transparent; color: var(--ink); gap: 12px; }
.role-symbol { display: grid; place-items: center; flex: none; width: 36px; height: 36px; border-radius: 8px; background: var(--graphite); color: var(--accent); }
.grant-role :deep(.role-symbol) { font-size: 21px; }
.role-name { flex: 1; min-width: 0; display: grid; gap: 3px; }
.role-name small, .grant-role p, .grant-summary > span, .grant-group summary small, .grant-path { color: var(--secondary); font-size: 12px; }
.role-name strong { font-size: 18px; line-height: 1.3; font-weight: 650; }
.grant-role p { display: flex; align-items: baseline; gap: 6px; border-top: 1px solid var(--line); padding: 9px 0 8px; line-height: 1.5; }
.grant-summary, .grant-actions, .grant-group summary { display: flex; align-items: center; }
.grant-summary { flex-wrap: wrap; gap: 0 8px; margin: 16px 0 4px; min-height: 44px; }
.grant-summary h2 { font-size: 16px; font-weight: 650; }
.grant-actions { margin-left: auto; }
.grant-actions button { min-height: 44px; min-width: 44px; border: 0; background: transparent; font-size: 13px; color: #884600; }
.grant-actions button:disabled { color: #85898e; }
.grant-group { border-top: 1px solid var(--line); }
.grant-group summary { min-height: 54px; gap: 9px; cursor: pointer; list-style: none; }
.grant-group summary::-webkit-details-marker { display: none; }
.grant-group summary strong { flex: 1; font-size: 15px; font-weight: 600; }
.group-icon { display: grid; place-items: center; width: 30px; height: 30px; border-radius: 8px; background: var(--canvas); color: #50565c; font-size: 17px; }
.group-chevron { color: var(--secondary); font-size: 12px; }
.grant-group[open] .group-chevron { transform: rotate(180deg); }
.grant-group :deep(.van-checkbox) { justify-content: space-between; min-height: 50px; margin-left: 39px; padding: 7px 2px 7px 0; border-top: 1px solid #f0f1f2; }
.grant-group :deep(.van-checkbox__label) { min-width: 0; color: var(--ink); }
.grant-group :deep(.van-checkbox__icon--disabled .van-icon-lock) { background: none; border: 0; font-size: 15px; color: #70767b; }
.grant-name { font-size: 14px; overflow-wrap: anywhere; }
.grant-path { display: block; overflow-wrap: anywhere; line-height: 1.4; }
.grant-save.van-button:not(:disabled) { background: var(--accent); color: var(--ink); padding-inline: 15px; }
</style>
