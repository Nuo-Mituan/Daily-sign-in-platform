<template>
  <div class="page-shell module-detail-page">
    <nav class="back-row" aria-label="面包屑">
      <button type="button" class="back-link" @click="router.push('/modules')">
        <el-icon><ArrowLeft /></el-icon>
        模块列表
      </button>
      <span class="back-slash">/</span>
      <span class="back-current">{{ module?.name || '模块配置' }}</span>
    </nav>

    <div v-if="loading" class="detail-loading">
      <div class="loading-card panel">
        <div class="skeleton skeleton-icon"></div>
        <div class="loading-lines">
          <div class="skeleton skeleton-title"></div>
          <div class="skeleton skeleton-line"></div>
        </div>
      </div>
    </div>

    <div v-else-if="notFound" class="panel empty-library">
      <div class="empty-state">
        <div class="empty-state__icon"><el-icon><Warning /></el-icon></div>
        <div class="empty-state__title">模块不存在或已被删除</div>
        <div class="empty-state__desc">它可能刚刚被移除。返回列表查看当前可用的模块。</div>
        <el-button type="primary" class="back-btn" @click="router.push('/modules')">返回模块列表</el-button>
      </div>
    </div>

    <template v-else-if="module">
      <section class="module-hero">
        <div class="hero-accent"></div>
        <div class="hero-left">
          <ModuleIcon :icon="module.icon" :size="68" :tone="module.id" />
          <div class="hero-copy">
            <div class="hero-title-line">
              <h1>{{ module.name }}</h1>
              <span class="version-badge">v{{ module.version }}</span>
              <span v-if="module.enabled" class="enabled-chip"><i></i>已启用</span>
              <span v-else class="disabled-chip">已禁用</span>
            </div>
            <p class="hero-desc">{{ module.description || '这个模块还没有填写描述。' }}</p>
            <div class="hero-meta">
              <span><el-icon><Key /></el-icon><code>{{ module.key }}</code></span>
              <span v-if="module.author"><el-icon><User /></el-icon>{{ module.author }}</span>
              <span><el-icon><Operation /></el-icon>{{ module.param_count }} 个参数</span>
              <span class="meta-divider"></span>
              <span>
                <el-icon><UserFilled /></el-icon>
                {{ module.multi_account ? `${module.account_count} 个账号` : '单账号' }}
              </span>
              <span>
                <el-icon><Bell /></el-icon>
                推送 {{ module.push_unified ? '统一' : module.push_independent ? '独立' : '关闭' }}
              </span>
              <span class="meta-divider"></span>
              <span class="meta-schedule">
                <el-icon><Calendar /></el-icon>
                {{ describeSchedule(module.start_time, module.end_time, module.repeat_cycle, module.repeat_sub_value) }}
              </span>
            </div>
          </div>
        </div>
        <div class="hero-actions">
          <div class="toggle-block">
            <span>{{ module.enabled ? '运行中' : '已暂停' }}</span>
            <el-switch
              :model-value="module.enabled"
              :loading="toggleLoading"
              :disabled="Boolean(module.load_error)"
              :before-change="toggleEnabled"
            />
          </div>
          <el-button
            class="run-button"
            :loading="runStarting"
            :disabled="Boolean(module.load_error)"
            @click="runNow"
          >
            <el-icon><VideoPlay /></el-icon>
            立即执行
          </el-button>
          <el-dropdown trigger="click" @command="handleHeaderCommand">
            <button type="button" class="more-button" aria-label="更多操作">
              <el-icon><MoreFilled /></el-icon>
            </button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="logs">
                  <el-icon><Document /></el-icon>
                  查看执行日志
                </el-dropdown-item>
                <el-dropdown-item command="delete" divided>
                  <el-icon><Delete /></el-icon>
                  删除模块
                </el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </section>

      <el-alert
        v-if="module.load_error"
        type="error"
        :closable="false"
        show-icon
        class="load-alert"
        title="模块加载异常"
      >
        <template #default>
          {{ module.load_error }}。请修复服务器上的模块文件后，在模块列表页点击“扫描目录”。
        </template>
      </el-alert>

      <el-tabs v-model="activeTab" class="detail-tabs" @tab-change="handleTabChange">
        <el-tab-pane name="config">
          <template #label>
            <span class="tab-label"><el-icon><Setting /></el-icon>账号与执行时间</span>
          </template>

          <div class="config-grid">
            <section class="panel params-panel">
              <div class="panel-head">
                <div>
                  <div class="panel-title">{{ module.multi_account ? '账号列表' : '模块参数' }}</div>
                  <div class="panel-desc">
                    <template v-if="module.multi_account">
                      按顺序串行执行；可拖拽排序，每个账号的参数独立加密保存。
                    </template>
                    <template v-else>
                      表单由模块的 config.json 自动生成，保存后加密写入数据库。
                    </template>
                  </div>
                </div>
                <span v-if="module.multi_account" class="required-note">
                  {{ accounts.length }} / 50 个账号
                </span>
                <span v-else-if="requiredCount" class="required-note">{{ requiredCount }} 个必填</span>
                <button type="button" class="reveal-btn" @click="revealSensitive">
                  <el-icon><View /></el-icon>
                  显示敏感值
                </button>
              </div>
              <div class="panel-body">
                <AccountEditor
                  v-if="module.multi_account"
                  v-model="accounts"
                  :param-schema="module.param_schema"
                  :max="50"
                />
                <div v-else-if="!module.param_schema.length" class="empty-params">
                  <el-icon><CircleCheck /></el-icon>
                  <div>
                    <strong>此模块无需配置参数</strong>
                    <p>设置随机时间窗并启用即可运行。</p>
                  </div>
                </div>
                <el-form
                  v-else
                  ref="paramsFormRef"
                  :model="params"
                  label-position="top"
                  class="params-form"
                >
                  <el-form-item
                    v-for="param in module.param_schema"
                    :key="param.key"
                    :label="param.label"
                    :prop="param.key"
                    :rules="rulesFor(param)"
                  >
                    <ParamField
                      v-model="params[param.key]"
                      :param="param"
                      :disabled="Boolean(module.load_error)"
                    />
                    <div v-if="param.help" class="param-help">
                      <el-icon><InfoFilled /></el-icon>{{ param.help }}
                    </div>
                    <div v-else-if="param.type === 'password'" class="param-help">
                      <el-icon><Lock /></el-icon>敏感参数会加密存储，请勿在公共设备上保存。
                    </div>
                  </el-form-item>
                </el-form>
              </div>
            </section>

            <aside class="config-side">
              <section class="panel schedule-panel">
                <div class="panel-head">
                  <div>
                    <div class="panel-title">随机执行时间</div>
                    <div class="panel-desc">执行日 00:00 生成随机时间，保存后立即重新安排</div>
                  </div>
                  <span class="cron-icon"><el-icon><Timer /></el-icon></span>
                </div>
                <div class="panel-body">
                  <RandomScheduleField
                    :start-time="startTime"
                    :end-time="endTime"
                    :repeat-cycle="repeatCycle"
                    :repeat-sub-value="repeatSubValue"
                    @update:start-time="(value) => (startTime = value)"
                    @update:end-time="(value) => (endTime = value)"
                    @update:repeat-cycle="(value) => (repeatCycle = value)"
                    @update:repeat-sub-value="(value) => (repeatSubValue = value)"
                  />

                  <div class="schedule-summary">
                    <div class="summary-row">
                      <span>当前已保存</span>
                      <code>{{ module.start_time }}–{{ module.end_time }} · {{ cycleDayLabel(module.repeat_cycle, module.repeat_sub_value) }}</code>
                    </div>
                    <div class="summary-row">
                      <span>本次执行时间</span>
                      <strong>{{ currentScheduleLabel }}</strong>
                    </div>
                    <div class="summary-row">
                      <span>执行状态</span>
                      <span class="schedule-pill" :class="scheduleMeta.className">
                        <i></i>{{ scheduleMeta.label }}
                      </span>
                    </div>
                    <div v-if="module.schedule_note" class="schedule-note">
                      {{ module.schedule_note }}
                    </div>
                  </div>

                  <div class="schedule-actions">
                    <button
                      type="button"
                      class="reset-cron"
                      :disabled="Boolean(module.load_error)"
                      @click="resetDefaultSchedule"
                    >
                      <el-icon><RefreshLeft /></el-icon>
                      使用模块默认时间窗
                    </button>
                    <button
                      type="button"
                      class="regenerate-btn"
                      :disabled="!module.enabled || regenerating || Boolean(module.load_error)"
                      :title="module.enabled ? '重新生成本期随机时间' : '请先启用模块'"
                      @click="regenerateSchedule"
                    >
                      <el-icon :class="{ 'is-loading': regenerating }"><Refresh /></el-icon>
                      重新生成
                    </button>
                  </div>

                  <div class="push-toggle-row">
                    <div>
                      <strong><el-icon><Bell /></el-icon>独立推送</strong>
                      <p>本模块每次执行结束后立即单独发送一条通知。</p>
                    </div>
                    <el-switch v-model="pushIndependent" />
                  </div>
                  <div class="push-toggle-row">
                    <div>
                      <strong><el-icon><Bell /></el-icon>统一推送</strong>
                      <p>加入每日统一批次，所有模块终态后汇总为一条日报；统一优先级高于独立推送。</p>
                    </div>
                    <el-switch v-model="pushUnified" />
                  </div>
                  <p v-if="pushIndependent && pushUnified" class="push-priority-hint">
                    两种推送同时开启时，统一推送优先，本次执行不会再发送独立消息。
                  </p>
                  <router-link to="/settings" class="push-config-link">
                    配置全局推送渠道 <el-icon><ArrowRight /></el-icon>
                  </router-link>
                </div>
              </section>

              <section class="panel tips-panel">
                <div class="tips-head">
                  <span class="tips-icon"><el-icon><Lock /></el-icon></span>
                  <strong>执行说明</strong>
                </div>
                <ul>
                  <li>执行日：每日 / 选定星期 / 每月15日 / 每月选定日期 / 每年选定月-日。</li>
                  <li>多账号按列表顺序串行执行，账号间随机等待 {{ intervalText }}。</li>
                  <li>推送内容可到用户设置中自定义模板变量。</li>
                  <li>参数通过 SECRET_KEY 派生密钥加密，请勿随意更换。</li>
                </ul>
              </section>
            </aside>
          </div>

          <div class="save-bar">
            <div class="save-hint">
              <el-icon><InfoFilled /></el-icon>
              保存后若时间窗或周期变化，会取消旧计划并重新生成本期随机时间。{{ timezone }} 时区。
            </div>
            <div class="save-actions">
              <el-button :disabled="saving" @click="reloadDetail">还原修改</el-button>
              <el-button
                type="primary"
                :loading="saving"
                :disabled="Boolean(module.load_error)"
                @click="saveConfig"
              >
                <el-icon v-if="!saving"><Select /></el-icon>
                保存配置
              </el-button>
            </div>
          </div>
        </el-tab-pane>

        <el-tab-pane name="logs">
          <template #label>
            <span class="tab-label"><el-icon><Document /></el-icon>执行日志</span>
          </template>

          <section class="panel logs-panel">
            <div class="panel-head logs-head">
              <div>
                <div class="panel-title">运行记录</div>
                <div class="panel-desc">点击任意一行查看完整日志，执行中的任务会实时输出</div>
              </div>
              <div class="logs-actions">
                <el-select
                  v-model="logStatusFilter"
                  placeholder="全部状态"
                  clearable
                  class="status-filter"
                  @change="handleStatusFilter"
                >
                  <el-option label="全部状态" value="" />
                  <el-option label="成功" value="success" />
                  <el-option label="失败" value="failed" />
                  <el-option label="执行中" value="running" />
                </el-select>
                <el-button text :loading="logsLoading" @click="loadLogs">
                  <el-icon><Refresh /></el-icon>
                  刷新
                </el-button>
                <el-button text type="danger" :disabled="!logs.length" @click="clearLogs">
                  清空记录
                </el-button>
              </div>
            </div>
            <div class="panel-body logs-body">
              <el-table
                v-if="logs.length"
                :data="logs"
                class="logs-table"
                @row-click="openLog"
              >
                <el-table-column label="开始时间" width="170">
                  <template #default="{ row }">
                    <div class="time-cell">
                      <span>{{ formatDateTime(row.started_at) }}</span>
                      <small>{{ timeFromNow(row.started_at) }}</small>
                    </div>
                  </template>
                </el-table-column>
                <el-table-column label="触发" width="96">
                  <template #default="{ row }">
                    <span class="trigger-label">{{ triggerLabel(row.trigger) }}</span>
                  </template>
                </el-table-column>
                <el-table-column label="状态" width="100">
                  <template #default="{ row }">
                    <StatusTag :status="row.status" />
                  </template>
                </el-table-column>
                <el-table-column label="耗时" width="96">
                  <template #default="{ row }">
                    <span class="duration">{{ formatDuration(row.duration_ms) }}</span>
                  </template>
                </el-table-column>
                <el-table-column label="结果" min-width="260">
                  <template #default="{ row }">
                    <span class="result-message">{{ row.message || '—' }}</span>
                  </template>
                </el-table-column>
                <el-table-column width="40" align="right">
                  <template #default>
                    <el-icon class="row-arrow"><ArrowRight /></el-icon>
                  </template>
                </el-table-column>
              </el-table>
              <div v-else class="empty-state">
                <div class="empty-state__icon"><el-icon><Document /></el-icon></div>
                <div class="empty-state__title">还没有执行记录</div>
                <div class="empty-state__desc">
                  点击上方“立即执行”手动运行一次，或等待随机计划时间自动触发。
                </div>
              </div>

              <div v-if="logTotal > logPageSize" class="pagination-row">
                <span class="muted">共 {{ logTotal }} 条记录</span>
                <el-pagination
                  v-model:current-page="logPage"
                  :page-size="logPageSize"
                  :total="logTotal"
                  layout="prev, pager, next"
                  background
                  @current-change="loadLogs"
                />
              </div>
            </div>
          </section>
        </el-tab-pane>
      </el-tabs>

      <RunLogDrawer
        v-model="logDrawerOpen"
        :log-id="selectedLogId"
        :title="module.name"
        @finished="handleLogFinished"
      />
    </template>
  </div>
