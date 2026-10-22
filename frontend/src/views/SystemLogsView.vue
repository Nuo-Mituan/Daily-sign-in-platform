<template>
  <div class="page-shell system-logs-page">
    <header class="page-header">
      <div>
        <span class="eyebrow">SYSTEM OBSERVABILITY</span>
        <h1 class="page-title">系统日志</h1>
        <p class="page-subtitle">只读查询应用、模块与推送审计日志；不支持任何写入操作。</p>
      </div>
      <el-button :loading="loading" @click="loadLogs"><el-icon><Refresh /></el-icon>刷新</el-button>
    </header>

    <section class="panel">
      <div class="panel-head">
        <div>
          <div class="panel-title">环形日志</div>
          <div class="panel-desc">按 seq 倒序分页；文本已脱敏。队列深度：{{ metrics.sse?.current_queue_depth ?? '—' }}，丢弃：{{ metrics.sse?.dropped_chunks ?? '—' }}</div>
        </div>
        <div class="filters">
          <el-select v-model="scope" clearable placeholder="全部域" size="small" @change="reload">
            <el-option label="系统" value="system" />
            <el-option label="模块" value="module" />
            <el-option label="推送" value="push" />
          </el-select>
          <el-select v-model="level" clearable placeholder="全部级别" size="small" @change="reload">
            <el-option label="INFO / OUT" value="INFO" />
            <el-option label="WARNING" value="WARNING" />
            <el-option label="STDOUT" value="STDOUT" />
            <el-option label="ERROR" value="ERROR" />
          </el-select>
        </div>
      </div>
      <div class="panel-body">
        <el-table :data="logs" class="log-table">
          <el-table-column label="seq" width="92" prop="seq" />
          <el-table-column label="时间" width="190" prop="created_at" />
          <el-table-column label="域" width="90" prop="scope_type" />
          <el-table-column label="级别" width="90" prop="level" />
          <el-table-column label="内容" min-width="400">
            <template #default="{ row }"><pre class="log-text">{{ row.text }}</pre></template>
          </el-table-column>
        </el-table>
        <div v-if="total > pageSize" class="pagination-row">
          <el-pagination v-model:current-page="page" :page-size="pageSize" :total="total" layout="prev, pager, next" background @current-change="loadLogs" />
        </div>
      </div>
    </section>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { Refresh } from '@element-plus/icons-vue'
import { systemApi } from '@/api'

const logs = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = 50
const scope = ref('system')
const level = ref('')
const loading = ref(false)
const metrics = ref({})

async function loadLogs() {
  loading.value = true
  try {
    const data = await systemApi.systemLogs({
      page: page.value,
      page_size: pageSize,
      scope_type: scope.value || undefined,
      level: level.value || undefined,
    })
    logs.value = data.items
    total.value = data.total
  } finally {
    loading.value = false
  }
}

function reload() {
  page.value = 1
  loadLogs()
}

onMounted(async () => {
  await Promise.all([loadLogs(), systemApi.metrics().then((data) => { metrics.value = data }).catch(() => {})])
})
</script>

<style scoped>
.system-logs-page { padding-top: 30px; }
.filters { display: flex; gap: 8px; }
.filters :deep(.el-select) { width: 120px; }
.log-table { width: 100%; }
.log-text { max-width: 760px; margin: 0; white-space: pre-wrap; word-break: break-word; font-size: 9.5px; line-height: 1.6; color: #66708a; }
@media (max-width: 720px) { .system-logs-page { padding-top: 20px; } .panel-head { align-items: flex-start; flex-direction: column; gap: 10px; } }
</style>
