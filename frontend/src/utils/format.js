import dayjs from 'dayjs'

export function formatDateTime(value) {
  if (!value) return '—'
  const parsed = dayjs(value)
  return parsed.isValid() ? parsed.format('YYYY-MM-DD HH:mm:ss') : '—'
}

export function formatShortDateTime(value) {
  if (!value) return '—'
  const parsed = dayjs(value)
  return parsed.isValid() ? parsed.format('MM-DD HH:mm') : '—'
}

export function formatClock(value) {
  if (!value) return '—'
  const parsed = dayjs(value)
  return parsed.isValid() ? parsed.format('HH:mm:ss') : '—'
}

export function timeFromNow(value) {
  if (!value) return '—'
  const parsed = dayjs(value)
  return parsed.isValid() ? parsed.fromNow() : '—'
}

export function formatDuration(ms) {
  if (ms === null || ms === undefined || Number.isNaN(Number(ms))) return '—'
  const value = Number(ms)
  if (value < 1000) return `${value} ms`
  const seconds = value / 1000
  if (seconds < 60) return `${seconds.toFixed(seconds < 10 ? 1 : 0)} s`
  const minutes = Math.floor(seconds / 60)
  const rest = Math.round(seconds % 60)
  return `${minutes} 分 ${rest} 秒`
}

export const STATUS_META = {
  running: { label: '执行中', className: 'is-running' },
  success: { label: '成功', className: 'is-success' },
  failed: { label: '失败', className: 'is-failed' },
  idle: { label: '待执行', className: 'is-idle' },
  disabled: { label: '已禁用', className: 'is-disabled' },
}

export function statusMeta(status) {
  return STATUS_META[status] || STATUS_META.idle
}

export function triggerLabel(trigger) {
  if (trigger === 'schedule') return '定时执行'
  if (trigger === 'test') return '测试执行'
  return '手动执行'
}

export function greeting(now = new Date()) {
  const hour = now.getHours()
  if (hour < 6) return '夜深了'
  if (hour < 11) return '早上好'
  if (hour < 14) return '中午好'
  if (hour < 18) return '下午好'
  return '晚上好'
}

export function todayLabel(now = new Date()) {
  return dayjs(now).format('YYYY年M月D日 dddd')
}

export function initialOf(name) {
  return (name || 'A').trim().slice(0, 1).toUpperCase()
}

export function relativeSeconds(startedAt, now = new Date()) {
  if (!startedAt) return 0
  return Math.max(0, Math.floor((now.getTime() - dayjs(startedAt).valueOf()) / 1000))
}
