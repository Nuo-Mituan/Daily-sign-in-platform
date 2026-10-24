<template>
  <div class="page-shell modules-page">
    <header class="page-header">
      <div>
        <span class="eyebrow">MODULE LIBRARY</span>
        <h1 class="page-title">签到模块</h1>
        <p class="page-subtitle">
          每个模块都是独立插件。上传或扫描目录即可热加载，无需重启服务。
        </p>
      </div>
      <div class="header-actions">
        <el-button :loading="scanning" @click="scan">
          <el-icon><Refresh /></el-icon>
          扫描目录
        </el-button>
        <el-button type="primary" @click="openUpload">
          <el-icon><Plus /></el-icon>
          上传模块
        </el-button>
      </div>
    </header>

    <transition name="route-fade">
      <div v-if="scanErrors.length" class="scan-alert">
        <span class="scan-alert-icon"><el-icon><WarningFilled /></el-icon></span>
        <div class="scan-alert-copy">
          <strong>扫描完成，但发现 {{ scanErrors.length }} 个异常模块</strong>
          <ul>
            <li v-for="error in scanErrors" :key="error.key">
              <code>{{ error.key }}</code>
              <span>{{ error.error }}</span>
            </li>
          </ul>
        </div>
        <button type="button" class="scan-close" aria-label="关闭" @click="scanErrors = []">
          <el-icon><Close /></el-icon>
        </button>
      </div>
    </transition>

    <div class="toolbar">
      <el-input
        v-model="keyword"
        class="search-input"
        placeholder="搜索模块名称、标识或描述"
        clearable
        :prefix-icon="Search"
      />
      <div class="filter-group">
        <button
          v-for="option in filterOptions"
          :key="option.value"
          type="button"
          class="filter-pill"
          :class="{ active: filter === option.value }"
          @click="filter = option.value"
        >
          {{ option.label }}
          <span>{{ option.count }}</span>
        </button>
      </div>
      <span class="result-note">共 {{ filtered.length }} 个模块</span>
    </div>

    <div v-if="initialLoading" class="module-grid">
      <div v-for="index in 3" :key="index" class="skeleton-card">
        <div class="skeleton skeleton-icon"></div>
        <div class="skeleton skeleton-title"></div>
        <div class="skeleton skeleton-line"></div>
        <div class="skeleton skeleton-meta"></div>
      </div>
    </div>

    <div v-else-if="modules.length === 0" class="panel empty-library">
      <div class="empty-art">
        <span class="empty-ring ring-one"></span>
        <span class="empty-ring ring-two"></span>
        <span class="empty-icon">🧩</span>
      </div>
      <h2>还没有安装任何模块</h2>
      <p>
        上传 ZIP 模块包，或将模块目录放入服务器的 <code>modules/</code> 目录后点击“扫描目录”。
      </p>
      <div class="empty-actions">
        <el-button type="primary" @click="openUpload">
          <el-icon><UploadFilled /></el-icon>
          上传第一个模块
        </el-button>
        <el-button @click="scan" :loading="scanning">扫描目录</el-button>
        <router-link to="/guide" class="guide-link">阅读模块开发指南</router-link>
      </div>
    </div>

    <div v-else-if="filtered.length === 0" class="panel empty-library compact">
      <div class="empty-state">
        <div class="empty-state__icon"><el-icon><Search /></el-icon></div>
        <div class="empty-state__title">没有符合条件的模块</div>
        <div class="empty-state__desc">试试更换筛选条件，或清空搜索关键词。</div>
        <el-button class="reset-btn" text type="primary" @click="resetFilters">重置筛选</el-button>
      </div>
    </div>

    <div v-else class="module-grid">
      <article
        v-for="(module, index) in filtered"
        :key="module.id"
        class="module-card"
        :class="{ 'is-disabled': !module.enabled, 'has-error': module.load_error }"
        @click="goDetail(module)"
      >
        <div class="card-top">
          <ModuleIcon :icon="module.icon" :source="module.icon_source" :icon-data="module.icon_data" :module-key="module.key || module.directory_name" :size="48" :tone="index + module.id" />
          <div class="card-heading">
            <div class="card-title-line">
              <h2 :title="module.name">{{ module.name }}</h2>
              <span class="version-badge">v{{ module.version }}</span>
            </div>
            <div class="card-key-line">
              <span class="key-hash">#</span>
              <span class="mono">{{ module.key }}</span>
              <span v-if="module.author" class="author">by {{ module.author }}</span>
            </div>
          </div>
          <div class="switch-holder" @click.stop>
            <el-switch
              :model-value="module.enabled"
              :loading="Boolean(toggling[module.id])"
              :disabled="Boolean(module.load_error)"
              :before-change="() => toggleModule(module)"
              :aria-label="`启用或禁用 ${module.name}`"
            />
          </div>
        </div>

        <p class="card-description">{{ module.description || '这个模块还没有填写描述。' }}</p>

        <div v-if="module.load_error" class="card-error">
          <el-icon><Warning /></el-icon>
          <div>
            <strong>模块加载异常</strong>
            <p>{{ module.load_error }}</p>
          </div>
        </div>

        <div class="card-meta">
          <div class="meta-row">
            <span class="meta-label"><el-icon><Timer /></el-icon>时间窗</span>
            <span class="meta-value cron-value">
              <code>{{ module.start_time }}–{{ module.end_time }}</code>
              <em>{{ cycleDayLabel(module.repeat_cycle, module.repeat_sub_value) }}</em>
            </span>
          </div>
          <div class="meta-row">
            <span class="meta-label"><el-icon><Calendar /></el-icon>本次</span>
            <span class="meta-value schedule-value">
              <template v-if="module.current_schedule_at">
                <span>{{ formatDateTime(module.current_schedule_at) }}</span>
                <span class="schedule-chip" :class="scheduleStatusMeta(module.schedule_status).className">
                  {{ scheduleStatusMeta(module.schedule_status).label }}
                </span>
              </template>
              <template v-else>
                <span class="schedule-chip" :class="scheduleStatusMeta(module.schedule_status).className">
                  {{ scheduleStatusMeta(module.schedule_status).label }}
                </span>
                <span v-if="!module.enabled" class="meta-idle">启用后自动安排</span>
              </template>
            </span>
          </div>
          <div class="meta-row">
            <span class="meta-label"><el-icon><UserFilled /></el-icon>模式</span>
            <span class="meta-value mode-value">
              <span>{{ module.multi_account ? `${module.account_count} 个账号` : '单账号' }}</span>
              <span class="meta-dot">·</span>
              <span class="push-state" :class="{ on: module.push_enabled }">
                <el-icon><Bell /></el-icon>
                推送{{ module.push_unified ? '统一' : module.push_independent ? '独立' : '关闭' }}
              </span>
            </span>
          </div>
          <div class="meta-row">
            <span class="meta-label"><el-icon><Clock /></el-icon>最近</span>
            <span class="meta-value last-run-value">
              <template v-if="module.last_status">
                <StatusTag :status="module.last_status" />
                <em v-if="module.last_run_at">{{ timeFromNow(module.last_run_at) }}</em>
              </template>
              <span v-else class="meta-idle">尚未执行</span>
            </span>
          </div>
        </div>

        <div class="card-footer" @click.stop>
          <button type="button" class="card-action" @click="goDetail(module)">
            <el-icon><Setting /></el-icon>
            配置
          </button>
          <button
            type="button"
            class="card-action"
            :disabled="isRunning(module) || Boolean(module.load_error)"
            @click="runNow(module)"
          >
            <el-icon :class="{ 'is-loading': running[module.id] }">
              <VideoPlay />
            </el-icon>
            {{ isRunning(module) ? '执行中' : '立即执行' }}
          </button>
          <span class="footer-spacer"></span>
          <button
            type="button"
            class="icon-action"
            title="查看执行日志"
            @click="openLogs(module)"
          >
            <el-icon><Document /></el-icon>
          </button>
          <el-dropdown trigger="click" @command="(command) => handleCardCommand(command, module)">
            <button type="button" class="icon-action" title="更多操作">
              <el-icon><MoreFilled /></el-icon>
            </button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="logs">
                  <el-icon><Document /></el-icon>
                  查看日志
                </el-dropdown-item>
                <el-dropdown-item command="delete" divided>
                  <el-icon><Delete /></el-icon>
                  彻底删除
                </el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </article>
    </div>

    <RunLogDrawer
      v-model="logDrawerOpen"
      :log-id="selectedLogId"
      :title="activeLogTitle"
      @finished="handleRunFinished"
    />

    <el-dialog
      v-model="uploadDialogOpen"
      title="上传签到模块"
      width="580px"
      :close-on-click-modal="false"
      @closed="resetUploadForm"
    >
      <div class="upload-intro">
        <span class="upload-intro-icon"><el-icon><UploadFilled /></el-icon></span>
        <div>
          <strong>从 ZIP 安装一个新模块</strong>
          <p>
            上传完成后会立即解析 <code>config.json</code> 并加入列表。新模块默认禁用，
            填写参数后手动开启即可。
          </p>
        </div>
      </div>

      <el-upload
        ref="uploadRef"
        drag
        action="#"
        accept=".zip,application/zip"
        :auto-upload="false"
        :limit="1"
        :on-change="handleUploadChange"
        :on-remove="handleUploadRemove"
        :on-exceed="handleUploadExceed"
        class="module-uploader"
      >
        <el-icon class="upload-cloud"><UploadFilled /></el-icon>
        <div class="el-upload__text">
          拖拽 ZIP 压缩包到此处，或 <em>点击选择文件</em>
        </div>
        <template #tip>
          <div class="el-upload__tip">仅支持 .zip 格式，最大 10 MB；压缩包内只能包含一个模块。</div>
        </template>
      </el-upload>

      <div class="upload-form">
        <div class="upload-field">
          <label for="module-key">模块标识（可选）</label>
          <el-input
            id="module-key"
            v-model="uploadName"
            placeholder="留空则使用压缩包内目录名，如 my_checkin"
            clearable
          />
          <span>字母、数字、下划线或短横线，将作为 modules/ 下的目录名。</span>
        </div>
        <div class="overwrite-row">
          <div>
            <strong>覆盖同名模块</strong>
            <p>覆盖代码文件，但保留数据库中已保存的账号和随机调度配置。</p>
          </div>
          <el-switch v-model="uploadOverwrite" />
        </div>
      </div>

      <div class="zip-preview">
        <span class="zip-preview-label">压缩包结构示例</span>
        <pre>my_checkin/
