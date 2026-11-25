<script setup lang="ts">
import { session } from '@web/lib/session'
</script>
<template>
  <section class="mobile-profile">
    <header class="record-page-title"><h1>个人信息</h1></header>
    <div class="profile-person"><span>{{ session.user?.display_name.slice(0, 1) }}</span><div><h2>{{ session.user?.display_name }}</h2><small>{{ session.user?.role_name }}</small></div></div>
    <van-cell-group><van-cell title="用户名" :value="session.user?.username" /><van-cell title="角色" :value="session.user?.role_name" /></van-cell-group>
    <van-cell-group title="已授权页面"><div class="profile-pages"><van-tag v-for="page in session.pages" :key="page.code" plain>{{ page.name }}</van-tag></div></van-cell-group>
    <p class="record-note">如需修改账号信息或密码，请联系平台管理员。</p>
  </section>
</template>
