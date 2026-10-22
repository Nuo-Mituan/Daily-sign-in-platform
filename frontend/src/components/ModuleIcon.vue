<template>
  <span class="module-icon" :class="toneClass" :style="iconStyle">{{ icon || '🧩' }}</span>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  icon: { type: String, default: '🧩' },
  size: { type: [Number, String], default: 46 },
  tone: { type: [String, Number], default: 0 },
})

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
