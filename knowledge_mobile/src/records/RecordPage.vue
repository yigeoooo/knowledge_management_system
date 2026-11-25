<script setup lang="ts">
import PageHeader from '../PageHeader.vue'
import RecordPager from './RecordPager.vue'
defineProps<{
  title: string; listTitle: string; createLabel?: string; emptyText?: string; filtered?: boolean; emptyIcon?: string; busy?: boolean; total:number
  page:number; size:number; sizes?:number[]; loading:boolean; error:string
}>()
const emit = defineEmits<{ create: []; refresh: []; reset: []; page: [number]; size: [number] }>()
</script>
<template>
  <section class="record-page">
    <PageHeader :title="title">
      <van-button v-if="createLabel" type="primary" size="small" icon="plus" :disabled="busy" @click="emit('create')">{{ createLabel }}</van-button>
    </PageHeader>
    <slot name="filters" />
    <header class="record-section-title"><h2>{{ listTitle }} <span>{{ total }}</span></h2>
      <van-button size="small" icon="replay" :loading="loading" aria-label="刷新列表" @click="emit('refresh')" />
    </header>
    <div class="record-group" :aria-busy="loading">
      <p v-if="error" role="alert" class="form-error">{{ error }}</p>
      <slot />
      <div v-if="!loading && !total && !error" class="record-empty">
        <van-icon :name="filtered ? 'search' : emptyIcon || 'records-o'" />
        <p>{{ filtered ? '没有符合条件的记录' : emptyText || '暂无记录' }}</p>
        <van-button v-if="filtered" size="small" @click="emit('reset')">清除筛选</van-button>
        <van-button v-else-if="createLabel" size="small" :disabled="busy" @click="emit('create')">{{ createLabel }}</van-button>
      </div>
      <p v-if="loading && !total" class="records-loading" role="status">加载中…</p>
    </div>
    <RecordPager :page="page" :size="size" :total="total" :sizes="sizes" @page="emit('page', $event)" @size="emit('size', $event)" />
  </section>
</template>
