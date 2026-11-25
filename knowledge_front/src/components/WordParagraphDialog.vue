<script setup lang="ts">
import { reactive, ref } from 'vue'
import type { Editor } from '@tiptap/core'
import { indentCharacters } from '../lib/word/paragraph'

const props = defineProps<{ editor: Editor | null }>()
const visible = ref(false)
const values = reactive({ textAlign: 'left', firstLine: 0, paragraphLeft: 0, paragraphRight: 0, lineHeight: 1.75, before: 0, after: 0 })
function open() {
  const editor = props.editor
  if (!editor) return
  const attrs = editor.getAttributes(editor.isActive('heading') ? 'heading' : 'paragraph')
  Object.assign(values, { textAlign: attrs.textAlign || 'left', firstLine: indentCharacters(attrs), paragraphLeft: attrs.paragraphLeft || 0,
    paragraphRight: attrs.paragraphRight || 0, lineHeight: Number(attrs.lineHeight || 1.75),
    before: parseFloat(attrs.margin?.top || '0') * 0.75, after: parseFloat(attrs.margin?.bottom || '0') * 0.75 })
  visible.value = true
}
function apply() {
  const attrs = { textAlign: values.textAlign, indent: values.firstLine / 2, indentUnit: 'em', paragraphLeft: values.paragraphLeft,
    paragraphRight: values.paragraphRight, lineHeight: values.lineHeight, lineSpacingPt: null, margin: { top: String(values.before / 0.75), bottom: String(values.after / 0.75) } }
  props.editor?.chain().focus().updateAttributes('paragraph', attrs).updateAttributes('heading', attrs).run()
  visible.value = false
}
defineExpose({ open })
</script>
<template>
  <el-dialog v-model="visible" title="段落设置" width="480px" append-to-body :z-index="2400" :close-on-click-modal="false">
    <el-form label-width="130px" @submit.prevent="apply">
      <el-form-item label="对齐方式"><el-select v-model="values.textAlign" aria-label="段落对齐方式"><el-option v-for="[value, label] in [['left', '左对齐'], ['center', '居中'], ['right', '右对齐'], ['justify', '两端对齐']]" :key="value" :label="label" :value="value" /></el-select></el-form-item>
      <el-form-item label="首行缩进（字符）"><el-input-number v-model="values.firstLine" aria-label="首行缩进（字符）" :min="0" :max="8" :step="0.5" /></el-form-item>
      <el-form-item label="左侧缩进（厘米）"><el-input-number v-model="values.paragraphLeft" aria-label="左侧缩进（厘米）" :min="0" :max="5" :step="0.1" /></el-form-item>
      <el-form-item label="右侧缩进（厘米）"><el-input-number v-model="values.paragraphRight" aria-label="右侧缩进（厘米）" :min="0" :max="5" :step="0.1" /></el-form-item>
      <el-form-item label="行距（倍）"><el-input-number v-model="values.lineHeight" aria-label="行距（倍）" :min="1" :max="5" :step="0.25" /></el-form-item>
      <el-form-item label="段前间距（磅）"><el-input-number v-model="values.before" aria-label="段前间距（磅）" :min="0" :max="100" /></el-form-item>
      <el-form-item label="段后间距（磅）"><el-input-number v-model="values.after" aria-label="段后间距（磅）" :min="0" :max="100" /></el-form-item>
    </el-form>
    <p class="paragraph-help">首行缩进设为 0 可与正文左边界对齐；设置后对当前段落或选中的多个段落生效。回车会沿用正文段落设置。</p>
    <template #footer><el-button @click="visible = false">取消</el-button><el-button type="primary" @click="apply">应用段落设置</el-button></template>
  </el-dialog>
</template>
<style scoped>.paragraph-help { color: #777f8b; font-size: 13px; line-height: 1.8; }</style>