</template>

<script setup>
import {
  computed,
  onMounted,
  reactive,
  ref,
  watch,
} from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  ArrowLeft,
  ArrowRight,
  Bell,
  Calendar,
  CircleCheck,
  Delete,
  Document,
  InfoFilled,
  Key,
  Lock,
  MoreFilled,
  Operation,
  Refresh,
  View,
  RefreshLeft,
  Select,
  Setting,
  Timer,
  User,
  UserFilled,
  VideoPlay,
  Warning,
} from '@element-plus/icons-vue'
import ModuleIcon from '@/components/ModuleIcon.vue'
import StatusTag from '@/components/StatusTag.vue'
import ParamField from '@/components/ParamField.vue'
import AccountEditor from '@/components/AccountEditor.vue'
import RandomScheduleField from '@/components/RandomScheduleField.vue'
import RunLogDrawer from '@/components/RunLogDrawer.vue'
import { logsApi, modulesApi } from '@/api'
import { useAppStore } from '@/stores/app'
import {
  cycleDayLabel,
  describeSchedule,
  normalizeRepeatSubValue,
  scheduleStatusMeta,
  validateSchedule,
} from '@/utils/schedule'
import {
  createAccount,
  fillAccountParams,
  validateAccountFields,
} from '@/utils/accounts'
import {
  formatDateTime,
  formatDuration,
  timeFromNow,
  triggerLabel,
} from '@/utils/format'

