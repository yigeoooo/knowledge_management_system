<script setup lang="ts">
import { nextTick, onMounted, onUnmounted, ref, shallowRef, watch } from 'vue'
import type { Editor, JSONContent } from '@tiptap/core'
import { UmoEditor } from '@umoteam/editor'
import { wordPagination } from '../lib/word/pagination'
import WordParagraphDialog from './WordParagraphDialog.vue'
import { WordParagraph, paragraphKeyDown, clearParagraphIndent, pixelsPerCm } from '../lib/word/paragraph'

interface PageSettings {
  size: { width: number; height: number; label?: string }
  margin: { left: number; right: number; top: number; bottom: number }
  orientation: string
  layout?: string
  zoomLevel?: number
  autoWidth?: boolean
}
interface UmoInstance {
  useEditor(): Editor | null
  getPage(): PageSettings
  toggleFullscreen(value?: boolean): void
  setReadOnly(value: boolean): void
  setDocument(value: { title: string }): void
}
const props = defineProps<{
  content: JSONContent
  title: string
  disabled: boolean
  saveDocument: () => Promise<boolean>
}>()
const emit = defineEmits<{ change: [content: JSONContent, text: string] }>()
const instance = ref<UmoInstance | null>(null)
const host = ref<HTMLElement | null>(null)
const activeEditor = shallowRef<Editor | null>(null)
const paragraphDialog = ref<{ open(): void } | null>(null)
const contextMenu = ref<{ x: number; y: number } | null>(null)
const pageCount = ref(1)
const isFullscreen = ref(false)
let containerObserver: MutationObserver | undefined
let pageBreakKeyHandler: ((event: KeyboardEvent) => void) | undefined
let editorDom: HTMLElement | undefined
let pageObserver: MutationObserver | undefined
let resizeObserver: ResizeObserver | undefined
// Umo persists internal state in localStorage. Give each mount a private key;
// the page's per-user sessionStorage draft remains the source of truth.
const editorKey = `kbs-${Array.from(crypto.getRandomValues(new Uint32Array(4))).join('-')}`
const initialPage = props.content.attrs?.page as PageSettings | undefined
const defaultPage = initialPage || { size: { width: 21, height: 29.7 }, margin: { left: 3.18, right: 3.18, top: 2.54, bottom: 2.54 }, orientation: 'portrait' }
function paginationSize(page: PageSettings) {
  return { width: (page.orientation === 'landscape' ? page.size.height : page.size.width) * pixelsPerCm,
    height: (page.orientation === 'landscape' ? page.size.width : page.size.height) * pixelsPerCm,
    left: page.margin.left * pixelsPerCm, right: page.margin.right * pixelsPerCm,
    top: page.margin.top * pixelsPerCm, bottom: page.margin.bottom * pixelsPerCm, enabled: page.layout !== 'web' }
}
const options = {
  editorKey,
  locale: 'zh-CN',
  theme: 'light',
  height: 'max(760px, calc(100dvh - 180px))',
  fullscreenZIndex: 2100,
  toolbar: { defaultMode: 'ribbon', menus: ['base', 'insert', 'table', 'page', 'view'] },
  extensions: [WordParagraph, wordPagination(() => paginationSize(instance.value?.getPage() || defaultPage))],
  document: {
    title: props.title,
    content: props.content,
    readOnly: props.disabled,
    characterLimit: 200000,
    autoSave: { enabled: false },
    enableBlockMenu: false,
    enableMarkdown: false,
    editorProps: { attributes: { class: 'umo-editor', role: 'textbox', 'aria-label': 'Word 文档正文', 'aria-multiline': 'true' }, handleKeyDown: paragraphKeyDown },
  },
  page: {
    layouts: ['page', 'web'],
    showBreakMarks: false,
    ...(initialPage ? { defaultMargin: initialPage.margin, defaultOrientation: initialPage.orientation } : {}),
  },
  dicts: {
    fonts: [
      { label: { zh_CN: '默认字体', en_US: 'Default' }, value: null },
      ...[['宋体', 'SimSun'], ['黑体', 'SimHei'], ['楷体', 'KaiTi'], ['仿宋', 'FangSong'],
        ['微软雅黑', 'Microsoft YaHei'], ['Arial', 'Arial'], ['Times New Roman', 'Times New Roman'],
        ['Consolas', 'Consolas']].map(([name, value]) => ({ label: { zh_CN: name, en_US: name }, value })),
    ],
    ...(initialPage ? { pageSizes: [
      { label: initialPage.size.label || '草稿页面', width: initialPage.size.width, height: initialPage.size.height, default: true },
      { label: 'A4', width: 21, height: 29.7 }, { label: 'A3', width: 29.7, height: 42 },
      { label: 'A5', width: 14.8, height: 21 },
    ] } : {}),
  },
  // Only expose formats that the local DOCX writer can faithfully save.
  // No document content or editor resources are sent to a third-party service.
  disableExtensions: ['image', 'inlineImage', 'video', 'audio', 'file', 'text-box', 'textBox',
    'details', 'tag', 'columns', 'callout', 'mention', 'option-box', 'optionBox', 'bookmark',
    'footnote', 'toc', 'template', 'web-page', 'iframe', 'math', 'mermaid', 'echarts',
    'watermark', 'background', 'reset', 'locale', 'theme', 'skin'],
  translations: { zh_CN: { save: {
    text: '保存到知识库', saved: '已保存到知识库', unsaved: '未保存到知识库',
    saving: '正在保存到知识库…', success: '已保存到知识库', savedAt: '知识库保存时间：',
  } } },
  async onSave() {
    const success = await props.saveDocument()
    instance.value?.toggleFullscreen(false)
    return { status: success ? 'success' : 'error', showMessage: false }
  },
}
function changed() {
  const editor = instance.value?.useEditor()
  if (!editor) return
  const content = editor.getJSON()
  const page = instance.value!.getPage()
  content.attrs = { ...content.attrs, page: { size: page.size, margin: page.margin, orientation: page.orientation } }
  emit('change', content, editor.getText())
}
function fitPage() {
  const page = instance.value?.getPage()
  const viewport = host.value?.querySelector('.umo-zoomable-container')
  if (!page?.autoWidth || page.layout === 'web' || !viewport) return
  const width = page.orientation === 'landscape' ? page.size.height : page.size.width
  page.zoomLevel = Math.max(25, Math.min(180, Math.floor((viewport.clientWidth - 48) / (width * 96 / 2.54) * 100)))
}
async function created() {
  await nextTick()
  const page = instance.value?.getPage()
  activeEditor.value = instance.value?.useEditor() || null
  if (activeEditor.value) {
    const view = activeEditor.value.view as typeof activeEditor.value.view & { __umoPageBreak?: () => boolean }
    view.__umoPageBreak = () => {
      const editor = activeEditor.value
      const node = editor?.schema.nodes.pageBreak?.create()
      if (!editor || !node) return false
      editor.view.dispatch(editor.state.tr.replaceSelectionWith(node).scrollIntoView())
      return true
    }
  }
  if (page) page.autoWidth = true
  const container = host.value?.querySelector('.umo-editor-container')
  editorDom = activeEditor.value?.view.dom
  if (editorDom) {
    pageBreakKeyHandler = (event) => {
      if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') {
        event.preventDefault()
        const editor = activeEditor.value
        if (editor) {
          const node = editor.schema.nodes.pageBreak?.create()
          if (node) editor.view.dispatch(editor.state.tr.replaceSelectionWith(node).scrollIntoView())
        }
      }
    }
    editorDom.addEventListener('keydown', pageBreakKeyHandler)
  }
  if (container) {
    containerObserver = new MutationObserver(() => { isFullscreen.value = container.classList.contains('umo-editor-is-fullscreen') })
    containerObserver.observe(container, { attributes: true, attributeFilter: ['class'] })
  }
  const paper = host.value?.querySelector('.umo-page-content')
  if (paper) {
    const countPages = () => {
      pageCount.value = Number(paper.getAttribute('data-page-count') || 1)
    }
    pageObserver = new MutationObserver(countPages)
    pageObserver.observe(paper, { attributes: true, attributeFilter: ['data-page-count'] })
    countPages()
  }
  watch(() => [page?.size, page?.margin, page?.orientation, page?.layout], () => {
    if (!page || !activeEditor.value) return
    const editor = activeEditor.value
    editor.view.dispatch(editor.state.tr.setMeta('wordLayout', true))
    fitPage()
  }, { deep: true })
  fitPage()
  const viewport = host.value?.querySelector('.umo-zoomable-container')
  if (viewport) {
    resizeObserver = new ResizeObserver(fitPage)
    resizeObserver.observe(viewport)
  }
  changed()
}
function openParagraph() { contextMenu.value = null; paragraphDialog.value?.open() }
function clearIndent() { contextMenu.value = null; if (activeEditor.value) clearParagraphIndent(activeEditor.value) }
function showContextMenu(event: MouseEvent) {
  const editor = activeEditor.value
  if (!editor?.isEditable || !(event.target instanceof Element) || !event.target.closest('.umo-editor')) return
  event.preventDefault()
  if (editor.state.selection.empty) {
    const point = editor.view.posAtCoords({ left: event.clientX, top: event.clientY })
    if (point) editor.commands.setTextSelection(point.pos)
  }
  contextMenu.value = { x: Math.min(event.clientX, window.innerWidth - 180), y: Math.min(event.clientY, window.innerHeight - 150) }
}
function fullscreen() { instance.value?.toggleFullscreen(true) }
function exitFullscreen() { instance.value?.toggleFullscreen(false) }
function escapeFullscreen(event: KeyboardEvent) {
  if (event.key === 'Escape' && isFullscreen.value && !document.querySelector('.el-overlay-dialog')) exitFullscreen()
}
function reset(content: JSONContent) {
  instance.value?.useEditor()?.commands.setContent(content)
}
watch(() => props.disabled, value => instance.value?.setReadOnly(value))
watch(() => props.title, title => instance.value?.setDocument({ title }))
function clearInternalDraft() {
  try {
    for (const key of Object.keys(localStorage)) {
      if (key.startsWith(`umo-editor:${editorKey}:`)) localStorage.removeItem(key)
    }
  } catch { /* The host page reports draft storage failures. */ }
}
onMounted(() => { window.addEventListener('pagehide', clearInternalDraft); window.addEventListener('keydown', escapeFullscreen) })
onUnmounted(() => { resizeObserver?.disconnect(); pageObserver?.disconnect(); containerObserver?.disconnect(); if (editorDom && pageBreakKeyHandler) editorDom.removeEventListener('keydown', pageBreakKeyHandler); window.removeEventListener('keydown', escapeFullscreen); window.removeEventListener('pagehide', clearInternalDraft); clearInternalDraft() })
defineExpose({ reset, fullscreen })
</script>

