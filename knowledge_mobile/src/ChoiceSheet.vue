<script setup lang="ts">
import { computed, ref } from 'vue'
const props = defineProps<{
  modelValue: string; label: string; placeholder: string
  options: { value: string; text: string }[]; disabled?: boolean; searchable?: boolean
}>()
const emit = defineEmits<{ 'update:modelValue': [string] }>()
const open = ref(false), query = ref('')
const selected = computed(() => props.options.find(item => item.value === props.modelValue))
const visible = computed(() => props.options.filter(item => item.text.toLowerCase().includes(query.value.trim().toLowerCase())))
function choose(value: string) {
  open.value = false
  if (value !== props.modelValue) emit('update:modelValue', value)
}
</script>
<template>
  <button type="button" class="choice-trigger" :class="{ chosen: !!modelValue }" :disabled="disabled"
    :aria-label="label + '，' + (selected?.text || placeholder)" aria-haspopup="dialog" :aria-expanded="open"
    @click="query = ''; open = true">
    <slot name="value" :text="selected?.text || placeholder"><span>{{ selected?.text || placeholder }}</span></slot>
    <van-icon name="arrow-down" />
  </button>
  <van-action-sheet v-model:show="open" teleport="body" :title="label" cancel-text="取消" :closeable="false" class="choices-sheet">
    <van-search v-if="searchable" v-model="query" :placeholder="'搜索' + label" :aria-label="'搜索' + label" />
    <div class="choice-options">
      <button v-for="option in visible" :key="option.value" type="button" :aria-pressed="option.value === modelValue"
        @click="choose(option.value)">
        <span>{{ option.text }}</span><van-icon v-if="option.value === modelValue" name="success" />
      </button>
      <van-empty v-if="!visible.length" description="暂无匹配选项" :image-size="48" />
    </div>
  </van-action-sheet>
</template>
