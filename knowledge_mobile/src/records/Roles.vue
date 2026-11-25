<script setup lang="ts">
import Roles from '@web/views/RoleManagementView.vue'
import RecordRow from './RecordRow.vue'
</script>
<template>
  <Roles>
    <template #records="{ rows, edit, toggle, remove, busy }">
      <RecordRow v-for="row in rows" :key="row.id" :title="row.name" :subtitle="row.code"
        :badge="row.status === 'active' ? '启用' : '停用'" :inactive="row.status !== 'active'"
        :actions="[
          { name:'编辑', run:() => edit(row), disabled:busy },
          { name:row.status === 'active' ? '停用角色' : '启用角色', run:() => toggle(row), disabled:busy || row.code === 'super_admin' },
          { name:'删除', run:() => remove(row), disabled:busy || row.code === 'super_admin', color:'var(--el-color-danger)' },
        ]">
        <span>{{ row.is_system ? '系统角色' : '自定义角色' }}</span><span>{{ row.user_count }} 位用户</span>
        <small>更新于 {{ new Date(row.updated_at).toLocaleString('zh-CN', {hour12:false}) }}</small>
      </RecordRow>
    </template>
  </Roles>
</template>
