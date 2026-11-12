<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { api } from '../lib/session'
import { metricNames, percentage, runStatus, type Run } from '../lib/evaluations'
import MarkdownContent from './MarkdownContent.vue'
const router = useRouter()
const props = defineProps<{ run: Run | null }>()
const emit = defineEmits<{ close: []; updated: [Run] }>()
const selectedId = ref(''), saving = ref(false)
const review = reactive({ baseline: null as number | null, candidate: null as number | null, note: '' })
const pair = computed(() => props.run?.results?.find(r => r.id === selectedId.value))
const example = computed(() => props.run?.snapshot?.examples.find(e => e.id === selectedId.value))
const metricRows = computed(() => Object.keys(props.run?.summary.baseline.metrics || {}).map(key => ({ key, name: metricNames[key] || key, baseline: props.run?.summary.baseline.metrics[key], candidate: props.run?.summary.candidate.metrics[key], delta: props.run?.summary.delta[key] })))
const releaseTarget = computed(() => Object.entries(props.run?.snapshot?.candidate || {}).find(([key, value]) => value.id !== props.run?.snapshot?.baseline[key]?.id))
const finished = computed(() => props.run && ['COMPLETED', 'FAILED'].includes(props.run.status))
watch(() => props.run?.id, () => { selectedId.value = props.run?.results?.[0]?.id || props.run?.snapshot?.examples[0]?.id || '' })
watch(() => pair.value?.id, () => Object.assign(review, { baseline: pair.value?.review?.baseline ?? null, candidate: pair.value?.review?.candidate ?? null, note: pair.value?.review?.note || '' }))
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
      <div class="experiment-heading"><div><h2>{{ run.name }}</h2><span>{{ run.snapshot?.dataset_name }} · {{ run.completed }}/{{ run.total }} 题 · {{ runStatus[run.status] }}</span></div><div><el-tag :type="run.reviewed_only ? 'success' : 'warning'">{{ run.reviewed_only ? '已启用测试题' : '草稿试测 · 非验收结论' }}</el-tag><el-button @click="exportRun">导出实验 JSON</el-button></div></div>
      <el-alert v-if="run.quality_reasons?.length" class="quality-notice" :title="run.quality_reasons.join('；')" type="warning" :closable="false" />
      <el-alert v-else-if="run.quality_reasons" class="quality-notice" title="候选答案已全部人工复核合格；发布时还需检查版本、测试题和运行条件是否仍匹配。" type="success" :closable="false" />
      <el-button v-if="releaseTarget" link type="primary" class="quality-notice" @click="router.push({ path: '/prompts', query: { prompt: releaseTarget[0], version: releaseTarget[1].id } })">返回提示词，检查发布条件</el-button>
      <el-alert v-if="run.error_message" :title="run.error_message" type="warning" :closable="false" />
      <el-collapse><el-collapse-item title="汇总指标与实验条件" name="metrics"><p class="hint">共 {{ run.summary.paired_count }} 个完整成功对比；人工复核 {{ run.summary.human_reviewed_count }} 题。字面覆盖率只检查要点是否出现，语义正确性需人工复核。Δ 为同题候选减基线。</p><el-table :data="metricRows" size="small"><el-table-column prop="name" label="指标" min-width="200" /><el-table-column label="基线"><template #default="{ row }">{{ percentage(row.baseline?.value) }} · {{ row.baseline?.count || 0 }} 题</template></el-table-column><el-table-column label="候选"><template #default="{ row }">{{ percentage(row.candidate?.value) }} · {{ row.candidate?.count || 0 }} 题</template></el-table-column><el-table-column label="Δ 同题差值"><template #default="{ row }"><span :class="row.delta > 0 ? 'positive' : row.delta < 0 ? 'negative' : ''">{{ row.delta > 0 ? '+' : '' }}{{ percentage(row.delta) }}</span></template></el-table-column></el-table><p>人工合格率：基线 {{ percentage(run.summary.human.baseline) }} / 候选 {{ percentage(run.summary.human.candidate) }}</p><div class="snapshot-info"><span>测试集指纹 {{ run.snapshot?.dataset_hash }}</span><span>运行条件指纹 {{ run.snapshot?.environment_hash }}</span></div><details><summary>查看固定的提示词版本和运行配置</summary><pre>{{ JSON.stringify({ baseline: Object.fromEntries(Object.entries(run.snapshot?.baseline || {}).map(([key, p]) => [key, { version: p.version, sha256: p.sha256 }])), candidate: Object.fromEntries(Object.entries(run.snapshot?.candidate || {}).map(([key, p]) => [key, { version: p.version, sha256: p.sha256 }])), environment: run.snapshot?.environment }, null, 2) }}</pre></details></el-collapse-item></el-collapse>
      <div class="comparison-workspace">
        <aside aria-label="评测题目"><button v-for="e in run.snapshot?.examples" :key="e.id" :class="{ selected: selectedId === e.id }" @click="selectedId = e.id"><strong>{{ e.name }}</strong><small>{{ run.results?.find(r => r.id === e.id)?.review ? '已人工复核' : run.results?.some(r => r.id === e.id) ? '已运行 · 待复核' : '等待运行' }}</small></button></aside>
        <section class="comparison-content">
          <template v-if="example"><h3>{{ example.inputs.question }}</h3><div class="reference"><strong>参考标注</strong><p>{{ example.reference.reference_answer || example.reference.answer_points.join('；') || '按文档与状态判断' }}</p><span>预期文档：{{ example.reference.expected_documents.join('、') || '未标注' }} · 预期状态：{{ example.reference.expected_status || '未标注' }}</span><p v-if="example.reference.source_notes">核对依据：{{ example.reference.source_notes }}</p></div></template>
          <div v-if="pair" class="answer-columns"><article v-for="arm in (['baseline', 'candidate'] as const)" :key="arm"><h4>{{ arm === 'baseline' ? '基线 · 当前发布版本快照' : '候选 · 试测版本快照' }}</h4><el-alert v-if="pair[arm].error" :title="`执行失败：${pair[arm].error}`" type="error" :closable="false" /><template v-else><div class="answer-meta">{{ pair[arm].outputs.status }} · {{ ((pair[arm].outputs.latency_ms || 0) / 1000).toFixed(1) }} 秒 · 输入 {{ pair[arm].outputs.token_usage?.input_tokens ?? '—' }} / 输出 {{ pair[arm].outputs.token_usage?.output_tokens ?? '—' }} tokens</div><MarkdownContent :content="pair[arm].outputs.answer || ''" /><details><summary>查看逐题指标及引用</summary><p v-for="(value, key) in pair[arm].scores" :key="key">{{ metricNames[key] || key }}：{{ percentage(value) }}</p><p>召回文档：{{ pair[arm].outputs.retrieved_documents?.join('、') || '无' }}</p><p>引用文档：{{ pair[arm].outputs.cited_documents?.join('、') || '无' }}</p><small>LangSmith 运行编号：{{ pair[arm].outputs.run_id }}</small></details></template></article></div>
          <el-empty v-else description="这道题还没有完成评测" :image-size="60" />
          <el-form v-if="pair && finished && !pair.baseline.error && !pair.candidate.error" class="human-review" label-position="top"><h4>人工复核</h4><p class="hint">核对事实、遗漏、引用和表达要求。机器评分不能代替这一步。</p><div class="review-selects"><el-form-item label="基线答案"><el-select v-model="review.baseline" placeholder="是否合格"><el-option :value="1" label="合格" /><el-option :value="0" label="不合格" /></el-select></el-form-item><el-form-item label="候选答案"><el-select v-model="review.candidate" placeholder="是否合格"><el-option :value="1" label="合格" /><el-option :value="0" label="不合格" /></el-select></el-form-item></div><el-form-item label="复核说明"><el-input v-model="review.note" type="textarea" :rows="2" maxlength="2000" placeholder="记录事实错误、遗漏条件或表达改善，作为下次优化依据" /></el-form-item><el-button type="primary" :loading="saving" :disabled="review.baseline === null || review.candidate === null || !review.note.trim()" @click="saveReview">保存人工复核</el-button><small v-if="pair.review"> 上次复核：{{ new Date(pair.review.reviewed_at).toLocaleString('zh-CN') }}</small></el-form>
        </section>
      </div>
    </div>
  </el-dialog>
