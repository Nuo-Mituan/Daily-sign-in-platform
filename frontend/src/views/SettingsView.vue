<template>
  <div v-loading="loading" class="page-shell settings-page">
    <header class="page-header">
      <div>
        <span class="eyebrow">ACCOUNT & NOTIFICATIONS</span>
        <h1 class="page-title">用户设置</h1>
        <p class="page-subtitle">管理登录凭据与全局推送通道。模块通知还受各模块自己的推送开关控制。</p>
      </div>
      <div class="header-actions">
        <router-link to="/modules" class="header-link">
          <el-icon><Grid /></el-icon>
          管理模块推送开关
        </router-link>
      </div>
    </header>

    <div class="settings-grid">
      <div class="security-column">
        <section class="panel settings-card">
          <div class="panel-head">
            <div>
              <div class="panel-title">修改用户名</div>
              <div class="panel-desc">用户名用于登录，修改需要验证当前密码。</div>
            </div>
            <span class="section-icon"><el-icon><User /></el-icon></span>
          </div>
          <div class="panel-body">
            <div class="current-user-row">
              <span class="account-avatar">{{ initialOf(auth.user?.username) }}</span>
              <div>
                <span>当前用户名</span>
                <strong>{{ auth.user?.username }}</strong>
              </div>
              <span class="stable-badge">登录中</span>
            </div>
            <el-form
              ref="usernameFormRef"
              :model="usernameForm"
              :rules="usernameRules"
              label-position="top"
              class="settings-form"
              @submit.prevent="submitUsername"
            >
              <el-form-item label="新用户名" prop="new_username">
                <el-input
                  v-model="usernameForm.new_username"
                  maxlength="64"
                  placeholder="3-64 个字符，不含空格和斜杠"
                  autocomplete="off"
                  show-word-limit
                />
              </el-form-item>
              <el-form-item label="当前密码" prop="current_password">
                <el-input
                  v-model="usernameForm.current_password"
                  type="password"
                  show-password
                  autocomplete="current-password"
                  placeholder="验证身份后才能修改用户名"
                />
              </el-form-item>
              <div class="form-actions">
                <span class="form-hint">重复提交同一用户名是安全的（幂等）。</span>
                <el-button type="primary" :loading="usernameSubmitting" @click="submitUsername">
                  保存用户名
                </el-button>
              </div>
            </el-form>
          </div>
        </section>

        <section class="panel settings-card">
          <div class="panel-head">
            <div>
              <div class="panel-title">修改密码</div>
              <div class="panel-desc">修改成功后会立即退出登录，请使用新密码重新登录。</div>
            </div>
            <span class="section-icon mint"><el-icon><Lock /></el-icon></span>
          </div>
          <div class="panel-body">
            <el-form
              ref="passwordFormRef"
              :model="passwordForm"
              :rules="passwordRules"
              label-position="top"
              class="settings-form"
              @submit.prevent="submitPassword"
            >
              <el-form-item label="当前密码" prop="old_password">
                <el-input
                  v-model="passwordForm.old_password"
                  type="password"
                  show-password
                  autocomplete="current-password"
                  placeholder="请输入当前密码"
                />
              </el-form-item>
              <div class="two-column-form">
                <el-form-item label="新密码" prop="new_password">
                  <el-input
                    v-model="passwordForm.new_password"
                    type="password"
                    show-password
                    autocomplete="new-password"
                    placeholder="至少 6 位"
                  />
                </el-form-item>
                <el-form-item label="确认新密码" prop="confirm_password">
                  <el-input
                    v-model="passwordForm.confirm_password"
                    type="password"
                    show-password
                    autocomplete="new-password"
                    placeholder="再次输入新密码"
                  />
                </el-form-item>
              </div>
              <div class="form-actions">
                <span class="form-hint">连续输错 5 次将暂时限制敏感操作。</span>
                <el-button type="primary" :loading="passwordSubmitting" @click="submitPassword">
                  更新密码
                </el-button>
              </div>
            </el-form>
          </div>
        </section>
      </div>

      <aside class="security-side">
        <section class="panel session-card">
          <span class="mini-eyebrow">SESSION</span>
          <div class="session-orbit">
            <span class="orbit-ring"></span>
            <span class="session-avatar">{{ initialOf(auth.user?.username) }}</span>
          </div>
          <h3>{{ auth.user?.username }}</h3>
          <p>管理员 · 单用户实例</p>
          <div class="session-meta">
            <div><span>认证方式</span><strong>Cookie Session</strong></div>
            <div><span>数据存储</span><strong>本地 SQLite</strong></div>
            <div><span>凭据加密</span><strong>AES-256-GCM</strong></div>
          </div>
          <button type="button" class="logout-all-btn" @click="logoutAllSessions">
            <el-icon><SwitchButton /></el-icon>
            注销所有会话
          </button>
        </section>

        <section class="panel tips-card">
          <div class="tips-title"><el-icon><Warning /></el-icon>账号安全建议</div>
          <ul>
            <li>使用独立且足够长的密码，不要复用其他平台密码。</li>
            <li>修改用户名后，旧用户名立即失效，已登录会话仍然有效。</li>
            <li>连续验证失败会触发临时限流，生产环境建议同时在反向代理层限流。</li>
            <li>如需强制所有旧 Cookie 会话失效，可使用「注销所有会话」；更换 <code>SECRET_KEY</code> 会同时导致已保存参数无法解密，请务必谨慎。</li>
          </ul>
        </section>
      </aside>
    </div>

    <section class="panel push-panel">
      <div class="panel-head push-head">
        <div class="push-title-wrap">
          <span class="section-icon amber"><el-icon><Bell /></el-icon></span>
          <div>
            <div class="panel-title">全局推送通知</div>
            <div class="panel-desc">
              签到成功、失败、多账号部分失败与随机时间生成失败都会使用这里的渠道；每个模块需单独打开推送开关。
            </div>
          </div>
        </div>
        <span class="push-state" :class="{ active: pushForm.channel !== 'none' }">
          <i></i>{{ pushForm.channel === 'none' ? '未启用渠道' : '已选择渠道' }}
        </span>
      </div>

      <div class="panel-body push-body">
        <div class="push-channel-row">
          <div class="channel-control">
            <label>推送渠道</label>
            <el-select v-model="pushForm.channel" class="full-width" @change="handleChannelChange">
              <el-option
                v-for="channel in channels"
                :key="channel.channel"
                :label="channel.label"
                :value="channel.channel"
              />
            </el-select>
          </div>
          <p class="channel-note">
            凭据使用平台 <code>SECRET_KEY</code> 加密存储；除测试消息外，只有签到任务会触发推送。
          </p>
        </div>

        <div v-if="activeFields.length" class="credential-grid">
          <div v-for="field in activeFields" :key="field.key" class="credential-field">
            <label>
              {{ field.label }}
              <em v-if="field.required">*</em>
            </label>
            <el-input
              v-model="pushForm.config[field.key]"
              :type="field.secret ? 'password' : 'text'"
              :show-password="Boolean(field.secret)"
              :placeholder="field.placeholder || ''"
              autocomplete="off"
            />
            <p v-if="field.help">{{ field.help }}</p>
          </div>
        </div>
        <div v-else class="channel-empty">
          <el-icon><Bell /></el-icon>
          <div>
            <strong>当前不发送推送</strong>
            <span>选择 Bark、Server 酱、PushPlus、钉钉或飞书后填写凭据即可。</span>
          </div>
        </div>

        <div class="template-section">
          <div class="template-head">
            <div>
              <strong>消息模板</strong>
              <span>使用变量自定义通知内容，未知变量会原样保留。</span>
            </div>
            <button type="button" class="restore-template" @click="restoreTemplates">
              <el-icon><RefreshLeft /></el-icon>恢复默认
            </button>
          </div>
          <div class="template-grid">
            <div class="template-field">
              <label>标题模板</label>
              <el-input
                v-model="pushForm.title_template"
                maxlength="300"
                placeholder="{event}｜{module_name}"
              />
            </div>
            <div class="template-field">
              <label>正文模板</label>
              <el-input
                v-model="pushForm.body_template"
                type="textarea"
                :rows="7"
                maxlength="8000"
                placeholder="支持 Markdown 与变量"
              />
            </div>
            <div class="variable-box">
              <span class="variable-label">可用变量（点击插入正文）</span>
              <div class="variable-list">
                <button
                  v-for="variable in availableVariables"
                  :key="variable"
                  type="button"
                  class="variable-chip"
                  @click="insertVariable(variable)"
                >
                  {{ variable }}
                </button>
              </div>
              <p>发送测试消息时会先保存当前配置。</p>
            </div>
          </div>
        </div>

        <div class="push-actions">
          <div class="push-hint">
            <el-icon><InfoFilled /></el-icon>
            关闭模块推送开关后，该模块的签到结果和随机时间告警都不会推送。
          </div>
          <div class="push-buttons">
            <el-button
              :disabled="pushForm.channel === 'none'"
              @click="revealPushSecrets"
            >
              <el-icon><View /></el-icon>
              显示凭据
            </el-button>
            <el-button :loading="testingPush" :disabled="pushForm.channel === 'none'" @click="testPush">
              <el-icon><Promotion /></el-icon>
              发送测试
            </el-button>
            <el-button type="primary" :loading="savingPush" @click="savePush">
              <el-icon v-if="!savingPush"><Select /></el-icon>
              保存推送配置
            </el-button>
          </div>
        </div>
      </div>
    </section>

    <section class="panel log-settings-panel">
      <div class="panel-head">
        <div class="push-title-wrap">
          <span class="section-icon"><el-icon><DataLine /></el-icon></span>
          <div>
            <div class="panel-title">日志设置</div>
            <div class="panel-desc">
              系统日志、模块执行日志和推送审计统一进入环形存储；天数或容量任一超限即按时间顺序淘汰最旧记录。
            </div>
          </div>
        </div>
        <span class="log-stats-chip">
          {{ logSettings.total_rows.toLocaleString() }} 条 ·
          {{ formatBytes(logSettings.total_bytes) }}
        </span>
      </div>
      <div class="panel-body log-settings-body">
        <div class="log-retention-control">
          <label for="log-retention-days">保留天数</label>
          <el-input-number
            id="log-retention-days"
            v-model="logSettings.retention_days"
            :min="1"
            :max="365"
            :step="1"
            controls-position="right"
          />
          <span>天（范围 1-365，默认 31）</span>
          <el-button
            type="primary"
            :loading="savingLogSettings"
            @click="saveLogSettings"
          >
            保存并立即裁剪
          </el-button>
        </div>
        <ul class="log-policy-list">
          <li><strong>双约束：</strong>保留天数与每个日志域的最大条数/字节数同时生效，任一触发即 FIFO 淘汰。</li>
          <li><strong>独立配额：</strong>每个模块单独计量；系统日志与推送审计日志分别计量，互不挤占。</li>
          <li><strong>即时清理：</strong>保存后立即执行一次裁剪；此外启动时与每日 03:10 自动执行。</li>
          <li><strong>可追溯：</strong>读取始终按单调 <code>seq</code> 排序，服务重启后序号与内容保持不变。</li>
        </ul>
      </div>
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Bell,
  DataLine,
  Grid,
  InfoFilled,
  Lock,
  Promotion,
  RefreshLeft,
  Select,
  SwitchButton,
  User,
  View,
  Warning,
} from '@element-plus/icons-vue'
import { pushApi, systemApi } from '@/api'
import { useAuthStore } from '@/stores/auth'
import { initialOf } from '@/utils/format'