├── config.json
├── main.py
└── helpers.py  <span class="zip-optional">（可选）</span></pre>
        <router-link to="/guide" class="zip-guide-link" @click="uploadDialogOpen = false">
          查看完整开发规范 <el-icon><ArrowRight /></el-icon>
        </router-link>
      </div>

      <template #footer>
        <el-button @click="uploadDialogOpen = false">取消</el-button>
        <el-button type="primary" :loading="uploadSubmitting" @click="submitUpload">
          {{ uploadSubmitting ? '正在安装…' : '上传并安装' }}
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  ArrowRight,
  Bell,
  Calendar,
  Clock,
  Close,
  Delete,
  Document,
  MoreFilled,
  Plus,
  Refresh,
  Search,
  Setting,
  Timer,
  UploadFilled,
  UserFilled,
  VideoPlay,
  Warning,
  WarningFilled,
} from '@element-plus/icons-vue'
import ModuleIcon from '@/components/ModuleIcon.vue'
import StatusTag from '@/components/StatusTag.vue'
import RunLogDrawer from '@/components/RunLogDrawer.vue'
import { modulesApi } from '@/api'
import { cycleDayLabel, scheduleStatusMeta } from '@/utils/schedule'
import { formatDateTime, timeFromNow } from '@/utils/format'

