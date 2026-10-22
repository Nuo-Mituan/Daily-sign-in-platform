<template>
  <el-drawer
    :model-value="modelValue"
    :size="drawerSize"
    :show-close="false"
    direction="rtl"
    class="run-log-drawer"
    @update:model-value="(value) => emit('update:modelValue', value)"
  >
    <template #header>
      <div class="drawer-header">
        <div class="drawer-heading">
          <span class="eyebrow">EXECUTION LOG</span>
          <div class="drawer-title-row">
            <h3 class="drawer-title">{{ displayTitle }}</h3>
            <StatusTag
              v-if="log"
              :status="log.status"
              :label="streaming ? '实时输出中' : undefined"
            />
          </div>
        </div>
        <button type="button" class="close-btn" aria-label="关闭" @click="closeDrawer">
          <el-icon><Close /></el-icon>
        </button>
      </div>
    </template>

    <div v-loading="loading" class="drawer-body">
      <template v-if="log">
        <div class="log-meta-grid">
          <div class="meta-cell">
            <span class="meta-label">模块</span>
            <span class="meta-value">{{ log.module_name }}</span>
          </div>
          <div class="meta-cell">
            <span class="meta-label">触发方式</span>
            <span class="meta-value">{{ triggerLabel(log.trigger) }}</span>
          </div>
          <div class="meta-cell">
            <span class="meta-label">开始时间</span>
            <span class="meta-value">{{ formatDateTime(log.started_at) }}</span>
          </div>
          <div class="meta-cell">
            <span class="meta-label">{{ streaming ? '已运行' : '耗时' }}</span>
            <span class="meta-value mono-value">{{ elapsedLabel }}</span>
          </div>
        </div>

        <el-alert
          v-if="log.message"
          :type="log.status === 'success' ? 'success' : log.status === 'failed' ? 'error' : 'info'"
          :closable="false"
          show-icon
          class="log-message"
          :title="log.message"
        />
        <el-alert
          v-if="streamError"
          type="warning"
          :closable="false"
          show-icon
          class="log-message"
          :title="streamError"
        />

        <div class="terminal-shell">
          <div class="terminal-bar">
            <div class="terminal-dots" aria-hidden="true">
              <i></i><i></i><i></i>
            </div>
            <span class="terminal-title">stdout / stderr</span>
            <span class="terminal-state" :class="{ live: streaming }">
              <i></i>{{ streaming ? 'LIVE' : 'FINISHED' }}
            </span>
            <div class="terminal-actions">
              <button type="button" class="term-btn" title="复制日志" @click="copyOutput">
                <el-icon><CopyDocument /></el-icon>
              </button>
              <button type="button" class="term-btn" title="下载日志" @click="downloadOutput">
                <el-icon><Download /></el-icon>
              </button>
            </div>
          </div>
          <div ref="terminal" class="terminal">
            <pre v-if="output">{{ output }}</pre>
            <div v-else class="terminal-placeholder">
              <el-icon v-if="streaming" class="is-loading"><Loading /></el-icon>
              <span>{{ streaming ? '等待模块输出…' : '本次执行没有输出内容' }}</span>
            </div>
          </div>
        </div>

        <div class="drawer-footer">
          <button
            v-if="streamError && log.status === 'running'"
            type="button"
            class="ghost-btn"
            @click="reconnect"
          >
            <el-icon><RefreshRight /></el-icon>
            从断点重新连接
          </button>
          <button type="button" class="close-btn-text" @click="closeDrawer">关闭</button>
        </div>
      </template>

      <div v-else-if="!loading" class="empty-state">
        <div class="empty-state__icon">
          <el-icon><Document /></el-icon>
        </div>
        <div class="empty-state__title">无法加载执行记录</div>
        <div class="empty-state__desc">{{ streamError || '执行记录可能已被清理' }}</div>
      </div>
    </div>
  </el-drawer>
</template>