const router = useRouter()
const auth = useAuthStore()

const loading = ref(false)
const usernameFormRef = ref(null)
const passwordFormRef = ref(null)
const usernameSubmitting = ref(false)
const passwordSubmitting = ref(false)
const savingPush = ref(false)
const testingPush = ref(false)
const savingLogSettings = ref(false)

const logSettings = reactive({
  retention_days: 31,
  total_rows: 0,
  total_bytes: 0,
})

const usernameForm = reactive({
  new_username: '',
  current_password: '',
})

const passwordForm = reactive({
  old_password: '',
  new_password: '',
  confirm_password: '',
})

const pushForm = reactive({
  channel: 'none',
  config: {},
  title_template: '',
  body_template: '',
})

const channels = ref([])
const availableVariables = ref([])
const defaultTitleTemplate = ref('')
const defaultBodyTemplate = ref('')

const usernameRules = {
  new_username: [
    { required: true, message: '请输入新用户名', trigger: 'blur' },
    { min: 3, max: 64, message: '用户名长度需为 3-64 位', trigger: 'blur' },
    {
      validator: (_rule, value, callback) => {
        if (/\s/.test(value) || /[\\/]/.test(value)) {
          callback(new Error('用户名不能包含空格或斜杠'))
        } else {
          callback()
        }
      },
      trigger: 'blur',
    },
  ],
  current_password: [{ required: true, message: '请输入当前密码', trigger: 'blur' }],
}

