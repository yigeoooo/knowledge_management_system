<script setup lang="ts">
defineProps<{ turnCount: number; disabled?: boolean }>()
defineEmits<{ newConversation: [] }>()
</script>

<template>
  <div v-if="turnCount > 200" class="conversation-length-notice" role="status" aria-label="长对话提醒">
    <p>当前已聊 {{ turnCount }} 轮，建议开启新对话，让交流更清晰。</p>
    <el-button link type="primary" :disabled="disabled" @click="$emit('newConversation')">开启新对话</el-button>
  </div>
</template>

<style scoped>
.conversation-length-notice {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 6px 14px;
  padding: 10px 12px;
  background: #fff8ee;
  border-radius: 12px;
  color: #85622f;
  font-size: 12px;
  line-height: 1.7;
}
.conversation-length-notice p { flex: 1 1 200px; margin: 0; }
.conversation-length-notice .el-button { flex-shrink: 0; font-size: 12px; }
</style>
