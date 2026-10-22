<template>
  <div class="page-shell logs-page">
    <header class="page-header">
      <div>
        <span class="eyebrow">EXECUTION HISTORY</span>
        <h1 class="page-title">执行记录</h1>
        <p class="page-subtitle">查看所有模块的历史运行结果，点击记录可查看完整日志或实时输出。</p>
      </div>
      <div class="header-actions">
        <div class="auto-refresh">
          <span>自动刷新</span>
          <el-switch v-model="autoRefresh" size="small" />
        </div>
        <el-button :loading="loading" @click="loadLogs">
          <el-icon><Refresh /></el-icon>
          刷新
        </el-button>
      </div>
    </header>

    <div class="logs-toolbar">
      <div class="filter-item">
        <label class="filter-label">模块</label>
        <el-select
          v-model="moduleFilter"
          placeholder="全部模块"
          clearable
          class="filter-control module-filter"
          @change="handleFilterChange"
        >
          <el-option label="全部模块" value="" />
          <el-option
            v-for="item in modules"
            :key="item.id"
            :label="item.name"
            :value="item.id"
          />
        </el-select>
      </div>
      <div class="filter-item">
        <label class="filter-label">状态</label>
        <el-select
          v-model="statusFilter"
          placeholder="全部状态"
          clearable
          class="filter-control status-filter"
          @change="handleFilterChange"
        >
          <el-option label="全部状态" value="" />
          <el-option label="成功" value="success" />
          <el-option label="失败" value="failed" />
          <el-option label="执行中" value="running" />
        </el-select>
      </div>
      <div class="filter-item">
        <label class="filter-label">触发方式</label>
        <el-select
          v-model="triggerFilter"
          placeholder="全部方式"
          clearable
          class="filter-control trigger-filter"
          @change="handleFilterChange"
        >
          <el-option label="全部方式" value="" />
          <el-option label="定时执行" value="schedule" />
          <el-option label="手动执行" value="manual" />
          <el-option label="测试执行" value="test" />
        </el-select>
      </div>
      <button type="button" class="reset-filters" @click="resetFilters">
        <el-icon><RefreshLeft /></el-icon>
        重置
      </button>
      <span class="toolbar-summary">共 {{ total }} 条记录</span>
    </div>

    <section class="panel history-panel">
      <div class="panel-head history-head">
        <div>
          <div class="panel-title">运行历史</div>
          <div class="panel-desc">
            第 {{ page }} 页 · 每页 {{ pageSize }} 条
            <span v-if="autoRefresh" class="live-note"><i></i>每 10 秒自动刷新</span>
          </div>
        </div>
        <span class="records-chip">{{ total }} RECORDS</span>
      </div>
      <div class="panel-body history-body">
        <el-table
          v-if="logs.length"
          :data="logs"
          class="history-table"
          @row-click="openLog"
        >
          <el-table-column label="模块" min-width="190">
            <template #default="{ row }">
              <div class="module-cell">
                <span class="mini-avatar">{{ row.module_name.slice(0, 1) }}</span>
                <div class="module-copy">
                  <strong>{{ row.module_name }}</strong>
                  <span class="mono">{{ row.module_key }}</span>
                </div>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="触发" width="100">
            <template #default="{ row }">
              <span class="trigger-label">{{ triggerLabel(row.trigger) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="状态" width="100">
            <template #default="{ row }">
              <StatusTag :status="row.status" />
            </template>
          </el-table-column>
          <el-table-column label="开始时间" width="170">
            <template #default="{ row }">
              <div class="time-cell">
                <span>{{ formatDateTime(row.started_at) }}</span>
                <small>{{ timeFromNow(row.started_at) }}</small>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="耗时" width="92">
            <template #default="{ row }">
              <span class="duration">{{ formatDuration(row.duration_ms) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="结果" min-width="250">
            <template #default="{ row }">
              <span class="result-message">{{ row.message || '—' }}</span>
            </template>
          </el-table-column>
          <el-table-column width="42" align="right">
            <template #default>
              <el-icon class="row-arrow"><ArrowRight /></el-icon>
            </template>
          </el-table-column>
        </el-table>

        <div v-else class="empty-state">
          <div class="empty-state__icon"><el-icon><Tickets /></el-icon></div>
          <div class="empty-state__title">没有匹配的执行记录</div>
          <div class="empty-state__desc">
            {{ hasFilters ? '试试调整筛选条件，或重置后查看全部记录。' : '模块执行后，历史记录会显示在这里。' }}
          </div>
          <el-button v-if="hasFilters" text type="primary" class="reset-empty" @click="resetFilters">
            重置筛选
          </el-button>
        </div>

        <div v-if="total > pageSize" class="pagination-row">
          <span class="pagination-note">第 {{ page }} / {{ Math.max(1, Math.ceil(total / pageSize)) }} 页</span>
          <el-pagination
            v-model:current-page="page"
            :page-size="pageSize"
            :total="total"
            layout="prev, pager, next"
            background
            @current-change="loadLogs"
          />
        </div>
      </div>
    </section>

    <RunLogDrawer
      v-model="logDrawerOpen"
      :log-id="selectedLogId"
      :title="selectedTitle"
      @finished="loadLogs"
    />
  </div>
</template>

<script setup>
import {
  computed,
  onBeforeUnmount,
  onMounted,
  ref,
  watch,
} from 'vue'
import {
  ArrowRight,
  Refresh,
  RefreshLeft,
  Tickets,
} from '@element-plus/icons-vue'
import StatusTag from '@/components/StatusTag.vue'
import RunLogDrawer from '@/components/RunLogDrawer.vue'
import { logsApi, modulesApi } from '@/api'
import {
  formatDateTime,
  formatDuration,
  timeFromNow,
  triggerLabel,
} from '@/utils/format'

const modules = ref([])
const logs = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = 15
const loading = ref(false)
const autoRefresh = ref(false)
const moduleFilter = ref('')
const statusFilter = ref('')
const triggerFilter = ref('')

const logDrawerOpen = ref(false)
const selectedLogId = ref(null)
const selectedTitle = ref('执行日志')

let refreshTimer = null

const hasFilters = computed(
  () => Boolean(moduleFilter.value) || Boolean(statusFilter.value) || Boolean(triggerFilter.value),
)

async function loadModules() {
  try {
    modules.value = await modulesApi.list()
  } catch {
    // Error shown by the HTTP layer.
  }
}

async function loadLogs() {
  loading.value = true
  try {
    const params = {
      page: page.value,
      page_size: pageSize,
    }
    if (moduleFilter.value !== '' && moduleFilter.value !== undefined && moduleFilter.value !== null) {
      params.module_id = moduleFilter.value
    }
    if (statusFilter.value) params.status = statusFilter.value
    if (triggerFilter.value) params.trigger = triggerFilter.value
    const data = await logsApi.list(params)
    logs.value = data.items
    total.value = data.total
    if (data.pages > 0 && page.value > data.pages) {
      page.value = data.pages
      await loadLogs()
    }
  } catch {
    // Error shown by the HTTP layer.
  } finally {
    loading.value = false
  }
}

function handleFilterChange() {
  page.value = 1
  loadLogs()
}

function resetFilters() {
  moduleFilter.value = ''
  statusFilter.value = ''
  triggerFilter.value = ''
  page.value = 1
  loadLogs()
}

function openLog(row) {
  selectedLogId.value = row.id
  selectedTitle.value = row.module_name
  logDrawerOpen.value = true
}

function startAutoRefresh() {
  stopAutoRefresh()
  refreshTimer = window.setInterval(() => {
    loadLogs()
  }, 10000)
}

function stopAutoRefresh() {
  if (refreshTimer) {
    window.clearInterval(refreshTimer)
    refreshTimer = null
  }
}

watch(autoRefresh, (enabled) => {
  if (enabled) {
    startAutoRefresh()
  } else {
    stopAutoRefresh()
  }
})

onMounted(async () => {
  await Promise.all([loadModules(), loadLogs()])
})

onBeforeUnmount(stopAutoRefresh)
</script>

<style scoped>
.logs-page {
  padding-top: 30px;
}

.auto-refresh {
  display: flex;
  align-items: center;
  gap: 7px;
  margin-right: 6px;
  color: #8b95a9;
  font-size: 11px;
  white-space: nowrap;
}

.logs-toolbar {
  display: flex;
  align-items: flex-end;
  gap: 15px;
  flex-wrap: wrap;
  margin-bottom: 18px;
  padding: 15px 18px;
  background: #fff;
  border: 1px solid var(--line);
  border-radius: 15px;
  box-shadow: var(--shadow-sm);
}

.filter-item {
  display: flex;
  flex-direction: column;
  gap: 5px;
}

.filter-label {
  color: #9ba4b6;
  font-size: 9.5px;
  font-weight: 600;
  letter-spacing: 0.02em;
}

.filter-control {
  width: 150px;
}

.module-filter {
  width: 200px;
}

.trigger-filter {
  width: 140px;
}

.filter-control :deep(.el-select__wrapper) {
  background: #f8f9fc;
  box-shadow: none;
  font-size: 11.5px;
}

.reset-filters {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  height: 32px;
  margin-bottom: 1px;
  padding: 0 9px;
  color: #96a0b3;
  background: transparent;
  border: 0;
  border-radius: 7px;
  font-size: 10.5px;
  cursor: pointer;
}

.reset-filters:hover {
  color: #69748b;
  background: #f6f8fc;
}

.toolbar-summary {
  margin-left: auto;
  padding-bottom: 7px;
  color: #a4adbe;
  font-size: 10.5px;
}

.history-panel {
  min-width: 0;
}

.history-head {
  align-items: center;
}

.live-note {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  margin-left: 7px;
  color: #0b8765;
}

.live-note i {
  width: 4px;
  height: 4px;
  background: #10b981;
  border-radius: 50%;
  animation: pulse-dot 1.2s infinite;
}

.records-chip {
  color: #a6aebe;
  font-family: var(--font-mono);
  font-size: 8.5px;
  letter-spacing: 0.1em;
}

.history-body {
  padding-top: 14px;
  overflow-x: auto;
}

.history-table {
  width: 100%;
}

.history-table :deep(.el-table__row) {
  cursor: pointer;
}

.module-cell {
  display: flex;
  align-items: center;
  gap: 9px;
}

.mini-avatar {
  display: grid;
  width: 30px;
  height: 30px;
  flex: none;
  place-items: center;
  color: #5d58cf;
  background: #f0f1fe;
  border-radius: 8px;
  font-size: 11px;
  font-weight: 700;
}

.module-copy {
  display: flex;
  min-width: 0;
  flex-direction: column;
  line-height: 1.45;
}

.module-copy strong {
  overflow: hidden;
  color: #354057;
  font-size: 11.5px;
  font-weight: 620;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.module-copy span {
  color: #a2aabc;
  font-size: 9.5px;
}

.trigger-label {
  color: #7e889d;
  font-size: 10.5px;
}

.time-cell {
  display: flex;
  flex-direction: column;
  line-height: 1.45;
}

.time-cell span {
  color: #5e6980;
  font-size: 11px;
}

.time-cell small {
  color: #a2abbd;
  font-size: 9.5px;
}

.duration {
  color: #8e97aa;
  font-family: var(--font-mono);
  font-size: 10px;
}

.result-message {
  display: -webkit-box;
  overflow: hidden;
  color: #737d92;
  font-size: 10.5px;
  line-height: 1.55;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}

.row-arrow {
  color: #c1c8d7;
  font-size: 12px;
}

.pagination-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding-top: 17px;
}

.pagination-note {
  color: #a1aaba;
  font-size: 10px;
}

.reset-empty {
  margin-top: 7px;
}

@media (max-width: 900px) {
  .logs-toolbar {
    gap: 10px;
    padding: 13px;
  }

  .filter-control,
  .module-filter,
  .trigger-filter {
    width: 140px;
  }

  .toolbar-summary {
    width: 100%;
    margin-left: 0;
    padding: 0;
  }
}

@media (max-width: 720px) {
  .logs-page {
    padding-top: 20px;
  }

  .header-actions {
    display: flex;
    justify-content: space-between;
  }

  .auto-refresh {
    margin-right: 0;
  }

  .filter-item {
    flex: 1;
    min-width: 130px;
  }

  .filter-control,
  .module-filter,
  .trigger-filter {
    width: 100%;
  }

  .pagination-row {
    flex-direction: column;
    align-items: flex-start;
  }
}
</style>
