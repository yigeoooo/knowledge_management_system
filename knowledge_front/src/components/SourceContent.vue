<script setup lang="ts">
import { computed } from "vue";
import MarkdownContent from "./MarkdownContent.vue";

const props = defineProps<{ content: string; filename?: string }>();
const plainText = computed(() => /\.(pdf|txt|docx?)$/i.test(props.filename || ""));
</script>

<template>
  <div v-if="plainText" class="source-plain-text">{{ content }}</div>
  <MarkdownContent v-else :content="content" />
</template>

<style scoped>
.source-plain-text { min-width: 0; white-space: pre-wrap; overflow-wrap: anywhere; line-height: 1.85; }
</style>
