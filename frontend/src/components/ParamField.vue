<template>
  <el-input
    v-if="param.type === 'text' || param.type === 'password'"
    :model-value="modelValue ?? ''"
    :type="param.type === 'password' ? 'password' : 'text'"
    :show-password="param.type === 'password'"
    :placeholder="param.placeholder || ''"
    :disabled="disabled"
    clearable
    @update:model-value="(value) => emit('update:modelValue', value)"
  />

  <el-input
    v-else-if="param.type === 'textarea'"
    :model-value="modelValue ?? ''"
    type="textarea"
    :rows="param.rows || 4"
    :placeholder="param.placeholder || ''"
    :disabled="disabled"
    resize="vertical"
    @update:model-value="(value) => emit('update:modelValue', value)"
  />

  <el-input-number
    v-else-if="param.type === 'number'"
    :model-value="modelValue ?? undefined"
    :min="param.min ?? undefined"
    :max="param.max ?? undefined"
    :step="param.step ?? 1"
    :placeholder="param.placeholder || '请输入数字'"
    :disabled="disabled"
    controls-position="right"
    class="full-width"
    @update:model-value="(value) => emit('update:modelValue', value)"
  />

  <el-select
    v-else-if="param.type === 'select'"
    :model-value="modelValue ?? ''"
    :placeholder="param.placeholder || '请选择'"
    :disabled="disabled"
    clearable
    class="full-width"
    @update:model-value="(value) => emit('update:modelValue', value)"
  >
    <el-option
      v-for="option in options"
      :key="String(option.value)"
      :label="option.label"
      :value="option.value"
    />
  </el-select>

  <el-switch
    v-else-if="param.type === 'switch'"
    :model-value="Boolean(modelValue)"
    :disabled="disabled"
    @update:model-value="(value) => emit('update:modelValue', value)"
  />

  <el-input
    v-else
    :model-value="modelValue ?? ''"
    :placeholder="param.placeholder || ''"
    :disabled="disabled"
    @update:model-value="(value) => emit('update:modelValue', value)"
  />
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  param: { type: Object, required: true },
  modelValue: { type: [String, Number, Boolean, null], default: '' },
  disabled: { type: Boolean, default: false },
})

const emit = defineEmits(['update:modelValue'])

const options = computed(() =>
  (props.param.options || []).map((option) => {
    if (option && typeof option === 'object' && !Array.isArray(option)) {
      return {
        label: option.label ?? String(option.value ?? ''),
        value: option.value,
      }
    }
    return { label: String(option), value: option }
  }),
)
</script>

<style scoped>
.full-width {
  width: 100%;
}
</style>
