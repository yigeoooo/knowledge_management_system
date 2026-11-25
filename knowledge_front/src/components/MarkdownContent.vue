<script setup lang="ts">
import { computed } from "vue";
import { renderMarkdown } from "../lib/markdown";

const props = defineProps<{ content: string }>();
const html = computed(() => renderMarkdown(props.content));
</script>

<template>
  <div class="markdown-content" v-html="html"></div>
</template>

<style scoped>
.markdown-content { min-width: 0; white-space: normal; line-height: 1.85; color: #30343b; overflow-wrap: anywhere; }
.markdown-content :deep(p) { margin: 0 0 14px; }
.markdown-content :deep(ul), .markdown-content :deep(ol) { padding-left: 24px; margin: 0 0 14px; }
.markdown-content :deep(li + li) { margin-top: 4px; }
.markdown-content :deep(pre) { overflow-x: auto; border-radius: 6px; background: #0d1117; margin: 14px 0; white-space: pre; overflow-wrap: normal; }
.markdown-content :deep(code) { font-family: ui-monospace, monospace; }
.markdown-content :deep(:not(pre) > code) { padding: 2px 4px; border-radius: 3px; background: #f2f3f5; }
.markdown-content :deep(table) { display: block; max-width: 100%; overflow-x: auto; border-collapse: collapse; margin: 16px 0; }
.markdown-content :deep(th), .markdown-content :deep(td) { border: 1px solid #e4e7ed; padding: 8px 12px; }
.markdown-content :deep(th) { background: #fafbfc; }
.markdown-content :deep(blockquote) { margin: 14px 0; padding: 4px 14px; border-left: 3px solid #efbf7b; color: #747b86; }
.markdown-content :deep(hr) { margin: 18px 0; border: 0; border-top: 1px solid #ebeef2; }
.markdown-content :deep(img) { max-width: 100%; }
.markdown-content :deep(h1) { font-size: 20px; }
.markdown-content :deep(h2) { font-size: 18px; }
.markdown-content :deep(h3), .markdown-content :deep(h4), .markdown-content :deep(h5), .markdown-content :deep(h6) { font-size: 16px; }
.markdown-content :deep(h1), .markdown-content :deep(h2), .markdown-content :deep(h3), .markdown-content :deep(h4), .markdown-content :deep(h5), .markdown-content :deep(h6) { display: block; line-height: 1.5; margin: 20px 0 12px; }
.markdown-content :deep(> :first-child) { margin-top: 0; }
.markdown-content :deep(> :last-child) { margin-bottom: 0; }
</style>