const router = useRouter()

const modules = ref([])
const keyword = ref('')
const filter = ref('all')
const loading = ref(false)
const initialLoading = ref(true)
const scanning = ref(false)
const scanErrors = ref([])
const toggling = reactive({})
const running = reactive({})

const logDrawerOpen = ref(false)
const selectedLogId = ref(null)
const activeLogTitle = ref('执行日志')

const uploadDialogOpen = ref(false)
const uploadSubmitting = ref(false)
const uploadRef = ref(null)
const uploadFile = ref(null)
const uploadName = ref('')
const uploadOverwrite = ref(false)

const counts = computed(() => ({
  all: modules.value.length,
  enabled: modules.value.filter((item) => item.enabled).length,
  disabled: modules.value.filter((item) => !item.enabled).length,
  error: modules.value.filter((item) => Boolean(item.load_error)).length,
}))

const filterOptions = computed(() => [
  { value: 'all', label: '全部', count: counts.value.all },
  { value: 'enabled', label: '已启用', count: counts.value.enabled },
  { value: 'disabled', label: '未启用', count: counts.value.disabled },
  { value: 'error', label: '异常', count: counts.value.error },
])

const filtered = computed(() => {
  const query = keyword.value.trim().toLowerCase()
  return modules.value.filter((item) => {
    if (filter.value === 'enabled' && !item.enabled) return false
    if (filter.value === 'disabled' && item.enabled) return false
    if (filter.value === 'error' && !item.load_error) return false
    if (!query) return true
    return [item.name, item.key, item.description, item.author]
      .filter(Boolean)
      .some((value) => String(value).toLowerCase().includes(query))
  })
})

