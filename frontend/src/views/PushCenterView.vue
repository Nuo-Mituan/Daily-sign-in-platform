<template>
  <div class="page-shell push-center-page">
    <header class="page-header">
      <div>
        <span class="eyebrow">PUSH CENTER</span>
        <h1 class="page-title">推送中心</h1>
        <p class="page-subtitle">查看独立推送与统一日报，管理可热更新的推送驱动。</p>
      </div>
      <div class="header-actions">
        <el-button :loading="loading" @click="loadAll">
          <el-icon><Refresh /></el-icon>刷新
        </el-button>
        <router-link to="/settings" class="header-link">
          <el-icon><Setting /></el-icon>推送渠道设置
        </router-link>
      </div>
    </header>

    <el-tabs v-model="tab" class="push-tabs" @tab-change="handleTab">
      <el-tab-pane label="推送记录" name="records">
        <section class="panel">
          <div class="panel-head">
            <div>
              <div class="panel-title">发送历史</div>
              <div class="panel-desc">独立推送、统一汇总与 flush 后补发记录，按时间倒序。</div>
            </div>
            <div class="record-filters">
              <el-select v-model="recordKind" clearable placeholder="全部类型" size="small" @change="loadRecords">
                <el-option label="独立推送" value="independent" />
                <el-option label="统一汇总" value="unified" />
                <el-option label="flush 后补发" value="supplement" />
              </el-select>
              <el-select v-model="recordStatus" clearable placeholder="全部状态" size="small" @change="loadRecords">
                <el-option label="成功" value="success" />
                <el-option label="失败" value="failed" />
              </el-select>
            </div>
          </div>
          <div class="panel-body">
            <el-table :data="records" class="push-table">
              <el-table-column label="类型" width="112">
                <template #default="{ row }">{{ kindLabel(row.kind) }}</template>
              </el-table-column>
              <el-table-column label="模块" min-width="140">
                <template #default="{ row }">{{ row.module_name || '—' }}</template>
              </el-table-column>
              <el-table-column label="渠道" width="100">
                <template #default="{ row }">{{ row.channel }}</template>
              </el-table-column>
              <el-table-column label="状态" width="88">
                <template #default="{ row }">
                  <span class="push-status" :class="row.status">{{ row.status === 'success' ? '成功' : '失败' }}</span>
                </template>
              </el-table-column>
              <el-table-column label="周期" width="108">
                <template #default="{ row }">{{ row.cycle_id || '—' }}</template>
              </el-table-column>
              <el-table-column label="时间" width="160">
                <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
              </el-table-column>
              <el-table-column label="标题 / 错误" min-width="260">
                <template #default="{ row }">
                  <span class="record-title">{{ row.title || row.error || '—' }}</span>
                </template>
              </el-table-column>
              <el-table-column width="70" align="right">
                <template #default="{ row }">
                  <el-popover v-if="row.body" placement="left" width="420" trigger="click">
                    <template #reference><el-button text size="small">正文</el-button></template>
                    <pre class="record-body">{{ row.body }}</pre>
                  </el-popover>
                </template>
              </el-table-column>
            </el-table>
            <div v-if="recordsTotal > recordPageSize" class="pagination-row">
              <el-pagination
                v-model:current-page="recordPage"
                :page-size="recordPageSize"
                :total="recordsTotal"
                layout="prev, pager, next"
                background
                @current-change="loadRecords"
              />
            </div>
          </div>
        </section>
      </el-tab-pane>

      <el-tab-pane label="统一批次" name="batches">
        <UnifiedTimeoutSettings
          v-model:enabled="timeoutEnabled"
          v-model:time="timeoutTime"
          :saving="savingTimeout"
          @save="saveTimeoutSettings"
        />

        <section class="panel">
          <div class="panel-head">
            <div>
              <div class="panel-title">统一推送批次摘要</div>
              <div class="panel-desc">批次明细 flush 后即清理，仅保留统计与摘要。</div>
            </div>
          </div>
          <div class="panel-body">
            <el-table :data="batches" class="push-table">
              <el-table-column label="周期" width="110" prop="cycle_id" />
              <el-table-column label="状态" width="92">
                <template #default="{ row }">
                  <span class="push-status" :class="row.status">{{ batchLabel(row.status) }}</span>
                </template>
              </el-table-column>
              <el-table-column label="预期" width="70" prop="expected_count" />
              <el-table-column label="成功" width="70" prop="success_count" />
              <el-table-column label="失败" width="70" prop="failed_count" />
              <el-table-column label="超时" width="70" prop="timeout_count" />
              <el-table-column label="跳过" width="70" prop="skipped_count" />
              <el-table-column label="未完成" width="78" prop="pending_count" />
              <el-table-column label="清理状态" width="150">
                <template #default="{ row }">
                  <span class="cleared-note">{{ row.details_cleared ? '内容已清理，仅保留摘要' : '明细保留中' }}</span>
                </template>
              </el-table-column>
              <el-table-column label="发送时间" width="160">
                <template #default="{ row }">{{ row.flushed_at ? formatDateTime(row.flushed_at) : '—' }}</template>
              </el-table-column>
              <el-table-column width="70" align="right">
                <template #default="{ row }">
                  <el-popover v-if="row.summary" placement="left" width="460" trigger="click">
                    <template #reference><el-button text size="small">摘要</el-button></template>
                    <pre class="record-body">{{ row.summary }}</pre>
                  </el-popover>
                </template>
              </el-table-column>
            </el-table>
          </div>
        </section>
      </el-tab-pane>

      <el-tab-pane label="驱动管理" name="drivers">
        <section class="panel">
          <div class="panel-head">
            <div>
              <div class="panel-title">推送驱动</div>
              <div class="panel-desc">
                支持上传 .py / .zip；上传校验不是安全沙箱，仅允许可信管理员安装驱动。
              </div>
            </div>
            <div class="driver-upload">
              <input ref="fileInput" type="file" accept=".py,.zip" hidden @change="handleFile" />
              <el-button @click="fileInput?.click()">选择驱动文件</el-button>
              <span v-if="selectedFile" class="selected-file">{{ selectedFile.name }}</span>
              <template v-if="selectedFile && selectedFile.name.endsWith('.py')">
                <el-input v-model="driverKey" size="small" placeholder="key，如 my_driver" />
                <el-input v-model="driverName" size="small" placeholder="驱动名称" />
                <el-input v-model="driverVersion" size="small" placeholder="1.0.0" />
              </template>
              <el-button type="primary" :loading="uploading" :disabled="!selectedFile" @click="uploadDriver">
                上传并热加载
              </el-button>
            </div>
          </div>
          <div class="panel-body">
            <div class="driver-grid">
              <article v-for="driver in drivers" :key="driver.key" class="driver-card">
                <div class="driver-head">
                  <div>
                    <strong>{{ driver.name }}</strong>
                    <span class="driver-key">{{ driver.key }}</span>
                  </div>
                  <span class="driver-badge">{{ driver.builtin ? '内置' : driver.version }}</span>
                </div>
                <p class="driver-desc">{{ driver.description || '无描述' }}</p>
                <div class="driver-meta">
                  <span>{{ driver.fields.length }} 个字段</span>
                  <span>历史 {{ driver.versions.length }} 个版本</span>
                </div>
                <div v-if="!driver.builtin" class="driver-actions">
                  <el-button size="small" @click="rollbackDriver(driver)">回滚上一版</el-button>
                  <el-button size="small" type="danger" plain @click="removeDriver(driver)">删除</el-button>
                </div>
              </article>
            </div>
          </div>
        </section>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Refresh, Setting } from '@element-plus/icons-vue'
