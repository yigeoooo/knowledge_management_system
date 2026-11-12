<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '../lib/session'
import type { Prompt, PromptVersion, ReleaseCheck, Dataset } from '../lib/evaluations'
const router = useRouter(), route = useRoute()
const prompts = ref<Prompt[]>([]), detail = ref<Prompt | null>(null), versionId = ref('')
const content = ref(''), note = ref(''), loading = ref(false), saving = ref(false), error = ref('')
const gate = ref<ReleaseCheck | null>(null), checkingRelease = ref(false), gateError = ref('')
const releaseDatasetId = ref(''), releaseDatasets = ref<Dataset[]>([])
let gateSequence = 0
let generation = 0
const selected = computed(() => detail.value?.versions?.find(v => v.id === versionId.value))
const dirty = computed(() => content.value !== selected.value?.content)
const canPublish = computed(() => selected.value && gate.value?.eligible && !checkingRelease.value && !dirty.value && selected.value.version !== detail.value?.active_version)
async function checkRelease() {
  const sequence = ++gateSequence
  gate.value = null; gateError.value = ''; checkingRelease.value = true
  try {
    if (!detail.value || !selected.value) return
    const params = releaseDatasetId.value ? `?dataset_id=${encodeURIComponent(releaseDatasetId.value)}` : ''
    const result = await api<ReleaseCheck>(`/prompts/${detail.value.key}/versions/${selected.value.version}/release-check${params}`)
    if (sequence === gateSequence) {
      releaseDatasets.value = result.datasets || []; gate.value = result
      if (!releaseDatasetId.value && result.dataset_id) releaseDatasetId.value = result.dataset_id
    }
  } catch (e) { if (sequence === gateSequence) gateError.value = (e as Error).message }
  finally { if (sequence === gateSequence) checkingRelease.value = false }
}
watch([versionId, releaseDatasetId], checkRelease)
function selectVersion() { content.value = selected.value?.content || ''; note.value = '' }
async function load(key: string, prefer?: string) {
  const current = ++generation
  loading.value = true; error.value = ''
  try {
    const result = await api<Prompt>(`/prompts/${key}`)
    if (current !== generation) return
    detail.value = result
    versionId.value = prefer || result.versions?.find(v => v.version === result.active_version)?.id || ''
    selectVersion()
  } catch (e) { if (current === generation) error.value = (e as Error).message }
  finally { if (current === generation) loading.value = false }
}
async function choose(key: string) {
  if (saving.value) return
  if (dirty.value && detail.value) {
    try { await ElMessageBox.confirm('尚未保存的修改将丢失。', '切换提示词', { confirmButtonText: '继续切换', cancelButtonText: '返回编辑' }) } catch { return }
  }
  await load(key)
}
async function save() {
  if (!detail.value || saving.value) return
  saving.value = true
  try {
    const row = await api<PromptVersion>(`/prompts/${detail.value.key}/versions`, { method: 'POST', body: JSON.stringify({ content: content.value, note: note.value }) })
    await load(detail.value.key, row.id)
    ElMessage.success('已保存新版本，正式问答仍使用已发布版本')
  } catch (e) { ElMessage.error((e as Error).message) }
  finally { saving.value = false }
}
async function publish() {
  if (!detail.value || !selected.value || !canPublish.value || saving.value) return
  try { await ElMessageBox.confirm(`将“${detail.value.name}”从 v${detail.value.active_version} 切换为 v${selected.value.version}。验收依据为所选知识库的唯一评测集，发布时会复查全部已启用题目。提示词全局共用，发布后对所有知识库生效。`, '发布提示词', { confirmButtonText: '确认发布', cancelButtonText: '取消' }) } catch { return }
  saving.value = true
  try {
    await api(`/prompts/${detail.value.key}/publish`, { method: 'POST', body: JSON.stringify({ version: selected.value.version, expected_generation: detail.value.generation, evaluation_run_id: gate.value?.evaluation_run_id, dataset_id: gate.value?.dataset_id }) })
    await initialize(detail.value.key, versionId.value)
    ElMessage.success('已发布，后续开始执行的问答将使用此版本')
  } catch (e) { ElMessage.error((e as Error).message) }
  finally { saving.value = false }
}
async function initialize(key?: string, prefer?: string) {
  try {
    prompts.value = (await api<{ items: Prompt[] }>('/prompts')).items
    if (key || prompts.value[0]) await load(key || prompts.value[0]!.key, prefer)
  } catch (e) { error.value = (e as Error).message }
}
function testVersion() {
  if (detail.value && selected.value) void router.push({ path: '/evaluations', query: { prompt: detail.value.key, version: selected.value.id, ...(releaseDatasetId.value ? { dataset: releaseDatasetId.value } : {}) } })
}
onMounted(() => initialize(typeof route.query.prompt === 'string' ? route.query.prompt : undefined, typeof route.query.version === 'string' ? route.query.version : undefined))
onBeforeUnmount(() => { generation++; gateSequence++ })
</script>
<template>
  <div class="page-heading"><div><div class="page-eyebrow">PROMPT STUDIO</div><h1>提示词管理</h1><p>保存每一次改进，用相同测试题比较效果，再发布正式版本。</p></div><el-button @click="router.push('/evaluations')">质量评测</el-button></div>
  <el-alert v-if="error" :title="error" type="error" :closable="false" />
  <div class="prompt-studio">
    <aside aria-label="提示词用途"><h3>提示词用途</h3><button v-for="p in prompts" :key="p.key" :class="{ active: detail?.key === p.key }" :disabled="saving" @click="choose(p.key)"><strong>{{ p.name }}</strong><span>当前发布 v{{ p.key === detail?.key ? detail.active_version : p.active_version }}</span></button></aside>
    <section v-loading="loading" class="prompt-editor">
      <template v-if="detail"><div class="editor-heading"><div><h2>{{ detail.name }}</h2><span>版本保存后不再覆盖；新版本和历史回退均需通过质量评测。</span></div><el-tag effect="plain">当前发布 v{{ detail.active_version }}</el-tag></div>
        <el-form label-position="top"><el-form-item label="查看 / 基于某个版本编辑"><el-select v-model="versionId" :disabled="saving" @change="selectVersion"><el-option v-for="v in detail.versions" :key="v.id" :value="v.id" :label="`v${v.version}${v.version === detail.active_version ? ' · 当前发布' : ' · 历史 / 草稿'} · ${v.note || '无修改说明'}`" /></el-select></el-form-item>
          <el-form-item label="提示词正文"><el-input v-model="content" type="textarea" :rows="18" maxlength="20000" show-word-limit :disabled="saving" /></el-form-item>
          <el-form-item label="本次修改说明"><el-input v-model="note" maxlength="1000" placeholder="例如：缩短机器人回答，同时保留价格和适用条件" :disabled="saving" /></el-form-item>
        </el-form>
        <div v-if="selected && selected.version !== detail.active_version" class="release-gate" aria-label="发布条件">
          <el-form label-position="top"><el-form-item label="发布验收使用的知识库评测集"><el-select v-model="releaseDatasetId" :disabled="saving" aria-label="发布验收评测集" placeholder="选择知识库的唯一评测集"><el-option v-for="dataset in releaseDatasets" :key="dataset.id" :value="dataset.id" :label="`${dataset.knowledge_base_name || ''} · ${dataset.name}`" /></el-select></el-form-item></el-form>
          <p class="release-scope">每个知识库一个评测集，本次仅使用所选集验收。提示词全局共用，发布后对所有知识库生效。</p>
          <el-alert :type="gate?.eligible ? 'success' : 'warning'" :closable="false" :title="checkingRelease ? '正在检查发布条件…' : gate?.eligible ? '已通过质量评测，可以发布' : '尚未满足发布条件'" show-icon>
            <p v-if="gateError">{{ gateError }}</p><p v-for="reason in gate?.reasons" :key="reason">{{ reason }}</p>
            <p v-if="gate?.eligible">依据实验：{{ gate.runs.find(r => r.id === gate?.evaluation_run_id)?.name }}</p>
            <p>需覆盖所选评测集当前全部已启用题目，并逐题确认候选答案合格；题目范围变化后需重测。</p>
          </el-alert>
          <el-button link type="primary" :loading="checkingRelease" @click="checkRelease">刷新发布条件</el-button>
          <el-button v-if="gate?.runs[0]" link type="primary" @click="router.push({ path: '/evaluations', query: { run: gate.evaluation_run_id || gate.runs[0].id } })">查看评测依据</el-button>
        </div>
        <div class="editor-footer"><small>{{ selected ? `v${selected.version} · ${new Date(selected.created_at).toLocaleString('zh-CN')}` : '' }}<span v-if="dirty"> · 有未保存修改</span></small><div><el-button :disabled="dirty || loading || saving" @click="testVersion">试测此版本</el-button><el-button :disabled="!canPublish || loading" :loading="saving" @click="publish">发布所选版本</el-button><el-button type="primary" :disabled="!dirty || loading || content.trim().length < 20" :loading="saving" @click="save">保存新版本</el-button></div></div>
      </template><el-empty v-else description="请选择提示词用途" />
    </section>
  </div>
