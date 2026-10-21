<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { ElMessage, ElMessageBox } from "element-plus";
import type { FormInstance, FormRules } from "element-plus";
import { Plus, Refresh, Search, User as UserIcon } from "@element-plus/icons-vue";
import { api, clearSession, session } from "../lib/session";
import { installPages } from "../router";

interface ManagedUser {
  id: string;
  username: string;
  display_name: string;
  role_id: string;
  role_code: string;
  role_name: string;
  status: "active" | "disabled";
  created_at: string;
  updated_at: string;
}
interface RoleOption {
  id: string;
  name: string;
  code: string;
  status: string;
}
interface UserPage {
  items: ManagedUser[];
  total: number;
}

const router = useRouter();
const rows = ref<ManagedUser[]>([]);
const total = ref(0),
  page = ref(1),
  pageSize = ref(20);
const filters = reactive({ q: "", status: "" });
const appliedFilters = reactive({ q: "", status: "" });
const loading = ref(false),
  listError = ref(""),
  actionId = ref("");
let listRequest = 0;

const editorOpen = ref(false),
  editorLoading = ref(false),
  saving = ref(false),
  editorError = ref("");
const editing = ref<ManagedUser | null>(null),
  roles = ref<RoleOption[]>([]);
const formRef = ref<FormInstance>();
const form = reactive({
  username: "",
  display_name: "",
  role_id: "",
  status: "active",
  password: "",
  confirm_password: "",
});
let editorRequest = 0;
const editorProtected = computed(() => (editing.value ? isProtected(editing.value) : false));
const editingRoot = computed(() => editing.value?.username === "root");
const rules: FormRules = {
  username: [
    { required: true, whitespace: true, message: "请输入用户名", trigger: "blur" },
    { max: 100, message: "用户名不能超过 100 个字符", trigger: "blur" },
    { pattern: /^\S+$/u, message: "用户名不能包含空格", trigger: "blur" },
  ],
  display_name: [
    { required: true, whitespace: true, message: "请输入显示名称", trigger: "blur" },
    { max: 100, message: "显示名称不能超过 100 个字符", trigger: "blur" },
  ],
  role_id: [{ required: true, message: "请选择角色", trigger: "change" }],
  status: [{ required: true, message: "请选择账号状态", trigger: "change" }],
  password: [
    {
      validator: (_rule, value: string, callback) => {
        if (!value && editing.value) return callback();
        if (!value || value.length < 12 || value.length > 1024)
          return callback(new Error("密码需为 12–1024 个字符"));
        callback();
      },
      trigger: "blur",
    },
  ],
  confirm_password: [
    {
      validator: (_rule, value: string, callback) => {
        if (value !== form.password) return callback(new Error("两次输入的密码不一致"));
        callback();
      },
      trigger: "blur",
    },
  ],
};

const detailsOpen = ref(false),
  detailsLoading = ref(false),
  detailsError = ref("");
const details = ref<ManagedUser | null>(null);
let detailRequest = 0;

function isProtected(user: ManagedUser) {
  return user.username === "root" || user.id === session.user?.id;
}
function formatTime(value: string) {
  return new Date(value).toLocaleString("zh-CN", { hour12: false });
}
function errorText(error: unknown) {
  return error instanceof Error ? error.message : "操作失败，请稍后重试";
}

async function loadUsers() {
  const current = ++listRequest;
  loading.value = true;
  listError.value = "";
  try {
    const params = new URLSearchParams({
      ...appliedFilters,
      page: String(page.value),
      page_size: String(pageSize.value),
    });
    const result = await api<UserPage>(`/users?${params}`);
    if (current !== listRequest) return;
    const lastPage = Math.max(1, Math.ceil(result.total / pageSize.value));
    if (page.value > lastPage) {
      page.value = lastPage;
      await loadUsers();
      return;
    }
    rows.value = result.items;
    total.value = result.total;
  } catch (error) {
    if (current === listRequest) {
      listError.value = errorText(error);
      rows.value = [];
      total.value = 0;
    }
  } finally {
    if (current === listRequest) loading.value = false;
  }
}

