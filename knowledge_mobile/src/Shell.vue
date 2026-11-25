<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { showConfirmDialog, showFailToast } from 'vant'

import { App } from '@capacitor/app'
import type { PluginListenerHandle } from '@capacitor/core'
import { logout, refresh, clearSession, ApiError, session } from '@web/lib/session'
import { visible, mobileIcon } from './pages'
import { native } from './network'
import { firstPage, syncPages } from './router'
import logo from '../../knowledge_front/public/brand/dexforce-logo.svg?url'
const route = useRoute(), router = useRouter(), menu = ref(false), content = ref<HTMLElement>()
const tabs = computed(() => ['Dashboard','KnowledgeQA','Profile'].flatMap(key => visible.value.filter(p => p.component_key === key)))
const labels: Record<string,string> = { Dashboard:'工作台', KnowledgeQA:'问答', Profile:'我的' }
const chat = computed(() => ['KnowledgeQA','RobotQA'].includes(String(route.meta.key)))
const listeners: PluginListenerHandle[] = []
async function signOut() {
  try { await showConfirmDialog({title:'退出登录',message:'要退出当前账号吗？',confirmButtonText:'退出'}) } catch { return }
  try { await logout(); menu.value = false; await router.replace('/login') } catch(e) { showFailToast((e as Error).message) }
}
watch(() => route.fullPath, async () => { menu.value = false; await nextTick(); content.value?.scrollTo(0,0) })
onMounted(async () => {
  if (!native) return
  listeners.push(await App.addListener('appStateChange', async ({ isActive }) => {
    if (!isActive || !session.user) return
    try {
      await refresh()
      if (syncPages()) await router.replace(session.pages.some(p => p.route_path === route.path) ? route.fullPath : firstPage())
    } catch(e) {
      if (e instanceof ApiError && e.status === 401) { clearSession(); await router.replace('/login') }
    }
  }))
  listeners.push(await App.addListener('backButton', ({ canGoBack }) => {
    const confirm = document.querySelector<HTMLButtonElement>('.van-dialog:not([style*="display: none"]) .van-dialog__cancel')
    if (confirm) { confirm.click(); return }
    const sheet = [...document.querySelectorAll<HTMLButtonElement>('.van-action-sheet__cancel')].find(el => el.getClientRects().length)
    if (sheet) { sheet.click(); return }
    const overlay = [...document.querySelectorAll<HTMLElement>('.el-overlay')].reverse().find(el => el.getClientRects().length)
    if (overlay) { document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',code:'Escape',bubbles:true})); return }
    if (menu.value) menu.value = false
    else if (canGoBack) router.back()
    else if (session.user && route.path !== firstPage()) void router.replace(firstPage())
    else void App.minimizeApp()
  }))
})
onUnmounted(() => listeners.forEach(handle => { void handle.remove() }))
</script>
<template>
  <RouterView v-if="!session.user" />
  <div v-else class="phone-app">
    <header class="app-bar"><img :src="logo" alt="跨维智能" class="brand-logo"><span>知识平台</span><button aria-label="退出登录" title="退出登录" @click="signOut"><van-icon name="revoke" size="21" /></button></header>
    <main ref="content" :class="['phone-content',{ chatting:chat }]"><RouterView :key="route.path" /></main>
    <van-tabbar :fixed="false" safe-area-inset-bottom :model-value="menu || !tabs.some(p => p.route_path === route.path) ? 'features' : route.path" aria-label="主导航">
      <van-tabbar-item v-for="p in tabs" :key="p.code" :name="p.route_path" :to="p.route_path" :icon="mobileIcon(p)">{{ labels[p.component_key] }}</van-tabbar-item>
      <van-tabbar-item name="features" icon="apps-o" :aria-expanded="menu" @click="menu = true">全部功能</van-tabbar-item>
    </van-tabbar>
    <van-popup v-model:show="menu" position="bottom" round safe-area-inset-bottom teleport="body" class="features-sheet" aria-label="全部功能">
      <header><h2>全部功能</h2><van-button size="small" icon="cross" aria-label="关闭菜单" @click="menu = false" /></header>
      <nav class="features">
        <RouterLink v-for="p in visible" :key="p.code" :to="p.route_path" @click="menu = false">
          <van-icon :name="mobileIcon(p)" /><span>{{ p.name }}</span>
        </RouterLink>
      </nav>
    </van-popup>
  </div>
</template>