</template>
<style scoped>
.release-scope{font-size:12px;color:#8793a4;margin-bottom:12px!important}.release-gate{margin:0 0 20px}.release-gate p{margin:4px 0;line-height:1.7}.release-gate>.el-button{margin-top:8px}.prompt-studio{display:grid;grid-template-columns:230px minmax(0,1fr);border:1px solid #e5eaf1;border-radius:16px;background:#fff;overflow:hidden}.prompt-studio aside{padding:22px 14px;background:#f8fafc;border-right:1px solid #e8edf3}.prompt-studio h3{margin:0 12px 18px;color:#7c899a;font-size:12px}.prompt-studio aside button{display:block;width:100%;text-align:left;border:0;border-radius:10px;background:transparent;padding:15px 14px;margin-bottom:6px;cursor:pointer;color:#465366}.prompt-studio aside button:hover{background:#eef3f9}.prompt-studio aside button.active{background:#e8f0fc;color:#2461b0}.prompt-studio aside strong{display:block;font-size:14px;font-weight:500}.prompt-studio aside span{display:block;font-size:11px;color:#8996a8;margin-top:7px}.prompt-editor{padding:26px 30px;min-width:0}.editor-heading{display:flex;justify-content:space-between;gap:16px;align-items:center;margin-bottom:24px}.editor-heading h2{font-size:19px;margin:0 0 8px}.editor-heading span,.editor-footer small{font-size:12px;color:#8c97a7}.editor-footer{display:flex;justify-content:space-between;align-items:center;gap:14px;flex-wrap:wrap}.prompt-editor :deep(textarea){line-height:1.8;font-size:13px}.prompt-editor :deep(.el-select){width:100%}@media(max-width:850px){.prompt-studio{grid-template-columns:1fr}.prompt-studio aside{display:flex;overflow:auto;padding:12px;gap:8px}.prompt-studio aside h3{display:none}.prompt-studio aside button{min-width:150px;margin:0}.prompt-editor{padding:18px}.editor-footer .el-button{margin:4px}}
</style>