function resetFilters() {
  keyword.value = ''
  filter.value = 'all'
}

async function load(silent = false) {
  if (!silent) loading.value = true
  try {
    modules.value = await modulesApi.list()
  } catch {
    // The HTTP layer shows the error.
  } finally {
    loading.value = false
    initialLoading.value = false
  }
}

async function scan() {
  scanning.value = true
  try {
    const result = await modulesApi.scan()
    scanErrors.value = result.invalid || []
    await load(true)
    if (scanErrors.value.length) {
      ElMessage.warning(result.message)
    } else {
      ElMessage.success(result.message)
    }
  } catch {
    // Error already displayed.
  } finally {
    scanning.value = false
  }
}

async function toggleModule(module) {
  if (toggling[module.id]) return false
  toggling[module.id] = true
  try {
    const updated = await modulesApi.toggle(module.id, !module.enabled)
    Object.assign(module, updated)
    ElMessage.success(updated.enabled ? '模块已启用，已加入调度队列' : '模块已暂停，定时任务已移除')
    return true
  } catch {
    return false
  } finally {
    toggling[module.id] = false
  }
}

function isRunning(module) {
  return Boolean(running[module.id]) || module.last_status === 'running'
}

async function runNow(module) {
  if (running[module.id]) return
  running[module.id] = true
  try {
    const result = await modulesApi.run(module.id)
    module.last_status = 'running'
    module.last_run_at = new Date().toISOString()
    selectedLogId.value = result.log_id
    activeLogTitle.value = module.name
    logDrawerOpen.value = true
  } catch {
    // Error already displayed.
  } finally {
    running[module.id] = false
  }
}

async function handleRunFinished() {
  await load(true)
}

function goDetail(module) {
  router.push({ name: 'module-detail', params: { id: module.id } })
}

function openLogs(module) {
  router.push({ name: 'module-detail', params: { id: module.id }, query: { tab: 'logs' } })
}

async function handleCardCommand(command, module) {
  if (command === 'logs') {
    openLogs(module)
  } else if (command === 'delete') {
    await deleteModule(module)
  }
}

async function deleteModule(module) {
  try {
    await ElMessageBox.confirm(
      `彻底删除「${module.name}」会移除 modules/${module.directory_name || module.key} 目录、数据库记录和全部历史日志，且不可恢复。\n确定继续吗？`,
      '彻底删除模块',
      {
        confirmButtonText: '彻底删除',
        cancelButtonText: '取消',
        type: 'warning',
        confirmButtonClass: 'danger-confirm',
      },
    )
  } catch {
    return
  }
  try {
    const result = await modulesApi.remove(module.id)
    modules.value = modules.value.filter((item) => item.id !== module.id)
    ElMessage.success(result.message)
  } catch {
    // Error already displayed.
  }
}

function openUpload() {
  uploadDialogOpen.value = true
}

function resetUploadForm() {
  uploadFile.value = null
  uploadName.value = ''
  uploadOverwrite.value = false
  uploadSubmitting.value = false
  uploadRef.value?.clearFiles()
}

function handleUploadChange(file) {
  const raw = file.raw
  if (!raw) return
  if (!raw.name.toLowerCase().endsWith('.zip')) {
    ElMessage.error('请选择 .zip 格式的模块压缩包')
    uploadRef.value?.clearFiles()
    uploadFile.value = null
    return
  }
  if (raw.size > 10 * 1024 * 1024) {
    ElMessage.error('压缩包不能超过 10 MB')
    uploadRef.value?.clearFiles()
    uploadFile.value = null
    return
  }
  uploadFile.value = raw
}

function handleUploadRemove() {
  uploadFile.value = null
}

function handleUploadExceed() {
  ElMessage.warning('一次只能上传一个压缩包，请先移除当前文件')
}

