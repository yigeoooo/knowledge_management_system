<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '../lib/session'
import { runStatus, type Dataset, type Example, type Prompt, type Run } from '../lib/evaluations'
import EvaluationExampleDialog from '../components/EvaluationExampleDialog.vue'
import EvaluationRunDialog from '../components/EvaluationRunDialog.vue'
import EvaluationProgress from '../components/EvaluationProgress.vue'
import EvaluationReviewStatus from '../components/EvaluationReviewStatus.vue'
import EvaluationSingleRunDialog from '../components/EvaluationSingleRunDialog.vue'
const route = useRoute()
const datasets = ref<Dataset[]>([]), bases = ref<{ id: string; name: string; dataset_id?: string | null }[]>([]), datasetId = ref('')
const examples = ref<Example[]>([]), prompts = ref<Prompt[]>([]), runs = ref<Run[]>([]), activeRun = ref<Run | null>(null)
const tab = ref('examples'), error = ref(''), loading = ref(false), saving = ref(false)
const runScope = ref<'dataset' | 'single'>('dataset'), runsLoading = ref(false)
const newDataset = ref(false), editor = ref(false), editing = ref<Example | null>(null), singleExample = ref<Example | null>(null)
const datasetForm = reactive({ name: '', knowledge_base_id: '', description: '' })
const runName = ref(''), reviewedOnly = ref(true), overrides = reactive<Record<string, string>>({})
const dataset = computed(() => datasets.value.find(d => d.id === datasetId.value))
const availableBases = computed(() => bases.value.filter(b => !b.dataset_id && !datasets.value.some(d => d.knowledge_base_id === b.id)))
const reviewedCount = computed(() => examples.value.filter(e => e.status === 'enabled').length)
const visibleRuns = computed(() => runs.value.filter(r => (!datasetId.value || r.dataset_id === datasetId.value) && (r.scope || 'dataset') === runScope.value))
let disposed = false, exampleSequence = 0, detailSequence = 0, runSequence = 0, timer: ReturnType<typeof setTimeout> | undefined
const controller = new AbortController()
function fail(e: unknown) { if (!disposed) ElMessage.error((e as Error).message) }
async function loadExamples() {
  const sequence = ++exampleSequence
  examples.value = []; loading.value = true
  try { if (datasetId.value) { const result = await api<{ items: Example[] }>(`/evaluations/datasets/${datasetId.value}/examples`, { signal: controller.signal }); if (sequence === exampleSequence && !disposed) examples.value = result.items } }
  catch (e) { if (sequence === exampleSequence) fail(e) }
  finally { if (sequence === exampleSequence && !disposed) loading.value = false }
}
async function loadRuns() {
  const sequence = ++runSequence
  const query = new URLSearchParams({ scope: runScope.value })
  if (datasetId.value) query.set('dataset_id', datasetId.value)
  runsLoading.value = true
  try { const result = await api<{ items: Run[] }>(`/evaluations/runs?${query}`, { signal: controller.signal }); if (!disposed && sequence === runSequence) runs.value = result.items }
  catch (e) { if (sequence === runSequence) fail(e) }
  finally { if (!disposed && sequence === runSequence) runsLoading.value = false }
}
async function showRun(id: string) {
  const sequence = ++detailSequence
  try { const result = await api<Run>(`/evaluations/runs/${id}`, { signal: controller.signal }); if (!disposed && sequence === detailSequence) activeRun.value = result }
  catch (e) { if (sequence === detailSequence) fail(e) }
}
function closeRun() { ++detailSequence; activeRun.value = null }
function updatedRun(run: Run) { if (activeRun.value?.id === run.id) activeRun.value = run; runs.value = runs.value.map(r => r.id === run.id ? run : r) }
async function tick() {
  if (disposed) return
  if (runs.value.some(r => ['PENDING', 'RUNNING'].includes(r.status))) await loadRuns()
  if (activeRun.value && ['PENDING', 'RUNNING'].includes(activeRun.value.status)) await showRun(activeRun.value.id)
  if (!disposed) timer = setTimeout(tick, 4000)
}
async function initialize() {
  error.value = ''
  try {
    const [sets, options, promptList] = await Promise.all([api<{ items: Dataset[] }>('/evaluations/datasets'), api<{ knowledge_bases: { id: string; name: string }[] }>('/evaluations/options'), api<{ items: Prompt[] }>('/prompts')])
    if (disposed) return
    datasets.value = sets.items; bases.value = options.knowledge_bases
    const details = await Promise.all(promptList.items.map(p => api<Prompt>(`/prompts/${p.key}`)))
    if (disposed) return
    prompts.value = details
    if (!datasetId.value) datasetId.value = datasets.value.find(d => d.id === route.query.dataset)?.id || datasets.value[0]?.id || ''
    datasetForm.knowledge_base_id = availableBases.value[0]?.id || ''
    if (typeof route.query.prompt === 'string' && typeof route.query.version === 'string') {
      const prompt = details.find(p => p.key === route.query.prompt)
      if (prompt?.versions?.some(v => v.id === route.query.version)) { overrides[prompt.key] = route.query.version; tab.value = 'compare' }
    }
    if (!datasetId.value) await loadRuns()
    if (typeof route.query.run === 'string') {
      tab.value = 'runs'; await showRun(route.query.run)
      if (activeRun.value) { datasetId.value = activeRun.value.dataset_id; runScope.value = activeRun.value.scope || 'dataset' }
    }
    timer = setTimeout(tick, 4000)
  } catch (e) { if (!disposed) error.value = (e as Error).message }
}
async function openDataset() {
  try {
    const [options, sets] = await Promise.all([api<{ knowledge_bases: typeof bases.value }>('/evaluations/options'), api<{ items: Dataset[] }>('/evaluations/datasets')])
    bases.value = options.knowledge_bases; datasets.value = sets.items
    datasetForm.knowledge_base_id = availableBases.value[0]?.id || ''
    datasetForm.name = ''; datasetForm.description = ''; newDataset.value = true
  } catch (e) { fail(e) }
}
async function createDataset() {
  saving.value = true
  try { const result = await api<{ id: string }>('/evaluations/datasets', { method: 'POST', body: JSON.stringify(datasetForm) }); datasets.value = (await api<{ items: Dataset[] }>('/evaluations/datasets')).items; datasetId.value = result.id; newDataset.value = false; ElMessage.success('评测集已创建') }
  catch (e) { fail(e) } finally { saving.value = false }
}
function edit(row?: Example) { editing.value = row || null; editor.value = true }
function savedExample() { editor.value = false; void loadExamples() }
async function remove(row: Example) {
  try { await ElMessageBox.confirm('删除题目后，已有实验的固定样本与结果仍保留。', '删除测试题', { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' }) } catch { return }
  saving.value = true
  try { await api(`/evaluations/examples/${row.id}`, { method: 'DELETE', body: JSON.stringify({ expected_revision: row.revision }) }); await loadExamples() } catch (e) { fail(e) } finally { saving.value = false }
}
async function start() {
  saving.value = true
  try {
    const candidate = Object.fromEntries(Object.entries(overrides).filter(([, v]) => v))
    const run = await api<Run>('/evaluations/runs', { method: 'POST', body: JSON.stringify({ dataset_id: datasetId.value, name: runName.value || `${dataset.value?.name} · ${new Date().toLocaleString('zh-CN')}`, reviewed_only: reviewedOnly.value, overrides: candidate }) })
    runScope.value = 'dataset'; await loadRuns(); tab.value = 'runs'; await showRun(run.id); ElMessage.success('评测已开始，离开页面后后台仍会继续')
  } catch (e) { fail(e) } finally { saving.value = false }
}
async function singleStarted(run: Run) {
  singleExample.value = null
  runScope.value = 'single'
  runs.value = [run, ...runs.value.filter(r => r.id !== run.id)]
  await showRun(run.id)
  ElMessage.success('单题测试已开始，结果会保存在实验记录中')
}
watch(datasetId, () => { editor.value = false; singleExample.value = null; void loadExamples() })
watch([datasetId, runScope], () => { runs.value = []; void loadRuns() })
onMounted(initialize)
onBeforeUnmount(() => { disposed = true; controller.abort(); ++exampleSequence; ++detailSequence; ++runSequence; clearTimeout(timer) })
</script>
<template>
  <div class="page-heading"><div><div class="page-eyebrow">RAG EVALUATION</div><h1>质量评测</h1><p>每个知识库维护一个评测集，用其中全部已启用题目检验提示词改进。</p></div><el-button type="primary" :disabled="!availableBases.length" @click="openDataset">新建评测集</el-button></div>
  <p v-if="datasets.length && !availableBases.length" class="dataset-description">当前知识库均已建立评测集，可选择现有评测集继续添加或修改题目。</p>
  <el-alert v-if="error" :title="error" type="error" :closable="false" />
  <el-card shadow="never" class="resource-card"><div class="dataset-bar"><div><span>当前评测集</span><el-select v-model="datasetId" placeholder="选择评测集" filterable><el-option v-for="d in datasets" :key="d.id" :label="d.name" :value="d.id" /></el-select></div><div class="dataset-counts"><strong>{{ examples.length }}</strong> 题 <span>/</span> <strong>{{ reviewedCount }}</strong> 已启用</div></div><p v-if="dataset?.knowledge_base_name" class="dataset-description">所属知识库：{{ dataset.knowledge_base_name }} · 唯一评测集</p><p v-if="dataset?.description" class="dataset-description">{{ dataset.description }}</p>
    <el-tabs v-model="tab"><el-tab-pane label="测试题与人工标注" name="examples"><div class="tab-toolbar"><p>对照知识库资料出题，保存并启用后即可用于正式评测；未完成的题目可保存草稿。</p><el-button :disabled="!datasetId || saving" @click="edit()">添加测试题</el-button></div><el-table v-loading="loading" :data="examples"><el-table-column prop="name" label="样本" min-width="150" /><el-table-column prop="inputs.question" label="问题" min-width="260" show-overflow-tooltip /><el-table-column label="渠道" width="95"><template #default="{ row }">{{ row.inputs.robot ? '机器人' : '网页' }}</template></el-table-column><el-table-column label="题目状态" width="110"><template #default="{ row }"><el-tag :type="row.status === 'enabled' ? 'success' : 'warning'">{{ row.status === 'enabled' ? '已启用' : '草稿' }}</el-tag></template></el-table-column><el-table-column label="操作" width="290"><template #default="{ row }"><el-button link type="primary" :disabled="saving" @click="edit(row)">查看 / 编辑</el-button><el-button link type="primary" :disabled="saving" @click="singleExample = row">单题测试</el-button><el-button link type="danger" :disabled="saving" @click="remove(row)">删除</el-button></template></el-table-column><template #empty><el-empty description="添加真实问题，填写依据和预期答案" :image-size="70" /></template></el-table></el-tab-pane>
      <el-tab-pane label="发起版本对比" name="compare"><el-alert title="用于发布时，请一次只调整一个提示词用途，并使用本集全部已启用题目；题目范围变化后需重测，完成后还需逐题人工复核。多用途组合可用于探索试测。" type="info" show-icon :closable="false" /><el-form label-position="top" class="experiment-form"><el-form-item label="实验名称"><el-input v-model="runName" maxlength="200" placeholder="例如：机器人回答精简 · 第一轮对比" /></el-form-item><el-form-item label="样本范围"><el-switch v-model="reviewedOnly" active-text="只使用已启用测试题" inactive-text="包含草稿，结果仅供试测" /></el-form-item><el-table :data="prompts"><el-table-column prop="name" label="提示词用途" width="180" /><el-table-column label="基线" width="140"><template #default="{ row }">当前发布 v{{ row.active_version }}</template></el-table-column><el-table-column label="候选版本（不选则与基线相同）" min-width="250"><template #default="{ row }"><el-select v-model="overrides[row.key]" clearable placeholder="保持当前发布版本"><el-option v-for="v in row.versions" :key="v.id" :value="v.id" :label="`v${v.version} · ${v.note || '无修改说明'}`" /></el-select></template></el-table-column></el-table><div class="start-actions"><span>{{ reviewedOnly ? reviewedCount : examples.length }} 题 × 2 组回答</span><el-button type="primary" :loading="saving" :disabled="!datasetId || !(reviewedOnly ? reviewedCount : examples.length)" @click="start">开始对比评测</el-button></div></el-form></el-tab-pane>
      <el-tab-pane label="实验记录" name="runs">
        <div class="tab-toolbar record-toolbar">
          <el-radio-group v-model="runScope" aria-label="实验记录类型">
            <el-radio-button value="dataset">评测集记录</el-radio-button>
            <el-radio-button value="single">单题测试记录</el-radio-button>
          </el-radio-group>
          <el-button :loading="runsLoading" @click="loadRuns">刷新</el-button>
        </div>
        <p class="record-help">每类显示当前评测集最近 50 条记录。逐题人工确认后标记已处理，合格与不合格都计入处理进度。</p>
        <el-table v-loading="runsLoading" :data="visibleRuns" class="run-records-table" row-key="id">
          <el-table-column label="实验名称" min-width="220">
            <template #default="{ row }"><div class="record-name">{{ row.name }}</div><small class="record-scope">{{ row.scope === 'single' ? '单题调试' : row.reviewed_only ? '已启用题目' : '包含草稿试测' }}</small></template>
          </el-table-column>
          <el-table-column label="答案生成" min-width="170">
            <template #default="{ row }"><div class="record-execution" :class="{ failed: row.status === 'FAILED' }">{{ row.status === 'COMPLETED' ? '答案已生成' : runStatus[row.status] }}</div><EvaluationProgress :run="row" compact /></template>
          </el-table-column>
          <el-table-column label="处理情况与结果" min-width="250"><template #default="{ row }"><EvaluationReviewStatus :run="row" /></template></el-table-column>
          <el-table-column label="创建时间" min-width="180"><template #default="{ row }">{{ new Date(row.created_at).toLocaleString('zh-CN') }}</template></el-table-column>
          <el-table-column label="操作" width="140"><template #default="{ row }"><el-button link type="primary" @click="showRun(row.id)">查看逐题对比</el-button></template></el-table-column>
          <template #empty><el-empty :description="runScope === 'single' ? '暂无单题测试记录' : '暂无评测集记录'" :image-size="65" /></template>
        </el-table>
      </el-tab-pane>
    </el-tabs>
  </el-card>
  <el-dialog v-model="newDataset" title="新建评测集" width="min(560px, 92vw)" align-center><el-form label-position="top"><el-form-item label="名称"><el-input v-model="datasetForm.name" maxlength="200" /></el-form-item><el-form-item label="知识库"><el-select v-model="datasetForm.knowledge_base_id" aria-label="创建评测集的知识库"><el-option v-for="b in bases" :key="b.id" :value="b.id" :label="b.name" :disabled="!!b.dataset_id || datasets.some(d => d.knowledge_base_id === b.id)">{{ b.name }}{{ b.dataset_id || datasets.some(d => d.knowledge_base_id === b.id) ? ' · 已有评测集' : '' }}</el-option></el-select></el-form-item><el-form-item label="用途说明"><el-input v-model="datasetForm.description" type="textarea" :rows="3" maxlength="2000" /></el-form-item></el-form><template #footer><el-button @click="newDataset = false">取消</el-button><el-button type="primary" :loading="saving" :disabled="!datasetForm.name.trim() || !availableBases.some(b => b.id === datasetForm.knowledge_base_id)" @click="createDataset">创建</el-button></template></el-dialog>
  <EvaluationExampleDialog :open="editor" :dataset="dataset" :example="editing" @close="editor = false" @saved="savedExample" />
  <EvaluationSingleRunDialog :example="singleExample" :dataset="dataset || null" :prompts="prompts" :initial-overrides="overrides" @close="singleExample = null" @started="singleStarted" />
  <EvaluationRunDialog :run="activeRun" @close="closeRun" @updated="updatedRun" />
</template>
<style scoped>
.record-toolbar{margin-top:4px}.record-help{font-size:12px;color:#8995a6;line-height:1.8;margin:0 0 16px}.record-name{color:#45546a;line-height:1.7;overflow-wrap:anywhere}.record-scope{display:block;color:#8995a6;font-size:11px;margin-top:5px}.record-execution{font-size:12px;color:#6a7f9c;margin-bottom:8px}.record-execution.failed{color:#bf7e36}
.document-meta{margin-left:12px;color:#8995a6;font-size:11px}.dataset-bar{display:flex;justify-content:space-between;align-items:center;gap:20px;margin-bottom:20px}.dataset-bar>div:first-child{display:flex;align-items:center;gap:16px}.dataset-bar .el-select{width:320px}.dataset-bar span,.dataset-counts{color:#8b97a8;font-size:12px}.dataset-counts strong{font-size:18px;color:#3c526c;margin:0 5px}.dataset-counts span{margin:0 12px}.dataset-description{font-size:12px;color:#8995a6;line-height:1.8}.tab-toolbar{display:flex;align-items:center;justify-content:space-between;gap:16px;padding:6px 0 18px}.tab-toolbar p,.help-text{font-size:12px;color:#8693a7;line-height:1.8;margin:0}.experiment-form{margin:24px 0 0;max-width:1050px}.experiment-form .el-select{width:100%}.start-actions{display:flex;justify-content:flex-end;align-items:center;gap:20px;margin-top:26px}.start-actions span{font-size:12px;color:#8391a5}.example-editor{max-height:68vh;overflow:auto;padding:0 8px}.form-columns{display:grid;grid-template-columns:1fr 1fr;gap:22px}.form-columns .el-select{width:100%}.help-text{margin-bottom:12px}@media(max-width:800px){.dataset-bar{display:block}.dataset-bar>div:first-child{display:block}.dataset-bar .el-select{width:100%;margin:10px 0}.form-columns{grid-template-columns:1fr;gap:0}.tab-toolbar{flex-wrap:wrap}}
</style>