function search() {
  appliedFilters.q = filters.q.trim();
  appliedFilters.status = filters.status;
  page.value = 1;
  void loadUsers();
}
function resetFilters() {
  filters.q = "";
  filters.status = "";
  search();
}
function resizePage() {
  page.value = 1;
  void loadUsers();
}

async function openEditor(user?: ManagedUser) {
  const current = ++editorRequest;
  editing.value = user || null;
  Object.assign(form, {
    username: "",
    display_name: "",
    role_id: "",
    status: "active",
    password: "",
    confirm_password: "",
  });
  editorError.value = "";
  editorLoading.value = true;
  editorOpen.value = true;
  await nextTick();
  formRef.value?.clearValidate();
  try {
    const [options, fresh] = await Promise.all([
      api<{ items: RoleOption[] }>("/users/role-options"),
      user ? api<ManagedUser>(`/users/${user.id}`) : Promise.resolve(null),
    ]);
    if (current !== editorRequest || !editorOpen.value) return;
    roles.value = options.items;
    editing.value = fresh;
    if (fresh) {
      Object.assign(form, {
        username: fresh.username,
        display_name: fresh.display_name,
        role_id: fresh.role_id,
        status: fresh.status,
      });
    } else {
      const available = options.items.filter((role) => role.status === "active");
      form.role_id = available.find((role) => role.code === "user")?.id || available[0]?.id || "";
    }
  } catch (error) {
    if (current === editorRequest) editorError.value = errorText(error);
  } finally {
    if (current === editorRequest) editorLoading.value = false;
  }
}

async function saveUser() {
  if (saving.value || editorLoading.value || editorError.value || !formRef.value) return;
  saving.value = true;
  try {
    if (!(await formRef.value.validate().catch(() => false))) return;
    if (editing.value?.status === "active" && form.status === "disabled") {
      try {
        await ElMessageBox.confirm(
          `停用“${editing.value.username}”后，该用户将无法登录，现有会话也会失效。`,
          "确认停用用户",
          { type: "warning", confirmButtonText: "确认停用", cancelButtonText: "取消" }
        );
      } catch {
        return;
      }
    }
    const body = {
      username: form.username.trim(),
      display_name: form.display_name.trim(),
      role_id: form.role_id,
      status: form.status,
      ...(form.password ? { password: form.password } : {}),
    };
    if (editing.value) {
      const result = await api<{ user: ManagedUser; reauthenticate: boolean }>(
        `/users/${editing.value.id}`,
        { method: "PUT", body: JSON.stringify(body) }
      );
      editorOpen.value = false;
      if (result.reauthenticate) {
        clearSession();
        installPages();
        ElMessage.success("信息已更新，请使用新的登录信息重新登录");
        await router.replace({ path: "/login", query: { redirect: "/users" } });
        return;
      }
      if (session.user && result.user.id === session.user.id) {
        session.user.username = result.user.username;
        session.user.display_name = result.user.display_name;
      }
      ElMessage.success("用户信息已更新");
    } else {
      await api<ManagedUser>("/users", { method: "POST", body: JSON.stringify(body) });
      editorOpen.value = false;
      filters.q = "";
      filters.status = "";
      appliedFilters.q = "";
      appliedFilters.status = "";
      page.value = 1;
      ElMessage.success("用户已创建");
    }
    await loadUsers();
  } catch (error) {
    ElMessage.error(errorText(error));
  } finally {
    saving.value = false;
  }
}

async function showDetails(user: ManagedUser) {
  const current = ++detailRequest;
  details.value = null;
  detailsError.value = "";
  detailsLoading.value = true;
  detailsOpen.value = true;
  try {
    const result = await api<ManagedUser>(`/users/${user.id}`);
    if (current === detailRequest && detailsOpen.value) details.value = result;
  } catch (error) {
    if (current === detailRequest) detailsError.value = errorText(error);
  } finally {
    if (current === detailRequest) detailsLoading.value = false;
  }
}