async function submitUpload() {
  if (!uploadFile.value) {
    ElMessage.warning('请先选择一个 ZIP 模块包')
    return
  }
  const name = uploadName.value.trim()
  if (name && !/^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$/.test(name)) {
    ElMessage.error('模块标识只能包含字母、数字、下划线和短横线，且以字母或数字开头')
    return
  }
  uploadSubmitting.value = true
  try {
    const formData = new FormData()
    formData.append('file', uploadFile.value, uploadFile.value.name)
    if (name) formData.append('name', name)
    const result = await modulesApi.upload(formData, uploadOverwrite.value)
    uploadDialogOpen.value = false
    ElMessage.success(result.message)
    await load(true)
  } catch {
    // Error already displayed.
  } finally {
    uploadSubmitting.value = false
  }
}

onMounted(() => load())
</script>

<style scoped>
.modules-page {
  padding-top: 30px;
}

.scan-alert {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  margin-bottom: 18px;
  padding: 15px 17px;
  background: #fffaf0;
  border: 1px solid #f5e3b8;
  border-radius: 14px;
}

.scan-alert-icon {
  display: grid;
  width: 28px;
  height: 28px;
  flex: none;
  place-items: center;
  color: #bd861f;
  background: #fdf1d9;
  border-radius: 8px;
  font-size: 15px;
}

.scan-alert-copy {
  flex: 1;
  min-width: 0;
}

.scan-alert-copy strong {
  color: #85601c;
  font-size: 12px;
  font-weight: 650;
}

.scan-alert-copy ul {
  display: flex;
  flex-direction: column;
  gap: 3px;
  margin: 7px 0 0;
  padding: 0;
  list-style: none;
}

.scan-alert-copy li {
  color: #9b7b3e;
  font-size: 11px;
  line-height: 1.6;
}

.scan-alert-copy li code {
  margin-right: 7px;
  padding: 1px 5px;
  background: #fdf3df;
  border-radius: 4px;
  font-family: var(--font-mono);
  font-size: 10px;
}

.scan-close {
  display: grid;
  width: 25px;
  height: 25px;
  flex: none;
  place-items: center;
  color: #b39153;
  background: transparent;
  border: 0;
  border-radius: 6px;
  cursor: pointer;
}

.scan-close:hover {
  background: #fdf1d9;
}

.toolbar {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-bottom: 20px;
  padding: 12px 14px;
  background: #fff;
  border: 1px solid var(--line);
  border-radius: 15px;
  box-shadow: var(--shadow-sm);
}

.search-input {
  width: 270px;
  flex: none;
}

.search-input :deep(.el-input__wrapper) {
  background: #f8f9fc;
  box-shadow: none;
}

.search-input :deep(.el-input__wrapper.is-focus) {
  background: #fff;
  box-shadow: 0 0 0 1px var(--brand) inset;
}

.filter-group {
  display: flex;
  align-items: center;
  gap: 3px;
}

.filter-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 32px;
  padding: 0 10px;
  color: #7d879c;
  background: transparent;
  border: 0;
  border-radius: 8px;
  font-size: 11.5px;
  font-weight: 550;
  cursor: pointer;
  transition: all 0.16s ease;
}

.filter-pill span {
  min-width: 17px;
  padding: 0 4px;
  color: #a0a9bb;
  background: #f0f2f7;
  border-radius: 999px;
  font-family: var(--font-mono);
  font-size: 9px;
  line-height: 16px;
  text-align: center;
}

.filter-pill:hover {
  color: var(--ink-soft);
  background: #f7f8fc;
}

.filter-pill.active {
  color: var(--brand-strong);
  background: var(--brand-soft);
}

.filter-pill.active span {
  color: #5f5ccc;
  background: #fff;
}

.result-note {
  margin-left: auto;
  color: #a0a8ba;
  font-size: 10.5px;
  white-space: nowrap;
}

.module-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(335px, 1fr));
  gap: 17px;
}

.module-card {
  position: relative;
  display: flex;
  min-width: 0;
  flex-direction: column;
  padding: 20px 20px 0;
  overflow: hidden;
  background: #fff;
  border: 1px solid var(--line);
  border-radius: 18px;
  box-shadow: var(--shadow-sm);
  cursor: pointer;
  transition: transform 0.22s ease, box-shadow 0.22s ease,
    border-color 0.22s ease;
}