<script setup>
import {
  computed,
  nextTick,
  onBeforeUnmount,
  onMounted,
  ref,
  watch,
} from 'vue'
import { ElMessage } from 'element-plus'
import StatusTag from '@/components/StatusTag.vue'
import { logsApi, streamExecutionLog } from '@/api'
import {
  formatDateTime,
  formatDuration,
  triggerLabel,
} from '@/utils/format'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  logId: { type: [Number, String], default: null },
  title: { type: String, default: '执行日志' },
})

const emit = defineEmits(['update:modelValue', 'finished'])

const log = ref(null)
const output = ref('')
const loading = ref(false)
const streaming = ref(false)
const streamError = ref('')
const terminal = ref(null)
const elapsedSeconds = ref(0)
const viewportWidth = ref(typeof window === 'undefined' ? 1200 : window.innerWidth)

let aborter = null
let tickTimer = null
let reconnectTimer = null
let reconnectAttempts = 0
let ignoreScroll = false
const lastSeq = ref(0)

const drawerSize = computed(() => (viewportWidth.value < 760 ? '100%' : '700px'))

const displayTitle = computed(() => props.title || log.value?.module_name || '执行日志')

const elapsedLabel = computed(() => {
  if (log.value?.duration_ms !== null && log.value?.duration_ms !== undefined) {
    return formatDuration(log.value.duration_ms)
  }
  if (streaming.value) {
    return elapsedSeconds.value < 60
      ? `${elapsedSeconds.value} 秒`
      : `${Math.floor(elapsedSeconds.value / 60)} 分 ${elapsedSeconds.value % 60} 秒`
  }
  return '—'
})

watch(
  () => props.modelValue,
  (open) => {
    if (open) {
      load()
    } else {
      cleanupStream()
    }
  },
)

watch(
  () => props.logId,
  () => {
    if (props.modelValue) load()
  },
)

function onResize() {
  viewportWidth.value = window.innerWidth
}

async function load() {
  cleanupStream()
  log.value = null
  output.value = ''
  streamError.value = ''
  lastSeq.value = 0
  loading.value = true
  ignoreScroll = false
  if (!props.logId && props.logId !== 0) {
    loading.value = false
    streamError.value = '缺少执行记录 ID'
    return
  }
  try {
    const data = await logsApi.get(props.logId)
    log.value = data
    output.value = data.output || ''
    lastSeq.value = Number(data.last_seq) || 0
    if (data.status === 'running') {
      startStream()
    } else {
      await nextTick()
      scrollToBottom(true)
    }
  } catch (error) {
    streamError.value = error.message || '加载执行记录失败'
  } finally {
    loading.value = false
  }
}

function startStream() {
  if (!props.modelValue) return
  stopStream()
  if (reconnectTimer) {
    window.clearTimeout(reconnectTimer)
    reconnectTimer = null
  }
  streaming.value = true
  streamError.value = ''
  aborter = new AbortController()
  startTick()

  streamExecutionLog(props.logId, {
    signal: aborter.signal,
    lastSeq: lastSeq.value,
    onSeq(seq) {
      if (seq > lastSeq.value) lastSeq.value = seq
    },
    onChunk(text, seq) {
      if (!props.modelValue) return
      if (seq && seq <= lastSeq.value) return
      output.value += text
      scrollToBottom()
    },
    onDone(payload) {
      if (!props.modelValue) return
      streaming.value = false
      aborter = null
      reconnectAttempts = 0
      stopTick()
      if (Number(payload.last_seq)) lastSeq.value = Number(payload.last_seq)
      const status = ['success', 'failed', 'running'].includes(payload.status)
        ? payload.status
        : 'failed'
      log.value = {
        ...log.value,
        status,
        message: payload.message ?? log.value?.message,
        duration_ms: payload.duration_ms ?? log.value?.duration_ms,
        finished_at: new Date().toISOString(),
      }
      emit('finished', log.value)
      nextTick(() => scrollToBottom(true))
    },
    onError(error) {
      if (!props.modelValue) return
      streaming.value = false
      aborter = null
      stopTick()
      if (reconnectAttempts < 3 && log.value?.status === 'running') {
        reconnectAttempts += 1
        streamError.value = `连接中断，正在从日志序号 ${lastSeq.value} 补读…`
        reconnectTimer = window.setTimeout(() => {
          reconnectTimer = null
          startStream()
        }, 1000 * reconnectAttempts)
      } else {
        streamError.value = error.message || '实时日志连接中断'
      }
    },
  })
}