async function toggleStatus(user: ManagedUser) {
  if (actionId.value || isProtected(user)) return;
  actionId.value = user.id;
  const disabling = user.status === "active";
  try {
    if (disabling) {
      try {
        await ElMessageBox.confirm(
          `停用“${user.username}”后，该用户将无法登录，现有会话也会失效。`,
          "确认停用用户",
          { type: "warning", confirmButtonText: "确认停用", cancelButtonText: "取消" }
        );
      } catch {
        return;
      }
    }
    await api(`/users/${user.id}`, {
      method: "PUT",
      body: JSON.stringify({ status: disabling ? "disabled" : "active" }),
    });
    ElMessage.success(disabling ? "用户已停用" : "用户已启用");
    await loadUsers();
  } catch (error) {
    ElMessage.error(errorText(error));
  } finally {
    actionId.value = "";
  }
}

async function deleteUser(user: ManagedUser) {
  if (actionId.value || isProtected(user)) return;
  actionId.value = user.id;
  try {
    try {
      await ElMessageBox.confirm(
        `确认删除“${user.username}”？删除后该用户将从列表移除，无法再登录；历史操作记录仍会保留，该用户名不能再次注册。`,
        "删除用户",
        {
          type: "warning",
          confirmButtonText: "确认删除",
          cancelButtonText: "取消",
          confirmButtonClass: "el-button--danger",
        }
      );
    } catch {
      return;
    }
    await api(`/users/${user.id}`, { method: "DELETE" });
    ElMessage.success("用户已删除");
    await loadUsers();
  } catch (error) {
    ElMessage.error(errorText(error));
  } finally {
    actionId.value = "";
  }
}

watch(editorOpen, (open) => {
  if (!open) {
    ++editorRequest;
    form.password = "";
    form.confirm_password = "";
  }
});
watch(detailsOpen, (open) => {
  if (!open) ++detailRequest;
});
onMounted(loadUsers);
onBeforeUnmount(() => {
  ++listRequest;
  ++editorRequest;
  ++detailRequest;
});
</script>

