// Icon type resolution is intentionally pure so it can be unit-tested without
// mounting Vue. Priority: legacy base64 fields, data URI, HTTPS, local file,
// then Emoji/text. Anything path-like but unsafe is a hard fallback to ⚠️.
export const DATA_URI_RE = /^data:image\/(x-icon|png|svg\+xml);base64,[A-Za-z0-9+/=]+$/
const LOCAL_EXT_RE = /\.(ico|png|svg|jpe?g|webp|gif)$/i
const UNSAFE_PATH_RE = /(^|[\\/])\.\.([\\/]|$)|\\|\0/

export function classifyModuleIcon({ icon = '', source = 'url', iconData = '', moduleKey = '' } = {}) {
  const value = String(icon || '')
  const data = source === 'base64' ? String(iconData || '') : ''

  if (data) {
    return DATA_URI_RE.test(data) && data.length <= 65536
      ? { type: 'base64', src: data }
      : { type: 'fallback', src: '' }
  }
  if (value.startsWith('data:')) {
    return DATA_URI_RE.test(value) && value.length <= 65536
      ? { type: 'base64', src: value }
      : { type: 'fallback', src: '' }
  }
  if (/^https?:\/\//i.test(value)) return { type: 'remote-url', src: value }

  // Public static paths are safe to use as-is. Other absolute paths are not
  // allowed to reach the module filesystem endpoint.
  if (value.startsWith('/')) {
    return value.startsWith('/static/')
      ? { type: 'local-path', src: value, path: value }
      : { type: 'fallback', src: '' }
  }

  const looksLocal =
    value.startsWith('./') || value.includes('/') || LOCAL_EXT_RE.test(value)
  if (looksLocal) {
    if (!moduleKey || UNSAFE_PATH_RE.test(value)) {
      return { type: 'fallback', src: '' }
    }
    const relative = value.startsWith('./') ? value.slice(2) : value
    return relative
      ? { type: 'local-path', path: relative }
      : { type: 'fallback', src: '' }
  }

  if (source === 'local' && moduleKey) return { type: 'local-path', path: 'icon.ico' }

  // A colon/other protocol-like string that reached here is not a safe URL.
  if (value.includes('://') || value.startsWith(':') || value.includes('::')) {
    return { type: 'fallback', src: '' }
  }
  return { type: 'emoji', src: '' }
}

export function isImageContentType(value = '') {
  return /^image\//i.test(String(value))
}
