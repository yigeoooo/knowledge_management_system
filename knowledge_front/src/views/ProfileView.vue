<script setup lang="ts">
import { session } from "../lib/session";
</script>
<template>
  <div class="page-heading">
    <div>
      <div class="page-eyebrow">YOUR ACCOUNT</div>
      <h1>个人信息</h1>
      <p>查看你的账号与平台访问权限。</p>
    </div>
  </div>
  <el-card
    shadow="never"
    class="profile-card"
  >
    <div class="profile-heading">
      <el-avatar :size="76">{{ session.user?.display_name.slice(0, 1).toUpperCase() }}</el-avatar>
      <div>
        <h2>{{ session.user?.display_name }}</h2>
        <el-tag>{{ session.user?.role_name }}</el-tag>
      </div>
    </div>
    <el-descriptions
      :column="1"
      border
    >
      <el-descriptions-item label="用户名">{{ session.user?.username }}</el-descriptions-item>
      <el-descriptions-item label="角色">{{ session.user?.role_name }}</el-descriptions-item>
      <el-descriptions-item label="已授权页面">
        <div class="profile-tags">
          <el-tag
            v-for="page in session.pages"
            :key="page.code"
            type="info"
            effect="plain"
          >
            {{ page.name }}
          </el-tag>
        </div>
      </el-descriptions-item>
    </el-descriptions>
    <el-alert
      title="如需修改账号信息或密码，请联系平台管理员。"
      type="info"
      :closable="false"
      show-icon
    />
  </el-card>
</template>
