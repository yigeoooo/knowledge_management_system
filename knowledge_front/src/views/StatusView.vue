<script setup lang="ts">
import { session } from "../lib/session";
import { entryPath } from "../router";
</script>
<template>
  <main class="status-page">
    <el-result
      :icon="$route.path === '/403' ? 'warning' : 'info'"
      :title="$route.path === '/403' ? '暂无访问权限' : '页面未找到'"
      sub-title="你可以返回首页，或联系管理员确认页面访问权限。"
    >
      <template #extra>
        <el-button @click="$router.push('/')">返回首页</el-button>
        <el-button
          v-if="session.user && entryPath() !== '/403'"
          type="primary"
          @click="$router.push(entryPath())"
        >
          进入工作空间
        </el-button>
        <el-button
          v-else-if="!session.user"
          type="primary"
          @click="$router.push('/login')"
        >
          登录平台
        </el-button>
      </template>
    </el-result>
  </main>
</template>