const passwordRules = {
  old_password: [{ required: true, message: '请输入当前密码', trigger: 'blur' }],
  new_password: [
    { required: true, message: '请输入新密码', trigger: 'blur' },
    { min: 6, max: 128, message: '新密码长度需为 6-128 位', trigger: 'blur' },
  ],
  confirm_password: [
    { required: true, message: '请再次输入新密码', trigger: 'blur' },
    {
      validator: (_rule, value, callback) => {
        if (value !== passwordForm.new_password) {
          callback(new Error('两次输入的新密码不一致'))
        } else {
          callback()
        }
      },
      trigger: 'blur',
    },
  ],
}

const selectedChannel = computed(() =>
  channels.value.find((item) => item.channel === pushForm.channel),
)
const activeFields = computed(() => selectedChannel.value?.fields || [])

async function loadLogSettings() {
  try {
    const data = await systemApi.getLogSettings()
    logSettings.retention_days = Number(data.retention_days) || 31
    logSettings.total_rows = Number(data.total_rows) || 0
    logSettings.total_bytes = Number(data.total_bytes) || 0
  } catch {
    // HTTP layer shows the error.
  }
}

function formatBytes(value) {
  const size = Number(value) || 0
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  if (size < 1024 * 1024 * 1024) return `${(size / (1024 * 1024)).toFixed(1)} MB`
  return `${(size / (1024 * 1024 * 1024)).toFixed(2)} GB`
}

