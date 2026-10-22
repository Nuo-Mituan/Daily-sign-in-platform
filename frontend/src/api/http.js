import axios from 'axios'
import { ElMessage } from 'element-plus'
import { getCsrfToken, setCsrfToken } from '@/api/csrf'

const http = axios.create({
  baseURL: import.meta.env.VITE_API_BASE || '/api',
  timeout: 30000,
  withCredentials: true,
})

http.interceptors.request.use((config) => {
  const method = String(config.method || 'get').toUpperCase()
  if (!['GET', 'HEAD', 'OPTIONS'].includes(method)) {
    const token = getCsrfToken()
    if (token) {
      config.headers['X-CSRF-Token'] = token
    }
  }
  return config
})

function extractMessage(error) {
  const data = error.response?.data
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
  if (error.code === 'ECONNABORTED') return '请求超时，请稍后重试'
  if (!error.response) return '无法连接服务器，请检查后端服务是否运行'
  if (error.response.status === 401) return '登录状态已失效，请重新登录'
  if (error.response.status === 403) return '请求校验失败，请刷新页面后重试'
  return `请求失败（HTTP ${error.response.status}）`
}

http.interceptors.response.use(
  (response) => response.data,
  (error) => {
    const status = error.response?.status
    const config = error.config || {}
    const message = extractMessage(error)

    if (status === 401) {
      // Remove credentials left by pre-cookie releases.
      localStorage.removeItem('checkin_token')
      localStorage.removeItem('checkin_user')
      setCsrfToken('')
      if (!window.location.pathname.startsWith('/login')) {
        const redirect = encodeURIComponent(
          `${window.location.pathname}${window.location.search}`,
        )
        window.location.assign(`/login?redirect=${redirect}`)
      }
    } else if (!config.silent) {
      ElMessage.error(message)
    }

    const normalized = new Error(message)
    normalized.status = status
    normalized.original = error
    return Promise.reject(normalized)
  },
)

export default http