.module-card::before {
  position: absolute;
  top: 0;
  right: 30px;
  left: 30px;
  height: 1.5px;
  background: linear-gradient(90deg, transparent, #a5a5f5, transparent);
  opacity: 0;
  content: "";
  transition: opacity 0.22s ease;
}

.module-card:hover {
  border-color: #dfe2f1;
  box-shadow: var(--shadow-md);
  transform: translateY(-3px);
}

.module-card:hover::before {
  opacity: 1;
}

.module-card.is-disabled {
  background: #fdfdff;
}

.module-card.has-error {
  border-color: #f1d6d6;
}

.card-top {
  display: flex;
  align-items: flex-start;
  gap: 12px;
}

.card-heading {
  min-width: 0;
  flex: 1;
  padding-top: 2px;
}

.card-title-line {
  display: flex;
  align-items: center;
  gap: 7px;
}

.card-title-line h2 {
  overflow: hidden;
  color: #232e45;
  font-size: 15px;
  font-weight: 680;
  letter-spacing: -0.015em;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.version-badge {
  flex: none;
  padding: 1px 6px;
  color: #99a2b5;
  background: #f5f7fb;
  border: 1px solid #eef1f7;
  border-radius: 5px;
  font-family: var(--font-mono);
  font-size: 8.5px;
}

.card-key-line {
  display: flex;
  align-items: center;
  gap: 4px;
  margin-top: 2px;
  color: #a3acbe;
  font-size: 9.5px;
}

.key-hash {
  color: #c1c8d5;
  font-family: var(--font-mono);
}

.author {
  overflow: hidden;
  margin-left: 4px;
  color: #b3bac9;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.mode-value {
  display: inline-flex;
  align-items: center;
  gap: 5px;
}

.meta-dot {
  color: #c2c8d3;
}

.push-state {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  color: #9aa3b5;
  font-size: 9px;
}

.push-state.on {
  color: #9a762c;
}

.push-state .el-icon {
  font-size: 10px;
}

.schedule-chip {
  display: inline-flex;
  padding: 1px 6px;
  border-radius: 999px;
  font-size: 8.5px;
  font-weight: 600;
}

.schedule-chip.is-pending,
.schedule-chip.is-running {
  color: #5757c6;
  background: #f0f1fe;
}

.schedule-chip.is-fallback {
  color: #9b6b17;
  background: #fdf5e6;
}

.schedule-chip.is-success {
  color: #0b8765;
  background: #eaf9f3;
}

.schedule-chip.is-failed {
  color: #c13c3c;
  background: #fdf0f0;
}

.schedule-chip.is-idle {
  color: #949cad;
  background: #f3f5f8;
}

.switch-holder {
  flex: none;
  padding-top: 3px;
}

.card-description {
  display: -webkit-box;
  min-height: 38px;
  margin-top: 13px;
  overflow: hidden;
  color: #8b95a9;
  font-size: 11.5px;
  line-height: 1.7;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}

.card-error {
  display: flex;
  align-items: flex-start;
  gap: 7px;
  margin-top: 10px;
  padding: 9px 10px;
  color: #b64a4a;
  background: #fdf4f4;
  border: 1px solid #f7e4e4;
  border-radius: 9px;
  font-size: 10.5px;
}

.card-error > .el-icon {
  flex: none;
  margin-top: 2px;
}

.card-error strong {
  display: block;
  font-size: 10.5px;
  font-weight: 650;
}

.card-error p {
  margin-top: 1px;
  color: #c07a7a;
  line-height: 1.55;
  word-break: break-word;
}

.card-meta {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: 14px;
  padding: 12px 0;
  border-top: 1px dashed #eff1f6;
}

.meta-row {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  min-height: 19px;
}

.meta-label {
  display: inline-flex;
  width: 62px;
  flex: none;
  align-items: center;
  gap: 4px;
  padding-top: 1px;
  color: #a4adbe;
  font-size: 10px;
  font-weight: 550;
}

.meta-value {
  display: flex;
  min-width: 0;
  flex: 1;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  color: #5f6a81;
  font-size: 10.5px;
  line-height: 1.55;
}

.cron-value code {
  padding: 1px 5px;
  color: #5756c5;
  background: #f4f4fd;
  border: 1px solid #eaeaf9;
  border-radius: 4px;
  font-family: var(--font-mono);
  font-size: 9.5px;
}

.cron-value em {
  overflow: hidden;
  color: #a0a8b9;
  font-size: 9.5px;
  font-style: normal;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.last-run-value :deep(.status-pill) {
  height: 20px;
  padding: 0 7px;
  font-size: 9.5px;
}

.last-run-value em {
  color: #a0a8b9;
  font-size: 9.5px;
  font-style: normal;
}

.meta-idle {
  color: #b1b8c7;
  font-size: 10px;
}

.card-footer {
  display: flex;
  align-items: center;
  gap: 2px;
  margin: auto -20px 0;
  padding: 10px 13px;
  border-top: 1px solid #f2f4f8;
}

.card-action {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  height: 29px;
  padding: 0 9px;
  color: #727c92;
  background: transparent;
  border: 0;
  border-radius: 7px;
  font-size: 10.5px;
  font-weight: 550;
  cursor: pointer;
  transition: all 0.15s ease;
}

.card-action:hover {
  color: var(--brand-strong);
  background: #f5f5fe;
}

.card-action:disabled {
  color: #b7bdc9;
  cursor: not-allowed;
}

.card-action:disabled:hover {
  color: #b7bdc9;
  background: transparent;
}

.footer-spacer {
  flex: 1;
}

.icon-action {
  display: grid;
  width: 29px;
  height: 29px;
  place-items: center;
  color: #9ca5b8;
  background: transparent;
  border: 0;
  border-radius: 7px;
  font-size: 13px;
  cursor: pointer;
  transition: all 0.15s ease;
}

.icon-action:hover {
  color: var(--ink-soft);
  background: #f4f6fa;
}

.empty-library {
  display: flex;
  align-items: center;
  flex-direction: column;
  padding: 58px 26px 52px;
  text-align: center;
}

.empty-library.compact {
  padding: 20px;
}

.empty-art {
  position: relative;
  display: grid;
  width: 90px;
  height: 90px;
  place-items: center;
  margin-bottom: 18px;
}

.empty-ring {
  position: absolute;
  border: 1px solid #e7eaf5;
  border-radius: 50%;
}

.ring-one {
  inset: 0;
}

.ring-two {
  inset: 11px;
  border-style: dashed;
  animation: spin-slow 26s linear infinite;
}

.empty-icon {
  display: grid;
  width: 48px;
  height: 48px;
  place-items: center;
  background: linear-gradient(140deg, #f2efff, #e8f2ff);
  border-radius: 14px;
  font-size: 24px;
  box-shadow: 0 8px 20px rgba(83, 84, 200, 0.1);
}

.empty-library h2 {
  color: #303b53;
  font-size: 17px;
  font-weight: 680;
  letter-spacing: -0.01em;
}

.empty-library > p {
  max-width: 470px;
  margin-top: 7px;
  color: #8f98ab;
  font-size: 12px;
  line-height: 1.8;
}

.empty-library > p code {
  padding: 1px 5px;
  color: #5b5bc8;
  background: #f1f1fd;
  border-radius: 4px;
  font-family: var(--font-mono);
  font-size: 10.5px;
}

.empty-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 22px;
  flex-wrap: wrap;
  justify-content: center;
}

.guide-link {
  margin-left: 5px;
  color: #7b84a0;
  font-size: 11.5px;
  font-weight: 600;
}

.guide-link:hover {
  color: var(--brand);
}

.reset-btn {
  margin-top: 7px;
}

.skeleton-card {
  height: 270px;
  padding: 22px;
  background: #fff;
  border: 1px solid var(--line);
  border-radius: 18px;
}

.skeleton {
  background: linear-gradient(90deg, #f3f5f9 25%, #eceff6 37%, #f3f5f9 63%);
  background-size: 400% 100%;
  border-radius: 6px;
  animation: skeleton-shine 1.4s ease infinite;
}

.skeleton-icon {
  width: 48px;
  height: 48px;
  border-radius: 14px;
}

.skeleton-title {
  width: 42%;
  height: 15px;
  margin-top: 17px;
}

.skeleton-line {
  width: 100%;
  height: 10px;
  margin-top: 18px;
}

.skeleton-meta {
  width: 75%;
  height: 10px;
  margin-top: 38px;
}

@keyframes skeleton-shine {
  0% {
    background-position: 100% 50%;
  }
  100% {
    background-position: 0 50%;
  }
}

@keyframes spin-slow {
  to {
    transform: rotate(360deg);
  }
}

/* ------------------------------------------------------------------ upload dialog */
.upload-intro {
  display: flex;
  align-items: flex-start;
  gap: 11px;
  margin-bottom: 18px;
}

.upload-intro-icon {
  display: grid;
  width: 36px;
  height: 36px;
  flex: none;
  place-items: center;
  color: #5d5bd6;
  background: #eff0ff;
  border-radius: 10px;
  font-size: 17px;
}

.upload-intro strong {
  color: #3d4860;
  font-size: 12.5px;
  font-weight: 650;
}

.upload-intro p {
  margin-top: 2px;
  color: #98a1b4;
  font-size: 10.5px;
  line-height: 1.65;
}

.upload-intro code {
  color: #5654c6;
  font-family: var(--font-mono);
  font-size: 9.5px;
}

.module-uploader :deep(.el-upload) {
  width: 100%;
}

.module-uploader :deep(.el-upload-dragger) {
  padding: 26px 18px;
  background: #fafbff;
  border: 1px dashed #d8dcea;
  border-radius: 13px;
  transition: all 0.18s ease;
}

.module-uploader :deep(.el-upload-dragger:hover) {
  background: #f6f6fe;
  border-color: #b8b9ed;
}

.upload-cloud {
  color: #8b8ce4;
  font-size: 32px;
}

.module-uploader :deep(.el-upload__text) {
  color: #7c869c;
  font-size: 12px;
}

.module-uploader :deep(.el-upload__text em) {
  color: var(--brand);
  font-style: normal;
  font-weight: 600;
}

.module-uploader :deep(.el-upload__tip) {
  margin-top: 6px;
  color: #a8b0c1;
  font-size: 10px;
}

.module-uploader :deep(.el-upload-list__item) {
  margin-top: 8px;
  font-size: 11.5px;
}

.upload-form {
  margin-top: 18px;
}

.upload-field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.upload-field label {
  color: #59647c;
  font-size: 11.5px;
  font-weight: 600;
}

.upload-field > span {
  color: #a5adbe;
  font-size: 9.5px;
}

.overwrite-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-top: 15px;
  padding: 11px 13px;
  background: #fafbfe;
  border: 1px solid #eff2f7;
  border-radius: 10px;
}

.overwrite-row strong {
  color: #5a657d;
  font-size: 11px;
  font-weight: 600;
}

.overwrite-row p {
  margin-top: 1px;
  color: #a1a9ba;
  font-size: 9.5px;
}

.zip-preview {
  position: relative;
  margin-top: 18px;
  padding: 13px 15px;
  background: #0f172a;
  border-radius: 12px;
}

.zip-preview-label {
  display: block;
  margin-bottom: 7px;
  color: rgba(198, 209, 237, 0.4);
  font-size: 8.5px;
  font-weight: 700;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}

.zip-preview pre {
  margin: 0;
  color: #c9d6ec;
  font-family: var(--font-mono);
  font-size: 10px;
  line-height: 1.7;
  white-space: pre-wrap;
}

.zip-optional {
  color: #64748b;
}

.zip-guide-link {
  position: absolute;
  right: 14px;
  bottom: 13px;
  display: inline-flex;
  align-items: center;
  gap: 3px;
  color: #a5b4fc;
  font-size: 9.5px;
}

@media (max-width: 980px) {
  .toolbar {
    flex-wrap: wrap;
  }

  .search-input {
    width: 100%;
  }

  .result-note {
    margin-left: 0;
  }
}

@media (max-width: 720px) {
  .modules-page {
    padding-top: 20px;
  }

  .module-grid {
    grid-template-columns: 1fr;
  }

  .toolbar {
    padding: 10px;
    gap: 8px;
  }

  .filter-group {
    width: 100%;
    overflow-x: auto;
    padding-bottom: 2px;
  }

  .filter-pill {
    flex: none;
  }

  .result-note {
    display: none;
  }

  .search-input {
    width: 100%;
  }

  .header-actions {
    display: grid;
    grid-template-columns: 1fr 1fr;
  }

  .empty-library {
    padding: 42px 18px;
  }

  .zip-guide-link {
    position: static;
    display: flex;
    margin-top: 8px;
  }
}
</style>