async function saveLogSettings() {
  const days = Number(logSettings.retention_days)
  if (!Number.isInteger(days) || days < 1 || days > 365) {
    ElMessage.warning('保留天数必须是 1-365 的整数')
    return
  }
  savingLogSettings.value = true
  try {
    const data = await systemApi.updateLogSettings({ retention_days: days })
    logSettings.retention_days = data.retention_days
    logSettings.total_rows = data.total_rows
    logSettings.total_bytes = data.total_bytes
    ElMessage.success(data.message || '日志保留策略已保存并完成裁剪')
  } catch {
    // HTTP layer shows validation / server errors.
  } finally {
    savingLogSettings.value = false
  }
}

async function loadPushConfig() {
  try {
    const data = await pushApi.getConfig()
    channels.value = data.channels || []
    availableVariables.value = data.available_variables || []
    defaultTitleTemplate.value = data.default_title_template || ''
    defaultBodyTemplate.value = data.default_body_template || ''
    pushForm.channel = data.channel || 'none'
    pushForm.title_template = data.title_template || defaultTitleTemplate.value
    pushForm.body_template = data.body_template || defaultBodyTemplate.value
    pushForm.config = { ...(data.config || {}) }
  } catch {
    // HTTP layer shows the error.
  }
}

function handleChannelChange() {
  for (const field of activeFields.value) {
    if (pushForm.config[field.key] === undefined) {
      pushForm.config[field.key] = ''
    }
  }
}

function restoreTemplates() {
  pushForm.title_template = defaultTitleTemplate.value
  pushForm.body_template = defaultBodyTemplate.value
}