const route = useRoute()
const router = useRouter()
const appStore = useAppStore()

const loading = ref(true)
const notFound = ref(false)
const module = ref(null)
const params = reactive({})
const accounts = ref([])
const paramsFormRef = ref(null)
const startTime = ref('08:00')
const endTime = ref('10:00')
const repeatCycle = ref('daily')
const repeatSubValue = ref('')
const pushIndependent = ref(false)
const pushUnified = ref(false)
const activeTab = ref(route.query.tab === 'logs' ? 'logs' : 'config')
const saving = ref(false)
const toggleLoading = ref(false)
const regenerating = ref(false)
const runStarting = ref(false)

const logs = ref([])
const logsLoading = ref(false)
const logPage = ref(1)
const logPageSize = 10
const logTotal = ref(0)
const logStatusFilter = ref('')
const logDrawerOpen = ref(false)
const selectedLogId = ref(null)

const timezone = computed(() => appStore.meta?.timezone || 'Asia/Shanghai')
const requiredCount = computed(
  () => (module.value?.param_schema || []).filter((item) => item.required).length,
)
const scheduleMeta = computed(() =>
  scheduleStatusMeta(module.value?.schedule_status || 'none'),
)
const currentScheduleLabel = computed(() => {
  if (!module.value?.current_schedule_at) return '尚未生成本期时间'
  return formatDateTime(module.value.current_schedule_at)
})
const intervalText = computed(() => {
  const meta = appStore.meta
  if (!meta) return '2–5 分钟'
  const min = Number(meta.account_interval_min_seconds || 0)
  const max = Number(meta.account_interval_max_seconds || 0)
  if (max < 60) return `${min}–${max} 秒`
  return `${Math.round(min / 60)}–${Math.round(max / 60)} 分钟`
})

