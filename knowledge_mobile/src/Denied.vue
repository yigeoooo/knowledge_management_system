<script setup lang="ts">
import { firstPage } from './router'
</script>
<template>
  <van-empty image="error" description="当前账号无法打开此页面">
    <van-button v-if="firstPage() !== '/403'" type="primary" @click="$router.replace(firstPage())">返回工作区</van-button>
  </van-empty>
</template>
