<template>
  <div class="random-schedule-field">
    <div class="time-row">
      <div class="time-control">
        <label class="field-label">开始时间</label>
        <el-input
          :model-value="startTime"
          maxlength="5"
          placeholder="HH:mm"
          clearable
          spellcheck="false"
          class="time-input"
          @update:model-value="(value) => emit('update:start-time', value)"
          @blur="normalizeTime('start')"
        >
          <template #prefix><el-icon><Clock /></el-icon></template>
        </el-input>
      </div>
      <span class="time-separator">—</span>
      <div class="time-control">
        <label class="field-label">结束时间</label>
        <el-input
          :model-value="endTime"
          maxlength="5"
          placeholder="HH:mm"
          clearable
          spellcheck="false"
          class="time-input"
          @update:model-value="(value) => emit('update:end-time', value)"
          @blur="normalizeTime('end')"
        >
          <template #prefix><el-icon><Clock /></el-icon></template>
        </el-input>
      </div>
    </div>

    <div class="cycle-control">
      <label class="field-label">重复周期</label>
      <el-select
        :model-value="repeatCycle"
        class="full-width"
        @update:model-value="handleCycleChange"
      >
        <el-option
          v-for="item in REPEAT_CYCLES"
          :key="item.value"
          :label="item.label"
          :value="item.value"
        />
      </el-select>
    </div>

    <div v-if="repeatCycle === 'weekly'" class="cycle-control sub-control">
      <label class="field-label">星期几</label>
      <el-select
        :model-value="normalizedSub"
        class="full-width"
        @update:model-value="updateSubValue"
      >
        <el-option
          v-for="item in WEEKDAY_OPTIONS"
          :key="item.value"
          :label="item.label"
          :value="item.value"
        />
      </el-select>
    </div>

    <div v-else-if="repeatCycle === 'monthly'" class="cycle-control sub-control">
      <label class="field-label">日期（上限 28）</label>
      <el-select
        :model-value="normalizedSub"
        class="full-width"
        @update:model-value="updateSubValue"
      >
        <el-option
          v-for="item in MONTHLY_DAY_OPTIONS"
          :key="item.value"
          :label="item.label"
          :value="item.value"
        />
      </el-select>
    </div>

    <div v-else-if="repeatCycle === 'yearly'" class="cycle-control sub-control">
      <label class="field-label">月-日</label>
      <div class="year-row">
        <el-select
          :model-value="yearParts.month"
          class="year-part"
          @update:model-value="handleYearMonthChange"
        >
          <el-option
            v-for="item in MONTH_OPTIONS"
            :key="item.value"
            :label="item.label"
            :value="item.value"
          />
        </el-select>
        <el-select
          :model-value="yearParts.day"
          class="year-part"
          @update:model-value="handleYearDayChange"
        >
          <el-option
            v-for="item in yearDayOptions"
            :key="item.value"
            :label="item.label"
            :value="item.value"
          />
        </el-select>
      </div>
    </div>

    <div class="schedule-description" :class="{ invalid: Boolean(error) }">
      <el-icon v-if="error"><WarningFilled /></el-icon>
      <el-icon v-else><Calendar /></el-icon>
      <span>{{ error || description }}</span>
    </div>
    <p class="schedule-hint">
      在每个周期的执行日，于上述时间窗内均匀随机选择一个执行时间。时间窗不能跨天；
      每年 2 月 29 日仅在闰年执行。
    </p>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import {
  MONTHLY_DAY_OPTIONS,
  MONTH_OPTIONS,
  REPEAT_CYCLES,
  WEEKDAY_OPTIONS,
  daysInYearMonth,
  describeSchedule,
  formatYearSub,
  isValidTime,
  normalizeRepeatSubValue,
  validateRepeatSubValue,
  validateSchedule,
  yearlyParts,
} from '@/utils/schedule'

const props = defineProps({
  startTime: { type: String, default: '08:00' },
  endTime: { type: String, default: '10:00' },
  repeatCycle: { type: String, default: 'daily' },
  repeatSubValue: { type: String, default: '' },
})

const emit = defineEmits([
  'update:start-time',
  'update:end-time',
  'update:repeat-cycle',
  'update:repeat-sub-value',
])

const normalizedSub = computed(() =>
  normalizeRepeatSubValue(props.repeatCycle, props.repeatSubValue),
)
const yearParts = computed(() => yearlyParts(normalizedSub.value))
const yearDayOptions = computed(() =>
  Array.from({ length: daysInYearMonth(yearParts.value.month) }, (_, index) => ({
    value: String(index + 1),
    label: `${index + 1} 日`,
  })),
)
const timeError = computed(() => validateSchedule(props.startTime, props.endTime))
const subError = computed(() =>
  validateRepeatSubValue(props.repeatCycle, normalizedSub.value),
)
const error = computed(() => timeError.value || subError.value)
const description = computed(() =>
  describeSchedule(
    props.startTime,
    props.endTime,
    props.repeatCycle,
    normalizedSub.value,
  ),
)

function updateSubValue(value) {
  emit(
    'update:repeat-sub-value',
    normalizeRepeatSubValue(props.repeatCycle, value),
  )
}

function handleCycleChange(value) {
  emit('update:repeat-cycle', value)
  emit(
    'update:repeat-sub-value',
    normalizeRepeatSubValue(value, props.repeatSubValue),
  )
}

function handleYearMonthChange(month) {
  const maxDay = daysInYearMonth(month)
  const day = Math.min(Number(yearParts.value.day) || 1, maxDay)
  emit('update:repeat-sub-value', formatYearSub(month, day))
}

function handleYearDayChange(day) {
  emit(
    'update:repeat-sub-value',
    formatYearSub(yearParts.value.month, day),
  )
}

function normalizeTime(which) {
  const raw = String(which === 'start' ? props.startTime : props.endTime || '').trim()
  if (!isValidTime(raw)) return
  const [hour, minute] = raw.split(':')
  const normalized = `${hour.padStart(2, '0')}:${minute}`
  if (which === 'start' && normalized !== props.startTime) {
    emit('update:start-time', normalized)
  }
  if (which === 'end' && normalized !== props.endTime) {
    emit('update:end-time', normalized)
  }
}
</script>

<style scoped>
.random-schedule-field {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.time-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr);
  align-items: end;
  gap: 9px;
}

.time-control,
.cycle-control {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 6px;
}

.field-label {
  color: #59647c;
  font-size: 11px;
  font-weight: 600;
}

.time-input :deep(input) {
  font-family: var(--font-mono);
  letter-spacing: 0.04em;
}

.time-separator {
  padding-bottom: 8px;
  color: #b0b8c8;
  font-size: 12px;
}

.full-width {
  width: 100%;
}

.sub-control {
  padding: 9px 10px;
  background: #fafbfe;
  border: 1px solid #eef1f7;
  border-radius: 9px;
}

.year-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
}

.year-part {
  width: 100%;
}

.schedule-description {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  padding: 9px 11px;
  color: #5257c4;
  background: #f5f5ff;
  border: 1px solid #ececfb;
  border-radius: 9px;
  font-size: 10.5px;
  line-height: 1.6;
}

.schedule-description.invalid {
  color: #be4a4a;
  background: #fdf4f4;
  border-color: #f6e2e2;
}

.schedule-hint {
  color: #a0a8b9;
  font-size: 9.5px;
  line-height: 1.65;
}

@media (max-width: 420px) {
  .time-row {
    grid-template-columns: 1fr;
  }

  .time-separator {
    display: none;
  }
}
</style>
