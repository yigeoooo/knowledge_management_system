<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { api } from '../lib/session'
import { metricNames, percentage, runStatus, type Run } from '../lib/evaluations'
import MarkdownContent from './MarkdownContent.vue'
import EvaluationProgress from './EvaluationProgress.vue'
import EvaluationContext from './EvaluationContext.vue'
const router = useRouter()
const props = defineProps<{ run: Run | null }>()
const emit = defineEmits<{ close: []; updated: [Run] }>()
const selectedId = ref(''), saving = ref(false)
const review = reactive({ candidate: null as number | null, note: '' })
const pair = computed(() => props.run?.results?.find(r => r.id === selectedId.value))
const example = computed(() => props.run?.snapshot?.examples.find(e => e.id === selectedId.value))
const hasHistory = computed(() => { const context = example.value?.inputs.context; return !!context?.summary || (Array.isArray(context?.turns) && context.turns.length > 0) })
const metricRows = computed(() => Object.keys(props.run?.summary.baseline.metrics || {}).map(key => ({ key, name: metricNames[key] || key, baseline: props.run?.summary.baseline.metrics[key], candidate: props.run?.summary.candidate.metrics[key], delta: props.run?.summary.delta[key] })))
const releaseTarget = computed(() => Object.entries(props.run?.snapshot?.candidate || {}).find(([key, value]) => value.id !== props.run?.snapshot?.baseline[key]?.id))
const finished = computed(() => props.run && ['COMPLETED', 'FAILED'].includes(props.run.status))
watch(() => props.run?.id, () => { selectedId.value = props.run?.results?.[0]?.id || props.run?.snapshot?.examples[0]?.id || '' }, { immediate: true })
watch([() => props.run?.id, selectedId, () => pair.value?.id], () => Object.assign(review, {
  candidate: pair.value?.review?.candidate ?? null, note: pair.value?.review?.note || '',
}), { immediate: true })
function resultState(id: string): { label: string; type: 'info' | 'warning' | 'success' | 'danger' } {
  const result = props.run?.results?.find(r => r.id === id)
  if (!result) return { label: finished.value ? '未生成' : '等待生成', type: 'info' }
  if (result.baseline.error || result.candidate.error) return { label: '执行异常', type: 'warning' }
  if (result.review?.candidate === 1) return { label: '合格', type: 'success' }
  if (result.review?.candidate === 0) return { label: '不合格', type: 'danger' }
  return { label: '待确认', type: 'warning' }
}
const navigationExamples = computed(() => props.run?.snapshot?.examples.map(e => ({ ...e, verdict: resultState(e.id) })) || [])
async function saveReview() {
  if (!props.run || !pair.value || saving.value) return
  saving.value = true
  try { const updated = await api<Run>(`/evaluations/runs/${props.run.id}/reviews/${pair.value.id}`, { method: 'POST', body: JSON.stringify(review) }); emit('updated', updated); ElMessage.success('人工复核已保存') }
  catch (e) { ElMessage.error((e as Error).message) }
  finally { saving.value = false }
}
function exportRun() {
  if (!props.run) return
  const url = URL.createObjectURL(new Blob([JSON.stringify(props.run, null, 2)], { type: 'application/json' }))
  const link = document.createElement('a'); link.href = url; link.download = `evaluation-${props.run.id}.json`; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000)
}
</script>
<template>
  <el-dialog :model-value="!!run" title="评测对比详情" width="min(1440px, 94vw)" top="4vh" destroy-on-close class="evaluation-dialog" @close="emit('close')">
    <div v-if="run" class="experiment-detail">
      <div class="experiment-heading"><div><h2>{{ run.name }}</h2><span>{{ run.snapshot?.dataset_name }} · {{ run.completed }}/{{ run.total }} 题 · {{ runStatus[run.status] }}</span></div><div><el-tag :type="run.scope !== 'single' && run.reviewed_only ? 'success' : 'warning'">{{ run.scope === 'single' ? '单题测试 · 非验收结论' : run.reviewed_only ? '已启用测试题' : '草稿试测 · 非验收结论' }}</el-tag><el-button @click="exportRun">导出实验 JSON</el-button></div></div>
      <EvaluationProgress :run="run" />
      <el-alert v-if="finished && run.quality_reasons?.length" class="quality-notice" :title="run.quality_reasons.join('；')" type="warning" :closable="false" />
      <el-alert v-else-if="finished && run.quality_reasons" class="quality-notice" title="候选答案已全部人工复核合格；发布时还需检查版本、测试题和运行条件是否仍匹配。" type="success" :closable="false" />
      <el-button v-if="finished && releaseTarget && run.scope !== 'single'" link type="primary" class="quality-notice" @click="router.push({ path: '/prompts', query: { prompt: releaseTarget[0], version: releaseTarget[1].id } })">返回提示词，检查发布条件</el-button>
      <el-alert v-if="run.error_message" :title="run.error_message" type="warning" :closable="false" />
      <el-collapse><el-collapse-item title="汇总指标与实验条件" name="metrics"><p class="hint">共 {{ run.summary.paired_count }} 个完整成功对比；人工复核 {{ run.summary.human_reviewed_count }} 题。字面覆盖率只检查要点是否出现，语义正确性需人工复核。Δ 为同题候选减基线。</p><el-table :data="metricRows" size="small"><el-table-column prop="name" label="指标" min-width="200" /><el-table-column label="基线"><template #default="{ row }">{{ percentage(row.baseline?.value) }} · {{ row.baseline?.count || 0 }} 题</template></el-table-column><el-table-column label="候选"><template #default="{ row }">{{ percentage(row.candidate?.value) }} · {{ row.candidate?.count || 0 }} 题</template></el-table-column><el-table-column label="Δ 同题差值"><template #default="{ row }"><span :class="row.delta > 0 ? 'positive' : row.delta < 0 ? 'negative' : ''">{{ row.delta > 0 ? '+' : '' }}{{ percentage(row.delta) }}</span></template></el-table-column></el-table><p>本题对比结果合格率：{{ percentage(run.summary.human.candidate) }}（按已人工确认的题目计算）</p><div class="snapshot-info"><span>测试集指纹 {{ run.snapshot?.dataset_hash }}</span><span>运行条件指纹 {{ run.snapshot?.environment_hash }}</span></div><details><summary>查看固定的提示词版本和运行配置</summary><pre>{{ JSON.stringify({ baseline: Object.fromEntries(Object.entries(run.snapshot?.baseline || {}).map(([key, p]) => [key, { version: p.version, sha256: p.sha256 }])), candidate: Object.fromEntries(Object.entries(run.snapshot?.candidate || {}).map(([key, p]) => [key, { version: p.version, sha256: p.sha256 }])), environment: run.snapshot?.environment }, null, 2) }}</pre></details></el-collapse-item></el-collapse>
      <div class="comparison-workspace">
        <aside aria-label="评测题目"><button v-for="e in navigationExamples" :key="e.id" :class="{ selected: selectedId === e.id }" :aria-pressed="selectedId === e.id" @click="selectedId = e.id"><strong>{{ e.name }}</strong><el-tag :type="e.verdict.type" :effect="['success', 'danger'].includes(e.verdict.type) ? 'dark' : 'light'" class="question-result">{{ e.verdict.label }}</el-tag></button></aside>
        <section class="comparison-content">
          <template v-if="example"><h3>{{ example.inputs.question }}</h3><div class="reference"><strong>参考标注</strong><p>{{ example.reference.reference_answer || example.reference.answer_points.join('；') || '按文档与状态判断' }}</p><span>预期文档：{{ example.reference.expected_documents.join('、') || '未标注' }} · 预期状态：{{ example.reference.expected_status || '未标注' }}</span><p v-if="example.reference.source_notes">核对依据：{{ example.reference.source_notes }}</p></div></template>
          <EvaluationContext v-if="example && example.inputs.task !== 'suggestions'" :key="`${run.id}:${example.id}`" :context="example.inputs.context || {}" />
          <div v-if="pair" class="answer-columns"><article v-for="arm in (['baseline', 'candidate'] as const)" :key="arm"><h4>{{ arm === 'baseline' ? '基线 · 当前发布版本快照' : '候选 · 试测版本快照' }}</h4><el-alert v-if="pair[arm].error" :title="`执行失败：${pair[arm].error}`" type="error" :closable="false" /><template v-else><div class="answer-meta">{{ pair[arm].outputs.status }} · {{ ((pair[arm].outputs.latency_ms || 0) / 1000).toFixed(1) }} 秒 · 输入 {{ pair[arm].outputs.token_usage?.input_tokens ?? '—' }} / 输出 {{ pair[arm].outputs.token_usage?.output_tokens ?? '—' }} tokens</div><div v-if="hasHistory && pair[arm].outputs.resolved_question" class="resolved-question"><strong>结合历史理解的问题</strong><p>{{ pair[arm].outputs.resolved_question }}</p></div><MarkdownContent :content="pair[arm].outputs.answer || ''" /><details><summary>查看逐题指标及引用</summary><p v-for="(value, key) in pair[arm].scores" :key="key">{{ metricNames[key] || key }}：{{ percentage(value) }}</p><p>召回文档：{{ pair[arm].outputs.retrieved_documents?.join('、') || '无' }}</p><p>引用文档：{{ pair[arm].outputs.cited_documents?.join('、') || '无' }}</p><small>LangSmith 运行编号：{{ pair[arm].outputs.run_id }}</small></details></template></article></div>
          <el-empty v-else description="这道题还没有完成评测" :image-size="60" />
          <el-form v-if="pair && finished && !pair.baseline.error && !pair.candidate.error" class="human-review" label-position="top">
            <h4>确认本题结果</h4>
            <p class="hint">对照参考答案与旧版本，只需确认新版本（候选）答案是否满足要求。</p>
            <el-form-item label="本题对比结果">
              <el-radio-group v-model="review.candidate" aria-label="本题对比结果" :disabled="saving">
                <el-radio-button :value="1">合格</el-radio-button>
                <el-radio-button :value="0">不合格</el-radio-button>
              </el-radio-group>
            </el-form-item>
            <el-form-item label="复核说明（选填）">
              <el-input v-model="review.note" type="textarea" :rows="2" maxlength="2000" :disabled="saving" placeholder="可记录错误、遗漏或改善点，方便后续优化" />
            </el-form-item>
            <el-button type="primary" :loading="saving" :disabled="review.candidate === null" @click="saveReview">保存人工复核</el-button>
            <small v-if="pair.review"> 上次复核：{{ new Date(pair.review.reviewed_at).toLocaleString('zh-CN') }}</small>
          </el-form>
        </section>
      </div>
    </div>
  </el-dialog>