function mergeSummary(summary) {
  if (!summary || !module.value) return
  for (const key of [
    'enabled',
    'push_enabled',
    'push_independent',
    'push_unified',
    'current_schedule_at',
    'schedule_period_start',
    'schedule_status',
    'schedule_source',
    'schedule_fallback_used',
    'schedule_note',
    'last_run_at',
    'last_status',
    'last_message',
  ]) {
    if (summary[key] !== undefined) module.value[key] = summary[key]
  }
}

function hydrateParams(detail) {
  Object.keys(params).forEach((key) => delete params[key])
  for (const spec of detail.param_schema || []) {
    let value = detail.params?.[spec.key]
    if (spec.type === 'switch') {
      value = value === undefined || value === null ? Boolean(spec.default) : Boolean(value)
    } else if (value === undefined || value === null || value === '') {
      if (spec.default !== undefined && spec.default !== null) {
        value = spec.default
      } else if (spec.type === 'number') {
        value = undefined
      } else {
        value = ''
      }
    }
    params[spec.key] = value
  }
}

function hydrateAccounts(detail) {
  if (!detail.multi_account) {
    accounts.value = []
    return
  }
  const schema = detail.param_schema || []
  let list = (detail.accounts || []).map((account) => ({
    id: account.id,
    label: account.label || '',
    params: fillAccountParams(schema, account.params || {}),
  }))
  if (!list.length) {
    list = [createAccount(schema)]
  }
  accounts.value = list
}

function applyModule(detail) {
  module.value = detail
  startTime.value = detail.start_time || '08:00'
  endTime.value = detail.end_time || '10:00'
  repeatCycle.value = detail.repeat_cycle || 'daily'
  repeatSubValue.value =
    detail.repeat_sub_value || detail.default_repeat_sub_value || ''
  pushIndependent.value = Boolean(detail.push_independent)
  pushUnified.value = Boolean(detail.push_unified)
  if (detail.multi_account) {
    Object.keys(params).forEach((key) => delete params[key])
    hydrateAccounts(detail)
  } else {
    accounts.value = []
    hydrateParams(detail)
  }
  paramsFormRef.value?.clearValidate()
}

async function initialize() {
  loading.value = true
  notFound.value = false
  module.value = null
  try {
    const detail = await modulesApi.get(route.params.id)
    applyModule(detail)
    activeTab.value = route.query.tab === 'logs' ? 'logs' : 'config'
    await loadLogs()
  } catch (error) {
    if (error.status === 404) {
      notFound.value = true
    }
  } finally {
    loading.value = false
  }
}

async function reloadDetail() {
  try {
    const detail = await modulesApi.get(route.params.id)
    applyModule(detail)
    ElMessage.info('已还原为最近一次保存的配置')
  } catch {
    // Error shown by the HTTP layer.
  }
}

function rulesFor(param) {
  const rules = []
  if (param.required && param.type !== 'switch') {
    rules.push({
      required: true,
      message: `请填写${param.label}`,
      trigger: param.type === 'select' ? 'change' : ['blur', 'change'],
    })
  }
  return rules
}

