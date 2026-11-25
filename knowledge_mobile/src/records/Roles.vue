<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import type { FormInstance, FormRules } from "element-plus";

import { api } from "@web/lib/session";
import { queryParams } from "@web/lib/query";
import RecordPage from './RecordPage.vue'
import RecordFilters from './RecordFilters.vue'
import RecordRow from './RecordRow.vue'

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
  <RecordPage title="角色管理" list-title="角色列表" create-label="新增角色"
    empty-text="还没有角色" empty-icon="shield-o" :filtered="!!(appliedFilters.q || appliedFilters.status)" @reset="resetFilters"
    :total="total" :page="page" :size="pageSize" :sizes="[10, 20, 50, 100]" :loading="loading" :error="listError" :busy="!!actionId"
    @create="openEditor()" @refresh="loadRoles" @page="page = $event; loadRoles()" @size="pageSize = $event; resizePage()">
    <template #filters>
      <RecordFilters v-model:query="filters.q" v-model:status="filters.status"
        placeholder="搜索角色名称或编码" status-label="角色状态" :maxlength="100" @search="search" @reset="resetFilters" />
    </template>
    <RecordRow icon="shield-o" v-for="row in rows" :key="row.id" :title="row.name" :subtitle="row.code"
      :badge="row.status === 'active' ? '启用' : '停用'" :inactive="row.status !== 'active'"
      :actions="[
        { name:'编辑', run:() => openEditor(row), disabled:!!actionId },
        { name:row.status === 'active' ? '停用角色' : '启用角色', run:() => toggleStatus(row), disabled:!!actionId || row.code === 'super_admin' },
        { name:'删除', run:() => deleteRole(row), disabled:!!actionId || row.code === 'super_admin', color:'var(--el-color-danger)' },
      ]">
      <span>{{ row.is_system ? '系统角色' : '自定义角色' }}</span><span>{{ row.user_count }} 位用户</span>
      <small>更新于 {{ formatTime(row.updated_at) }}</small>
    </RecordRow>
  </RecordPage>

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
</style>
