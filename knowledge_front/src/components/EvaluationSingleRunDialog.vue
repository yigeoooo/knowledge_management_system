<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { api } from '../lib/session'
import EvaluationContext from './EvaluationContext.vue'
import type { Dataset, Example, Prompt, Run } from '../lib/evaluations'

const props = defineProps<{ example: Example | null; dataset: Dataset | null; prompts: Prompt[]; initialOverrides: Record<string, string> }>()
const emit = defineEmits<{ close: []; started: [Run] }>()
const saving = ref(false), error = ref('')
const overrides = reactive<Record<string, string>>({})
const applicablePrompts = computed(() => props.prompts.filter(p => props.example?.prompt_keys?.includes(p.key)))
watch(() => props.example, () => {
  error.value = ''
  for (const key of Object.keys(overrides)) delete overrides[key]
  for (const prompt of applicablePrompts.value) { const newest = [...(prompt.versions || [])].sort((a, b) => b.version - a.version)[0]; overrides[prompt.key] = props.initialOverrides[prompt.key] ?? (newest && newest.version !== prompt.active_version ? newest.id : '') }
})
async function start() {
  if (!props.example || !props.dataset || saving.value || !applicablePrompts.value.length) return
  saving.value = true; error.value = ''
  try {
    const run = await api<Run>('/evaluations/runs', { method: 'POST', body: JSON.stringify({
      dataset_id: props.dataset.id, example_id: props.example.id, expected_revision: props.example.revision,
      name: `单题测试 · ${props.example.name}`.slice(0, 200),
      overrides: Object.fromEntries(applicablePrompts.value.filter(p => overrides[p.key]).map(p => [p.key, overrides[p.key]])),
    }) })
    emit('started', run)
  } catch (e) { error.value = (e as Error).message }
  finally { saving.value = false }
}
</script>

<template>
  <el-dialog :model-value="!!example" title="单题测试" width="min(760px, 94vw)" top="8vh" destroy-on-close class="single-run-dialog" :close-on-click-modal="!saving" :close-on-press-escape="!saving" :show-close="!saving" @close="emit('close')">
    <div v-if="example" class="single-run-content">
      <div class="single-question"><div><strong>{{ example.name }}</strong><el-tag size="small" :type="example.status === 'enabled' ? 'success' : 'info'">{{ example.status === 'enabled' ? '已启用' : '草稿' }}</el-tag></div><p>{{ example.inputs.question }}</p><small>{{ dataset?.name }} · {{ example.inputs.robot ? '机器人' : '网页' }}</small></div>
      <p class="single-help">仅测试当前已保存的这道题，对比当前发布版本与所选候选版本。结果保存在实验记录中，单题测试不作为完整发布验收。</p>
      <EvaluationContext v-if="example.inputs.task !== 'suggestions'" :key="example.id" :context="example.inputs.context || {}" preview />
      <el-alert v-if="error" :title="error" type="error" show-icon :closable="false" />
      <el-form label-position="top" class="single-versions" :disabled="saving">
        <el-form-item v-for="prompt in applicablePrompts" :key="prompt.key" :label="prompt.name">
          <span class="baseline-version">基线：当前发布 v{{ prompt.active_version }}</span>
          <el-select v-model="overrides[prompt.key]" clearable :aria-label="`${prompt.name}候选版本`" placeholder="保持当前发布版本">
            <el-option v-for="version in prompt.versions" :key="version.id" :value="version.id" :label="`v${version.version} · ${version.note || '无修改说明'}`" />
          </el-select>
        </el-form-item>
      </el-form>
      <p v-if="!applicablePrompts.length" class="single-help">未加载到这道题可用的提示词，请刷新页面后重试。</p>
    </div>
    <template #footer><div class="single-footer"><span>1 题 × 2 组回答</span><div><el-button :disabled="saving" @click="emit('close')">取消</el-button><el-button type="primary" :loading="saving" :disabled="!dataset || !applicablePrompts.length" @click="start">开始单题测试</el-button></div></div></template>
  </el-dialog>
</template>

<style scoped>
.single-run-content{max-height:65vh;overflow:auto;padding:0 4px}.single-question{background:#f5f8fc;border:1px solid #e6edf6;border-radius:12px;padding:18px;overflow-wrap:anywhere}.single-question>div{display:flex;gap:12px;align-items:center;justify-content:space-between}.single-question strong{color:#425774;font-size:15px}.single-question p{line-height:1.8;margin:12px 0;white-space:pre-wrap;max-height:160px;overflow:auto}.single-question small,.single-help{color:#78899f;font-size:12px;line-height:1.8}.single-help{margin:16px 0}.single-versions{margin-top:20px}.single-versions .el-select{width:100%}.baseline-version{font-size:12px;color:#8391a5;margin-bottom:7px}.single-footer{display:flex;justify-content:space-between;align-items:center;gap:12px}.single-footer>span{font-size:12px;color:#8391a5}@media(max-width:600px){.single-question{padding:14px}.single-footer{flex-wrap:wrap;justify-content:flex-end}.single-footer>span{margin-right:auto}}
</style>
