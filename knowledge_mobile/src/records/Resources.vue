<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRoute } from "vue-router";
import { api } from "@web/lib/session";
import { queryParams } from "@web/lib/query";
import { resources } from "@web/lib/resources";

import RecordPage from './RecordPage.vue'
import RecordFilters from './RecordFilters.vue'
import RecordRow from './RecordRow.vue'

const route = useRoute();
const config = computed(() => resources[route.path]!);
const rows = ref<Record<string, unknown>[]>([]);
const total = ref(0);
const page = ref(1);
const query = ref("");
const status = ref("");
const loading = ref(false);
const error = ref("");
let generation = 0;

async function load() {
  const current = ++generation;
  const path = route.path;
  loading.value = true;
  error.value = "";
  try {
    const params = queryParams({
      page: String(page.value),
      page_size: "20",
      q: query.value,
      status: status.value,
    });
    const result = await api<{ items: Record<string, unknown>[]; total?: number }>(
      `${path}?${params}`,
    );
    if (current !== generation) return;
    const items = result.items;
    rows.value = items;
    total.value = result.total ?? items.length;
  } catch (value) {
    if (current === generation) error.value = value instanceof Error ? value.message : "加载失败";
  } finally {
    if (current === generation) loading.value = false;
  }
}

function search() {
  page.value = 1;
  void load();
}

function format(value: unknown, prop: string) {
  if (typeof value === "boolean") return value ? "是" : "否";
  if (prop === "source_type") {
    const source = String(value || "").toUpperCase();
    return source === "WEB" ? "网页（WEB）" : source === "ROBOT" ? "机器人（ROBOT）" : value || "—";
  }
  if (typeof value === "string" && prop.endsWith("_at")) {
    return new Date(value).toLocaleString("zh-CN", { hour12: false });
  }
  return value ?? "—";
}

function statusText(value: unknown) {
  return (
    {
      active: "启用",
      disabled: "停用",
      archived: "已归档",
      PROCESSING: "处理中",
      SUCCESS: "成功",
      PARTIAL: "部分有依据",
      NO_EVIDENCE: "依据不足",
      SOURCES_ONLY: "仅返回资料",
      FAILED: "失败",
    } as Record<string, string>
  )[String(value)] || String(value);
}

onMounted(load);
</script>

<template>
  <RecordPage :title="config.title" list-title="记录" :total="total" :page="page" :size="20" :loading="loading" :error="error"
    @refresh="load" @page="page = $event; load()">
    <template #filters>
      <RecordFilters :placeholder="config.search" v-model:query="query" v-model:status="status" :status-label="config.status ? '状态' : undefined"
        @search="search" @reset="query = ''; status = ''; search()" />
    </template>
    <RecordRow v-for="row in rows" :key="String(row.id)" :title="String(row[config.columns[0].prop] || '—')"
      :badge="row.status ? statusText(row.status) : ''" :inactive="row.status !== 'active'">
      <dl class="record-fields">
        <template v-for="column in config.columns.slice(1)" :key="column.prop">
          <template v-if="column.prop !== 'status'"><dt>{{ column.label }}</dt><dd>{{ format(row[column.prop],column.prop) }}</dd></template>
        </template>
      </dl>
    </RecordRow>
  </RecordPage>
</template>
