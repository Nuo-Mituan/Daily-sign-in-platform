<template>
  <span class="status-pill" :class="meta.className">{{ label || meta.label }}</span>
</template>

<script setup>
import { computed } from 'vue'
import { statusMeta } from '@/utils/format'

const props = defineProps({
  status: { type: String, default: 'idle' },
  label: { type: String, default: '' },
})

const meta = computed(() => statusMeta(props.status))
</script>