</template>
<style scoped>
.quality-notice{margin-bottom:14px}.experiment-detail{max-height:79vh;overflow:auto}.experiment-heading{display:flex;justify-content:space-between;gap:16px;align-items:center;margin-bottom:20px;flex-wrap:wrap}.experiment-heading h2{font-size:19px;margin:0 0 8px}.experiment-heading span,.hint{font-size:12px;color:#8995a7;line-height:1.8}.experiment-heading .el-button{margin-left:12px}.comparison-workspace{display:grid;grid-template-columns:220px minmax(0,1fr);border-top:1px solid #e8edf2;min-height:450px}.comparison-workspace aside{padding:18px 12px 18px 0;border-right:1px solid #edf0f5;max-height:65vh;overflow:auto;position:sticky;top:0}.comparison-workspace aside button{background:transparent;border:0;border-radius:9px;text-align:left;width:100%;padding:14px 12px;margin-bottom:6px;cursor:pointer;color:#46556a}.comparison-workspace aside button.selected{background:#ebf2fc;color:#3264a6}.comparison-workspace aside strong{font-size:13px;line-height:1.7;font-weight:500;display:block}.comparison-workspace aside small{font-size:11px;color:#929dad;display:block;margin-top:7px}.comparison-content{padding:20px;min-width:0}.comparison-content h3{font-size:17px;margin:0 0 18px}.reference{background:#f5f8fc;padding:14px 18px;border-radius:10px;font-size:12px;line-height:1.8;margin-bottom:22px}.reference p{margin:6px 0}.reference span{color:#8794a6}.answer-columns{display:grid;grid-template-columns:1fr 1fr;gap:18px}.answer-columns article{border:1px solid #e5eaf1;border-radius:12px;padding:18px;min-width:0;overflow-wrap:anywhere}.answer-columns h4{margin:0 0 12px;font-size:14px}.answer-meta{color:#8a97a9;font-size:11px;line-height:1.8;margin-bottom:16px}.answer-columns details{border-top:1px solid #edf0f4;margin-top:20px;padding-top:14px;font-size:12px;line-height:1.8}.human-review{margin-top:24px;padding:22px;background:#fafbfd;border-radius:12px}.human-review h4{margin:0}.review-selects{display:flex;gap:18px}.review-selects .el-form-item{flex:1}.snapshot-info{display:grid;gap:8px;font-size:11px;color:#929dac;overflow-wrap:anywhere;margin:16px 0}pre{max-height:260px;overflow:auto;font-size:11px}.positive{color:#24815d}.negative{color:#c35757}summary{cursor:pointer;color:#54719a}.human-review small{color:#94a0b1}@media(max-width:900px){.comparison-workspace{grid-template-columns:160px minmax(0,1fr)}.answer-columns{grid-template-columns:1fr}}@media(max-width:600px){.comparison-workspace{display:block}.comparison-workspace aside{position:static;max-height:150px;border-bottom:1px solid #edf0f5}.comparison-content{padding:14px 0}}
</style>
