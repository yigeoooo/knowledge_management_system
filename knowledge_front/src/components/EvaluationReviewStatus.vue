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
</script>

<template>
  <div class="review-status" aria-label="人工处理情况">
    <div class="review-heading"><el-tag :type="state.type" size="small" effect="light">{{ state.label }}</el-tag><span class="review-count">已确认 {{ reviewed }} / {{ total }} 题</span></div>
    <div v-if="reviewed > 0 && run.summary.human_failed_count > 0" class="review-totals">
      <el-tag type="success" effect="light" class="passed-count">合格 <strong>{{ run.summary.human_passed_count }}</strong> 题</el-tag>
      <el-tag type="danger" effect="light" class="failed-count">不合格 <strong>{{ run.summary.human_failed_count }}</strong> 题</el-tag>
    </div>
  </div>
</template>

<style scoped>
.review-status{display:flex;align-items:flex-start;flex-direction:column;gap:10px;padding:7px 0}.review-heading{display:flex;align-items:center;flex-wrap:wrap;gap:6px 10px}.review-count{font-size:11px;color:#738299;font-variant-numeric:tabular-nums}.review-totals{display:flex;align-items:center;flex-wrap:wrap;gap:8px}.review-totals .el-tag{height:28px;padding:0 10px;border-radius:6px}.review-totals strong{font-size:15px;margin:0 3px;font-variant-numeric:tabular-nums}.passed-count{--el-tag-text-color:#26764f;--el-tag-bg-color:#edf8f1;--el-tag-border-color:#c7e7d3}.failed-count{--el-tag-text-color:#bc4747;--el-tag-bg-color:#fff1f1;--el-tag-border-color:#f1cccc}
</style>
