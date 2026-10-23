<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { Search, Refresh, Plus, FolderOpened } from '@element-plus/icons-vue'
import { api } from '../lib/session'
import { resources } from '../lib/resources'
const route = useRoute(), config = computed(() => resources[route.path]!)
const rows = ref<Record<string, unknown>[]>([]), total = ref(0), page = ref(1), query = ref(''), status = ref(''), loading = ref(false), error = ref('')
let generation = 0
async function load() {
  const current = ++generation, path = route.path
  loading.value = true; error.value = ''
  try {
    const params = new URLSearchParams({ page: String(page.value), page_size: '20', q: query.value, status: status.value })
    const result = await api<{ items: Record<string, unknown>[]; total?: number }>(`${path}?${params}`)
    if (current !== generation) return
    let items = result.items
    if (path === '/knowledge-bases') items = items.filter(item => `${item.name} ${item.code}`.includes(query.value) && (!status.value || item.status === status.value))
    rows.value = items; total.value = result.total ?? items.length
  } catch (e) { if (current === generation) error.value = (e as Error).message } finally { if (current === generation) loading.value = false }
}
function search() { page.value = 1; void load() }
function format(value: unknown, prop: string) {
  if (typeof value === 'boolean') return value ? '是' : '否'
  if (typeof value === 'string' && prop.endsWith('_at')) return new Date(value).toLocaleString('zh-CN', { hour12: false })
  return value ?? '—'
}
watch(() => route.path, () => { query.value = ''; status.value = ''; page.value = 1; rows.value = []; void load() }, { immediate: true })
</script>
<template>
  <div class="page-heading"><div><div class="page-eyebrow">{{ config.english }}</div><h1>{{ config.title }}</h1><p>{{ config.description }}</p></div><el-tooltip v-if="config.action" content="页面框架已就绪，编辑功能将在后续开发中接入"><span><el-button type="primary" :icon="Plus" disabled>{{ config.action }}</el-button></span></el-tooltip></div>
  <el-alert class="phase-notice" title="当前支持查看与搜索，新增、编辑等功能将逐步开放。" type="info" show-icon :closable="false" />
  <el-card shadow="never" class="resource-card"><div class="table-toolbar"><el-input v-model="query" :placeholder="config.search" :prefix-icon="Search" clearable @keyup.enter="search" @clear="search" /><el-select v-if="config.status" v-model="status" placeholder="全部状态" clearable @change="search"><el-option label="启用" value="active" /><el-option label="停用" value="disabled" /></el-select><el-button type="primary" plain @click="search">搜索</el-button><el-button :icon="Refresh" :loading="loading" @click="load">刷新</el-button></div>
    <el-alert v-if="error" :title="error" type="error" show-icon :closable="false" />
    <el-table v-loading="loading" :data="rows" style="width: 100%" :min-height="340"><el-table-column v-for="column in config.columns" :key="column.prop" :prop="column.prop" :label="column.label" :width="column.width" :min-width="column.width || 150" show-overflow-tooltip><template #default="{ row }"><el-tag v-if="column.prop === 'status'" :type="['active', 'SUCCESS', 'INDEXED'].includes(row.status) ? 'success' : 'info'" effect="light">{{ ({ active: '启用', disabled: '停用', archived: '已归档', PROCESSING: '处理中', SUCCESS: '成功', NO_EVIDENCE: '依据不足', FAILED: '失败' } as Record<string, string>)[row.status] || row.status }}</el-tag><span v-else>{{ format(row[column.prop], column.prop) }}</span></template></el-table-column><template #empty><el-empty :description="error ? '暂时无法加载数据，请点击刷新重试' : query || status ? '没有找到匹配的记录' : '暂无记录，期待第一份内容'" :image-size="80"><template #image><el-icon :size="70" color="#c6c8ce"><FolderOpened /></el-icon></template></el-empty></template></el-table>
    <div class="table-pagination"><span>共 {{ total }} 条记录</span><el-pagination v-model:current-page="page" :page-size="20" :total="total" layout="prev, pager, next" @current-change="load" /></div>
  </el-card>
</template>
