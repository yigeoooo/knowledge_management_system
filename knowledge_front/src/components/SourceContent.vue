<script setup lang="ts">
import { computed } from "vue";
import WordContent from "./WordContent.vue";
import MarkdownContent from "./MarkdownContent.vue";
import ExcelSourceContent from "./ExcelSourceContent.vue";

const props = defineProps<{ content: string; filename?: string; contentHtml?: string | null }>();
const plainText = computed(() => /\.(pdf|txt|docx?)$/i.test(props.filename || ""));
</script>

<template>
  <WordContent v-if="/\.docx$/i.test(filename || '') && contentHtml" :html="contentHtml" />
  <ExcelSourceContent v-else-if="/\.xlsx?$/i.test(filename || '')" :content="content" />
  <div v-else-if="plainText" class="source-plain-text">{{ content }}</div>
  <MarkdownContent v-else :content="content" />
</template>

<style scoped>
.source-plain-text { min-width: 0; white-space: pre-wrap; overflow-wrap: anywhere; line-height: 1.85; }
</style>
