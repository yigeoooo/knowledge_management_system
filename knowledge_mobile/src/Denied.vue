<script setup lang="ts">
import { firstPage } from './router'
</script>
<template><el-result icon="warning" title="当前账号无法打开此页面"><template #extra><el-button v-if="firstPage() !== '/403'" @click="$router.replace(firstPage())">返回工作区</el-button></template></el-result></template>
