<script setup lang="ts">
import { useRoute, useRouter } from 'vue-router'
import { firstPage } from './router'
defineProps<{ title:string }>()
const route = useRoute(), router = useRouter()
function goBack() {
  if (router.options.history.state.back) router.back()
  else void router.replace(firstPage())
}
</script>
<template>
  <header class="section-header">
    <button v-if="route.path !== firstPage() || router.options.history.state.back" type="button" aria-label="返回上一页" @click="goBack"><van-icon name="arrow-left" /></button>
    <h1>{{ title }}</h1><div v-if="$slots.default" class="section-action"><slot /></div>
  </header>
</template>
