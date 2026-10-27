<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useRoute } from "vue-router";
import { ElMessage } from "element-plus";
import { FolderOpened, Plus, Refresh, Search } from "@element-plus/icons-vue";
import { api } from "../lib/session";
import { queryParams } from "../lib/query";
import { resources } from "../lib/resources";
import MarkdownContent from "../components/MarkdownContent.vue";
import SourceContent from "../components/SourceContent.vue";

interface QASource {
  source_id?: string;
  document_title?: string;
  filename?: string;
  heading_path?: string | null;
  content?: string | null;
  modality?: string;
  score?: number | null;
  version_no?: number;
}

interface QALogDetail {
  id: string;
  request_id: string;
  source_type: string;
  user_id: string | null;
  user_name: string | null;
  robot_id: string | null;
  robot_name: string | null;
  robot_serial_no: string | null;
  knowledge_base_id: string;
  knowledge_base_name: string | null;
  question: string;
  answer: string | null;
  sources: QASource[];
  retrieval_count: number | null;
  model_name: string | null;
  status: string;
  error_message: string | null;
  latency_ms: number | null;
  created_at: string;
  updated_at: string;
}

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

const detailOpen = ref(false);
const detailLoading = ref(false);
const detailError = ref("");
const detail = ref<QALogDetail | null>(null);
let detailGeneration = 0;

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
    let items = result.items;
    if (path === "/knowledge-bases") {
      items = items.filter(
        (item) =>
          `${item.name} ${item.code}`.includes(query.value) &&
          (!status.value || item.status === status.value),
      );
    }
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

function statusType(value: unknown) {
  if (["active", "SUCCESS"].includes(String(value))) return "success";
  if (["PARTIAL", "PROCESSING", "SOURCES_ONLY"].includes(String(value))) return "warning";
  if (["FAILED"].includes(String(value))) return "danger";
  return "info";
}

function rowClass() {
  return config.value.detail ? "clickable-resource-row" : "";
}

async function openDetail(row: Record<string, unknown>) {
  if (!config.value.detail || typeof row.id !== "string") return;
  const current = ++detailGeneration;
  detailOpen.value = true;
  detailLoading.value = true;
  detailError.value = "";
  detail.value = null;
  try {
    const result = await api<QALogDetail>(`/qa-logs/${row.id}`);
    if (current === detailGeneration) detail.value = result;
  } catch (value) {
    if (current === detailGeneration) {
      detailError.value = value instanceof Error ? value.message : "详情加载失败";
      ElMessage.error(detailError.value);
    }
  } finally {
    if (current === detailGeneration) detailLoading.value = false;
  }
}

function closeDetail() {
  ++detailGeneration;
  detailOpen.value = false;
}

function sourceLabel(source: QASource) {
  if (source.modality === "image") return "图片资料";
  if (source.modality === "video") return "视频资料";
  return "文字资料";
}

watch(
  () => route.path,
  () => {
    query.value = "";
    status.value = "";
    page.value = 1;
    rows.value = [];
    closeDetail();
    void load();
  },
  { immediate: true },
);
</script>

