export const ICON_STATUS_MESSAGES = Object.freeze({
  415: '图标格式不支持，请使用 PNG / JPG / ICO / WebP',
  413: '图标文件过大，请压缩后重试',
  404: '图标不存在，请检查模块图标路径',
})

// Stable backend codes that mean "use the generic icon message"; concrete
// details without these codes are shown directly (e.g. SVG deprecation).
export const ICON_GENERIC_CODES = new Set([
  'icon_format_default',
  'icon_size_default',
])

export function iconErrorMessage({ status, code, detail } = {}) {
  if (ICON_GENERIC_CODES.has(code)) {
    return ICON_STATUS_MESSAGES[status] || ''
  }
  const concrete = typeof detail === 'string' ? detail.trim() : ''
  return concrete || ICON_STATUS_MESSAGES[status] || ''
}