async function saveConfig() {
  const scheduleError = validateSchedule(startTime.value, endTime.value)
  if (scheduleError) {
    ElMessage.warning(scheduleError)
    return
  }

  if (module.value.multi_account) {
    if (!accounts.value.length) {
      ElMessage.warning('请至少添加一个账号')
      return
    }
    for (let index = 0; index < accounts.value.length; index += 1) {
      const error = validateAccountFields(
        accounts.value[index],
        module.value.param_schema || [],
        index,
      )
      if (error) {
        ElMessage.warning(error)
        return
      }
    }
  } else if (paramsFormRef.value) {
    try {
      await paramsFormRef.value.validate()
    } catch {
      ElMessage.warning('请先完善必填参数')
      return
    }
  }

  saving.value = true
  try {
    repeatSubValue.value = normalizeRepeatSubValue(
      repeatCycle.value,
      repeatSubValue.value,
    )
    const payload = {
      start_time: String(startTime.value).trim(),
      end_time: String(endTime.value).trim(),
      repeat_cycle: repeatCycle.value,
      repeat_sub_value: repeatSubValue.value,
      push_enabled: pushIndependent.value || pushUnified.value,
      push_independent: pushIndependent.value,
      push_unified: pushUnified.value,
    }
    if (module.value.multi_account) {
      payload.accounts = accounts.value.map((account) => ({
        id: account.id,
        label: account.label || '',
        params: { ...account.params },
      }))
    } else {
      payload.params = { ...params }
    }
    const detail = await modulesApi.update(module.value.id, payload)
    applyModule(detail)
    ElMessage.success('配置已保存，随机执行时间已按最新设置安排')
  } catch {
    // Error shown by the HTTP layer.
  } finally {
    saving.value = false
  }
}

async function revealSensitive() {
  let password = ''
  try {
    const result = await ElMessageBox.prompt(
      '敏感值仅在本次页面会话中临时显示。请输入当前密码验证。',
      '显示敏感值',
      {
        confirmButtonText: '验证并显示',
        cancelButtonText: '取消',
        inputType: 'password',
        inputPlaceholder: '当前登录密码',
        inputValidator: (value) => Boolean(value) || '请输入当前密码',
      },
    )
    password = result.value
  } catch {
    return
  }
  try {
    const data = await modulesApi.revealSensitive(module.value.id, {
      current_password: password,
    })
    if (module.value.multi_account) {
      const byId = new Map(
        (data.accounts || []).map((account) => [account.id, account.params]),
      )
      accounts.value.forEach((account) => {
        const values = byId.get(account.id)
        if (values) Object.assign(account.params, values)
      })
    } else {
      Object.assign(params, data.params || {})
    }
    ElMessage.success('敏感值已临时显示，刷新页面后恢复掩码')
  } catch {
    // HTTP layer displays validation / password errors.
  }
}

async function regenerateSchedule() {
  if (!module.value?.enabled) {
    ElMessage.warning('请先启用模块后再重新生成')
    return
  }
  regenerating.value = true
  try {
    const result = await modulesApi.regenerateSchedule(module.value.id)
    mergeSummary(result.module)
    ElMessage.success(result.message || '本期随机执行时间已重新生成')
  } catch {
    // Error shown by the HTTP layer.
  } finally {
    regenerating.value = false
  }
}

function resetDefaultSchedule() {
  startTime.value = module.value.default_start_time
  endTime.value = module.value.default_end_time
  repeatCycle.value = module.value.default_repeat_cycle
  repeatSubValue.value = module.value.default_repeat_sub_value || ''
}

async function toggleEnabled() {
  if (toggleLoading.value || module.value.load_error) return false
  toggleLoading.value = true
  try {
    const updated = await modulesApi.toggle(module.value.id, !module.value.enabled)
    mergeSummary(updated)
    ElMessage.success(
      updated.enabled
        ? '模块已启用，已生成本期随机执行时间'
        : '模块已暂停，随机执行任务已移除',
    )
    return true
  } catch {
    return false
  } finally {
    toggleLoading.value = false
  }
}

async function runNow() {
  if (runStarting.value) return
  runStarting.value = true
  try {
    const result = await modulesApi.run(module.value.id)
    selectedLogId.value = result.log_id
    logDrawerOpen.value = true
    activeTab.value = 'logs'
    router.replace({ query: { ...route.query, tab: 'logs' } })
    logPage.value = 1
    await loadLogs()
  } catch {
    // Error shown by the HTTP layer.
  } finally {
    runStarting.value = false
  }
}

async function handleLogFinished() {
  try {
    const [detail] = await Promise.all([modulesApi.get(module.value.id), loadLogs()])
    applyModule(detail)
  } catch {
    // Ignore refresh failures; the drawer still shows the final output.
  }
}

function openLog(row) {
  selectedLogId.value = row.id
  logDrawerOpen.value = true
}

async function loadLogs() {
  if (!module.value) return
  logsLoading.value = true
  try {
    const query = {
      module_id: module.value.id,
      page: logPage.value,
      page_size: logPageSize,
    }
    if (logStatusFilter.value) query.status = logStatusFilter.value
    const data = await logsApi.list(query)
    logs.value = data.items
    logTotal.value = data.total
  } catch {
    // Error shown by the HTTP layer.
  } finally {
    logsLoading.value = false
  }
}

function handleStatusFilter() {
  logPage.value = 1
  loadLogs()
}

async function clearLogs() {
  try {
    await ElMessageBox.confirm(
      '清空后该模块的所有历史执行记录将被删除，日志文件仍保留在服务器 logs 目录。确定继续吗？',
      '清空执行记录',
      {
        confirmButtonText: '清空',
        cancelButtonText: '取消',
        type: 'warning',
      },
    )
  } catch {
    return
  }
  try {
    const result = await logsApi.clear(module.value.id)
    ElMessage.success(result.message)
    logPage.value = 1
    await loadLogs()
  } catch {
    // Error shown by the HTTP layer.
  }
}