function insertVariable(variable) {
  const current = pushForm.body_template || ''
  pushForm.body_template = `${current}${current && !current.endsWith('\n') ? ' ' : ''}${variable}`
}

async function submitUsername() {
  if (!usernameFormRef.value) return
  try {
    await usernameFormRef.value.validate()
  } catch {
    return
  }
  usernameSubmitting.value = true
  try {
    await auth.updateUsername({
      new_username: usernameForm.new_username.trim(),
      current_password: usernameForm.current_password,
    })
    usernameForm.new_username = ''
    usernameForm.current_password = ''
    usernameFormRef.value?.clearValidate()
    ElMessage.success('用户名已更新，下次登录请使用新用户名')
  } catch {
    // HTTP layer reports validation / rate-limit errors.
  } finally {
    usernameSubmitting.value = false
  }
}

async function submitPassword() {
  if (!passwordFormRef.value) return
  try {
    await passwordFormRef.value.validate()
  } catch {
    return
  }
  passwordSubmitting.value = true
  try {
    await auth.changePassword({
      old_password: passwordForm.old_password,
      new_password: passwordForm.new_password,
    })
    auth.clearSession()
    ElMessage.success('密码修改成功，请重新登录')
    router.replace({ name: 'login' })
  } catch {
    // HTTP layer reports errors.
  } finally {
    passwordSubmitting.value = false
  }
}

function validatePush() {
  for (const field of activeFields.value) {
    if (!field.required) continue
    const value = String(pushForm.config[field.key] || '').trim()
    if (!value) {
      ElMessage.warning(`请填写「${field.label}」`)
      return false
    }
  }
  if (!(pushForm.title_template || '').trim()) {
    ElMessage.warning('标题模板不能为空')
    return false
  }
  if (!(pushForm.body_template || '').trim()) {
    ElMessage.warning('正文模板不能为空')
    return false
  }
  return true
}

async function savePush(showSuccess = true) {
  if (!validatePush()) return false
  savingPush.value = true
  try {
    const config = {}
    for (const field of activeFields.value) {
      config[field.key] = pushForm.config[field.key] || ''
    }
    const saved = await pushApi.saveConfig({
      channel: pushForm.channel,
      config,
      title_template: pushForm.title_template,
      body_template: pushForm.body_template,
    })
    pushForm.channel = saved.channel
    pushForm.config = { ...(saved.config || {}) }
    pushForm.title_template = saved.title_template
    pushForm.body_template = saved.body_template
    if (showSuccess) ElMessage.success('推送配置已保存')
    return true
  } catch {
    return false
  } finally {
    savingPush.value = false
  }
}

async function logoutAllSessions() {
  try {
    await ElMessageBox.confirm(
      '这会注销包括当前设备在内的全部登录会话，是否继续？',
      '注销所有会话',
      {
        confirmButtonText: '全部注销',
        cancelButtonText: '取消',
        type: 'warning',
      },
    )
  } catch {
    return
  }
  try {
    await auth.logoutAll()
    ElMessage.success('全部登录会话已注销，请重新登录')
    router.replace({ name: 'login' })
  } catch {
    // HTTP layer reports the error.
  }
}

async function revealPushSecrets() {
  if (pushForm.channel === 'none') {
    ElMessage.warning('请先选择推送渠道')
    return
  }
  let password = ''
  try {
    const result = await ElMessageBox.prompt(
      '凭据仅在本页面内存中临时显示。请输入当前密码验证。',
      '显示推送凭据',
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
    const data = await pushApi.reveal({ current_password: password })
    pushForm.config = { ...(data.config || {}) }
    ElMessage.success('推送凭据已临时显示')
  } catch {
    // HTTP layer displays validation / password errors.
  }
}

async function testPush() {
  if (!(await savePush(false))) return
  testingPush.value = true
  try {
    const result = await pushApi.test()
    if (result.sent) {
      ElMessage.success(result.message || '测试消息已发送')
    } else {
      ElMessage.error(result.message || '测试消息发送失败')
    }
  } catch {
    // HTTP layer reports errors.
  } finally {
    testingPush.value = false
  }
}

onMounted(async () => {
  loading.value = true
  await Promise.all([loadPushConfig(), loadLogSettings()])
  loading.value = false
})
</script>

<style scoped>
.settings-page {
  padding-top: 30px;
}

.header-link {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  height: 34px;
  padding: 0 12px;
  color: #6f7990;
  background: #fff;
  border: 1px solid var(--line);
  border-radius: 9px;
  font-size: 11px;
  font-weight: 600;
  box-shadow: var(--shadow-sm);
}

.header-link:hover {
  color: var(--brand);
  border-color: #d9dbf6;
}

.settings-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.45fr) minmax(270px, 0.55fr);
  gap: 18px;
  align-items: start;
}