function stopStream() {
  if (aborter) {
    aborter.abort()
    aborter = null
  }
  streaming.value = false
  stopTick()
}

function cleanupStream() {
  stopStream()
  if (reconnectTimer) {
    window.clearTimeout(reconnectTimer)
    reconnectTimer = null
  }
  reconnectAttempts = 0
}

function reconnect() {
  if (!props.modelValue || !props.logId) return
  startStream()
}

function startTick() {
  stopTick()
  const update = () => {
    if (!log.value?.started_at) {
      elapsedSeconds.value = 0
      return
    }
    const started = new Date(log.value.started_at).getTime()
    elapsedSeconds.value = Number.isFinite(started)
      ? Math.max(0, Math.floor((Date.now() - started) / 1000))
      : 0
  }
  update()
  tickTimer = window.setInterval(update, 1000)
}

function stopTick() {
  if (tickTimer) {
    window.clearInterval(tickTimer)
    tickTimer = null
  }
}

function scrollToBottom(force = false) {
  nextTick(() => {
    const element = terminal.value
    if (!element) return
    const distance = element.scrollHeight - element.scrollTop - element.clientHeight
    if (force || distance < 90) {
      ignoreScroll = true
      element.scrollTop = element.scrollHeight
      window.requestAnimationFrame(() => {
        ignoreScroll = false
      })
    }
  })
}

async function copyOutput() {
  const text = output.value || ''
  if (!text) {
    ElMessage.info('当前没有可复制的日志')
    return
  }
  try {
    await navigator.clipboard.writeText(text)
    ElMessage.success('日志已复制到剪贴板')
  } catch {
    const textarea = document.createElement('textarea')
    textarea.value = text
    textarea.style.position = 'fixed'
    textarea.style.opacity = '0'
    document.body.appendChild(textarea)
    textarea.select()
    try {
      document.execCommand('copy')
      ElMessage.success('日志已复制到剪贴板')
    } catch {
      ElMessage.error('浏览器不允许访问剪贴板')
    } finally {
      document.body.removeChild(textarea)
    }
  }
}

function downloadOutput() {
  const text = output.value || ''
  if (!text) {
    ElMessage.info('当前没有可下载的日志')
    return
  }
  const blob = new Blob([text], { type: 'text/plain;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `checkin-log-${props.logId || 'unknown'}.txt`
  document.body.appendChild(anchor)
  anchor.click()
  document.body.removeChild(anchor)
  URL.revokeObjectURL(url)
}

function closeDrawer() {
  emit('update:modelValue', false)
}

onMounted(() => {
  window.addEventListener('resize', onResize)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', onResize)
  cleanupStream()
  stopTick()
})
</script>

<style scoped>
.drawer-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  width: 100%;
  padding: 2px 0;
}

.drawer-heading {
  min-width: 0;
}

.drawer-title-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 3px;
}

.drawer-title {
  overflow: hidden;
  font-size: 19px;
  font-weight: 740;
  letter-spacing: -0.02em;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.close-btn {
  display: grid;
  width: 34px;
  height: 34px;
  flex: none;
  place-items: center;
  color: #7f899e;
  background: #f5f7fb;
  border: 1px solid var(--line);
  border-radius: 10px;
  font-size: 16px;
  cursor: pointer;
  transition: all 0.16s ease;
}

.close-btn:hover {
  color: var(--ink);
  background: #eef1f7;
}

.drawer-body {
  display: flex;
  flex-direction: column;
  min-height: calc(100vh - 92px);
  padding: 20px 24px;
  background: #f7f9fd;
}

.log-meta-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 1px;
  overflow: hidden;
  background: var(--line);
  border: 1px solid var(--line);
  border-radius: 13px;
}

.meta-cell {
  display: flex;
  flex-direction: column;
  gap: 3px;
  padding: 11px 14px;
  background: #fff;
}

