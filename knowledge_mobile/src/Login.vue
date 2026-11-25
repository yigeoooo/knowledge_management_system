<script setup lang="ts">
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowRight, View, Hide } from '@element-plus/icons-vue'
import { login, session } from '@web/lib/session'
import { firstPage, syncPages } from './router'
import logo from '../../knowledge_front/public/brand/dexforce-logo.svg?url'
const route = useRoute(), router = useRouter()
const account = ref(''), password = ref(''), shown = ref(false), busy = ref(false), error = ref('')
async function submit() {
  if (busy.value) return
  error.value = ''; busy.value = true
  try {
    await login(account.value.trim(), password.value)
    password.value = ''; syncPages()
    const dest = typeof route.query.redirect === 'string' ? route.query.redirect : ''
    await router.replace(dest && session.pages.some(p => p.route_path === dest.split('?')[0]) ? dest : firstPage())
  } catch (e) { error.value = (e as Error).message }
  finally { busy.value = false }
}
</script>
<template>
  <main class="login-screen">
    <img :src="logo" class="brand-logo" alt="跨维智能 DEXFORCE">
    <div class="login-title"><h1>登录知识平台</h1></div>
    <form class="login-fields" @submit.prevent="submit">
      <label>用户名<input v-model="account" required name="username" autocomplete="username" placeholder="输入用户名" autocapitalize="none"></label>
      <label>密码<span class="password-field"><input v-model="password" required :type="shown ? 'text' : 'password'" name="password" autocomplete="current-password" placeholder="输入密码"><button type="button" :aria-label="shown ? '隐藏密码' : '显示密码'" @click="shown = !shown"><component :is="shown ? Hide : View" /></button></span></label>
      <p v-if="error" class="form-error" role="alert">{{ error }}</p>
      <button class="primary-action" :disabled="busy">{{ busy ? '正在登录' : '登录' }}<ArrowRight /></button>
    </form>
  </main>
</template>
