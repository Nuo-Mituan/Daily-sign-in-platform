import { ref } from 'vue'
import { defineStore } from 'pinia'
import { systemApi } from '@/api'

export const useAppStore = defineStore('app', () => {
  const meta = ref(null)
  const health = ref(null)
  const metaLoaded = ref(false)

  async function fetchMeta(force = false) {
    if (metaLoaded.value && !force) return meta.value
    try {
      meta.value = await systemApi.meta()
      metaLoaded.value = true
    } catch {
      // Metadata is cosmetic; pages keep working without it.
    }
    return meta.value
  }

  async function fetchHealth() {
    try {
      health.value = await systemApi.health()
    } catch {
      health.value = null
    }
    return health.value
  }

  return { meta, health, metaLoaded, fetchMeta, fetchHealth }
})
