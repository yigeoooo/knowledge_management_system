<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import type { FormInstance, FormRules } from "element-plus";
import { Delete, Edit, Plus, Refresh, Search, Setting } from "@element-plus/icons-vue";
import { api } from "../lib/session";
import { queryParams } from "../lib/query";

interface ManagedRole {
  id: string;
  code: string;
  name: string;
  description: string | null;
  is_system: boolean;
  status: "active" | "disabled";
  user_count: number;
  created_at: string;
  updated_at: string;
}

interface RolePage {
  items: ManagedRole[];
  total: number;
}

const rows = ref<ManagedRole[]>([]);
const total = ref(0);
const page = ref(1);
const pageSize = ref(20);
const filters = reactive({ q: "", status: "" });
const appliedFilters = reactive({ q: "", status: "" });
const loading = ref(false);
const listError = ref("");
const actionId = ref("");
let listRequest = 0;

const editorOpen = ref(false);
const editorLoading = ref(false);
const saving = ref(false);
const editorError = ref("");
const editing = ref<ManagedRole | null>(null);
const formRef = ref<FormInstance>();
const form = reactive({
  code: "",
  name: "",
  description: "",
  is_system: false,
  status: "active",
});
let editorRequest = 0;

const editingRootRole = computed(() => editing.value?.code === "super_admin");
const rules: FormRules = {
  code: [
    { required: true, whitespace: true, message: "请输入角色编码", trigger: "blur" },
    { max: 50, message: "角色编码不能超过 50 个字符", trigger: "blur" },
    {
      pattern: /^[a-z][a-z0-9_-]*$/u,
      message: "编码只能使用小写字母、数字、下划线或连字符，且以字母开头",
      trigger: "blur",
    },
  ],
  name: [
    { required: true, whitespace: true, message: "请输入角色名称", trigger: "blur" },
    { max: 100, message: "角色名称不能超过 100 个字符", trigger: "blur" },
  ],
  description: [{ max: 2000, message: "角色描述不能超过 2000 个字符", trigger: "blur" }],
  status: [{ required: true, message: "请选择角色状态", trigger: "change" }],
};

function formatTime(value: string) {
  return new Date(value).toLocaleString("zh-CN", { hour12: false });
}

function errorText(error: unknown) {
  return error instanceof Error ? error.message : "操作失败，请稍后重试";
}

