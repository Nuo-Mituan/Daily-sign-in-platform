import axios from 'axios'
import { ElMessage } from 'element-plus'
import { getCsrfToken, setCsrfToken } from '@/api/csrf'
import { extractErrorMessage } from '@/api/errorMessage'

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


http.interceptors.response.use(
  (response) => response.data,
  (error) => {
    const status = error.response?.status
    const config = error.config || {}
    const message = extractErrorMessage(error)

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
