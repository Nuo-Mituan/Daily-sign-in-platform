<template>
  <section class="panel timeout-panel">
    <div class="panel-head">
      <div>
        <div class="panel-title">超时推送兜底</div>
        <div class="panel-desc">
          主触发时间 = 当日所有已启用统一推送模块的最晚签到时间 + 1 分钟。
          只有主触发失败或未执行时，才会在此时间兜底发送。
        </div>
      </div>
      <el-switch
        v-model="enabledModel"
        :loading="saving"
        active-text="开启兜底"
        inactive-text="不兜底"
        @change="save"
      />
    </div>
    <div class="panel-body timeout-body">
      <template v-if="enabled">
        <span class="timeout-label">超时推送时间</span>
        <el-time-picker
          v-model="timeModel"
          format="HH:mm"
          value-format="HH:mm"
          :clearable="false"
          placeholder="23:30"
          @change="save"
        />
      </template>
      <p class="timeout-note">
        该配置仅作异常补偿：主触发成功后不会再次推送；兜底触发会将未完成模块标记为“推送超时”。
      </p>
    </div>
  </section>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  enabled: { type: Boolean, default: false },
  time: { type: String, default: '23:30' },
  saving: { type: Boolean, default: false },
})
const emit = defineEmits(['update:enabled', 'update:time', 'save'])

const enabledModel = computed({
  get: () => props.enabled,
  set: (value) => emit('update:enabled', Boolean(value)),
})
const timeModel = computed({
  get: () => props.time,
  set: (value) => emit('update:time', value || '23:30'),
})

function save() {
  emit('save', {
    enabled: enabledModel.value,
    time: timeModel.value,
  })
}
</script>

<style scoped>
.timeout-body {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  align-items: center;
}

.timeout-label {
  color: #56607a;
  font-weight: 600;
}

.timeout-note {
  flex-basis: 100%;
  margin: 0;
  color: #8a6d3b;
  line-height: 1.7;
}
</style>
