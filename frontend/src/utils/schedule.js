export const REPEAT_CYCLES = [
  {
    value: 'daily',
    label: '每日',
    description: '每天在时间窗内随机执行一次',
  },
  {
    value: 'weekly',
    label: '每周',
    description: '在选定的星期几，于时间窗内随机执行一次',
  },
  {
    value: 'monthly_15',
    label: '每月15日',
    description: '每月 15 日在时间窗内随机执行一次（大小月统一）',
  },
  {
    value: 'monthly',
    label: '每月',
    description: '在选定的日期（1–28 日），于时间窗内随机执行一次',
  },
  {
    value: 'yearly',
    label: '每年',
    description: '在选定的月-日，于时间窗内随机执行一次',
  },
]

export const WEEKDAY_OPTIONS = [
  { value: '1', label: '周一' },
  { value: '2', label: '周二' },
  { value: '3', label: '周三' },
  { value: '4', label: '周四' },
  { value: '5', label: '周五' },
  { value: '6', label: '周六' },
  { value: '7', label: '周日' },
]

export const MONTH_OPTIONS = Array.from({ length: 12 }, (_, index) => ({
  value: String(index + 1),
  label: `${index + 1} 月`,
}))

export const MONTHLY_DAY_OPTIONS = Array.from({ length: 28 }, (_, index) => ({
  value: String(index + 1),
  label: `${index + 1} 日`,
}))

export const TIME_PATTERN = /^(?:[01]\d|2[0-3]):[0-5]\d$/

export function isValidTime(value) {
  return TIME_PATTERN.test(String(value || '').trim())
}

export function validateSchedule(startTime, endTime) {
  if (!isValidTime(startTime)) {
    return '开始时间必须是 24 小时制 HH:mm，例如 09:00'
  }
  if (!isValidTime(endTime)) {
    return '结束时间必须是 24 小时制 HH:mm，例如 11:30'
  }
  if (String(startTime).trim() >= String(endTime).trim()) {
    return '开始时间必须早于结束时间（时间窗不能跨天）'
  }
  return ''
}

export function cycleMeta(value) {
  return REPEAT_CYCLES.find((item) => item.value === value) || REPEAT_CYCLES[0]
}

export function cycleLabel(value) {
  return cycleMeta(value).label
}

export function daysInYearMonth(month) {
  const monthNumber = Number(month)
  if (!Number.isInteger(monthNumber) || monthNumber < 1 || monthNumber > 12) {
    return 0
  }
  // Use a leap year so February offers 29; the backend skips non-leap years.
  return new Date(2024, monthNumber, 0).getDate()
}

export function yearlyParts(value) {
  const match = String(value || '').match(/^(\d{1,2})-(\d{1,2})$/)
  if (!match) return { month: '1', day: '1' }
  return { month: match[1], day: match[2] }
}

export function formatYearSub(month, day) {
  return `${Number(month)}-${Number(day)}`
}

export function normalizeRepeatSubValue(cycle, value) {
  const text = String(value ?? '').trim()
  if (cycle === 'daily' || cycle === 'monthly_15') return ''
  if (cycle === 'weekly') {
    const number = Number(text || 1)
    return Number.isInteger(number) && number >= 1 && number <= 7
      ? String(number)
      : '1'
  }
  if (cycle === 'monthly') {
    const number = Number(text || 1)
    return Number.isInteger(number) && number >= 1 && number <= 28
      ? String(number)
      : '1'
  }
  if (cycle === 'yearly') {
    const { month, day } = yearlyParts(text)
    const monthNumber = Number(month)
    const dayNumber = Number(day)
    if (
      Number.isInteger(monthNumber) &&
      monthNumber >= 1 &&
      monthNumber <= 12 &&
      Number.isInteger(dayNumber) &&
      dayNumber >= 1 &&
      dayNumber <= daysInYearMonth(monthNumber)
    ) {
      return formatYearSub(monthNumber, dayNumber)
    }
    return '1-1'
  }
  return ''
}

export function validateRepeatSubValue(cycle, value) {
  if (cycle === 'daily' || cycle === 'monthly_15') return ''
  if (cycle === 'weekly') {
    const number = Number(value)
    return Number.isInteger(number) && number >= 1 && number <= 7
      ? ''
      : '请选择星期几'
  }
  if (cycle === 'monthly') {
    const number = Number(value)
    return Number.isInteger(number) && number >= 1 && number <= 28
      ? ''
      : '请选择 1–28 日之间的日期'
  }
  if (cycle === 'yearly') {
    const { month, day } = yearlyParts(value)
    const monthNumber = Number(month)
    const dayNumber = Number(day)
    return Number.isInteger(monthNumber) &&
      monthNumber >= 1 &&
      monthNumber <= 12 &&
      Number.isInteger(dayNumber) &&
      dayNumber >= 1 &&
      dayNumber <= daysInYearMonth(monthNumber)
      ? ''
      : '请选择有效的月-日'
  }
  return '重复周期无效'
}

export function cycleDayLabel(value, subValue = '') {
  const cycle = value || 'daily'
  const sub = normalizeRepeatSubValue(cycle, subValue)
  if (cycle === 'daily') return '每天'
  if (cycle === 'weekly') {
    const weekday = WEEKDAY_OPTIONS.find((item) => item.value === sub)
    return `每周${weekday ? weekday.label.replace('周', '') : '一'}`
  }
  if (cycle === 'monthly_15') return '每月15日'
  if (cycle === 'monthly') return `每月${sub}日`
  const { month, day } = yearlyParts(sub)
  return `每年${Number(month)}月${Number(day)}日`
}

export function describeSchedule(startTime, endTime, repeatCycle, repeatSubValue = '') {
  if (!isValidTime(startTime) || !isValidTime(endTime)) {
    return '尚未设置有效的时间窗'
  }
  return `${cycleDayLabel(repeatCycle, repeatSubValue)} ${startTime}–${endTime} 之间随机执行`
}

export const SCHEDULE_STATUS_META = {
  none: { label: '未生成', className: 'is-idle' },
  pending: { label: '待执行', className: 'is-pending' },
  fallback: { label: '兜底时间', className: 'is-fallback' },
  running: { label: '执行中', className: 'is-running' },
  executed: { label: '已执行', className: 'is-success' },
  missed: { label: '已错过', className: 'is-failed' },
  cancelled: { label: '已取消', className: 'is-idle' },
}

export function scheduleStatusMeta(status) {
  return SCHEDULE_STATUS_META[status] || SCHEDULE_STATUS_META.none
}
