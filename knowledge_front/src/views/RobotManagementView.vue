<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import type { FormInstance, FormRules } from "element-plus";
import { Cpu, Delete, Edit, Plus, Refresh, Search, View } from "@element-plus/icons-vue";
import { api } from "../lib/session";
import { queryParams } from "../lib/query";

type RobotStatus = "active" | "disabled";
interface Robot {
  id: string;
  serial_no: string;
  name: string | null;
  description: string | null; default_location: string | null; default_location_name?: string | null; timezone: string | null;
  knowledge_base_id: string | null; knowledge_base_name: string | null; binding_version: number; knowledge_base_status: string | null;
  status: RobotStatus;
  last_request_at: string | null;
  created_by: string | null;
  created_at: string;
  updated_at: string;
}
interface RobotPage { items: Robot[]; total: number }

const rows = ref<Robot[]>([]);
const baseOptions = ref<{ id: string; name: string }[]>([]);
async function loadBaseOptions() { baseOptions.value = (await api<{items: typeof baseOptions.value}>("/robots/knowledge-base-options")).items; }
const total = ref(0);
const page = ref(1);
const pageSize = ref(20);
const filters = reactive({ q: "", status: "", knowledge_base_id: "" });
const applied = reactive({ q: "", status: "", knowledge_base_id: "" });
const loading = ref(false);
const listError = ref("");
const actionId = ref("");
let listRequest = 0;

const editorOpen = ref(false);
const editorLoading = ref(false);
const saving = ref(false);
const editorError = ref("");
const editing = ref<Robot | null>(null);
const formRef = ref<FormInstance>();
const form = reactive({ serial_no: "", name: "", description: "", default_location: "", timezone: "", knowledge_base_id: "", status: "active" as RobotStatus });
interface LocationOption { value: string; label: string; timezone: string }
const locationOptions = ref<LocationOption[]>([]), locationLoading = ref(false);
const timezoneOptions = ref<string[]>(['Asia/Shanghai']);
let locationRequest = 0;
async function searchLocations(query: string) {
  const sequence = ++locationRequest;
  if (query.trim().length < 2) { locationLoading.value = false; return; }
  locationLoading.value = true;
  try {
    const result = await api<{ items: LocationOption[] }>(`/robots/location-options?q=${encodeURIComponent(query.trim())}`);
    if (sequence === locationRequest) locationOptions.value = result.items;
  } catch (e) { if (sequence === locationRequest) ElMessage.error((e as Error).message); }
  finally { if (sequence === locationRequest) locationLoading.value = false; }
}
function timezoneLabel(value: string | null) {
  return value === 'Asia/Shanghai' ? '北京时间（Asia/Shanghai）' : value || '未设置';
}
function chooseLocation(value: string) {
  const option = locationOptions.value.find(p => p.value === value);
  if (option) form.timezone = option.timezone;
}
async function loadTimezones(open: boolean) {
  if (!open || timezoneOptions.value.length > 1) return;
  try { timezoneOptions.value = (await api<{ items: string[] }>('/robots/timezone-options')).items; }
  catch (e) { ElMessage.error((e as Error).message); }
}
let editorRequest = 0;

const detailOpen = ref(false);
const detailLoading = ref(false);
const detailError = ref("");
const detail = ref<Robot | null>(null);
let detailRequest = 0;

const rules: FormRules = {
  knowledge_base_id: [{ required: true, message: "请选择绑定知识库", trigger: "change" }],
  serial_no: [
    { required: true, whitespace: true, message: "请输入机器人序列号", trigger: "blur" },
    { max: 100, message: "序列号不能超过 100 个字符", trigger: "blur" },
  ],
  name: [{ max: 200, message: "机器人名称不能超过 200 个字符", trigger: "blur" }],
  description: [{ max: 2000, message: "描述不能超过 2000 个字符", trigger: "blur" }],
  status: [{ required: true, message: "请选择机器人状态", trigger: "change" }],
};