<template>
  <div ref="host" class="word-editor-host" @contextmenu="showContextMenu" @pointerdown="contextMenu = null" @keydown.esc="contextMenu = null">
    <UmoEditor ref="instance" v-bind="options" @created="created" @changed="changed"
      @changed:pageSize="changed" @changed:pageMargin="changed" @changed:pageOrientation="changed">
      <template #toolbar_base>
        <div class="paragraph-actions"><button type="button" :disabled="disabled" @mousedown.prevent @click="openParagraph">段落设置</button><button type="button" :disabled="disabled" @mousedown.prevent @click="clearIndent">清除缩进</button></div>
      </template>
    </UmoEditor>
    <Teleport to="body"><button v-if="isFullscreen" class="word-exit-fullscreen" type="button" @click="exitFullscreen">退出全屏 · Esc</button></Teleport>
    <WordParagraphDialog ref="paragraphDialog" :editor="activeEditor" />
    <Teleport to="body"><div v-if="contextMenu" class="word-context-menu" role="menu" :style="{ left: `${contextMenu.x}px`, top: `${contextMenu.y}px` }" @mousedown.prevent>
      <button role="menuitem" @click="openParagraph">段落设置…</button><button role="menuitem" @click="clearIndent">清除缩进 / 退出列表</button>
      <button role="menuitem" @click="activeEditor?.chain().focus().selectAll().run(); contextMenu = null">全选</button>
    </div></Teleport>
    <div class="word-pagination-note">自动分页 · 共 {{ pageCount }} 页</div>
  </div>