.security-column {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 18px;
}

.settings-card .panel-body {
  padding-top: 17px;
}

.section-icon {
  display: grid;
  width: 32px;
  height: 32px;
  flex: none;
  place-items: center;
  color: #625fd5;
  background: #f0f1fe;
  border-radius: 9px;
  font-size: 15px;
}

.section-icon.mint {
  color: #0b8e68;
  background: #eaf9f3;
}

.section-icon.amber {
  color: #b47b13;
  background: #fdf5e6;
}

.current-user-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 18px;
  padding: 11px 13px;
  background: #fafbfe;
  border: 1px solid #eef1f7;
  border-radius: 11px;
}

.account-avatar {
  display: grid;
  width: 34px;
  height: 34px;
  flex: none;
  place-items: center;
  color: #fff;
  background: linear-gradient(140deg, #6366f1, #8b5cf6);
  border-radius: 50%;
  font-size: 12px;
  font-weight: 700;
}

.current-user-row > div {
  display: flex;
  flex-direction: column;
  gap: 1px;
}

.current-user-row > div span {
  color: #9ba4b6;
  font-size: 9px;
}

.current-user-row > div strong {
  color: #404b63;
  font-size: 12.5px;
  font-weight: 650;
}

.stable-badge {
  margin-left: auto;
  padding: 3px 8px;
  color: #0b8765;
  background: var(--mint-soft);
  border-radius: 999px;
  font-size: 8.5px;
  font-weight: 600;
}

.settings-form :deep(.el-form-item) {
  margin-bottom: 16px;
}

.two-column-form {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}

.form-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding-top: 2px;
}

.form-hint {
  color: #a2aabc;
  font-size: 9.5px;
}

