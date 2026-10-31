/**
 * Convert an Axios error into the user-facing message.
 * Icon-specific messages are scoped to the icon route; ZIP uploads and other
 * endpoints keep their normal backend detail/generic fallback.
 */
const ICON_ROUTE_RE = /\/modules\/icon(?:[?#]|$)/
const ICON_STATUS_MESSAGES = Object.freeze({
  415: '图标格式不支持，请使用 PNG / JPG / ICO / WebP',
  413: '图标文件过大，请压缩后重试',
})

export function isIconRequest(error) {
  return ICON_ROUTE_RE.test(String(error?.config?.url || ''))
}

export function extractErrorMessage(error) {
  const status = error?.response?.status
  if (isIconRequest(error) && ICON_STATUS_MESSAGES[status]) {
    return ICON_STATUS_MESSAGES[status]
  }

  const data = error?.response?.data
  const detail = data?.detail
  if (typeof detail === 'string' && detail.trim()) return detail
  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) => {
        if (typeof item === 'string') return item
        const path = Array.isArray(item?.loc) ? item.loc.slice(1).join('.') : ''
        return `${path ? `${path}: ` : ''}${item?.msg || '参数校验失败'}`
      })
      .filter(Boolean)
    if (messages.length) return messages.join('；')
  }
  if (typeof data?.message === 'string') return data.message
  if (error?.code === 'ECONNABORTED') return '请求超时，请稍后重试'
  if (!error?.response) return '无法连接服务器，请检查后端服务是否运行'
  if (status === 401) return '登录状态已失效，请重新登录'
  if (status === 403) return '请求校验失败，请刷新页面后重试'
  return `请求失败（HTTP ${status}）`
}