function errorText(error: unknown) {
  return error instanceof Error ? error.message : "操作失败，请稍后重试";
}
function formatTime(value: string | null) {
  return value ? new Date(value).toLocaleString("zh-CN", { hour12: false }) : "—";
}
function statusLabel(status: RobotStatus) { return status === "active" ? "启用" : "停用"; }
function statusType(status: RobotStatus) { return status === "active" ? "success" : "info"; }

async function loadRobots() {
  const current = ++listRequest;
  loading.value = true;
  listError.value = "";
  try {
    const params = queryParams({ ...applied, page: page.value, page_size: pageSize.value });
    const result = await api<RobotPage>(`/robots?${params}`);
    if (current !== listRequest) return;
    const lastPage = Math.max(1, Math.ceil(result.total / pageSize.value));
    if (page.value > lastPage) {
      page.value = lastPage;
      await loadRobots();
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
  applied.q = filters.q.trim();
  applied.status = filters.status;
  applied.knowledge_base_id = filters.knowledge_base_id;
  page.value = 1;
  void loadRobots();
}
function resetFilters() {
  filters.q = "";
  filters.status = "";
  filters.knowledge_base_id = "";
  search();
}
function resizePage() {
  page.value = 1;
  void loadRobots();
}

async function openEditor(robot?: Robot) {
  const current = ++editorRequest;
  editing.value = robot || null;
  Object.assign(form, { serial_no: "", name: "", description: "", default_location: "", timezone: "", knowledge_base_id: "", status: "active" as RobotStatus });
  editorError.value = "";
  editorLoading.value = true;
  editorOpen.value = true;
  await nextTick();
  formRef.value?.clearValidate();
  try {
    await loadBaseOptions();
    const fresh = robot ? await api<Robot>(`/robots/${robot.id}`) : null;
    if (current !== editorRequest || !editorOpen.value) return;
    editing.value = fresh;
    if (fresh) Object.assign(form, {
      serial_no: fresh.serial_no,
      name: fresh.name || "",
      description: fresh.description || "",
      default_location: fresh.default_location || "", timezone: fresh.timezone || "",
      knowledge_base_id: fresh.knowledge_base_id || "",
      status: fresh.status,
    });
  } catch (error) {
    if (current === editorRequest) editorError.value = errorText(error);
  } finally {
    if (current === editorRequest) editorLoading.value = false;
  }
}

async function saveRobot() {
  if (saving.value || editorLoading.value || editorError.value || !formRef.value) return;
  saving.value = true;
  try {
    if (!(await formRef.value.validate().catch(() => false))) return;
    if (editing.value?.status === "active" && form.status === "disabled") {
      try {
        await ElMessageBox.confirm(
          `停用“${editing.value.name || editing.value.serial_no}”后，该机器人将无法调用问答接口。`,
          "确认停用机器人",
          { type: "warning", confirmButtonText: "确认停用", cancelButtonText: "取消" },
        );
      } catch { return; }
    }
    if (editing.value && form.knowledge_base_id !== editing.value.knowledge_base_id) {
      try { await ElMessageBox.confirm("换绑后旧会话将关闭，进行中的问答会取消；新对话使用新知识库。", "确认换绑知识库", { confirmButtonText: "确认换绑", cancelButtonText: "取消", type: "warning" }); } catch { return; }
    }
    const body = {
      ...(!editing.value || form.knowledge_base_id !== editing.value.knowledge_base_id ? {
        knowledge_base_id: form.knowledge_base_id, expected_binding_version: editing.value?.binding_version,
      } : {}),
      serial_no: form.serial_no.trim(),
      name: form.name.trim() || null,
      description: form.description.trim() || null,
      default_location: form.default_location.trim() || null, timezone: form.timezone.trim() || null,
      status: form.status,
    };
    if (editing.value) {
      await api<Robot>(`/robots/${editing.value.id}`, { method: "PUT", body: JSON.stringify(body) });
      ElMessage.success("机器人信息已更新");
    } else {
      await api<Robot>("/robots", { method: "POST", body: JSON.stringify(body) });
      ElMessage.success("机器人已注册");
    }
    editorOpen.value = false;
    await loadRobots();
  } catch (error) {
    ElMessage.error(errorText(error));
  } finally {
    saving.value = false;
  }
}

async function showDetails(robot: Robot) {
  const current = ++detailRequest;
  detail.value = null;
  detailError.value = "";
  detailLoading.value = true;
  detailOpen.value = true;
  try {
    const fresh = await api<Robot>(`/robots/${robot.id}`);
    if (current === detailRequest && detailOpen.value) detail.value = fresh;
  } catch (error) {
    if (current === detailRequest) detailError.value = errorText(error);
  } finally {
    if (current === detailRequest) detailLoading.value = false;
  }
}

async function disableRobot(robot: Robot) {
  if (actionId.value || robot.status === "disabled") return;
  actionId.value = robot.id;
  try {
    try {
      await ElMessageBox.confirm(
        `停用“${robot.name || robot.serial_no}”后，该机器人将无法继续提问，历史记录会保留。`,
        "停用机器人",
        { type: "warning", confirmButtonText: "确认停用", cancelButtonText: "取消" },
      );
    } catch { return; }
    await api(`/robots/${robot.id}`, { method: "DELETE" });
    ElMessage.success("机器人已停用");
    await loadRobots();
  } catch (error) {
    ElMessage.error(errorText(error));
  } finally {
    actionId.value = "";
  }
}

watch(editorOpen, (open) => { if (!open) ++editorRequest; });
watch(detailOpen, (open) => { if (!open) ++detailRequest; });
onMounted(() => { void loadRobots(); void loadBaseOptions().catch(e => ElMessage.error((e as Error).message)); });
onBeforeUnmount(() => { ++listRequest; ++editorRequest; ++detailRequest; });
</script>

<template>
  <div class="page-heading">
    <div>
      <div class="page-eyebrow">CONNECTED ROBOTS</div>
      <h1>机器人管理</h1>
      <p>注册机器人设备，管理身份和调用状态，让知识服务连接真实场景。</p>
    </div>
    <el-button type="primary" :icon="Plus" :disabled="!!actionId" @click="openEditor()">注册机器人</el-button>
  </div>

  <el-alert class="phase-notice" title="停用机器人后，其序列号不能继续调用问答接口；历史请求记录会保留。" type="info" show-icon :closable="false" />
  <el-card shadow="never" class="resource-card robots-card">
    <el-form class="robots-filters" :inline="true" @submit.prevent="search">
      <el-form-item label="序列号或名称">
        <el-input v-model="filters.q" placeholder="输入序列号或名称" :prefix-icon="Search" maxlength="200" clearable @clear="search" />
      </el-form-item>
      <el-form-item label="知识库"><el-select v-model="filters.knowledge_base_id" placeholder="全部知识库" clearable value-on-clear="" @change="search"><el-option v-for="base in baseOptions" :key="base.id" :label="base.name" :value="base.id" /></el-select></el-form-item>
      <el-form-item label="状态">
        <el-select v-model="filters.status" placeholder="全部状态" clearable value-on-clear="" @change="search">
          <el-option label="启用" value="active" /><el-option label="停用" value="disabled" />
        </el-select>
      </el-form-item>
      <el-form-item class="robots-filter-buttons">
        <el-button type="primary" :icon="Search" native-type="submit">查询</el-button>
        <el-button @click="resetFilters">重置</el-button>
      </el-form-item>
    </el-form>
    <div class="robots-list-heading">
      <span>机器人列表 <el-tag type="info" effect="plain" size="small">{{ total }}</el-tag></span>
      <el-button :icon="Refresh" :loading="loading" text @click="loadRobots">刷新</el-button>
    </div>
    <el-alert v-if="listError" :title="listError" type="error" show-icon :closable="false" class="list-error" />
    <el-table v-loading="loading" :data="rows" row-key="id" style="width: 100%">
      <el-table-column label="机器人" min-width="220">
        <template #default="{ row }"><div class="robot-cell"><el-avatar :size="34"><el-icon><Cpu /></el-icon></el-avatar><div><strong>{{ row.name || "未命名机器人" }}</strong><span>{{ row.serial_no }}</span></div></div></template>
      </el-table-column>
      <el-table-column label="绑定知识库" min-width="180"><template #default="{ row }">{{ row.knowledge_base_name || "待绑定" }}</template></el-table-column>
      <el-table-column label="绑定城市" min-width="200" show-overflow-tooltip><template #default="{ row }">{{ row.default_location_name || row.default_location || '未设置' }}</template></el-table-column>
      <el-table-column label="时区" min-width="210"><template #default="{ row }">{{ timezoneLabel(row.timezone) }}</template></el-table-column>
      <el-table-column prop="description" label="描述" min-width="250" show-overflow-tooltip />
      <el-table-column label="状态" width="100"><template #default="{ row }"><el-tag :type="statusType(row.status)">{{ statusLabel(row.status) }}</el-tag></template></el-table-column>
      <el-table-column label="最近请求" width="180"><template #default="{ row }">{{ formatTime(row.last_request_at) }}</template></el-table-column>
      <el-table-column label="更新时间" width="180"><template #default="{ row }">{{ formatTime(row.updated_at) }}</template></el-table-column>
      <el-table-column label="操作" fixed="right" width="270">
        <template #default="{ row }">
          <el-button link type="primary" :icon="View" @click="showDetails(row)">详情</el-button>
          <el-button link type="primary" :icon="Edit" :disabled="!!actionId" @click="openEditor(row)">编辑</el-button>
          <el-button v-if="row.status === 'active'" link type="danger" :icon="Delete" :disabled="!!actionId" @click="disableRobot(row)">停用</el-button>
        </template>
      </el-table-column>
      <template #empty><el-empty :description="applied.q || applied.status ? '没有找到匹配的机器人' : '暂无机器人，请先注册一台设备'" :image-size="80" /></template>
    </el-table>
    <div class="table-pagination"><span>共 {{ total }} 条记录</span><el-pagination v-model:current-page="page" v-model:page-size="pageSize" :page-sizes="[20, 50, 100]" :total="total" layout="sizes, prev, pager, next" @current-change="loadRobots" @size-change="resizePage" /></div>
  </el-card>

  <el-dialog v-model="editorOpen" :title="editing ? '编辑机器人' : '注册机器人'" width="560px" align-center destroy-on-close>
    <el-alert v-if="editorError" :title="editorError" type="error" :closable="false" show-icon />
    <el-form ref="formRef" v-loading="editorLoading" :model="form" :rules="rules" label-position="top" @submit.prevent="saveRobot">
      <el-form-item label="机器人序列号" prop="serial_no"><el-input v-model="form.serial_no" maxlength="100" placeholder="例如：ROBOT-001" /></el-form-item>
      <el-form-item label="绑定知识库" prop="knowledge_base_id"><el-select v-model="form.knowledge_base_id" placeholder="请选择知识库" filterable style="width:100%"><el-option v-if="editing?.knowledge_base_id && !baseOptions.some(b => b.id === editing?.knowledge_base_id)" :value="editing.knowledge_base_id" :label="`${editing.knowledge_base_name}（已停用）`" disabled /><el-option v-for="base in baseOptions" :key="base.id" :label="base.name" :value="base.id" /></el-select></el-form-item>
      <el-form-item label="机器人名称" prop="name"><el-input v-model="form.name" maxlength="200" placeholder="例如：一号巡检机器人" /></el-form-item>
      <el-form-item label="实时查询默认地点"><el-select v-model="form.default_location" filterable remote clearable :remote-method="searchLocations" :loading="locationLoading" placeholder="输入城市或区县名称搜索" style="width:100%" @change="chooseLocation"><el-option v-if="form.default_location && !locationOptions.some(p => p.value === form.default_location)" :value="form.default_location" :label="editing?.default_location === form.default_location ? editing.default_location_name || form.default_location : form.default_location" /><el-option v-for="place in locationOptions" :key="place.value" :value="place.value" :label="place.label" /></el-select></el-form-item>
      <el-form-item label="当地时区"><el-select v-model="form.timezone" filterable clearable placeholder="选择时区；选择地区后自动填入" style="width:100%" @visible-change="loadTimezones"><el-option v-if="form.timezone && !timezoneOptions.includes(form.timezone)" :value="form.timezone" :label="form.timezone" /><el-option v-for="zone in timezoneOptions" :key="zone" :value="zone" :label="zone === 'Asia/Shanghai' ? '北京时间（Asia/Shanghai）' : zone" /></el-select></el-form-item>
      <el-form-item label="描述" prop="description"><el-input v-model="form.description" type="textarea" :rows="4" maxlength="2000" show-word-limit placeholder="说明设备用途或所在场景" /></el-form-item>
      <el-form-item label="状态" prop="status"><el-select v-model="form.status" style="width: 100%"><el-option label="启用" value="active" /><el-option label="停用" value="disabled" /></el-select></el-form-item>
    </el-form>
    <template #footer><el-button @click="editorOpen = false">取消</el-button><el-button type="primary" :loading="saving" :disabled="editorLoading" @click="saveRobot">保存</el-button></template>
  </el-dialog>

  <el-dialog v-model="detailOpen" title="机器人详情" width="560px" align-center destroy-on-close class="robot-detail-dialog">
    <el-alert v-if="detailError" :title="detailError" type="error" :closable="false" show-icon />
    <div v-loading="detailLoading" class="robot-detail" v-if="detail">
      <div class="robot-detail-icon"><el-avatar :size="64"><el-icon><Cpu /></el-icon></el-avatar><div><h2>{{ detail.name || "未命名机器人" }}</h2><el-tag :type="statusType(detail.status)">{{ statusLabel(detail.status) }}</el-tag></div></div>
      <el-descriptions :column="1" border>
        <el-descriptions-item label="绑定知识库">{{ detail.knowledge_base_name || "待绑定" }}</el-descriptions-item>
      <el-descriptions-item label="序列号">{{ detail.serial_no }}</el-descriptions-item>
        <el-descriptions-item label="绑定城市">{{ detail.default_location_name || detail.default_location || "未设置" }}</el-descriptions-item>
        <el-descriptions-item label="时区">{{ timezoneLabel(detail.timezone) }}</el-descriptions-item>
        <el-descriptions-item label="描述">{{ detail.description || "—" }}</el-descriptions-item>
        <el-descriptions-item label="最近请求">{{ formatTime(detail.last_request_at) }}</el-descriptions-item>
        <el-descriptions-item label="注册时间">{{ formatTime(detail.created_at) }}</el-descriptions-item>
        <el-descriptions-item label="更新时间">{{ formatTime(detail.updated_at) }}</el-descriptions-item>
      </el-descriptions>
    </div>
    <template #footer><el-button @click="detailOpen = false">关闭</el-button></template>
  </el-dialog>
</template>

<style scoped>
.robots-filters { margin-bottom: 4px; }
.robots-filters :deep(.el-form-item) { margin-bottom: 16px; }
.robots-filters :deep(.el-input) { width: 260px; }
.robots-filters :deep(.el-select) { width: 150px; }
.robots-list-heading { display: flex; align-items: center; justify-content: space-between; margin: 8px 0 14px; color: #30343b; font-weight: 600; }
.robots-list-heading .el-tag { margin-left: 6px; }
.list-error { margin-bottom: 14px; }
.robot-cell, .robot-detail-icon { display: flex; align-items: center; gap: 10px; }
.robot-cell > div { display: flex; min-width: 0; flex-direction: column; gap: 2px; }
.robot-cell strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.robot-cell span { color: #8a8f98; font-size: 12px; }
.robot-detail { min-height: 300px; }
.robot-detail-icon { margin-bottom: 24px; }
.robot-detail-icon > div { display: flex; align-items: center; gap: 10px; }
.robot-detail-icon h2 { margin: 0; font-size: 20px; }
@media (max-width: 800px) { .robots-filters :deep(.el-input), .robots-filters :deep(.el-select) { width: 100%; } }
</style>
