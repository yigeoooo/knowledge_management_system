<script setup lang="ts">
const question = defineModel<string>({ required: true })
defineProps<{enabled:boolean; busy:boolean; sending:boolean}>()
const emit = defineEmits<{send: []}>()
</script>
<template>
  <div class="mobile-composer">
    <van-field v-model="question" type="textarea" :autosize="{maxHeight:120,minHeight:32}" rows="1"
      maxlength="2000" show-word-limit :disabled="!enabled" label="你的问题" label-class="visually-hidden" placeholder="输入问题…" @keydown.ctrl.enter.prevent="emit('send')" />
    <van-button type="primary" icon="guide-o" :aria-label="busy ? '回答中' : '发送问题'" :loading="sending" :disabled="!enabled || !question.trim()" @click="emit('send')" />
  </div>
</template>
