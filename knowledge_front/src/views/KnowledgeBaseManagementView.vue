<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'
import { Collection, Delete, Edit, Plus, Refresh, Search } from '@element-plus/icons-vue'
import { api, session } from '../lib/session'
import { queryParams } from '../lib/query'

type KnowledgeBaseStatus = 'active' | 'disabled' | 'archived'
interface KnowledgeBase {
  id: string
  code: string
  name: string
  description: string | null
  status: KnowledgeBaseStatus
  created_by: string | null
  created_by_name: string
  updated_by_name: string
  created_at: string
  updated_at: string
}
interface KnowledgeBasePage { items: KnowledgeBase[]; total: number }

const router = useRouter()
const canManageDocuments = computed(() => session.pages.some(page => page.route_path === '/documents' && router.hasRoute(`page:${page.code}`)))
const rows = ref<KnowledgeBase[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const filters = reactive({ q: '', status: '' })
const appliedFilters = reactive({ q: '', status: '' })
const loading = ref(false)
const listError = ref('')
const actionId = ref('')
let listRequest = 0

const editorOpen = ref(false)
const editorLoading = ref(false)
const saving = ref(false)
const editorError = ref('')
const editing = ref<KnowledgeBase | null>(null)
const formRef = ref<FormInstance>()
const form = reactive({ code: '', name: '', description: '', status: 'active' as KnowledgeBaseStatus })
let editorRequest = 0

const rules: FormRules = {
  code: [
    { required: true, whitespace: true, message: '请输入知识库编码', trigger: 'blur' },
    { max: 100, message: '编码不能超过 100 个字符', trigger: 'blur' },
    { pattern: /^[a-z][a-z0-9_-]*$/u, message: '编码只能使用小写字母、数字、下划线或连字符，且以字母开头', trigger: 'blur' },
  ],
  name: [
    { required: true, whitespace: true, message: '请输入知识库名称', trigger: 'blur' },
    { max: 200, message: '名称不能超过 200 个字符', trigger: 'blur' },
  ],
  description: [{ max: 2000, message: '描述不能超过 2000 个字符', trigger: 'blur' }],
  status: [{ required: true, message: '请选择知识库状态', trigger: 'change' }],
}

function errorText(error: unknown) { return error instanceof Error ? error.message : '操作失败，请稍后重试' }
function formatTime(value: string) { return new Date(value).toLocaleString('zh-CN', { hour12: false }) }
function statusLabel(status: KnowledgeBaseStatus) { return ({ active: '启用', disabled: '停用', archived: '已归档' })[status] }
function statusType(status: KnowledgeBaseStatus) { return status === 'active' ? 'success' : status === 'disabled' ? 'warning' : 'info' }

async function loadBases() {
  const current = ++listRequest
  loading.value = true
  listError.value = ''
  try {
    const params = queryParams({ ...appliedFilters, page: String(page.value), page_size: String(pageSize.value) })
    const result = await api<KnowledgeBasePage>(`/knowledge-bases?${params}`)
    if (current !== listRequest) return
    const lastPage = Math.max(1, Math.ceil(result.total / pageSize.value))
    if (page.value > lastPage) { page.value = lastPage; await loadBases(); return }
    rows.value = result.items
    total.value = result.total
  } catch (error) {
    if (current === listRequest) { listError.value = errorText(error); rows.value = []; total.value = 0 }
  } finally {
    if (current === listRequest) loading.value = false
  }
}

function search() { appliedFilters.q = filters.q.trim(); appliedFilters.status = filters.status; page.value = 1; void loadBases() }
function resetFilters() { filters.q = ''; filters.status = ''; search() }
function resizePage() { page.value = 1; void loadBases() }

async function openEditor(base?: KnowledgeBase) {
  const current = ++editorRequest
  editing.value = base || null
  Object.assign(form, { code: '', name: '', description: '', status: 'active' as KnowledgeBaseStatus })
  editorError.value = ''
  editorLoading.value = true
  editorOpen.value = true
  await nextTick()
  formRef.value?.clearValidate()
  try {
    const fresh = base ? await api<KnowledgeBase>(`/knowledge-bases/${base.id}`) : null
    if (current !== editorRequest || !editorOpen.value) return
    editing.value = fresh
    if (fresh) Object.assign(form, { code: fresh.code, name: fresh.name, description: fresh.description || '', status: fresh.status })
  } catch (error) {
    if (current === editorRequest) editorError.value = errorText(error)
  } finally {
    if (current === editorRequest) editorLoading.value = false
  }
}

async function saveBase() {
  if (saving.value || editorLoading.value || !formRef.value) return
  saving.value = true
  try {
    if (!(await formRef.value.validate().catch(() => false))) return
    const body = { code: form.code.trim().toLowerCase(), name: form.name.trim(), description: form.description.trim() || null, status: form.status }
    if (editing.value) {
      await api<KnowledgeBase>(`/knowledge-bases/${editing.value.id}`, { method: 'PUT', body: JSON.stringify(body) })
      ElMessage.success('知识库信息已更新')
    } else {
      await api<KnowledgeBase>('/knowledge-bases', { method: 'POST', body: JSON.stringify(body) })
      ElMessage.success(canManageDocuments.value ? '知识库已创建，现在可以上传文档' : '知识库已创建')
    }
    editorOpen.value = false
    await loadBases()
  } catch (error) { ElMessage.error(errorText(error)) } finally { saving.value = false }
}

async function archive(base: KnowledgeBase) {
  if (actionId.value) return
  actionId.value = base.id
  try {
    try {
      await ElMessageBox.confirm(`归档“${base.name}”后将不能上传、编辑或检索其中的文档，历史数据会保留。`, '确认归档知识库', { type: 'warning', confirmButtonText: '确认归档', cancelButtonText: '取消', confirmButtonClass: 'el-button--danger' })
    } catch { return }
    await api(`/knowledge-bases/${base.id}`, { method: 'DELETE' })
    ElMessage.success('知识库已归档')
    await loadBases()
  } catch (error) { ElMessage.error(errorText(error)) } finally { actionId.value = '' }
}

function openDocuments(base: KnowledgeBase) { void router.push({ path: '/documents', query: { knowledge_base_id: base.id } }) }
watch(editorOpen, open => { if (!open) ++editorRequest })
onMounted(loadBases)
onBeforeUnmount(() => { ++listRequest; ++editorRequest })
</script>

<template>
  <div class="page-heading">
    <div><div class="page-eyebrow">KNOWLEDGE BASES</div><h1>知识库管理</h1><p>创建知识库并管理其状态，文档始终归属于明确的知识库。</p></div>
    <el-button type="primary" :icon="Plus" :disabled="!!actionId" @click="openEditor()">新建知识库</el-button>
  </div>
  <el-alert class="phase-notice" title="停用或归档知识库后将禁止上传和管理文档；归档操作会保留历史文档与审计记录。" type="info" show-icon :closable="false" />
  <el-card shadow="never" class="resource-card knowledge-bases-card">
    <el-form class="knowledge-bases-filters" :inline="true" @submit.prevent="search">
      <el-form-item label="名称或编码"><el-input v-model="filters.q" placeholder="输入名称或编码" :prefix-icon="Search" maxlength="200" clearable @clear="search" /></el-form-item>
      <el-form-item label="状态"><el-select v-model="filters.status" placeholder="全部状态" clearable value-on-clear="" @change="search"><el-option label="启用" value="active" /><el-option label="停用" value="disabled" /><el-option label="已归档" value="archived" /></el-select></el-form-item>
      <el-form-item><el-button type="primary" :icon="Search" native-type="submit">查询</el-button><el-button @click="resetFilters">重置</el-button></el-form-item>
    </el-form>
    <div class="list-heading"><span>知识库列表 <el-tag type="info" effect="plain" size="small">{{ total }}</el-tag></span><el-button :icon="Refresh" :loading="loading" text @click="loadBases">刷新</el-button></div>
    <el-alert v-if="listError" :title="listError" type="error" show-icon :closable="false" class="list-error" />
    <el-table v-loading="loading" :data="rows" row-key="id" style="width: 100%">
      <el-table-column label="知识库" min-width="220"><template #default="{ row }"><div class="base-cell"><el-avatar :size="34"><el-icon><Collection /></el-icon></el-avatar><div><strong>{{ row.name }}</strong><span>{{ row.code }}</span></div></div></template></el-table-column>
      <el-table-column prop="description" label="描述" min-width="240" show-overflow-tooltip />
      <el-table-column label="状态" width="110"><template #default="{ row }"><el-tag :type="statusType(row.status)" effect="light">{{ statusLabel(row.status) }}</el-tag></template></el-table-column>
      <el-table-column label="创建人" min-width="130" show-overflow-tooltip><template #default="{ row }">{{ row.created_by_name || '—' }}</template></el-table-column>
      <el-table-column label="最后修改人" min-width="130" show-overflow-tooltip><template #default="{ row }">{{ row.updated_by_name || '—' }}</template></el-table-column>
      <el-table-column label="更新时间" width="180"><template #default="{ row }">{{ formatTime(row.updated_at) }}</template></el-table-column>
      <el-table-column label="操作" fixed="right" width="300"><template #default="{ row }"><el-button v-if="row.status === 'active' && canManageDocuments" link type="primary" @click="openDocuments(row)">管理文档</el-button><el-button link type="primary" :icon="Edit" :disabled="!!actionId" @click="openEditor(row)">编辑</el-button><el-button v-if="row.status !== 'archived'" link type="danger" :icon="Delete" :disabled="!!actionId" @click="archive(row)">归档</el-button></template></el-table-column>
      <template #empty><el-empty :description="filters.q || filters.status ? '没有找到匹配的知识库' : '暂无知识库，请先创建一个'" :image-size="80" /></template>
    </el-table>
    <div class="table-pagination"><span>共 {{ total }} 条记录</span><el-pagination v-model:current-page="page" v-model:page-size="pageSize" :page-sizes="[20, 50, 100]" :total="total" layout="sizes, prev, pager, next" @current-change="loadBases" @size-change="resizePage" /></div>
  </el-card>

  <el-dialog v-model="editorOpen" :title="editing ? '编辑知识库' : '新建知识库'" width="560px" align-center destroy-on-close>
    <el-alert v-if="editorError" :title="editorError" type="error" :closable="false" show-icon />
    <el-form ref="formRef" v-loading="editorLoading" :model="form" :rules="rules" label-position="top" @submit.prevent="saveBase">
      <el-form-item label="知识库名称" prop="name"><el-input v-model="form.name" maxlength="200" placeholder="例如：产品使用手册" /></el-form-item>
      <el-form-item label="唯一编码" prop="code"><el-input v-model="form.code" maxlength="100" placeholder="例如：product_manual" /><div class="form-tip">用于机器人和接口选择知识库，只能使用小写字母、数字、下划线或连字符。</div></el-form-item>
      <el-form-item label="描述" prop="description"><el-input v-model="form.description" type="textarea" :rows="4" maxlength="2000" show-word-limit placeholder="说明知识库的内容范围和用途" /></el-form-item>
      <el-form-item label="状态" prop="status"><el-select v-model="form.status" style="width: 100%"><el-option label="启用" value="active" /><el-option label="停用" value="disabled" /><el-option label="已归档" value="archived" /></el-select></el-form-item>
    </el-form>
    <template #footer><el-button @click="editorOpen = false">取消</el-button><el-button type="primary" :loading="saving" :disabled="editorLoading" @click="saveBase">保存</el-button></template>
  </el-dialog>
</template>

<style scoped>
.knowledge-bases-filters { margin-bottom: 4px; }
.knowledge-bases-filters :deep(.el-form-item) { margin-bottom: 16px; }
.knowledge-bases-filters :deep(.el-input) { width: 260px; }
.knowledge-bases-filters :deep(.el-select) { width: 150px; }
.list-heading { display: flex; align-items: center; justify-content: space-between; margin: 8px 0 14px; color: #30343b; font-weight: 600; }
.list-heading .el-tag { margin-left: 6px; }
.list-error { margin-bottom: 14px; }
.base-cell { display: flex; align-items: center; gap: 10px; }
.base-cell > div { display: flex; min-width: 0; flex-direction: column; gap: 2px; }
.base-cell strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.base-cell span { color: #8a8f98; font-size: 12px; }
.form-tip { margin-top: 5px; color: #8a8f98; font-size: 12px; line-height: 1.5; }
@media (max-width: 800px) { .knowledge-bases-filters :deep(.el-input), .knowledge-bases-filters :deep(.el-select) { width: 100%; } }
</style>
