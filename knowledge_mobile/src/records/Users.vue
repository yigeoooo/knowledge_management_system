<script setup lang="ts">
import Users from '@web/views/UsersView.vue'
import { session } from '@web/lib/session'
import RecordRow from './RecordRow.vue'
</script>
<template>
  <Users>
    <template #records="{ rows, details, edit, toggle, remove, protectedUser, busy }">
      <RecordRow v-for="row in rows" :key="row.id" :title="row.display_name" :subtitle="row.username"
        :badge="row.status === 'active' ? '启用' : '停用'" :inactive="row.status !== 'active'" :open="() => details(row)"
        :actions="[
          { name:'详情', run:() => details(row), disabled:busy },
          { name:'编辑', run:() => edit(row), disabled:busy },
          { name:row.status === 'active' ? '停用账号' : '启用账号', run:() => toggle(row), disabled:busy || protectedUser(row) },
          { name:'删除', run:() => remove(row), disabled:busy || protectedUser(row), color:'var(--el-color-danger)' },
        ]">
        <span>{{ row.role_name }}</span><span v-if="row.id === session.user?.id">本人</span>
      </RecordRow>
    </template>
  </Users>
</template>