async function loadRoles() {
  const current = ++listRequest;
  loading.value = true;
  listError.value = "";
  try {
    const params = queryParams({
      ...appliedFilters,
      page: String(page.value),
      page_size: String(pageSize.value),
    });
    const result = await api<RolePage>(`/roles?${params}`);
    if (current !== listRequest) return;
    const lastPage = Math.max(1, Math.ceil(result.total / pageSize.value));
    if (page.value > lastPage) {
      page.value = lastPage;
      await loadRoles();
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
  void loadRoles();
}

function resetFilters() {
  filters.q = "";
  filters.status = "";
  search();
}

function resizePage() {
  page.value = 1;
  void loadRoles();
}

async function openEditor(role?: ManagedRole) {
  const current = ++editorRequest;
  editing.value = role || null;
  Object.assign(form, {
    code: "",
    name: "",
    description: "",
    is_system: false,
    status: "active",
  });
  editorError.value = "";
  editorLoading.value = true;
  editorOpen.value = true;
  await nextTick();
  formRef.value?.clearValidate();
  try {
    const fresh = role ? await api<ManagedRole>(`/roles/${role.id}`) : null;
    if (current !== editorRequest || !editorOpen.value) return;
    editing.value = fresh;
    if (fresh) {
      Object.assign(form, {
        code: fresh.code,
        name: fresh.name,
        description: fresh.description || "",
        is_system: fresh.is_system,
        status: fresh.status,
      });
    }
  } catch (error) {
    if (current === editorRequest) editorError.value = errorText(error);
  } finally {
    if (current === editorRequest) editorLoading.value = false;
  }
}

async function saveRole() {
  if (saving.value || editorLoading.value || editorError.value || !formRef.value) return;
  saving.value = true;
  try {
    if (!(await formRef.value.validate().catch(() => false))) return;
    if (editing.value?.status === "active" && form.status === "disabled") {
      try {
        await ElMessageBox.confirm(
          `停用“${editing.value.name}”后，该角色下的用户将无法登录。`,
          "确认停用角色",
          {
            type: "warning",
            confirmButtonText: "确认停用",
            cancelButtonText: "取消",
          }
        );
      } catch {
        return;
      }
    }
    const body = {
      code: form.code.trim(),
      name: form.name.trim(),
      description: form.description.trim() || null,
      is_system: form.is_system,
      status: form.status,
    };
    if (editing.value) {
      await api<ManagedRole>(`/roles/${editing.value.id}`, {
        method: "PUT",
        body: JSON.stringify(body),
      });
      ElMessage.success("角色信息已更新");
    } else {
      await api<ManagedRole>("/roles", {
        method: "POST",
        body: JSON.stringify(body),
      });
      ElMessage.success("角色已创建");
    }
    editorOpen.value = false;
    await loadRoles();
  } catch (error) {
    ElMessage.error(errorText(error));
  } finally {
    saving.value = false;
  }
}

async function toggleStatus(role: ManagedRole) {
  if (actionId.value || role.code === "super_admin") return;
  actionId.value = role.id;
  const disabling = role.status === "active";
  try {
    if (disabling) {
      try {
        await ElMessageBox.confirm(
          `停用“${role.name}”后，该角色下的 ${role.user_count} 位用户将无法登录。`,
          "确认停用角色",
          {
            type: "warning",
            confirmButtonText: "确认停用",
            cancelButtonText: "取消",
          }
        );
      } catch {
        return;
      }
    }
    await api(`/roles/${role.id}`, {
      method: "PUT",
      body: JSON.stringify({ status: disabling ? "disabled" : "active" }),
    });
    ElMessage.success(disabling ? "角色已停用" : "角色已启用");
    await loadRoles();
  } catch (error) {
    ElMessage.error(errorText(error));
  } finally {
    actionId.value = "";
  }
}

async function deleteRole(role: ManagedRole) {
  if (actionId.value || role.code === "super_admin") return;
  actionId.value = role.id;
  try {
    try {
      await ElMessageBox.confirm(
        `确认删除“${role.name}”？删除后该角色将无法恢复。`,
        "删除角色",
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
    await api(`/roles/${role.id}`, { method: "DELETE" });
    ElMessage.success("角色已删除");
    await loadRoles();
  } catch (error) {
    ElMessage.error(errorText(error));
  } finally {
    actionId.value = "";
  }
}

watch(editorOpen, (open) => {
  if (!open) ++editorRequest;
});
onMounted(loadRoles);
onBeforeUnmount(() => {
  ++listRequest;
  ++editorRequest;
});
</script>

<template>
  <div class="page-heading">
    <div>
      <div class="page-eyebrow">ROLES</div>
      <h1>角色管理</h1>
      <p>以角色组织成员，让权限分配更加清晰。</p>
    </div>
    <el-button
      type="primary"
      :icon="Plus"
      :disabled="!!actionId"
      @click="openEditor()"
    >
      新增角色
    </el-button>
  </div>

  <el-alert
    class="phase-notice"
    title="super_admin 角色不能删除或停用；停用其他角色后，该角色下的用户将无法登录。"
    type="info"
    show-icon
    :closable="false"
  />

  <el-card
    shadow="never"
    class="resource-card roles-card"
  >
    <el-form
      class="roles-filters"
      :inline="true"
      @submit.prevent="search"
    >
      <el-form-item label="角色名称或编码">
        <el-input
          v-model="filters.q"
          placeholder="输入名称或编码进行查询"
          :prefix-icon="Search"
          maxlength="100"
          clearable
          @clear="search"
        />
      </el-form-item>
      <el-form-item label="角色状态">
        <el-select
          v-model="filters.status"
          placeholder="全部状态"
          clearable
          value-on-clear=""
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
      <el-form-item class="roles-filter-buttons">
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

    <div class="roles-list-heading">
      <span>
        角色列表
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
        @click="loadRoles"
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
      class="roles-error"
    />

    <el-table
      v-loading="loading"
      :data="rows"
      row-key="id"
      style="width: 100%"
    >
      <el-table-column
        label="角色名称"
        min-width="180"
      >
        <template #default="{ row }">
          <div class="role-cell">
            <el-avatar :size="34">
              <el-icon><Setting /></el-icon>
            </el-avatar>
            <div>
              <strong>{{ row.name }}</strong>
              <span>{{ row.code }}</span>
            </div>
          </div>
        </template>
      </el-table-column>
      <el-table-column
        label="角色编码"
        prop="code"
        min-width="150"
        show-overflow-tooltip
      />
      <el-table-column
        label="类型"
        width="110"
      >
        <template #default="{ row }">
          <el-tag
            :type="row.is_system ? 'warning' : 'info'"
            effect="light"
          >
            {{ row.is_system ? "系统角色" : "自定义角色" }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column
        label="用户数"
        prop="user_count"
        width="90"
      />
      <el-table-column
        label="状态"
        width="150"
      >
        <template #default="{ row }">
          <el-tooltip
            :content="row.code === 'super_admin' ? 'super_admin 角色不能停用' : '停用后该角色下的用户无法登录'"
            :disabled="row.code !== 'super_admin'"
          >
            <span>
              <el-switch
                :model-value="row.status === 'active'"
                :loading="actionId === row.id"
                :disabled="row.code === 'super_admin' || !!actionId"
                :aria-label="`${row.name}的启用状态`"
                @change="toggleStatus(row)"
              />
            </span>
          </el-tooltip>
          <span
            class="role-status-label"
            :class="{ 'is-disabled': row.status === 'disabled' }"
          >
            {{ row.status === "active" ? "启用" : "停用" }}
          </span>
        </template>
      </el-table-column>
      <el-table-column
        label="更新时间"
        min-width="180"
      >
        <template #default="{ row }">{{ formatTime(row.updated_at) }}</template>
      </el-table-column>
      <el-table-column
        label="操作"
        width="150"
        fixed="right"
      >
        <template #default="{ row }">
          <el-button
            type="primary"
            link
            :icon="Edit"
            :disabled="!!actionId"
            @click="openEditor(row)"
          >
            编辑
          </el-button>
          <el-tooltip
            :content="row.code === 'super_admin' ? 'super_admin 角色不能删除' : '删除角色'"
            :disabled="row.code !== 'super_admin'"
          >
            <span>
              <el-button
                type="danger"
                link
                :icon="Delete"
                :disabled="row.code === 'super_admin' || !!actionId"
                @click="deleteRole(row)"
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
                ? '没有找到符合条件的角色'
                : '暂无角色，请新增自定义角色'
          "
          :image-size="75"
        >
          <template #image>
            <el-icon
              :size="65"
              color="#bfc5cf"
            >
              <Setting />
            </el-icon>
          </template>
        </el-empty>
      </template>
    </el-table>

    <div class="table-pagination roles-pagination">
      <span>共 {{ total }} 个角色</span>
      <el-pagination
        v-model:current-page="page"
        v-model:page-size="pageSize"
        :total="total"
        :page-sizes="[10, 20, 50, 100]"
        layout="sizes, prev, pager, next"
        :pager-count="5"
        @size-change="resizePage"
        @current-change="loadRoles"
      />
    </div>
  </el-card>

  <el-dialog
    v-model="editorOpen"
    :title="editing ? '编辑角色' : '新增角色'"
    width="540px"
    align-center
    :close-on-click-modal="false"
    :close-on-press-escape="!saving"
    :show-close="!saving"
    destroy-on-close
  >
    <div
      v-loading="editorLoading"
      class="role-editor"
    >
      <el-alert
        v-if="editorError"
        :title="editorError"
        type="error"
        show-icon
        :closable="false"
        class="role-editor-error"
      />
      <el-form
        ref="formRef"
        :model="form"
        :rules="rules"
        label-position="top"
        @submit.prevent="saveRole"
      >
        <el-form-item
          label="角色编码"
          prop="code"
        >
          <el-input
            v-model="form.code"
            placeholder="例如 content_editor"
            maxlength="50"
                :disabled="editingRootRole"
          />
          <div class="role-form-note">编码用于接口和权限关联，角色创建后仍可修改。</div>
        </el-form-item>
        <el-form-item
          label="角色名称"
          prop="name"
        >
          <el-input
            v-model="form.name"
            placeholder="请输入角色名称"
            maxlength="100"
          />
        </el-form-item>
        <el-form-item
          label="角色描述"
          prop="description"
        >
          <el-input
            v-model="form.description"
            type="textarea"
            :rows="4"
            maxlength="2000"
            show-word-limit
            placeholder="描述角色的用途和可访问范围"
          />
        </el-form-item>
        <el-form-item
          label="角色类型"
          prop="is_system"
        >
          <el-radio-group
            v-model="form.is_system"
            :disabled="editingRootRole"
          >
            <el-radio :value="false">自定义角色</el-radio>
            <el-radio :value="true">系统角色</el-radio>
          </el-radio-group>
          <div class="role-form-note">系统角色用于标记平台内置或管理用途的角色类型。</div>
        </el-form-item>
        <el-form-item
          label="角色状态"
          prop="status"
        >
          <el-radio-group
            v-model="form.status"
            :disabled="editingRootRole"
          >
            <el-radio value="active">启用</el-radio>
            <el-radio value="disabled">停用</el-radio>
          </el-radio-group>
          <div class="role-form-note">停用后，该角色下的用户将无法登录。</div>
        </el-form-item>
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
        @click="saveRole"
      >
        {{ editing ? "保存修改" : "创建角色" }}
      </el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.roles-filters {
  display: flex;
  flex-wrap: wrap;
  gap: 12px 20px;
  padding-bottom: 18px;
  border-bottom: 1px solid #edf0f3;
}
.roles-filters .el-form-item {
  margin: 0;
}
.roles-filters .el-input {
  width: 255px;
}
.roles-filters .el-select {
  width: 140px;
}
.roles-list-heading {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin: 14px 0;
  font-size: 13px;
  color: #626b78;
}
.roles-list-heading > span {
  display: flex;
  gap: 10px;
  align-items: center;
}
.roles-error {
  margin-bottom: 16px;
}
.role-cell {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}
.role-cell .el-avatar {
  flex-shrink: 0;
  background: #fff2df;
  color: #ac752e;
  font-size: 15px;
}
.role-cell > div:last-child {
  min-width: 0;
}
.role-cell strong,
.role-cell span {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.role-cell strong {
  color: #4f5866;
  font-size: 12px;
  font-weight: 500;
}
.role-cell span {
  margin-top: 5px;
  color: #9aa1ac;
  font-family: monospace;
  font-size: 10px;
}
.role-status-label {
  margin-left: 9px;
  color: #a36a22;
  font-size: 11px;
}
.role-status-label.is-disabled {
  color: #9ca3af;
}
.role-editor {
  min-height: 280px;
}
.role-editor-error {
  margin-bottom: 18px;
}
.role-form-note {
  margin-top: 6px;
  color: #8e96a2;
  font-size: 11px;
  line-height: 1.8;
}
@media (max-width: 640px) {
  .roles-filters {
    display: block;
  }
  .roles-filters .el-form-item {
    display: flex;
    margin-bottom: 14px;
  }
  .roles-filters .el-input,
  .roles-filters .el-select {
    width: 100%;
  }
  .roles-filters :deep(.el-form-item__label) {
    width: 110px;
  }
  .roles-filter-buttons :deep(.el-form-item__content) {
    justify-content: flex-end;
  }
  .roles-pagination {
    align-items: flex-start;
    flex-direction: column;
    gap: 15px;
  }
  .roles-pagination .el-pagination {
    flex-wrap: wrap;
    row-gap: 10px;
  }
  .roles-pagination :deep(.el-pagination__sizes) {
    margin-right: 0;
  }
}
</style>