<template>
  <div class="page-heading">
    <div>
      <div class="page-eyebrow">TEAM MEMBERS</div>
      <h1>用户管理</h1>
      <p>管理团队成员、角色与账号状态，让协作有序进行。</p>
    </div>
    <el-button
      type="primary"
      :icon="Plus"
      :disabled="!!actionId"
      @click="openEditor()"
    >
      新增用户
    </el-button>
  </div>

  <el-card
    shadow="never"
    class="resource-card users-card"
  >
    <el-form
      class="users-filters"
      :inline="true"
      @submit.prevent="search"
    >
      <el-form-item label="显示名称">
        <el-input
          v-model="filters.q"
          placeholder="输入名称进行模糊查询"
          :prefix-icon="Search"
          maxlength="100"
          clearable
          @clear="search"
        />
      </el-form-item>
      <el-form-item label="账号状态">
        <el-select
          v-model="filters.status"
          placeholder="全部状态"
          clearable
          @change="search"
        >
          <el-option
            label="启用"
            value="active"
          />
          <el-option
            label="停用"
            value="disabled"
          />
        </el-select>
      </el-form-item>
      <el-form-item class="users-filter-buttons">
        <el-button
          type="primary"
          :icon="Search"
          native-type="submit"
        >
          查询
        </el-button>
        <el-button @click="resetFilters">重置</el-button>
      </el-form-item>
    </el-form>
    <div class="users-list-heading">
      <span>
        用户列表
        <el-tag
          type="info"
          effect="plain"
          size="small"
        >
          {{ total }}
        </el-tag>
      </span>
      <el-button
        :icon="Refresh"
        :loading="loading"
        text
        @click="loadUsers"
      >
        刷新
      </el-button>
    </div>
    <el-alert
      v-if="listError"
      :title="listError"
      type="error"
      show-icon
      :closable="false"
      class="users-error"
    />
    <el-table
      v-loading="loading"
      :data="rows"
      row-key="id"
      style="width: 100%"
    >
      <el-table-column
        label="用户名"
        min-width="190"
      >
        <template #default="{ row }">
          <div class="user-cell">
            <el-avatar :size="34">{{ row.display_name.slice(0, 1).toUpperCase() }}</el-avatar>
            <el-button
              class="user-name"
              link
              @click="showDetails(row)"
            >
              {{ row.username }}
            </el-button>
            <el-tag
              v-if="row.id === session.user?.id"
              type="info"
              size="small"
              effect="plain"
            >
              本人
            </el-tag>
          </div>
        </template>
      </el-table-column>
      <el-table-column
        prop="display_name"
        label="显示名称"
        min-width="140"
        show-overflow-tooltip
      />
      <el-table-column
        label="角色"
        min-width="130"
      >
        <template #default="{ row }">
          <el-tag
            :type="row.role_code === 'super_admin' ? 'warning' : 'info'"
            effect="light"
          >
            {{ row.role_name }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column
        label="账号状态"
        width="160"
      >
        <template #default="{ row }">
          <el-tooltip
            :content="row.username === 'root' ? 'Root 管理员保持启用' : '不能停用当前登录账号'"
            :disabled="!isProtected(row)"
          >
            <span>
              <el-switch
                :model-value="row.status === 'active'"
                :loading="actionId === row.id"
                :disabled="isProtected(row) || !!actionId"
                :aria-label="`${row.username}的启用状态`"
                @change="toggleStatus(row)"
              />
            </span>
          </el-tooltip>
          <span
            class="user-status-label"
            :class="{ 'is-disabled': row.status === 'disabled' }"
          >
            {{ row.status === "active" ? "启用" : "停用" }}
          </span>
        </template>
      </el-table-column>
      <el-table-column
        label="创建时间"
        min-width="185"
      >
        <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
      </el-table-column>
      <el-table-column
        label="操作"
        width="180"
        fixed="right"
      >
        <template #default="{ row }">
          <el-button
            type="primary"
            link
            :disabled="!!actionId"
            @click="showDetails(row)"
          >
            详情
          </el-button>
          <el-button
            type="primary"
            link
            :disabled="!!actionId"
            @click="openEditor(row)"
          >
            编辑
          </el-button>
          <el-tooltip
            content="不能删除 Root 管理员或当前登录账号"
            :disabled="!isProtected(row)"
          >
            <span class="user-delete-action">
              <el-button
                type="danger"
                link
                :disabled="isProtected(row) || !!actionId"
                @click="deleteUser(row)"
              >
                删除
              </el-button>
            </span>
          </el-tooltip>
        </template>
      </el-table-column>
      <template #empty>
        <el-empty
          :description="
            listError
              ? '加载失败，请点击刷新重试'
              : appliedFilters.q || appliedFilters.status
                ? '没有找到符合条件的用户'
                : '暂无用户，请新增团队成员'
          "
          :image-size="75"
        >
          <template #image>
            <el-icon
              :size="65"
              color="#bfc5cf"
            >
              <UserIcon />
            </el-icon>
          </template>
        </el-empty>
      </template>
    </el-table>
    <div class="table-pagination users-pagination">
      <span>共 {{ total }} 位用户</span>
      <el-pagination
        v-model:current-page="page"
        v-model:page-size="pageSize"
        :total="total"
        :page-sizes="[10, 20, 50, 100]"
        layout="sizes, prev, pager, next"
        :pager-count="5"
        @size-change="resizePage"
        @current-change="loadUsers"
      />
    </div>
  </el-card>

  <el-dialog
    v-model="editorOpen"
    :title="editing ? '编辑用户' : '新增用户'"
    width="560px"
    align-center
    :close-on-click-modal="false"
    :close-on-press-escape="!saving"
    :show-close="!saving"
    destroy-on-close
  >
    <div
      v-loading="editorLoading"
      class="user-editor"
    >
      <el-alert
        v-if="editorError"
        :title="editorError"
        type="error"
        :closable="false"
        show-icon
      >
        <el-button
          text
          @click="openEditor(editing || undefined)"
        >
          重新加载
        </el-button>
      </el-alert>
      <el-form
        ref="formRef"
        :model="form"
        :rules="rules"
        label-position="top"
        :disabled="saving || editorLoading || !!editorError"
        @submit.prevent="saveUser"
      >
        <div class="user-form-row">
          <el-form-item
            label="用户名"
            prop="username"
          >
            <el-input
              v-model="form.username"
              :disabled="editingRoot"
              placeholder="用于登录，不能包含空格"
              maxlength="100"
              autocomplete="off"
            />
          </el-form-item>
          <el-form-item
            label="显示名称"
            prop="display_name"
          >
            <el-input
              v-model="form.display_name"
              placeholder="在平台中显示的名称"
              maxlength="100"
            />
          </el-form-item>
        </div>
        <div class="user-form-row">
          <el-form-item
            label="角色"
            prop="role_id"
          >
            <el-select
              v-model="form.role_id"
              placeholder="请选择角色"
              :disabled="editorProtected"
            >
              <el-option
                v-for="role in roles"
                :key="role.id"
                :label="`${role.name}${role.status !== 'active' ? '（已停用）' : ''}`"
                :value="role.id"
                :disabled="role.status !== 'active'"
              />
            </el-select>
          </el-form-item>
          <el-form-item
            label="账号状态"
            prop="status"
          >
            <el-radio-group
              v-model="form.status"
              :disabled="editorProtected"
            >
              <el-radio-button value="active">启用</el-radio-button>
              <el-radio-button value="disabled">停用</el-radio-button>
            </el-radio-group>
          </el-form-item>
        </div>
        <el-alert
          v-if="editorProtected"
          class="user-protection-note"
          title="Root 和当前登录账号的角色、启用状态受到保护。"
          type="info"
          :closable="false"
        />
        <el-form-item
          :label="editing ? '新密码（不修改请留空）' : '初始密码'"
          prop="password"
        >
          <el-input
            v-model="form.password"
            type="password"
            show-password
            autocomplete="new-password"
            :placeholder="
              editing ? '留空保留原密码，填写则重置密码' : '请输入 12–1024 个字符的密码'
            "
            maxlength="1024"
          />
        </el-form-item>
        <el-form-item
          :label="editing ? '确认新密码' : '确认密码'"
          prop="confirm_password"
        >
          <el-input
            v-model="form.confirm_password"
            type="password"
            show-password
            autocomplete="new-password"
            placeholder="再次输入密码"
            maxlength="1024"
          />
        </el-form-item>
        <p
          v-if="editing"
          class="user-form-note"
        >
          修改用户名、密码、角色或状态后，用户需要重新登录。
        </p>
        <button
          class="user-form-submit"
          type="submit"
          tabindex="-1"
          aria-hidden="true"
        />
      </el-form>
    </div>
    <template #footer>
      <el-button
        :disabled="saving"
        @click="editorOpen = false"
      >
        取消
      </el-button>
      <el-button
        type="primary"
        :loading="saving"
        :disabled="editorLoading || !!editorError"
        @click="saveUser"
      >
        {{ editing ? "保存修改" : "创建用户" }}
      </el-button>
    </template>
  </el-dialog>

  <el-drawer
    v-model="detailsOpen"
    title="用户详情"
    size="480px"
    class="user-detail-drawer"
  >
    <div
      v-loading="detailsLoading"
      class="user-details"
    >
      <el-alert
        v-if="detailsError"
        :title="detailsError"
        type="error"
        :closable="false"
        show-icon
      />
      <template v-if="details">
        <div class="profile-heading">
          <el-avatar :size="64">{{ details.display_name.slice(0, 1).toUpperCase() }}</el-avatar>
          <div>
            <h2>{{ details.display_name }}</h2>
            <el-tag :type="details.status === 'active' ? 'success' : 'info'">
              {{ details.status === "active" ? "启用" : "停用" }}
            </el-tag>
          </div>
        </div>
        <el-descriptions
          :column="1"
          border
        >
          <el-descriptions-item label="用户名">{{ details.username }}</el-descriptions-item>
          <el-descriptions-item label="显示名称">{{ details.display_name }}</el-descriptions-item>
          <el-descriptions-item label="角色">{{ details.role_name }}</el-descriptions-item>
          <el-descriptions-item label="创建时间">
            {{ formatTime(details.created_at) }}
          </el-descriptions-item>
          <el-descriptions-item label="更新时间">
            {{ formatTime(details.updated_at) }}
          </el-descriptions-item>
        </el-descriptions>
      </template>
    </div>
    <template #footer>
      <el-button @click="detailsOpen = false">关闭</el-button>
      <el-button
        v-if="details"
        type="primary"
        @click="
          openEditor(details);
          detailsOpen = false;
        "
      >
        编辑用户
      </el-button>
    </template>
  </el-drawer>
</template>

<style scoped>
.users-filters {
  display: flex;
  flex-wrap: wrap;
  gap: 12px 20px;
  padding-bottom: 18px;
  border-bottom: 1px solid #edf0f3;
}
.users-filters .el-form-item {
  margin: 0;
}
.users-filters .el-input {
  width: 255px;
}
.users-filters .el-select {
  width: 140px;
}
.users-list-heading {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin: 14px 0;
  font-size: 13px;
  color: #626b78;
}
.users-list-heading > span {
  display: flex;
  gap: 10px;
  align-items: center;
}
.users-error {
  margin-bottom: 16px;
}
.user-cell {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}
.user-cell .el-avatar {
  flex-shrink: 0;
  background: #fff2df;
  color: #ac752e;
  font-size: 13px;
}
.user-cell .user-name {
  min-width: 0;
  max-width: 140px;
  justify-content: flex-start;
  font-size: 12px;
  color: #4f5866;
}
.user-name :deep(span) {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.user-cell .el-tag {
  flex-shrink: 0;
}
.user-status-label {
  margin-left: 9px;
  font-size: 11px;
  color: #a36a22;
}
.user-status-label.is-disabled {
  color: #9ca3af;
}
.user-delete-action {
  margin-left: 12px;
}
.user-editor {
  min-height: 230px;
}
.user-form-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 20px;
}
.user-form-row .el-select {
  width: 100%;
}
.user-protection-note {
  margin-bottom: 20px;
}
.user-form-note {
  font-size: 11px;
  color: #8e96a2;
  line-height: 1.8;
}
.user-form-submit {
  display: none;
}
.user-details {
  min-height: 220px;
}
.user-details :deep(.el-descriptions__label) {
  width: 95px;
}
.user-details :deep(.el-descriptions__content) {
  word-break: break-all;
}
.user-details .profile-heading h2 {
  overflow-wrap: anywhere;
}
:global(.user-detail-drawer) {
  max-width: 100vw;
}
@media (max-width: 640px) {
  .users-filters {
    display: block;
  }
  .users-filters .el-form-item {
    display: flex;
    margin-bottom: 14px;
  }
  .users-filters .el-input,
  .users-filters .el-select {
    width: 100%;
  }
  .users-filters :deep(.el-form-item__label) {
    width: 75px;
  }
  .users-filter-buttons :deep(.el-form-item__content) {
    justify-content: flex-end;
  }
  .users-pagination {
    align-items: flex-start;
    flex-direction: column;
    gap: 15px;
  }
  .users-pagination .el-pagination {
    flex-wrap: wrap;
    row-gap: 10px;
  }
  .users-pagination :deep(.el-pagination__sizes) {
    margin-right: 0;
  }
  .user-form-row {
    grid-template-columns: 1fr;
    gap: 0;
  }
}
</style>
