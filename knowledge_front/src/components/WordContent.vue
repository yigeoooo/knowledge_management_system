<script setup lang="ts">
import { computed } from 'vue'
import DOMPurify from 'dompurify'

const props = defineProps<{ html: string }>()
const safeHtml = computed(() => {
  const fragment = DOMPurify.sanitize(props.html, {
    RETURN_DOM_FRAGMENT: true,
    ALLOWED_TAGS: ['div', 'p', 'span', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'ol', 'ul', 'li',
      'table', 'tbody', 'thead', 'tr', 'td', 'th', 'b', 'strong', 'em', 'i', 'u', 's', 'sub', 'sup', 'br', 'hr', 'a'],
    ALLOWED_ATTR: ['style', 'href', 'colspan', 'rowspan', 'start', 'class'],
  })
  const allowedStyles = new Set(['font-family', 'font-size', 'font-weight', 'font-style', 'color',
    'background-color', 'text-decoration', 'text-align', 'text-indent', 'line-height', 'letter-spacing',
    'margin-left', 'margin-right', 'margin-top', 'margin-bottom', 'white-space', 'vertical-align',
    'list-style-type', 'width', 'break-before'])
  for (const element of fragment.querySelectorAll<HTMLElement>('[style]')) {
    for (const property of Array.from(element.style)) {
      const value = element.style.getPropertyValue(property)
      if (!allowedStyles.has(property) || /url\s*\(|expression\s*\(|@import/i.test(value)) element.style.removeProperty(property)
    }
  }
  // Retain only renderer-owned classes; document content cannot impersonate UI.
  for (const element of fragment.querySelectorAll('[class]')) {
    element.className = element.classList.contains('docx-page-break') ? 'docx-page-break'
      : element.classList.contains('docx-preview-table') ? 'docx-preview-table' : ''
  }
  const container = document.createElement('div')
  container.append(fragment)
  return container.innerHTML
})
</script>

<template><div class="word-content" v-html="safeHtml"></div></template>

<style scoped>
.word-content { min-width: 0; overflow-x: auto; overflow-wrap: anywhere; line-height: 1.5; }
.word-content :deep(p) { margin: 0 0 10px; }
.word-content :deep(b), .word-content :deep(strong) { font-weight: 700; }
.word-content :deep(i), .word-content :deep(em) { font-style: italic; }
.word-content :deep(ol), .word-content :deep(ul) { padding-left: 2em; margin: 8px 0; }
.word-content :deep(ol) { list-style: decimal; }
.word-content :deep(ul) { list-style: disc; }
.word-content :deep(table) { border-collapse: collapse; max-width: 100%; margin: 12px 0; }
.word-content :deep(td), .word-content :deep(th) { min-width: 30px; border: 1px solid #d7dbe2; padding: 6px 10px; }
.word-content :deep(h1) { font-size: 2em; }
.word-content :deep(h2) { font-size: 1.5em; }
.word-content :deep(h3) { font-size: 1.17em; }
.word-content :deep(.docx-page-break) { margin: 24px 0; border: 0; border-top: 1px dashed #c3c8d0; }
</style>
