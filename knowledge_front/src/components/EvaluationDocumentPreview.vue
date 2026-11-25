<script setup lang="ts">
import { computed, defineAsyncComponent, onBeforeUnmount, ref, watch } from 'vue'
import { api } from '../lib/session'
import type { EvaluationDocument } from '../lib/evaluations'
import type { ExcelWorkbook } from './ExcelEditor.vue'
import WordContent from './WordContent.vue'
import MarkdownContent from './MarkdownContent.vue'

const ExcelEditor = defineAsyncComponent(() => import('./ExcelEditor.vue'))
const props = defineProps<{
  datasetId: string
  initialDocumentId?: string
  expectedDocumentIds: string[]
  expanded: boolean
}>()
const emit = defineEmits<{ select: [EvaluationDocument]; expand: [] }>()
interface Preview {
  kind: 'word' | 'excel' | 'text' | 'markdown' | 'pdf' | 'image' | 'video' | 'download'
  document: { id: string; title: string; indexed: boolean }
  version: { id: string; number: number; filename: string }
  workbook?: ExcelWorkbook
  html?: string
  content?: string
  url?: string
}
const documents = ref<EvaluationDocument[]>([]), selectedId = ref('')
const preview = ref<Preview | null>(null), loading = ref(false), searching = ref(false)
const error = ref(''), searchError = ref('')
let listController: AbortController | undefined, previewController: AbortController | undefined
let listSequence = 0, previewSequence = 0
const options = computed(() => {
  const list = [...documents.value], current = preview.value
  if (current && !list.some(d => d.id === current.document.id)) {
    list.push({ ...current.document, filename: current.version.filename })
  }
  return list
})
const added = computed(() => props.expectedDocumentIds.includes(selectedId.value))
async function search(query = '') {
  const sequence = ++listSequence
  listController?.abort(); listController = new AbortController()
  searching.value = true; searchError.value = ''
  const params = new URLSearchParams({ q: query })
  if (selectedId.value) params.append('selected', selectedId.value)
  try {
    const result = await api<{ items: EvaluationDocument[] }>(`/evaluations/datasets/${props.datasetId}/documents?${params}`, { signal: listController.signal })
    if (sequence !== listSequence) return
    documents.value = result.items
    if (!selectedId.value) selectedId.value = result.items[0]?.id || ''
  } catch (e) { if (sequence === listSequence) searchError.value = (e as Error).message }
  finally { if (sequence === listSequence) searching.value = false }
}
async function loadPreview() {
  const sequence = ++previewSequence
  previewController?.abort(); previewController = new AbortController()
  preview.value = null; error.value = ''; loading.value = !!selectedId.value
  if (!selectedId.value) return
  try {
    const result = await api<Preview>(`/evaluations/datasets/${props.datasetId}/documents/${selectedId.value}/preview`, { signal: previewController.signal, timeoutMs: 60000 })
    if (sequence === previewSequence) preview.value = result
  } catch (e) { if (sequence === previewSequence) error.value = (e as Error).message }
  finally { if (sequence === previewSequence) loading.value = false }
}
function addDocument() {
  if (preview.value?.document.indexed) emit('select', { ...preview.value.document, filename: preview.value.version.filename })
}
watch(selectedId, loadPreview)
watch(() => props.datasetId, () => {
  selectedId.value = props.initialDocumentId || ''
  documents.value = []; preview.value = null
  void search()
}, { immediate: true })
onBeforeUnmount(() => { ++listSequence; ++previewSequence; listController?.abort(); previewController?.abort() })
</script>

