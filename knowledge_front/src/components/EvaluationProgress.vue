<script setup lang="ts">
import { computed } from 'vue'
import type { Run } from '../lib/evaluations'

const props = defineProps<{ run: Run; compact?: boolean }>()
const total = computed(() => Math.max(0, props.run.total))
const completed = computed(() => Math.min(total.value, Math.max(0, props.run.completed)))
const percent = computed(() => total.value ? Math.floor(completed.value / total.value * 100) : 0)
const active = computed(() => props.run.status === 'RUNNING')
const failed = computed(() => props.run.status === 'FAILED')
const finished = computed(() => props.run.status === 'COMPLETED' || failed.value)
const reviewed = computed(() => props.run.summary.human_reviewed_count)
const title = computed(() => ({
  PENDING: '等待开始评测', RUNNING: '正在生成对比答案',
  COMPLETED: '对比答案已生成', FAILED: '评测执行异常',
}[props.run.status] || '评测进度'))
const description = computed(() => {
  if (failed.value) return '请查看异常信息和逐题结果；执行失败的题目不能用于发布验收。'
  if (props.run.status === 'PENDING') return '任务已提交，等待后台执行；离开页面后仍会继续。'
  if (active.value) return '每题的两组答案生成后更新进度，可先查看已完成的对比。'
  if (props.run.scope === 'single') return '本题对比已完成，可确认候选答案是否合格；正式发布仍需完成整个评测集的验收。'
  return '答案生成完成后，需逐题确认候选答案是否合格；执行完成不代表通过验收。'
})
</script>

<template>
  <section class="evaluation-progress" :class="{ compact, active, failed, finished }" aria-label="评测进度">
    <div v-if="!compact" class="progress-heading">
      <div class="progress-state"><span class="state-dot" aria-hidden="true" /><strong>{{ title }}</strong></div>
      <span v-if="finished" class="review-count">已人工确认 {{ reviewed }} / {{ total }} 题</span>
      <span v-else class="refresh-hint">自动更新</span>
    </div>
    <div class="progress-numbers" aria-live="polite" aria-atomic="true">
      <span><template v-if="!compact">执行进度 · </template>{{ completed }} / {{ total }} 题</span><strong>{{ percent }}%</strong>
    </div>
    <div class="progress-track" role="progressbar" aria-label="评测执行进度" :aria-valuenow="percent" :aria-valuetext="`${completed} / ${total} 题`" aria-valuemin="0" aria-valuemax="100">
      <div class="progress-fill" :style="{ width: `${percent}%` }" />
    </div>
    <p v-if="!compact" class="progress-description">{{ description }}</p>
  </section>
</template>

<style scoped>
.evaluation-progress{--progress-color:#517fc4;padding:18px 20px;border:1px solid #dfE8f5;border-radius:12px;background:linear-gradient(110deg,#f3f7fd,#fafcfe);margin-bottom:16px}
.progress-heading,.progress-numbers{display:flex;align-items:center;justify-content:space-between;gap:12px}
.progress-heading{margin-bottom:18px;flex-wrap:wrap}.progress-state{display:flex;align-items:center;gap:9px;color:#395577;font-size:14px}
.state-dot{width:8px;height:8px;flex-shrink:0;border-radius:50%;background:var(--progress-color)}
.active .state-dot{animation:pulse 2s ease-in-out infinite}.refresh-hint,.review-count{font-size:12px;color:#677c98}
.progress-numbers{font-size:12px;color:#6e8098;margin-bottom:9px;font-variant-numeric:tabular-nums}.progress-numbers strong{color:#486a98;font-size:14px}
.progress-track{height:8px;overflow:hidden;border-radius:99px;background:#e5ecf5}.progress-fill{height:100%;border-radius:inherit;background:var(--progress-color);position:relative;overflow:hidden;transition:width .45s ease}
.active .progress-fill:after{content:'';position:absolute;inset:0;background:linear-gradient(100deg,transparent,rgba(255,255,255,.4),transparent);animation:sweep 2s ease-in-out infinite}
.progress-description{font-size:12px;line-height:1.8;color:#70829a;margin:12px 0 0}
.failed{--progress-color:#cf8d3f;background:#fffbf5;border-color:#f1e4d1}.failed .progress-state{color:#976c36}
.compact{padding:0;border:0;border-radius:0;background:none;margin:0;min-width:130px}.compact .progress-numbers{font-size:11px;margin-bottom:5px}.compact .progress-numbers strong{font-size:12px}.compact .progress-track{height:5px}
@keyframes pulse{50%{box-shadow:0 0 0 5px rgba(81,127,196,.12)}}@keyframes sweep{from{transform:translateX(-100%)}to{transform:translateX(100%)}}
@media(prefers-reduced-motion:reduce){.active .state-dot,.active .progress-fill:after{animation:none}.progress-fill{transition:none}}
@media(max-width:600px){.evaluation-progress:not(.compact){padding:14px}.progress-heading{gap:8px;margin-bottom:14px}.progress-description{font-size:11px}}
</style>
