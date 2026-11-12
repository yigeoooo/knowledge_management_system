<script setup lang="ts">
import { computed } from 'vue'
import type { Run } from '../lib/evaluations'

const props = defineProps<{ run: Run }>()
const total = computed(() => Math.max(0, props.run.total))
const reviewed = computed(() => Math.min(total.value, Math.max(0, props.run.summary.human_reviewed_count)))
const state = computed(() => {
  if (['PENDING', 'RUNNING'].includes(props.run.status)) return { label: '等待答案生成', type: 'info' as const }
  if (total.value > 0 && reviewed.value === total.value) return { label: '全部已处理', type: 'success' as const }
  if (props.run.status === 'FAILED') return { label: '执行异常 · 未全部处理', type: 'danger' as const }
  if (!total.value) return { label: '无可确认题目', type: 'info' as const }
  return reviewed.value ? { label: '部分已处理', type: 'warning' as const } : { label: '待处理', type: 'warning' as const }
})
const verdict = computed(() => reviewed.value && props.run.summary.human.candidate != null
  ? props.run.summary.human.candidate === 1 ? '已确认均合格' : '含不合格项'
  : '')
</script>

<template>
  <div class="review-status" aria-label="人工处理情况">
    <el-tag :type="state.type" size="small" effect="light">{{ state.label }}</el-tag>
    <span class="review-count">已确认 {{ reviewed }} / {{ total }} 题</span>
    <span v-if="verdict" class="review-verdict" :class="{ rejected: run.summary.human.candidate !== 1 }">{{ verdict }}</span>
  </div>
</template>

<style scoped>
.review-status{display:flex;align-items:flex-start;flex-direction:column;gap:6px;padding:5px 0}.review-count{font-size:12px;color:#738299;font-variant-numeric:tabular-nums}.review-verdict{font-size:11px;color:#348464;line-height:1.5}.review-verdict.rejected{color:#c45a50}
</style>