.meta-label {
  color: #98a1b4;
  font-size: 10.5px;
  font-weight: 650;
  letter-spacing: 0.04em;
}

.meta-value {
  overflow: hidden;
  color: var(--ink-soft);
  font-size: 12px;
  font-weight: 600;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.mono-value {
  font-family: var(--font-mono);
}

.log-message {
  margin-top: 14px;
}

.terminal-shell {
  display: flex;
  flex: 1;
  flex-direction: column;
  min-height: 280px;
  margin-top: 16px;
  overflow: hidden;
  background: #0b1220;
  border: 1px solid #1b2740;
  border-radius: 15px;
  box-shadow: 0 16px 40px rgba(7, 13, 28, 0.18);
}

.terminal-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  background: #0f182b;
  border-bottom: 1px solid #19243a;
}

.terminal-dots {
  display: flex;
  gap: 5px;
}

.terminal-dots i {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #374561;
}

.terminal-dots i:first-child {
  background: #f87171;
}

.terminal-dots i:nth-child(2) {
  background: #fbbf24;
}

.terminal-dots i:last-child {
  background: #34d399;
}

.terminal-title {
  color: #697896;
  font-family: var(--font-mono);
  font-size: 10.5px;
  letter-spacing: 0.06em;
}

.terminal-state {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  margin-left: auto;
  color: #64748b;
  font-family: var(--font-mono);
  font-size: 9.5px;
  font-weight: 700;
  letter-spacing: 0.1em;
}

.terminal-state i {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #64748b;
}

.terminal-state.live {
  color: #5eead4;
}

.terminal-state.live i {
  background: #2dd4bf;
  box-shadow: 0 0 8px rgba(45, 212, 191, 0.8);
  animation: pulse-dot 1.2s infinite;
}

.terminal-actions {
  display: flex;
  gap: 3px;
  margin-left: 8px;
}

.term-btn {
  display: grid;
  width: 27px;
  height: 27px;
  place-items: center;
  color: #8ea0be;
  background: transparent;
  border: 0;
  border-radius: 6px;
  font-size: 13px;
  cursor: pointer;
}

.term-btn:hover {
  color: #dbe7ff;
  background: #1b2740;
}

.terminal {
  flex: 1;
  max-height: calc(100vh - 430px);
  min-height: 260px;
  padding: 16px 18px 22px;
  overflow: auto;
  color: #c8d5ea;
  font-family: var(--font-mono);
  font-size: 12px;
  line-height: 1.75;
  scrollbar-color: #2b3a55 transparent;
}

.terminal pre {
  margin: 0;
  color: inherit;
  font-family: inherit;
  font-size: inherit;
  line-height: inherit;
  white-space: pre-wrap;
  word-break: break-word;
}

.terminal-placeholder {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  height: 220px;
  color: #52627f;
  font-family: var(--font-ui);
  font-size: 12.5px;
}

.drawer-footer {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
  padding-top: 18px;
}

.ghost-btn,
.close-btn-text {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  height: 36px;
  padding: 0 15px;
  border-radius: 9px;
  font-size: 12.5px;
  font-weight: 600;
  cursor: pointer;
}

.ghost-btn {
  color: var(--brand-strong);
  background: #fff;
  border: 1px solid #dedffb;
}

.ghost-btn:hover {
  background: var(--brand-soft);
}

.close-btn-text {
  color: #fff;
  background: #17203a;
  border: 1px solid #17203a;
}

.close-btn-text:hover {
  background: #263149;
}

@media (max-width: 760px) {
  .drawer-body {
    padding: 16px;
  }

  .log-meta-grid {
    grid-template-columns: repeat(2, 1fr);
  }

  .terminal {
    max-height: calc(100vh - 470px);
  }

}
</style>


<style>
.run-log-drawer .el-drawer__header {
  padding: 22px 24px 18px !important;
  margin: 0 !important;
  border-bottom: 1px solid var(--line);
}

.run-log-drawer .el-drawer__body {
  padding: 0 !important;
  overflow: hidden;
}
</style>