</template>

<style scoped>
.word-editor-host { min-width: 0; width: 100%; --umo-primary-color: #ef8c00; }
.word-editor-host :deep(.umo-editor-container) { border: none; border-radius: 0; }
.word-editor-host :deep(.umo-editor-is-fullscreen) { height: 100dvh !important; }
.word-editor-host :deep(.umo-editor) { font-family: SimSun, serif; font-size: 10.5pt; }
@media (max-width: 600px) {
  .word-editor-host :deep(.umo-editor-container:not(.umo-editor-is-fullscreen)) { height: 650px !important; }
}
.paragraph-actions { display: grid; grid-template-rows: 24px 24px; gap: 4px; height: 52px; width: 84px; flex-shrink: 0; }
.paragraph-actions button { border: 1px solid #e4e7ec; background: white; border-radius: 3px; padding: 0 8px; color: #444; font: 12px/22px sans-serif; white-space: nowrap; height: 24px; }
.word-pagination-note { font-size: 12px; padding: 6px 16px; color: #777f8b; text-align: right; border-top: 1px solid #edf0f3; }
/* The pagination extension supplies every sheet's margins. Umo's single-sheet
   header/footer would otherwise add a second set of margins. */
.word-editor-host :deep(.umo-page-node-header), .word-editor-host :deep(.umo-page-node-footer) { display: none; }
.word-editor-host :deep(.umo-editor) { float: none; display: flow-root; position: relative; }
.word-editor-host :deep(.word-pagination-floats) { display: contents; }
.word-editor-host :deep(.word-page-spacer) { float: left; clear: both; width: 0; height: 0; }
.word-editor-host :deep(.word-page-gap) { float: left; clear: both; position: relative; z-index: 2; width: calc(100% + var(--word-page-left) + var(--word-page-right)); margin-left: calc(-1 * var(--word-page-left)); pointer-events: none; }
.word-editor-host :deep(.umo-editor > .word-pagination-floats + *) { margin-top: 0; }
.word-editor-host :deep(.umo-editor.word-paginated > .umo-page-break) { margin: 0 !important; background: transparent; }
.word-editor-host :deep(.umo-editor.word-paginated > .umo-page-break + *) { margin-top: 0; }
.word-editor-host :deep(.umo-page-break::after) { top: 12px; transform: translateX(-50%); }
</style>
<style>
.word-exit-fullscreen { position: fixed; right: 20px; bottom: 42px; z-index: 2200; border: 1px solid #ef8c00; background: #fff; border-radius: 5px; padding: 9px 14px; font: 13px/20px sans-serif; box-shadow: 0 2px 10px #0002; }
.word-context-menu { position: fixed; z-index: 2500; display: grid; min-width: 180px; background: white; padding: 6px; border: 1px solid #e4e7ec; border-radius: 6px; box-shadow: 0 6px 24px #0002; }
.word-context-menu button { border: 0; background: white; text-align: left; padding: 8px; border-radius: 3px; font-size: 13px; }
.word-context-menu button:hover { background: #fff5e8; }
</style>