function handleTabChange(name) {
  router.replace({ query: { ...route.query, tab: name } })
  if (name === 'logs') loadLogs()
}

async function handleHeaderCommand(command) {
  if (command === 'logs') {
    activeTab.value = 'logs'
    handleTabChange('logs')
    await loadLogs()
  } else if (command === 'delete') {
    await deleteModule()
  }
}

async function deleteModule() {
  try {
    await ElMessageBox.confirm(
      `删除「${module.value.name}」会同时移除 modules/${module.value.key} 目录和全部历史日志，且不可恢复。\n确定继续吗？`,
      '删除模块',
      {
        confirmButtonText: '确认删除',
        cancelButtonText: '取消',
        type: 'warning',
      },
    )
  } catch {
    return
  }
  try {
    const result = await modulesApi.remove(module.value.id)
    ElMessage.success(result.message)
    router.push('/modules')
  } catch {
    // Error shown by the HTTP layer.
  }
}

watch(
  () => route.params.id,
  () => initialize(),
)

onMounted(async () => {
  appStore.fetchMeta()
  await initialize()
})
</script>

<style scoped>
.module-detail-page {
  padding-top: 24px;
}

.back-row {
  display: flex;
  align-items: center;
  gap: 9px;
  margin-bottom: 16px;
  font-size: 11.5px;
}

.back-link {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 0;
  color: #8993a8;
  background: transparent;
  border: 0;
  font-size: 11.5px;
  font-weight: 550;
  cursor: pointer;
}

.back-link:hover {
  color: var(--brand);
}

.back-slash {
  color: #c4cad6;
}

