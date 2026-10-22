import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { authApi } from '@/api'
import { setCsrfToken } from '@/api/csrf'

// Remove credentials persisted by pre-cookie releases.  New sessions live only
// in the HttpOnly cookie and the in-memory Pinia store.
localStorage.removeItem('checkin_token')
localStorage.removeItem('checkin_user')

export const useAuthStore = defineStore('auth', () => {
  const user = ref(null)
  const loggingIn = ref(false)
  const sessionChecked = ref(false)
  const isAuthenticated = computed(() => Boolean(user.value))
  const mustChangePassword = ref(false)

  function applySession(data) {
    user.value = data?.user || null
    setCsrfToken(data?.csrf_token || '')
    mustChangePassword.value = Boolean(data?.force_change_password)
    sessionChecked.value = true
    return data
  }

  function clearSession() {
    user.value = null
    mustChangePassword.value = false
    setCsrfToken('')
    sessionChecked.value = true
  }

  async function login(credentials) {
    loggingIn.value = true
    try {
      const data = await authApi.login(credentials)
      return applySession(data)
    } finally {
      loggingIn.value = false
    }
  }

  async function fetchSession() {
    if (user.value) {
      sessionChecked.value = true
      return user.value
    }
    try {
      const data = await authApi.session()
      applySession(data)
      return user.value
    } catch {
      clearSession()
      return null
    }
  }

  async function fetchMe() {
    return fetchSession()
  }

  async function refreshUser() {
    const data = await authApi.me()
    user.value = data
    return data
  }

  async function changePassword(payload) {
    const result = await authApi.changePassword(payload)
    mustChangePassword.value = false
    return result
  }

  async function updateUsername(payload) {
    const updated = await authApi.updateUsername(payload)
    user.value = updated
    return updated
  }

  async function logout() {
    try {
      await authApi.logout()
    } catch {
      // The local session still has to be cleared if the cookie already expired.
    } finally {
      clearSession()
    }
  }

  async function logoutAll() {
    try {
      await authApi.logoutAll()
    } finally {
      clearSession()
    }
  }

  function setUser(nextUser) {
    user.value = nextUser
  }

  return {
    user,
    loggingIn,
    sessionChecked,
    isAuthenticated,
    mustChangePassword,
    login,
    fetchSession,
    fetchMe,
    refreshUser,
    changePassword,
    updateUsername,
    logout,
    logoutAll,
    clearSession,
    setUser,
  }
})
