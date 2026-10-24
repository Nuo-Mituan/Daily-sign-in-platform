<template>
  <span class="module-icon" :class="[toneClass, { 'has-image': imageSrc }]" :style="iconStyle">
    <img
      v-if="imageSrc"
      :src="imageSrc"
      alt=""
      class="module-icon__image"
      @error="onImageError"
    />
    <template v-else>{{ failed ? '⚠️' : icon || '⚠️' }}</template>
  </span>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { modulesApi } from '@/api'
import { classifyModuleIcon } from '@/utils/moduleIcon'

const props = defineProps({
  icon: { type: String, default: '🧩' },
  source: { type: String, default: 'url' },
  iconData: { type: String, default: '' },
  moduleKey: { type: String, default: '' },
  size: { type: [Number, String], default: 46 },
  tone: { type: [String, Number], default: 0 },
})

const imageSrc = ref('')
const failed = ref(false)

watch(
  () => [props.source, props.iconData, props.moduleKey, props.icon],
  () => {
    const kind = classifyModuleIcon({
      icon: props.icon,
      source: props.source,
      iconData: props.iconData,
      moduleKey: props.moduleKey,
    })
    failed.value = kind.type === 'fallback'
    if (kind.type === 'emoji' || kind.type === 'fallback') {
      imageSrc.value = ''
      return
    }
    if (kind.type === 'base64' || kind.type === 'remote-url') {
      imageSrc.value = kind.src || ''
      failed.value = !imageSrc.value
      return
    }
    imageSrc.value = kind.path.startsWith('/static/')
      ? kind.path
      : modulesApi.iconUrl(props.moduleKey, kind.path)
  },
  { immediate: true },
)


function onImageError() {
  imageSrc.value = ''
  failed.value = true
}

const TONES = ['violet', 'mint', 'sky', 'amber']

const toneClass = computed(() => {
  if (typeof props.tone === 'string' && TONES.includes(props.tone)) {
    return `tone-${props.tone}`
  }
  const index = Math.abs(Number(props.tone) || 0) % TONES.length
  return `tone-${TONES[index]}`
})

const iconStyle = computed(() => {
  const size = typeof props.size === 'number' ? `${props.size}px` : props.size
  return {
    width: size,
    height: size,
    fontSize: `calc(${size} * 0.48)`,
  }
})
</script>

<style scoped>
.module-icon {
  display: inline-grid;
  place-items: center;
  flex: none;
  border: 1px solid rgba(255, 255, 255, 0.5);
  border-radius: 14px;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.7);
  line-height: 1;
  user-select: none;
}

.module-icon.has-image {
  background: transparent;
  border-color: transparent;
  box-shadow: none;
}

.module-icon__image {
  width: 100%;
  height: 100%;
  object-fit: cover;
  border-radius: inherit;
}

.tone-violet {
  background: linear-gradient(140deg, #f2efff, #e4e9ff);
}

.tone-mint {
  background: linear-gradient(140deg, #e7faf2, #d9f5ea);
}

.tone-sky {
  background: linear-gradient(140deg, #e9f6ff, #dff0ff);
}

.tone-amber {
  background: linear-gradient(140deg, #fff7e6, #fdf0d8);
}
</style>