.back-current {
  overflow: hidden;
  color: #657087;
  font-weight: 600;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.detail-loading {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.loading-card {
  display: flex;
  align-items: center;
  gap: 18px;
  padding: 28px;
}

.loading-lines {
  flex: 1;
}

.skeleton {
  background: linear-gradient(90deg, #f3f5f9 25%, #eceff6 37%, #f3f5f9 63%);
  background-size: 400% 100%;
  border-radius: 6px;
  animation: skeleton-shine 1.4s ease infinite;
}

.skeleton-icon {
  width: 68px;
  height: 68px;
  border-radius: 18px;
}

.skeleton-title {
  width: 30%;
  height: 17px;
}

.skeleton-line {
  width: 60%;
  height: 11px;
  margin-top: 13px;
}

@keyframes skeleton-shine {
  0% {
    background-position: 100% 50%;
  }
  100% {
    background-position: 0 50%;
  }
}

.module-hero {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 24px;
  padding: 26px 28px;
  overflow: hidden;
  background:
    radial-gradient(circle at 92% -20%, rgba(99, 102, 241, 0.08), transparent 36%),
    #fff;
  border: 1px solid var(--line);
  border-radius: 20px;
  box-shadow: var(--shadow-sm);
}

.hero-accent {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 3px;
  background: linear-gradient(90deg, #6366f1, #8b5cf6 42%, #22d3ee 72%, transparent);
  opacity: 0.75;
}

.hero-left {
  display: flex;
  min-width: 0;
  align-items: flex-start;
  gap: 18px;
}

.hero-copy {
  min-width: 0;
}

.hero-title-line {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}

.hero-title-line h1 {
  color: #1c2740;
  font-size: 24px;
  font-weight: 750;
  letter-spacing: -0.03em;
}

.version-badge {
  padding: 2px 6px;
  color: #8d97ac;
  background: #f5f7fb;
  border: 1px solid #eaeef5;
  border-radius: 5px;
  font-family: var(--font-mono);
  font-size: 9px;
}

.enabled-chip,
.disabled-chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 9.5px;
  font-weight: 600;
}

.enabled-chip {
  color: #0b8765;
  background: var(--mint-soft);
}

.enabled-chip i {
  width: 5px;
  height: 5px;
  background: #10b981;
  border-radius: 50%;
}

.disabled-chip {
  color: #8d95a7;
  background: #f2f4f8;
}

.hero-desc {
  max-width: 640px;
  margin-top: 6px;
  color: #8993a8;
  font-size: 11.5px;
  line-height: 1.7;
}

.hero-meta {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 14px;
  margin-top: 11px;
  color: #98a1b3;
  font-size: 10px;
}

.hero-meta span {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.hero-meta code {
  color: #69748b;
  font-family: var(--font-mono);
  font-size: 9.5px;
}

.meta-divider {
  width: 1px;
  height: 11px;
  background: #e5e9f1;
}

.meta-schedule {
  color: #8a93ab;
}

.meta-schedule .el-icon {
  color: #a4abcb;
}

.hero-actions {
  display: flex;
  flex: none;
  align-items: center;
  gap: 10px;
}

.toggle-block {
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 7px 12px;
  background: #f8f9fc;
  border: 1px solid #eef1f7;
  border-radius: 10px;
}

.toggle-block > span {
  color: #7c869b;
  font-size: 10.5px;
  font-weight: 550;
  white-space: nowrap;
}

.run-button {
  height: 36px;
  padding: 0 14px;
  font-size: 11.5px;
}

.more-button {
  display: grid;
  width: 36px;
  height: 36px;
  place-items: center;
  color: #8e97a9;
  background: #fff;
  border: 1px solid var(--line);
  border-radius: 9px;
  cursor: pointer;
}

.more-button:hover {
  color: var(--ink);
  background: #f7f8fc;
}

.load-alert {
  margin-top: 14px;
}

.detail-tabs {
  margin-top: 18px;
}

.detail-tabs :deep(.el-tabs__header) {
  margin-bottom: 17px;
  padding: 0 18px;
  background: #fff;
  border: 1px solid var(--line);
  border-radius: 13px;
  box-shadow: var(--shadow-sm);
}

.detail-tabs :deep(.el-tabs__nav-wrap::after) {
  display: none;
}

.detail-tabs :deep(.el-tabs__item) {
  height: 48px;
  font-size: 12px;
}

.detail-tabs :deep(.el-tabs__active-bar) {
  bottom: 8px;
  height: 2.5px;
}

.tab-label {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.config-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.3fr) minmax(330px, 0.7fr);
  gap: 18px;
  align-items: start;
}

.params-panel,
.schedule-panel {
  min-width: 0;
}

.required-note {
  flex: none;
  padding: 3px 8px;
  color: #9a6b1d;
  background: #fdf6e8;
  border-radius: 999px;
  font-size: 9px;
  font-weight: 600;
  white-space: nowrap;
}

.params-form :deep(.el-form-item) {
  margin-bottom: 20px;
}

.params-form :deep(.el-form-item:last-child) {
  margin-bottom: 6px;
}

.params-form :deep(.el-form-item__label) {
  padding-bottom: 5px;
  font-size: 11.5px;
}

.params-form :deep(.el-input-number .el-input__inner) {
  text-align: left;
}

.param-help {
  display: flex;
  width: 100%;
  flex: 1 0 100%;
  align-items: flex-start;
  gap: 4px;
  margin-top: 5px;
  color: #a2abbc;
  font-size: 9.5px;
  line-height: 1.6;
}

.empty-params {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 18px;
  color: #0b8765;
  background: #f2fbf7;
  border: 1px dashed #c8ecdf;
  border-radius: 12px;
}

.empty-params > .el-icon {
  flex: none;
  font-size: 21px;
}

.empty-params strong {
  font-size: 12px;
  font-weight: 650;
}

.empty-params p {
  margin-top: 1px;
  color: #7ba998;
  font-size: 10.5px;
}

.config-side {
  display: flex;
  flex-direction: column;
  gap: 18px;
  min-width: 0;
}

.cron-icon {
  display: grid;
  width: 30px;
  height: 30px;
  place-items: center;
  color: #6260d6;
  background: #f0f1ff;
  border-radius: 8px;
  font-size: 14px;
}

.field-label {
  display: block;
  margin-bottom: 8px;
  color: #59647c;
  font-size: 11.5px;
  font-weight: 600;
}

.schedule-summary {
  display: flex;
  flex-direction: column;
  gap: 9px;
  margin-top: 15px;
  padding: 13px 14px;
  background: #f9fafd;
  border: 1px solid #f0f2f7;
  border-radius: 11px;
}

.summary-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  color: #98a1b3;
  font-size: 10.5px;
}

.summary-row code {
  color: #5a58c7;
  font-family: var(--font-mono);
  font-size: 10px;
}

.summary-row strong {
  color: #5c6680;
  font-family: var(--font-mono);
  font-size: 10px;
  font-weight: 600;
}

.schedule-pill {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 7px;
  border-radius: 999px;
  font-size: 9.5px;
  font-weight: 600;
}

.schedule-pill i {
  width: 4px;
  height: 4px;
  background: currentColor;
  border-radius: 50%;
}

.schedule-pill.is-pending {
  color: #5757c6;
  background: #f0f1fe;
}

.schedule-pill.is-fallback {
  color: #9b6b17;
  background: #fdf5e6;
}

.schedule-pill.is-running {
  color: #4f52c4;
  background: #eef0ff;
}

.schedule-pill.is-success {
  color: #0b8765;
  background: #eaf9f3;
}

.schedule-pill.is-failed {
  color: #c13c3c;
  background: #fdf0f0;
}

.schedule-pill.is-idle {
  color: #949cad;
  background: #f3f5f8;
}

.schedule-note {
  padding-top: 7px;
  color: #a0a8b9;
  border-top: 1px dashed #eceff5;
  font-size: 9px;
  line-height: 1.55;
}

.schedule-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 9px;
  flex-wrap: wrap;
  margin-top: 11px;
}

.schedule-actions .reset-cron {
  margin-top: 0;
}

.regenerate-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  height: 27px;
  padding: 0 9px;
  color: #5c5bc6;
  background: #f3f3fe;
  border: 1px solid #e5e5f9;
  border-radius: 7px;
  font-size: 9.5px;
  font-weight: 550;
  cursor: pointer;
}

.regenerate-btn:hover:not(:disabled) {
  background: #ecedfe;
}

.regenerate-btn:disabled {
  color: #a9b0c0;
  background: #f6f7fa;
  border-color: #eef0f5;
  cursor: not-allowed;
}

.push-toggle-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  margin-top: 14px;
  padding: 11px 12px;
  background: #fafbfe;
  border: 1px solid #eef1f7;
  border-radius: 10px;
}

.push-toggle-row strong {
  display: flex;
  align-items: center;
  gap: 4px;
  color: #59647c;
  font-size: 10.5px;
  font-weight: 620;
}

.push-toggle-row p {
  max-width: 245px;
  margin-top: 2px;
  color: #a0a8b9;
  font-size: 8.5px;
  line-height: 1.55;
}

