<script setup lang="ts">
import { useRouter } from 'vue-router'
import { showConfirmDialog, showFailToast } from 'vant'
import { logout } from '@web/lib/session'

const router = useRouter()
async function signOut() {
  try {
    await showConfirmDialog({title:'退出登录', message:'要退出当前账号吗？', confirmButtonText:'退出'})
  } catch { return }
  try {
    await logout()
    await router.replace('/login')
  } catch (e) { showFailToast((e as Error).message) }
}
</script>
<template><van-button class="sign-out" block icon="revoke" @click="signOut">退出登录</van-button></template>
