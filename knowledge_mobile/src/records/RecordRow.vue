<script setup lang="ts">
import { ref } from 'vue'

type RowAction = { name: string; run: () => unknown; disabled?: boolean; color?: string }
const props = defineProps<{
  title: string; subtitle?: string; badge?: string; inactive?: boolean
  actions?: RowAction[]; open?: () => unknown
}>()
const sheet = ref(false)
function choose(action: { name?: string }) {
  sheet.value = false
  const item = props.actions?.find(a => a.name === action.name)
  if (item && !item.disabled) item.run()
}
</script>
<template>
  <article class="record-row">
    <div class="record-heading">
      <component :is="open ? 'button' : 'div'" class="record-identity" @click="open?.()">
        <strong>{{ title }}</strong><span v-if="subtitle">{{ subtitle }}</span>
      </component>
      <span v-if="badge" class="record-badge" :class="{ inactive }">{{ badge }}</span>
      <button v-if="actions?.length" class="record-more" :aria-label="title + '的操作'" aria-haspopup="dialog" @click="sheet = true"><VanIcon name="ellipsis" /></button>
    </div>
    <div v-if="$slots.default" class="record-info"><slot /></div>
    <VanActionSheet v-if="actions" v-model:show="sheet" teleport="body" :actions="actions" :description="title"
      cancel-text="取消" @select="choose" />
  </article>
</template>