.reveal-btn {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  margin-left: auto;
  padding: 0;
  color: #777fcc;
  background: transparent;
  border: 0;
  font-size: 9.5px;
  cursor: pointer;
}

.reveal-btn:hover {
  color: var(--brand);
}

.push-priority-hint {
  margin: 6px 0 0;
  color: #b07b35;
  font-size: 9px;
  line-height: 1.6;
}

.push-config-link {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  margin-top: 8px;
  color: #8a92a5;
  font-size: 9px;
}

.push-config-link:hover {
  color: var(--brand);
}

.reset-cron {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  margin-top: 13px;
  padding: 0;
  color: #8c95a8;
  background: transparent;
  border: 0;
  font-size: 10px;
  cursor: pointer;
}

.reset-cron:hover:not(:disabled) {
  color: var(--brand);
}

.reset-cron:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.tips-panel {
  padding: 17px 18px;
}

.tips-head {
  display: flex;
  align-items: center;
  gap: 7px;
  color: #606b82;
  font-size: 11.5px;
}

.tips-icon {
  display: grid;
  width: 24px;
  height: 24px;
  place-items: center;
  color: #7d84c9;
  background: #f2f3fe;
  border-radius: 6px;
  font-size: 11px;
}

.tips-panel ul {
  display: flex;
  flex-direction: column;
  gap: 7px;
  margin: 11px 0 0;
  padding: 0 0 0 2px;
  list-style: none;
}

.tips-panel li {
  position: relative;
  padding-left: 11px;
  color: #9ba3b5;
  font-size: 9.5px;
  line-height: 1.7;
}

.tips-panel li::before {
  position: absolute;
  top: 7px;
  left: 0;
  width: 3px;
  height: 3px;
  background: #c7ccd9;
  border-radius: 50%;
  content: "";
}

.save-bar {
  position: sticky;
  bottom: 16px;
  z-index: 5;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-top: 18px;
  padding: 13px 18px;
  background: rgba(255, 255, 255, 0.9);
  border: 1px solid var(--line);
  border-radius: 14px;
  box-shadow: 0 12px 32px rgba(28, 38, 68, 0.1);
  backdrop-filter: blur(14px);
}

.save-hint {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  color: #949db0;
  font-size: 10px;
}

.save-actions {
  display: flex;
  gap: 8px;
}

.logs-panel {
  min-width: 0;
}

.logs-head {
  align-items: center;
  flex-wrap: wrap;
}

.logs-actions {
  display: flex;
  align-items: center;
  gap: 3px;
}

.status-filter {
  width: 115px;
  margin-right: 4px;
}

.status-filter :deep(.el-select__wrapper) {
  background: #f8f9fc;
  box-shadow: none;
  font-size: 11px;
}

.logs-body {
  padding-top: 14px;
  overflow-x: auto;
}

.logs-table {
  width: 100%;
}

.logs-table :deep(.el-table__row) {
  cursor: pointer;
}

.time-cell {
  display: flex;
  flex-direction: column;
  line-height: 1.45;
}

.time-cell span {
  color: #5f6a81;
  font-size: 11px;
}

.time-cell small {
  color: #a2abbd;
  font-size: 9.5px;
}

.trigger-label {
  color: #7e889d;
  font-size: 10.5px;
}

.duration {
  color: #8f98aa;
  font-family: var(--font-mono);
  font-size: 10px;
}

.result-message {
  display: -webkit-box;
  overflow: hidden;
  color: #737d92;
  font-size: 10.5px;
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
  padding-top: 16px;
  font-size: 10.5px;
}

.back-btn {
  margin-top: 14px;
}

.empty-library {
  display: flex;
  justify-content: center;
  padding: 60px 20px;
  text-align: center;
}

@media (max-width: 1060px) {
  .module-hero {
    align-items: flex-start;
    flex-direction: column;
  }

  .hero-actions {
    align-self: stretch;
    justify-content: flex-end;
    padding-top: 5px;
    border-top: 1px solid #f2f4f8;
  }

  .toggle-block {
    margin-right: auto;
  }

  .config-grid {
    grid-template-columns: 1fr;
  }

  .config-side {
    display: grid;
    grid-template-columns: 1.3fr 0.7fr;
  }
}

@media (max-width: 760px) {
  .module-detail-page {
    padding-top: 16px;
  }

  .module-hero {
    padding: 20px 18px;
  }

  .hero-left {
    flex-direction: column;
    gap: 12px;
  }

  .hero-title-line h1 {
    font-size: 20px;
  }

  .hero-actions {
    flex-wrap: wrap;
  }

  .hero-meta {
    gap: 9px;
  }

  .hero-meta .meta-divider {
    display: none;
  }

  .config-side {
    display: flex;
  }

  .save-bar {
    align-items: stretch;
    flex-direction: column;
    bottom: 8px;
    padding: 12px 14px;
  }

  .push-toggle-row {
    align-items: flex-start;
    flex-direction: column;
  }

  .save-actions {
    width: 100%;
  }

  .save-actions :deep(.el-button) {
    flex: 1;
  }

  .logs-actions {
    flex-wrap: wrap;
    margin-top: 8px;
  }

  .logs-head {
    align-items: flex-start;
    flex-direction: column;
  }

  .pagination-row {
    flex-direction: column;
    align-items: flex-start;
  }
}
</style>
