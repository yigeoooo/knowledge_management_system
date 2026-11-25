<script setup lang="ts">
import Management from '@web/views/ManagementView.vue'
import RecordRow from './RecordRow.vue'
</script>
<template>
  <Management>
    <template #records="{ rows, columns, format, statusText }">
      <RecordRow v-for="row in rows" :key="String(row.id)" :title="String(row[columns[0].prop] || '—')"
        :badge="row.status ? statusText(row.status) : ''" :inactive="row.status !== 'active'">
        <dl class="record-fields">
          <template v-for="column in columns.slice(1)" :key="column.prop">
            <template v-if="column.prop !== 'status'"><dt>{{ column.label }}</dt><dd>{{ format(row[column.prop],column.prop) }}</dd></template>
          </template>
        </dl>
      </RecordRow>
    </template>
  </Management>
</template>
