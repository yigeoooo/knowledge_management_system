<script setup lang="ts">
import RecordPager from './RecordPager.vue'
defineProps<{
  title: string; listTitle: string; createLabel?: string; notice?: string; busy?: boolean; total:number
  page:number; size:number; sizes?:number[]; loading:boolean; error:string
}>()
const emit = defineEmits<{ create: []; refresh: []; page: [number]; size: [number] }>()
</script>
<template>
  <section class="record-page">
    <header class="record-page-title"><h1>{{ title }}</h1>
      <van-button v-if="createLabel" type="primary" size="small" icon="plus" :disabled="busy" @click="emit('create')">{{ createLabel }}</van-button>
    </header>
    <slot name="filters" />
    <header class="record-section-title"><h2>{{ listTitle }} <span>{{ total }}</span></h2>
      <van-button size="small" icon="replay" :loading="loading" aria-label="刷新列表" @click="emit('refresh')" />
    </header>
    <div class="record-group" :aria-busy="loading">
      <p v-if="error" role="alert" class="form-error">{{ error }}</p>
      <slot />
      <van-empty v-if="!loading && !total" :description="error ? '加载失败，请刷新重试' : '暂无匹配记录'" :image-size="64" />
      <p v-if="loading && !total" class="records-loading" role="status">加载中…</p>
    </div>
    <RecordPager :page="page" :size="size" :total="total" :sizes="sizes" @page="emit('page', $event)" @size="emit('size', $event)" />
    <p v-if="notice" class="record-note"><van-icon name="info-o" />{{ notice }}</p>
  </section>
</template>
