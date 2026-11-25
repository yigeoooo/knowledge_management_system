<script setup lang="ts">
import ChoiceSheet from '../ChoiceSheet.vue'
defineProps<{page:number; size:number; total:number; sizes?: number[]}>()
const emit = defineEmits<{page:[number]; size:[number]}>()
</script>
<template>
  <footer v-if="total > size || (sizes && total > sizes[0]) || (sizes && size !== 20)" class="record-pager">
    <ChoiceSheet v-if="sizes" :model-value="String(size)" label="每页条数" placeholder="每页条数"
      :options="sizes.map(n => ({value:String(n),text:n + ' 条/页'}))" @update:model-value="emit('size', Number($event))" />
    <van-pagination v-if="total > size" :model-value="page" :total-items="total" :items-per-page="size" mode="simple"
      @update:model-value="emit('page', $event)">
      <template #prev-text><van-icon name="arrow-left" aria-label="上一页" /></template>
      <template #next-text><van-icon name="arrow" aria-label="下一页" /></template>
    </van-pagination>
  </footer>
</template>
