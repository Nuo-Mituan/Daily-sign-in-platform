import http from './http'
export const authApi = {
  login: (payload) => http.post('/auth/login', payload, { silent: true }),
  session: () => http.get('/auth/session', { silent: true }),
  me: () => http.get('/auth/me', { silent: true }),
  logout: () => http.post('/auth/logout', null, { silent: true }),
  logoutAll: () => http.post('/auth/logout-all'),
  changePassword: (payload) => http.post('/auth/change-password', payload),
  updateUsername: (payload) => http.put('/auth/username', payload),
}

export const modulesApi = {
  list: () => http.get('/modules'),
  get: (id) => http.get(`/modules/${id}`),
  update: (id, payload) => http.put(`/modules/${id}`, payload),
  toggle: (id, enabled) => http.patch(`/modules/${id}/enabled`, { enabled }),
  run: (id) => http.post(`/modules/${id}/run`),
  remove: (id) => http.delete(`/modules/${id}`),
  scan: () => http.post('/modules/scan'),
  upload: (formData, overwrite = false) =>
    http.post('/modules/upload', formData, {
      params: overwrite ? { overwrite: true } : {},
      timeout: 120000,
    }),
  regenerateSchedule: (id) => http.post(`/modules/${id}/schedule/regenerate`),
  revealSensitive: (id, payload) =>
    http.post(`/modules/${id}/reveal-sensitive`, payload),
}

export const pushApi = {
  getConfig: () => http.get('/push/config'),
  saveConfig: (payload) => http.put('/push/config', payload),
  reveal: (payload) => http.post('/push/reveal', payload),
  test: () => http.post('/push/test'),
  getUnifiedSettings: () => http.get('/push/unified-settings'),
  updateUnifiedSettings: (payload) => http.put('/push/unified-settings', payload),
  listRecords: (params) => http.get('/push/records', { params }),
  listBatches: (params) => http.get('/push/batches', { params }),
  listDrivers: () => http.get('/push/drivers'),
  uploadDriver: (formData) =>
    http.post('/push/drivers/upload', formData, { timeout: 120000 }),
  rollbackDriver: (key, payload = {}) =>
    http.post(`/push/drivers/${key}/rollback`, payload),
  deleteDriver: (key) => http.delete(`/push/drivers/${key}`),
}

export const logsApi = {
  list: (params) => http.get('/logs', { params }),
  get: (id) => http.get(`/logs/${id}`),
  clear: (moduleId) =>
    http.delete('/logs', {
      params: moduleId ? { module_id: moduleId } : {},
    }),
}

export const dashboardApi = {
  get: (params) => http.get('/dashboard', { params }),
}

export const systemApi = {
  health: () => http.get('/health', { silent: true }),
  meta: () => http.get('/meta'),
  getDeveloperMode: () => http.get('/settings/developer'),
  updateDeveloperMode: (enabled) => http.put('/settings/developer', { enabled }),
  getLogSettings: () => http.get('/settings/logs'),
  updateLogSettings: (payload) => http.put('/settings/logs', payload),
  systemLogs: (params) => http.get('/system/logs', { params }),
  metrics: () => http.get('/system/metrics'),
}

export function apiBase() {
  return String(http.defaults.baseURL || '/api').replace(/\/+$/, '')
}

export async function streamExecutionLog(
  logId,
  { onChunk, onDone, onError, onSeq, lastSeq = 0, signal } = {},
) {
  try {
    const resumeSeq = Math.max(0, Number(lastSeq) || 0)
    const query = resumeSeq ? `?last_seq=${encodeURIComponent(resumeSeq)}` : ''
    const response = await fetch(`${apiBase()}/logs/${logId}/stream${query}`, {
      method: 'GET',
      headers: {
        Accept: 'text/event-stream',
        ...(resumeSeq ? { 'Last-Event-ID': String(resumeSeq) } : {}),
      },
      cache: 'no-store',
      credentials: 'include',
      signal,
    })

    if (!response.ok) {
      let detail = `日志流连接失败（HTTP ${response.status}）`
      try {
        const data = await response.json()
        if (typeof data?.detail === 'string') detail = data.detail
      } catch {
        // keep the default message
      }
      throw new Error(detail)
    }
    if (!response.body) {
      throw new Error('当前浏览器不支持流式日志')
    }

    const reader = response.body.getReader()
    const decoder = new TextDecoder('utf-8')
    let buffer = ''
    let doneCalled = false

    const processBlock = (raw) => {
      let event = 'message'
      const dataLines = []
      for (const line of raw.split(/\r?\n/)) {
        if (line.startsWith('event:')) {
          event = line.slice(6).trim()
        } else if (line.startsWith('data:')) {
          dataLines.push(line.slice(5).trimStart())
        }
      }
      if (!dataLines.length) return false
      let payload
      try {
        payload = JSON.parse(dataLines.join('\n'))
      } catch {
        return false
      }
      if (event === 'chunk') {
        const seq = Number(payload.seq) || 0
        onChunk?.(payload.text || '', seq)
        if (seq) onSeq?.(seq)
      } else if (event === 'done') {
        doneCalled = true
        onDone?.(payload)
        return true
      }
      return false
    }

    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      let boundary = buffer.indexOf('\n\n')
      while (boundary !== -1) {
        const raw = buffer.slice(0, boundary)
        buffer = buffer.slice(boundary + 2)
        if (processBlock(raw)) return
        boundary = buffer.indexOf('\n\n')
      }
    }

    if (buffer.trim()) processBlock(buffer)
    if (!doneCalled) {
      onDone?.({ status: 'unknown', message: '日志流已结束' })
    }
  } catch (error) {
    if (error?.name === 'AbortError') return
    onError?.(error)
  }
}