import UnifiedTimeoutSettings from '@/components/UnifiedTimeoutSettings.vue'
import { pushApi } from '@/api'
import { formatDateTime } from '@/utils/format'

const tab = ref('records')
const loading = ref(false)
const records = ref([])
const recordsTotal = ref(0)
const recordPage = ref(1)
const recordPageSize = 15
const recordKind = ref('')
const recordStatus = ref('')
const batches = ref([])
const drivers = ref([])
const fileInput = ref(null)
const selectedFile = ref(null)
const driverKey = ref('')
const driverName = ref('')
const driverVersion = ref('1.0.0')
const uploading = ref(false)
const timeoutEnabled = ref(false)
const timeoutTime = ref('23:30')
const savingTimeout = ref(false)

function kindLabel(kind) {
  return { independent: '独立推送', unified: '统一汇总', supplement: '补发单条' }[kind] || kind
}

function batchLabel(status) {
  return { pending: '等待中', sent: '已发送', failed: '发送失败', timeout: '推送超时', noop: '无需推送', expired: '已过期' }[status] || status
}

async function loadRecords() {
  const data = await pushApi.listRecords({
    page: recordPage.value,
    page_size: recordPageSize,
    kind: recordKind.value || undefined,
    status: recordStatus.value || undefined,
  })
  records.value = data.items
  recordsTotal.value = data.total
}

async function loadBatches() {
  const data = await pushApi.listBatches({ page: 1, page_size: 30 })
  batches.value = data.items
}

async function loadDrivers() {
  drivers.value = await pushApi.listDrivers()
}

async function loadTimeoutSettings() {
  const data = await pushApi.getUnifiedSettings()
  timeoutEnabled.value = Boolean(data.timeout_enabled)
  timeoutTime.value = data.timeout_time || '23:30'
}