</template>
<style scoped>
.resolved-question{background:#f5f8fc;border-radius:8px;padding:12px;margin:0 0 16px;font-size:12px;line-height:1.8;color:#627893}.resolved-question strong{font-size:11px}.resolved-question p{margin:6px 0 0;white-space:pre-wrap;overflow-wrap:anywhere}.quality-notice{margin-bottom:14px}.experiment-detail{max-height:79vh;overflow:auto}.experiment-heading{display:flex;justify-content:space-between;gap:16px;align-items:center;margin-bottom:20px;flex-wrap:wrap}.experiment-heading h2{font-size:19px;margin:0 0 8px}.experiment-heading span,.hint{font-size:12px;color:#8995a7;line-height:1.8}.experiment-heading .el-button{margin-left:12px}.comparison-workspace{display:grid;grid-template-columns:220px minmax(0,1fr);border-top:1px solid #e8edf2;min-height:450px}.comparison-workspace aside{padding:18px 12px 18px 0;border-right:1px solid #edf0f5;max-height:65vh;overflow:auto;position:sticky;top:0}.comparison-workspace aside button{background:transparent;border:0;border-radius:9px;text-align:left;width:100%;padding:14px 12px;margin-bottom:6px;cursor:pointer;color:#46556a}.comparison-workspace aside button.selected{background:#ebf2fc;color:#3264a6}.comparison-workspace aside strong{font-size:13px;line-height:1.7;font-weight:500;display:block}.comparison-workspace aside .question-result{margin-top:10px;min-width:72px;height:26px;font-weight:600;border-radius:6px}.question-result.el-tag--success{--el-tag-bg-color:#26815b;--el-tag-border-color:#26815b;--el-tag-text-color:#fff}.question-result.el-tag--danger{--el-tag-bg-color:#c64c4c;--el-tag-border-color:#c64c4c;--el-tag-text-color:#fff}.comparison-content{padding:20px;min-width:0}.comparison-content h3{font-size:17px;margin:0 0 18px}.reference{background:#f5f8fc;padding:14px 18px;border-radius:10px;font-size:12px;line-height:1.8;margin-bottom:22px}.reference p{margin:6px 0}.reference span{color:#8794a6}.answer-columns{display:grid;grid-template-columns:1fr 1fr;gap:18px}.answer-columns article{border:1px solid #e5eaf1;border-radius:12px;padding:18px;min-width:0;overflow-wrap:anywhere}.answer-columns h4{margin:0 0 12px;font-size:14px}.answer-meta{color:#8a97a9;font-size:11px;line-height:1.8;margin-bottom:16px}.answer-columns details{border-top:1px solid #edf0f4;margin-top:20px;padding-top:14px;font-size:12px;line-height:1.8}.human-review{margin-top:24px;padding:22px;background:#fafbfd;border-radius:12px}.human-review h4{margin:0}.snapshot-info{display:grid;gap:8px;font-size:11px;color:#929dac;overflow-wrap:anywhere;margin:16px 0}pre{max-height:260px;overflow:auto;font-size:11px}.positive{color:#24815d}.negative{color:#c35757}summary{cursor:pointer;color:#54719a}.human-review small{color:#94a0b1}@media(max-width:900px){.comparison-workspace{grid-template-columns:160px minmax(0,1fr)}.answer-columns{grid-template-columns:1fr}}@media(max-width:600px){.comparison-workspace{display:block}.comparison-workspace aside{position:static;max-height:150px;border-bottom:1px solid #edf0f5}.comparison-content{padding:14px 0}}
</style>
