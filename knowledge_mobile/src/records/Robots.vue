<script setup lang="ts">
import Robots from '@web/views/RobotManagementView.vue'
import RecordRow from './RecordRow.vue'
</script>
<template>
  <Robots>
    <template #records="{ rows, details, edit, disable, busy }">
      <RecordRow v-for="row in rows" :key="row.id" :title="row.name || '未命名机器人'" :subtitle="row.serial_no"
        :badge="row.status === 'active' ? '启用' : '停用'" :inactive="row.status !== 'active'" :open="() => details(row)"
        :actions="[
          { name:'详情', run:() => details(row) },
          { name:'编辑', run:() => edit(row), disabled:busy },
          ...(row.status === 'active' ? [{ name:'停用', run:() => disable(row), disabled:busy, color:'var(--el-color-danger)' }] : []),
        ]">
        <span>知识库 · {{ row.knowledge_base_name || '待绑定' }}</span>
        <span>{{ row.default_location_name || row.default_location || '城市未设置' }}</span>
      </RecordRow>
    </template>
  </Robots>
</template>
