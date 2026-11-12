<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{ context: Record<string, unknown>; preview?: boolean }>()
const summary = computed(() => typeof props.context.summary === 'string' ? props.context.summary : '')
const notice = computed(() => typeof props.context.notice === 'string' ? props.context.notice : '')
const turns = computed(() => (Array.isArray(props.context.turns) ? props.context.turns : [])
  .filter((turn): turn is Record<string, unknown> => !!turn && typeof turn === 'object')
  .map((turn, index) => ({
    number: typeof turn.turn_no === 'number' ? turn.turn_no : index + 1,
    question: typeof turn.question === 'string' ? turn.question : '',
    answer: typeof turn.answer === 'string' ? turn.answer : '',
  })))
const hasHistory = computed(() => !!summary.value.trim() || !!turns.value.length)
</script>

<template>
  <section class="evaluation-context" :aria-label="preview ? '待测试的历史上下文' : '本次评测的历史上下文'">
    <details v-if="hasHistory" open>
      <summary><strong>{{ preview ? '待测试的历史上下文' : '本次评测的历史上下文' }}</strong><span>{{ turns.length }} 轮{{ summary ? ' · 含摘要' : '' }}</span><small>点击展开 / 收起</small></summary>
      <p class="context-caption">{{ preview ? '使用题目中已保存的历史问答与摘要。' : '来自本次实验固定的题目快照，基线与候选使用相同的历史；后续编辑题目不会改变此处记录。' }}</p>
      <div class="context-records">
        <div v-if="summary" class="context-summary"><h4>更早的对话摘要</h4><p>{{ summary }}</p></div>
        <article v-for="(turn, index) in turns" :key="index" class="context-turn"><h4>第 {{ turn.number }} 轮</h4><div><span>用户</span><p>{{ turn.question || '未填写问题' }}</p></div><div><span>回答</span><p>{{ turn.answer || '未填写回答' }}</p></div></article>
      </div>
      <p v-if="notice" class="context-caption">{{ notice }}</p>
    </details>
    <p v-else class="empty-context">本题未配置历史问答或摘要，按单轮问题评测。</p>
  </section>
</template>

<style scoped>
.evaluation-context{margin:0 0 20px;border:1px solid #dfe8f2;border-radius:10px;background:#fbfcfe;overflow:hidden}.evaluation-context summary{padding:14px 16px;cursor:pointer;color:#486282;font-size:13px;line-height:1.8;overflow-wrap:anywhere}.evaluation-context summary>span{margin-left:12px;color:#7a8da4;font-size:12px}.evaluation-context summary>small{float:right;color:#8a9ab0;font-size:11px}.context-caption{margin:0;padding:0 16px 12px;color:#8391a5;font-size:11px;line-height:1.8}.context-records{max-height:330px;overflow:auto;padding:0 16px 14px;overscroll-behavior:contain}.context-summary,.context-turn{background:#fff;border:1px solid #e8edf4;border-radius:8px;padding:12px 14px;margin-bottom:10px}.context-records>:last-child{margin-bottom:0}.context-records h4{margin:0 0 10px;font-size:12px;color:#617794}.context-records p{margin:0;white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px;line-height:1.8;color:#43546c}.context-turn>div{display:grid;grid-template-columns:35px minmax(0,1fr);gap:10px}.context-turn>div+div{margin-top:10px}.context-turn>div>span{font-size:11px;line-height:2;color:#8494a9}.context-summary{background:#f3f7fc}.empty-context{margin:0;padding:12px 16px;color:#8794a7;font-size:12px;line-height:1.8}@media(max-width:600px){.evaluation-context summary>small{float:none;display:block;margin-left:14px}.context-records{padding:0 10px 10px}.context-turn>div{grid-template-columns:28px minmax(0,1fr);gap:6px}}
</style>