.security-side {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.session-card {
  padding: 20px;
  text-align: center;
  background:
    radial-gradient(circle at 50% 0%, rgba(99, 102, 241, 0.08), transparent 50%),
    #fff;
}

.mini-eyebrow {
  color: #a6adbe;
  font-family: var(--font-mono);
  font-size: 8px;
  font-weight: 700;
  letter-spacing: 0.14em;
}

.session-orbit {
  position: relative;
  display: grid;
  width: 76px;
  height: 76px;
  place-items: center;
  margin: 16px auto 11px;
}

.orbit-ring {
  position: absolute;
  inset: 0;
  border: 1px dashed #dfe2f2;
  border-radius: 50%;
  animation: orbit-spin 30s linear infinite;
}

.session-avatar {
  display: grid;
  width: 50px;
  height: 50px;
  place-items: center;
  color: #fff;
  background: linear-gradient(140deg, #6366f1, #8b5cf6);
  border-radius: 50%;
  box-shadow: 0 8px 20px rgba(99, 102, 241, 0.25);
  font-size: 19px;
  font-weight: 700;
}

.session-card h3 {
  color: #303b54;
  font-size: 15px;
  font-weight: 680;
}

.session-card > p {
  margin-top: 2px;
  color: #9ba4b6;
  font-size: 10px;
}

.session-meta {
  display: flex;
  flex-direction: column;
  gap: 7px;
  margin-top: 16px;
  padding-top: 13px;
  border-top: 1px dashed #eef1f6;
}

.session-meta div {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  color: #9da5b6;
  font-size: 9.5px;
}

.session-meta strong {
  color: #68738a;
  font-family: var(--font-mono);
  font-size: 8.5px;
  font-weight: 500;
}

.logout-all-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  width: 100%;
  margin-top: 12px;
  padding: 7px 10px;
  color: #b44747;
  background: #fdf5f5;
  border: 1px solid #f4dede;
  border-radius: 8px;
  font-size: 9.5px;
  font-weight: 600;
  cursor: pointer;
}

.logout-all-btn:hover {
  background: #fcecec;
}

.tips-card {
  padding: 17px 18px;
}

.tips-title {
  display: flex;
  align-items: center;
  gap: 6px;
  color: #707a90;
  font-size: 11px;
  font-weight: 650;
}

.tips-title > .el-icon {
  color: #b88b2d;
}

.tips-card ul {
  display: flex;
  flex-direction: column;
  gap: 7px;
  margin: 10px 0 0;
  padding: 0;
  list-style: none;
}

.tips-card li {
  position: relative;
  padding-left: 10px;
  color: #98a1b3;
  font-size: 9.5px;
  line-height: 1.65;
}

.tips-card li::before {
  position: absolute;
  top: 7px;
  left: 0;
  width: 3px;
  height: 3px;
  background: #c6ccda;
  border-radius: 50%;
  content: "";
}

.tips-card code {
  padding: 1px 4px;
  color: #5a58c7;
  background: #f2f2fd;
  border-radius: 3px;
  font-family: var(--font-mono);
  font-size: 8.5px;
}

/* ------------------------------------------------------------------ push */
.push-panel {
  margin-top: 18px;
}

.push-head {
  align-items: center;
}

.push-title-wrap {
  display: flex;
  align-items: flex-start;
  gap: 11px;
}

.push-state {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 4px 8px;
  color: #939caf;
  background: #f4f6fa;
  border-radius: 999px;
  font-size: 9px;
  font-weight: 600;
  white-space: nowrap;
}

.push-state i {
  width: 5px;
  height: 5px;
  background: #b3bac8;
  border-radius: 50%;
}

.push-state.active {
  color: #0b8765;
  background: var(--mint-soft);
}

.push-state.active i {
  background: #10b981;
}

.push-body {
  padding-top: 18px;
}

.push-channel-row {
  display: flex;
  align-items: flex-end;
  gap: 24px;
}

.channel-control {
  width: 250px;
  flex: none;
}

.channel-control label,
.credential-field label,
.template-field label {
  display: block;
  margin-bottom: 5px;
  color: #59647c;
  font-size: 10.5px;
  font-weight: 600;
}

.channel-note {
  max-width: 530px;
  padding-bottom: 7px;
  color: #9ba4b6;
  font-size: 9.5px;
  line-height: 1.65;
}

.channel-note code {
  color: #5d5ac8;
  font-family: var(--font-mono);
  font-size: 9px;
}

.full-width {
  width: 100%;
}

.credential-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 14px;
  margin-top: 18px;
  padding: 16px;
  background: #fafbfe;
  border: 1px solid #eef1f7;
  border-radius: 12px;
}

.credential-field label em {
  color: #e05555;
  font-style: normal;
}

.credential-field label em {
  margin-left: 2px;
}

.credential-field p {
  margin-top: 4px;
  color: #a3abbc;
  font-size: 8.5px;
  line-height: 1.6;
}

.channel-empty {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 18px;
  padding: 16px;
  color: #727fad;
  background: #f8f9fe;
  border: 1px dashed #e0e3f4;
  border-radius: 12px;
}

.channel-empty > .el-icon {
  font-size: 22px;
}

.channel-empty strong {
  display: block;
  color: #5c6680;
  font-size: 11px;
  font-weight: 650;
}

.channel-empty span {
  color: #9ba4b6;
  font-size: 9.5px;
}

.template-section {
  margin-top: 22px;
  padding-top: 18px;
  border-top: 1px dashed #edf0f6;
}

.template-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.template-head strong {
  display: block;
  color: #4b566d;
  font-size: 11.5px;
  font-weight: 650;
}

.template-head span {
  display: block;
  margin-top: 2px;
  color: #a0a8b9;
  font-size: 9.5px;
}

