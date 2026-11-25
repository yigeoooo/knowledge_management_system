<script setup lang="ts">
import ChoiceSheet from '../ChoiceSheet.vue'
const props = defineProps<{
  placeholder: string; maxlength?: number; statusLabel?: string; bases?: { id:string; name:string }[]
}>()
const query = defineModel<string>('query', { required:true })
const status = defineModel<string>('status', { default:'' })
const base = defineModel<string>('base', { default:'' })
const emit = defineEmits<{ search: []; reset: [] }>()
const statuses = [{value:'',text:'全部状态'}, {value:'active',text:'启用'}, {value:'disabled',text:'停用'}]
</script>
<template>
  <div class="record-filters">
    <div class="record-search">
      <van-search v-model="query" :maxlength="maxlength" :placeholder="placeholder" :aria-label="placeholder"
        @search="emit('search')" @clear="emit('search')" />
      <van-button size="small" @click="emit('search')">查询</van-button>
    </div>
    <div v-if="props.bases || statusLabel || query" class="filter-choices">
      <ChoiceSheet v-if="bases" v-model="base" label="知识库" placeholder="全部知识库" searchable
        :options="[{value:'',text:'全部知识库'}, ...bases.map(item => ({value:item.id,text:item.name}))]" @update:model-value="emit('search')" />
      <ChoiceSheet v-if="statusLabel" v-model="status" :label="statusLabel" placeholder="全部状态"
        :options="statuses" @update:model-value="emit('search')" />
      <button v-if="query || status || base" type="button" class="filter-reset" @click="emit('reset')">重置</button>
    </div>
  </div>
</template>