async function saveTimeoutSettings(payload = {}) {
  savingTimeout.value = true
  try {
    const data = await pushApi.updateUnifiedSettings({
      timeout_enabled: Boolean(payload.enabled ?? timeoutEnabled.value),
      timeout_time: payload.time || timeoutTime.value || '23:30',
    })
    timeoutEnabled.value = Boolean(data.timeout_enabled)
    timeoutTime.value = data.timeout_time
    ElMessage.success('超时推送设置已保存')
  } catch {
    await loadTimeoutSettings().catch(() => {})
  } finally {
    savingTimeout.value = false
  }
}

async function loadAll() {
  loading.value = true
  try {
    await Promise.all([loadRecords(), loadBatches(), loadDrivers(), loadTimeoutSettings()])
  } catch {
    // HTTP layer reports the error.
  } finally {
    loading.value = false
  }
}

function handleTab() {
  loadAll()
}

function handleFile(event) {
  selectedFile.value = event.target.files?.[0] || null
}

async function uploadDriver() {
  if (!selectedFile.value) return
  const form = new FormData()
  form.append('file', selectedFile.value)
  if (selectedFile.value.name.endsWith('.py')) {
    if (!driverKey.value.trim()) {
      ElMessage.warning('上传 .py 时必须填写 key')
      return
    }
    form.append('key', driverKey.value.trim())
    form.append('name', driverName.value.trim() || driverKey.value.trim())
    form.append('version', driverVersion.value.trim() || '1.0.0')
  }
  uploading.value = true
  try {
    await pushApi.uploadDriver(form)
    ElMessage.success('驱动已校验并热加载')
    selectedFile.value = null
    if (fileInput.value) fileInput.value.value = ''
    await loadDrivers()
  } catch {
    // HTTP layer reports validation errors.
  } finally {
    uploading.value = false
  }
}

async function rollbackDriver(driver) {
  try {
    await ElMessageBox.confirm(
      `确认将 ${driver.name} 回滚到上一历史版本？`,
      '回滚驱动',
      { confirmButtonText: '回滚', cancelButtonText: '取消', type: 'warning' },
    )
    await pushApi.rollbackDriver(driver.key)
    ElMessage.success('驱动已回滚并热加载')
    await loadDrivers()
  } catch {
    // Cancelled or HTTP error.
  }
}

async function removeDriver(driver) {
  try {
    await ElMessageBox.confirm(
      `删除驱动 ${driver.name} 及其全部历史版本？`,
      '删除驱动',
      { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' },
    )
    await pushApi.deleteDriver(driver.key)
    ElMessage.success('驱动已删除')
    await loadDrivers()
  } catch {
    // Cancelled or HTTP error.
  }
}

onMounted(loadAll)
</script>

<style scoped>
.push-center-page { padding-top: 30px; }
.push-tabs { margin-top: 18px; }
.record-filters { display: flex; gap: 8px; }
.record-filters :deep(.el-select) { width: 118px; }
.push-table { width: 100%; }
.record-title { color: #6f788b; font-size: 10px; }
.record-body { max-height: 360px; overflow: auto; margin: 0; white-space: pre-wrap; font-size: 10px; line-height: 1.6; }
.push-status { display: inline-flex; padding: 2px 7px; border-radius: 999px; font-size: 9px; font-weight: 700; }
.push-status.success { color: #2f7d5d; background: #edf9f2; }
.push-status.failed { color: #b44747; background: #fdf1f1; }
.push-status.pending { color: #8a6a27; background: #fbf7e9; }
.push-status.sent { color: #2f7d5d; background: #edf9f2; }
.cleared-note { color: #9aa4b6; font-size: 9.5px; }
.driver-upload { display: flex; align-items: center; gap: 7px; flex-wrap: wrap; justify-content: flex-end; }
.driver-upload :deep(.el-input) { width: 150px; }
.selected-file { max-width: 160px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: #7f8799; font-size: 9.5px; }
.driver-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 12px; }
.driver-card { padding: 13px; border: 1px solid #eef0f6; border-radius: 11px; background: #fbfcfe; }
.driver-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 8px; }
.driver-head strong { display: block; color: #39425a; font-size: 12px; }
.driver-key { color: #9aa2b3; font-family: var(--font-mono); font-size: 8.5px; }
.driver-badge { flex: none; padding: 2px 6px; border-radius: 999px; color: #747dd0; background: #f0f1ff; font-size: 8.5px; }
.driver-desc { min-height: 28px; margin: 8px 0; color: #8a93a6; font-size: 9.5px; line-height: 1.5; }
.driver-meta { display: flex; gap: 12px; color: #a3abba; font-size: 9px; }
.driver-actions { display: flex; gap: 7px; margin-top: 10px; }
@media (max-width: 720px) {
  .push-center-page { padding-top: 20px; }
  .panel-head { align-items: flex-start; flex-direction: column; gap: 10px; }
  .record-filters { width: 100%; }
  .record-filters :deep(.el-select) { flex: 1; width: auto; }
  .driver-upload { justify-content: flex-start; }
}
</style>