.restore-template {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  padding: 0;
  color: #8a93a6;
  background: transparent;
  border: 0;
  font-size: 9.5px;
  cursor: pointer;
}

.restore-template:hover {
  color: var(--brand);
}

.template-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.5fr) minmax(230px, 0.7fr);
  gap: 15px;
}

.template-field:first-child {
  grid-column: 1 / -1;
}

.variable-box {
  padding: 13px;
  background: #fafbfe;
  border: 1px solid #eef1f7;
  border-radius: 10px;
}

.variable-label {
  display: block;
  margin-bottom: 8px;
  color: #8e98ac;
  font-size: 9px;
  font-weight: 600;
}

.variable-list {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
}

.variable-chip {
  padding: 3px 6px;
  color: #625fc8;
  background: #f2f2fd;
  border: 1px solid #e8e8fa;
  border-radius: 5px;
  font-family: var(--font-mono);
  font-size: 8.5px;
  cursor: pointer;
}

.variable-chip:hover {
  background: #eaeafd;
}

.variable-box p {
  margin-top: 9px;
  color: #aab1c1;
  font-size: 8.5px;
  line-height: 1.5;
}

.push-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  margin-top: 19px;
  padding-top: 16px;
  border-top: 1px solid #f2f4f8;
}

.push-hint {
  display: flex;
  align-items: flex-start;
  gap: 5px;
  color: #a0a8b9;
  font-size: 9.5px;
  line-height: 1.6;
}

.push-hint > .el-icon {
  flex: none;
  margin-top: 2px;
}

.push-buttons {
  display: flex;
  flex: none;
  gap: 8px;
}

.log-settings-panel {
  margin-top: 18px;
}

.log-stats-chip {
  flex: none;
  padding: 4px 9px;
  color: #7d8497;
  background: #f7f8fb;
  border: 1px solid #eef0f6;
  border-radius: 999px;
  font-family: var(--font-mono);
  font-size: 9px;
}

.log-settings-body {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.log-retention-control {
  display: flex;
  align-items: center;
  gap: 9px;
  flex-wrap: wrap;
  color: #7d8497;
  font-size: 10px;
}

.log-retention-control > label {
  color: #4d566a;
  font-weight: 600;
}

.log-retention-control :deep(.el-input-number) {
  width: 105px;
}

.log-retention-control :deep(.el-button) {
  margin-left: auto;
}

.log-policy-list {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 7px 22px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.log-policy-list li {
  color: #8c94a5;
  font-size: 9.5px;
  line-height: 1.7;
}

.log-policy-list strong {
  color: #66708a;
}

@keyframes orbit-spin {
  to {
    transform: rotate(360deg);
  }
}

@media (max-width: 1050px) {
  .settings-grid {
    grid-template-columns: 1fr;
  }

  .security-side {
    display: grid;
    grid-template-columns: 1fr 1fr;
  }

  .template-grid {
    grid-template-columns: 1fr;
  }

  .template-field:first-child {
    grid-column: auto;
  }
}

@media (max-width: 720px) {
  .settings-page {
    padding-top: 20px;
  }

  .security-side {
    display: flex;
  }

  .two-column-form {
    grid-template-columns: 1fr;
  }

  .log-policy-list {
    grid-template-columns: 1fr;
  }

  .log-retention-control :deep(.el-button) {
    width: 100%;
    margin-left: 0;
  }

  .push-channel-row {
    align-items: flex-start;
    flex-direction: column;
    gap: 8px;
  }

  .channel-control {
    width: 100%;
  }

  .push-head {
    align-items: flex-start;
    flex-direction: column;
  }

  .push-state {
    margin-left: 43px;
  }

  .form-actions,
  .push-actions {
    align-items: stretch;
    flex-direction: column;
  }

  .push-buttons {
    width: 100%;
  }

  .push-buttons :deep(.el-button) {
    flex: 1;
  }

  .header-actions {
    width: 100%;
  }

  .header-link {
    justify-content: center;
  }
}
</style>

<style scoped>





</style>