<template>
  <section class="source-reference" aria-label="知识库资料预览">
    <header class="source-header">
      <div><h3>资料参考</h3><p>对照本知识库原文出题，切换文档不会改动题目。</p></div>
      <el-button link type="primary" @click="emit('expand')">{{ expanded ? '返回对照' : '放大预览' }}</el-button>
    </header>
    <el-select v-model="selectedId" filterable remote :remote-method="search" :loading="searching" aria-label="预览文档" placeholder="搜索并选择要预览的文档" @visible-change="(open: boolean) => open && search()">
      <el-option v-for="doc in options" :key="doc.id" :value="doc.id" :label="`${doc.title} · ${doc.id.slice(0, 8)}`">
        {{ doc.title }} <small>{{ doc.filename }} · {{ doc.id.slice(0, 8) }}</small>
      </el-option>
    </el-select>
    <el-alert v-if="searchError" :title="searchError" type="error" :closable="false"><el-button link @click="search()">重新加载文档</el-button></el-alert>
    <div v-if="preview" class="source-actions">
      <span>{{ preview.version.filename }} · v{{ preview.version.number }}</span>
      <el-button size="small" :disabled="added || !preview.document.indexed" @click="addDocument">{{ added ? '已加入预期文档' : '加入预期文档' }}</el-button>
    </div>
    <p v-if="preview && !preview.document.indexed" class="source-note">此文档尚未完成索引，可先阅读，索引完成后才能选为预期文档。</p>
    <div v-loading="loading" class="source-content">
      <el-alert v-if="error" :title="error" type="error" :closable="false"><el-button link @click="loadPreview">重试预览</el-button></el-alert>
      <template v-else-if="preview">
        <WordContent v-if="preview.kind === 'word'" :html="preview.html || ''" class="source-paper" />
        <ExcelEditor v-else-if="preview.kind === 'excel' && preview.workbook" :key="preview.version.id" :workbook="preview.workbook" :title="preview.document.title" readonly compact />
        <MarkdownContent v-else-if="preview.kind === 'markdown'" :content="preview.content || ''" class="source-paper" />
        <pre v-else-if="preview.kind === 'text'" class="source-paper plain-text">{{ preview.content }}</pre>
        <iframe v-else-if="preview.kind === 'pdf'" :src="preview.url" title="资料 PDF 预览" class="source-frame" />
        <img v-else-if="preview.kind === 'image'" :src="preview.url" :alt="preview.document.title" class="source-image" />
        <video v-else-if="preview.kind === 'video'" :src="preview.url" controls class="source-video" />
        <el-empty v-else description="此格式暂不支持在线预览"><a :href="preview.url" target="_blank" rel="noopener noreferrer">下载原文件查看</a></el-empty>
      </template>
      <el-empty v-else-if="!loading" :description="searching ? '正在加载文档…' : '选择本知识库的文档开始阅读'" :image-size="70" />
    </div>
  </section>
</template>

<style scoped>
.source-reference{height:100%;min-height:0;min-width:0;display:flex;flex-direction:column;gap:12px;padding:0 0 0 22px;border-left:1px solid #e6ebf1;box-sizing:border-box}.source-header{display:flex;justify-content:space-between;align-items:flex-start;gap:12px}.source-header h3{font-size:16px;margin:0 0 6px}.source-header p,.source-note{font-size:12px;line-height:1.7;color:#8793a4;margin:0}.source-reference small{font-size:11px;color:#8d98a8;margin-left:10px}.source-actions{display:flex;align-items:center;justify-content:space-between;gap:12px}.source-actions span{font-size:12px;color:#8793a4;overflow-wrap:anywhere}.source-content{min-height:0;flex:1;overflow:auto;border:1px solid #e4eaf2;border-radius:10px;background:#fff;position:relative}.source-paper{padding:20px;box-sizing:border-box;min-width:0}.plain-text{margin:0;white-space:pre-wrap;overflow-wrap:anywhere;font:inherit;font-size:14px;line-height:1.8}.source-frame{width:100%;height:100%;min-height:400px;border:0}.source-image,.source-video{display:block;max-width:100%;margin:auto}.source-content :deep(.excel-editor){height:100%;min-height:340px}.source-content>.el-alert{margin:12px;width:auto}.source-note{color:#b57624}@media(max-width:1023px){.source-reference{border-left:0;padding:0}.source-actions{flex-wrap:wrap}}
</style>
