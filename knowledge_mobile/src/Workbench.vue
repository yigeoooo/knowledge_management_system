<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ArrowRight, TopRight, Refresh } from '@element-plus/icons-vue'
import { api, session } from '@web/lib/session'
import { iconFor, visible } from './pages'
const stats = ref<Record<string, number>>({}), error = ref('')
const chats = computed(() => visible.value.filter(p => ['KnowledgeQA','RobotQA'].includes(p.component_key)))
const tools = computed(() => visible.value.filter(p => !['Dashboard','Profile','KnowledgeQA','RobotQA'].includes(p.component_key)))
const metrics: Record<string,string> = { RobotManagement: 'robot_count', UserManagement: 'user_count' }
async function load() {
  error.value = ''
  try { stats.value = await api('/dashboard') } catch(e) { error.value = (e as Error).message }
}
onMounted(load)
</script>
<template>
  <div class="workbench">
    <header class="work-title"><small>{{ new Date().toLocaleDateString('zh-CN',{month:'long',day:'numeric',weekday:'long'}) }}</small><h1>{{ session.user?.display_name }}的工作台</h1></header>
    <section v-if="chats.length" class="chat-entries" aria-label="开始问答">
      <RouterLink v-for="p in chats" :key="p.code" :to="p.route_path" :class="['chat-entry', { featured: p.component_key === 'KnowledgeQA' }]">
        <span class="entry-top"><component :is="iconFor(p)" /><TopRight /></span>
        <strong>{{ p.name }}</strong>
      </RouterLink>
    </section>
    <section v-if="tools.length" class="tool-list">
      <h2>管理与记录</h2>
      <RouterLink v-for="p in tools" :key="p.code" :to="p.route_path"><i><component :is="iconFor(p)" /></i><span>{{ p.name }}</span><small v-if="metrics[p.component_key] && stats[metrics[p.component_key]] != null">{{ stats[metrics[p.component_key]] }} {{ p.component_key === 'UserManagement' ? '人' : '台' }}</small><ArrowRight /></RouterLink>
    </section>
    <p v-if="error" class="form-error" role="alert">{{ error }} <button @click="load"><Refresh />重试</button></p>
  </div>
</template>