<template>
  <div class="page-heading">
    <div>
      <div class="page-eyebrow">{{ config.english }}</div>
      <h1>{{ config.title }}</h1>
      <p>{{ config.description }}</p>
    </div>
    <el-tooltip v-if="config.action" content="页面框架已就绪，编辑功能将在后续开发中接入">
      <span><el-button type="primary" :icon="Plus" disabled>{{ config.action }}</el-button></span>
    </el-tooltip>
  </div>

  <el-alert class="phase-notice" title="当前支持查看与搜索，新增、编辑等功能将逐步开放。" type="info" show-icon :closable="false" />
  <el-card shadow="never" class="resource-card">
    <div class="table-toolbar">
      <el-input v-model="query" :placeholder="config.search" :prefix-icon="Search" clearable @keyup.enter="search" @clear="search" />
      <el-select v-if="config.status" v-model="status" placeholder="全部状态" clearable value-on-clear="" @change="search">
        <el-option label="启用" value="active" />
        <el-option label="停用" value="disabled" />
      </el-select>
      <el-button type="primary" plain @click="search">搜索</el-button>
      <el-button :icon="Refresh" :loading="loading" @click="load">刷新</el-button>
    </div>
    <el-alert v-if="error" :title="error" type="error" show-icon :closable="false" />
    <el-table v-loading="loading" :data="rows" style="width: 100%" :min-height="340" :row-class-name="rowClass" @row-click="openDetail">
      <el-table-column v-for="column in config.columns" :key="column.prop" :prop="column.prop" :label="column.label" :width="column.width" :min-width="column.width || 150" show-overflow-tooltip>
        <template #default="{ row }">
          <el-tag v-if="column.prop === 'status'" :type="statusType(row.status)" effect="light">{{ statusText(row.status) }}</el-tag>
          <span v-else>{{ format(row[column.prop], column.prop) }}</span>
        </template>
      </el-table-column>
      <el-table-column v-if="config.detail" label="操作" width="100" fixed="right">
        <template #default="{ row }"><el-button type="primary" link @click.stop="openDetail(row)">查看详情</el-button></template>
      </el-table-column>
      <template #empty>
        <el-empty :description="error ? '暂时无法加载数据，请点击刷新重试' : query || status ? '没有找到匹配的记录' : '暂无记录，期待第一份内容'" :image-size="80">
          <template #image><el-icon :size="70" color="#c6c8ce"><FolderOpened /></el-icon></template>
        </el-empty>
      </template>
    </el-table>
    <div class="table-pagination"><span>共 {{ total }} 条记录</span><el-pagination v-model:current-page="page" :page-size="20" :total="total" layout="prev, pager, next" @current-change="load" /></div>
  </el-card>

  <el-dialog v-model="detailOpen" title="问答记录详情" width="780px" align-center destroy-on-close class="qa-detail-dialog" @closed="closeDetail">
    <div v-loading="detailLoading" class="qa-detail-body">
      <el-alert v-if="detailError" :title="detailError" type="error" show-icon :closable="false" />
      <template v-if="detail">
        <div class="qa-detail-summary"><el-tag :type="statusType(detail.status)" effect="light">{{ statusText(detail.status) }}</el-tag><span>{{ detail.source_type === "ROBOT" ? "机器人提问" : "网页提问" }}</span><span>{{ format(detail.created_at, "created_at") }}</span></div>
        <div class="qa-detail-meta">
          <div><span>请求编号</span><strong>{{ detail.request_id }}</strong></div>
          <div><span>知识库</span><strong>{{ detail.knowledge_base_name || detail.knowledge_base_id }}</strong></div>
          <div><span>耗时</span><strong>{{ detail.latency_ms == null ? "—" : `${detail.latency_ms} ms` }}</strong></div>
          <div><span>召回切片</span><strong>{{ detail.retrieval_count ?? "—" }}</strong></div>
          <div><span>回答模型</span><strong>{{ detail.model_name || "—" }}</strong></div>
          <div><span>提问人</span><strong>{{ detail.user_name || detail.robot_name || "—" }}</strong></div>
        </div>
        <section class="qa-detail-section"><h3>问题</h3><div class="qa-detail-text">{{ detail.question }}</div></section>
        <section class="qa-detail-section"><h3>回答</h3><MarkdownContent v-if="detail.answer" class="qa-detail-text qa-answer" :content="detail.answer" /><el-empty v-else description="本次没有生成回答" :image-size="60" /><el-alert v-if="detail.error_message" class="qa-detail-error" :title="detail.error_message" type="error" :closable="false" /></section>
        <section class="qa-detail-section"><h3>引用资料 <small>{{ detail.sources.length }} 条</small></h3><div v-if="detail.sources.length" class="qa-source-list"><article v-for="(source, index) in detail.sources" :key="source.source_id || index" class="qa-source-card"><div class="qa-source-heading"><strong>{{ source.source_id || index + 1 }}. {{ source.document_title || source.filename || "未命名资料" }}</strong><span>{{ sourceLabel(source) }}<template v-if="source.score != null"> · 匹配度 {{ source.score }}</template></span></div><div v-if="source.heading_path" class="qa-source-path">{{ source.heading_path }}</div><SourceContent v-if="source.content" class="qa-source-content" :content="source.content" :filename="source.filename" /></article></div><el-empty v-else description="本次没有引用资料" :image-size="60" /></section>
      </template>
    </div>
    <template #footer><el-button @click="detailOpen = false">关闭</el-button></template>
  </el-dialog>
</template>
