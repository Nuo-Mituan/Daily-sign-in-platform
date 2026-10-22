<template>
  <div class="account-editor">
    <div class="editor-head">
      <div>
        <span class="editor-count">{{ modelValue.length }} 个账号</span>
        <span class="editor-hint">按顺序线性执行，账号之间自动随机等待</span>
      </div>
      <el-button
        type="primary"
        plain
        size="small"
        :disabled="modelValue.length >= max"
        @click="addAccount"
      >
        <el-icon><Plus /></el-icon>
        添加账号
      </el-button>
    </div>

    <TransitionGroup name="account-list" tag="div" class="account-list">
      <div
        v-for="(account, index) in modelValue"
        :key="account.id"
        class="account-card"
        :class="{
          open: isOpen(account.id),
          dragging: draggingIndex === index,
          'drag-over': dragOverIndex === index && draggingIndex !== null && draggingIndex !== index,
        }"
        @dragover.prevent="onDragOver(index)"
        @drop.prevent="onDrop(index)"
      >
        <div class="account-header">
          <span
            class="drag-handle"
            title="拖拽排序"
            draggable="true"
            @dragstart="onDragStart(index, $event)"
            @dragend="onDragEnd"
            @click.stop
          >
            <el-icon><Rank /></el-icon>
          </span>
          <button type="button" class="header-main" @click="toggle(account.id)">
            <span class="account-index">{{ String(index + 1).padStart(2, '0') }}</span>
            <span class="account-title">
              <strong>{{ accountCardTitle(account, paramSchema, index) }}</strong>
              <small>{{ account.label ? '自定义备注' : '自动脱敏标识' }}</small>
            </span>
            <el-icon class="expand-icon" :class="{ rotated: isOpen(account.id) }">
              <ArrowDown />
            </el-icon>
          </button>
          <div class="header-actions" @click.stop>
            <button
              type="button"
              class="tiny-btn"
              title="上移"
              :disabled="index === 0"
              @click="move(index, -1)"
            >
              <el-icon><ArrowUp /></el-icon>
            </button>
            <button
              type="button"
              class="tiny-btn"
              title="下移"
              :disabled="index === modelValue.length - 1"
              @click="move(index, 1)"
            >
              <el-icon><ArrowDown /></el-icon>
            </button>
            <button type="button" class="tiny-btn" title="复制账号" @click="duplicate(index)">
              <el-icon><CopyDocument /></el-icon>
            </button>
            <button
              type="button"
              class="tiny-btn danger"
              title="删除账号"
              :disabled="modelValue.length <= 1"
              @click="remove(index)"
            >
              <el-icon><Delete /></el-icon>
            </button>
          </div>
        </div>

        <div v-show="isOpen(account.id)" class="account-body">
          <div class="account-label-field">
            <label>备注名称 <span>可选</span></label>
            <el-input
              v-model="account.label"
              maxlength="80"
              placeholder="例如：主账号 / 小号 / 家人账号"
              clearable
            />
            <p>备注会显示在执行日志和推送通知中；留空则自动使用脱敏后的账号标识。</p>
          </div>

          <div class="account-fields">
            <div
              v-for="spec in paramSchema"
              :key="spec.key"
              class="account-field"
            >
              <div class="field-head">
                <label>
                  {{ spec.label }}
                  <em v-if="spec.required" class="required">*</em>
                </label>
                <span v-if="spec.type === 'password'" class="secret-badge">
                  <el-icon><Lock /></el-icon>加密
                </span>
              </div>
              <ParamField v-model="account.params[spec.key]" :param="spec" />
              <p v-if="spec.help" class="field-help">
                <el-icon><InfoFilled /></el-icon>{{ spec.help }}
              </p>
            </div>
          </div>
        </div>
      </div>
    </TransitionGroup>

    <button
      type="button"
      class="add-account-dashed"
      :disabled="modelValue.length >= max"
      @click="addAccount"
    >
      <el-icon><Plus /></el-icon>
      添加第 {{ modelValue.length + 1 }} 个账号
      <span v-if="modelValue.length >= max">（已达到 {{ max }} 个上限）</span>
    </button>
  </div>
</template>

<script setup>
import { onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import {
  ArrowDown,
  ArrowUp,
  CopyDocument,
  Delete,
  InfoFilled,
  Lock,
  Plus,
  Rank,
} from '@element-plus/icons-vue'
import ParamField from '@/components/ParamField.vue'
import {
  accountCardTitle,
  createAccount,
} from '@/utils/accounts'

const props = defineProps({
  modelValue: { type: Array, default: () => [] },
  paramSchema: { type: Array, default: () => [] },
  max: { type: Number, default: 50 },
})

const emit = defineEmits(['update:modelValue'])

const expanded = ref(new Set())
const draggingIndex = ref(null)
const dragOverIndex = ref(null)

onMounted(() => {
  if (props.modelValue[0]) expanded.value.add(props.modelValue[0].id)
})

watch(
  () => props.modelValue[0]?.id,
  (firstId) => {
    if (!firstId) return
    const alive = props.modelValue.some((item) => expanded.value.has(item.id))
    if (!alive) {
      expanded.value.add(firstId)
      expanded.value = new Set(expanded.value)
    }
  },
)

function isOpen(id) {
  return expanded.value.has(id)
}

function toggle(id) {
  if (expanded.value.has(id)) {
    expanded.value.delete(id)
  } else {
    expanded.value.add(id)
  }
  expanded.value = new Set(expanded.value)
}

function commit(next) {
  emit('update:modelValue', next)
}

function addAccount() {
  if (props.modelValue.length >= props.max) {
    ElMessage.warning(`最多只能添加 ${props.max} 个账号`)
    return
  }
  const account = createAccount(props.paramSchema)
  expanded.value.add(account.id)
  expanded.value = new Set(expanded.value)
  commit([...props.modelValue, account])
}

function remove(index) {
  if (props.modelValue.length <= 1) {
    ElMessage.warning('至少保留一个账号')
    return
  }
  const next = [...props.modelValue]
  next.splice(index, 1)
  commit(next)
}

function duplicate(index) {
  if (props.modelValue.length >= props.max) {
    ElMessage.warning(`最多只能添加 ${props.max} 个账号`)
    return
  }
  const source = props.modelValue[index]
  const clone = {
    id: createAccount(props.paramSchema).id,
    label: source.label ? `${source.label} 副本` : '',
    params: { ...source.params },
  }
  const next = [...props.modelValue]
  next.splice(index + 1, 0, clone)
  expanded.value.add(clone.id)
  expanded.value = new Set(expanded.value)
  commit(next)
}

function move(index, offset) {
  const target = index + offset
  if (target < 0 || target >= props.modelValue.length) return
  const next = [...props.modelValue]
  const [item] = next.splice(index, 1)
  next.splice(target, 0, item)
  commit(next)
}

function onDragStart(index, event) {
  draggingIndex.value = index
  if (event.dataTransfer) {
    event.dataTransfer.effectAllowed = 'move'
    event.dataTransfer.setData('text/plain', String(index))
  }
}

function onDragOver(index) {
  dragOverIndex.value = index
}

function onDrop(index) {
  if (draggingIndex.value === null || draggingIndex.value === index) {
    onDragEnd()
    return
  }
  const next = [...props.modelValue]
  const [item] = next.splice(draggingIndex.value, 1)
  next.splice(index, 0, item)
  commit(next)
  onDragEnd()
}

function onDragEnd() {
  draggingIndex.value = null
  dragOverIndex.value = null
}
</script>

<style scoped>
.account-editor {
  display: flex;
  flex-direction: column;
  gap: 13px;
}

.editor-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  padding-bottom: 2px;
}

.editor-count {
  display: block;
  color: #48536c;
  font-size: 12px;
  font-weight: 650;
}

.editor-hint {
  display: block;
  margin-top: 2px;
  color: #a0a8b9;
  font-size: 9.5px;
}

.account-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.account-card {
  overflow: hidden;
  background: #fbfcfe;
  border: 1px solid #e8ebf4;
  border-radius: 13px;
  transition: border-color 0.16s ease, box-shadow 0.16s ease;
}

.account-card.open {
  background: #fff;
  border-color: #dcdfef;
  box-shadow: 0 5px 18px rgba(30, 40, 75, 0.04);
}

.account-card.dragging {
  opacity: 0.55;
  border-color: #a9aaf1;
}

.account-card.drag-over {
  border-color: #8e8ee6;
  box-shadow: 0 0 0 2px rgba(99, 102, 241, 0.08);
}

.account-header {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 9px 10px;
}

.drag-handle {
  display: grid;
  width: 24px;
  height: 30px;
  flex: none;
  place-items: center;
  color: #b5bdcd;
  border-radius: 6px;
  cursor: grab;
  font-size: 14px;
}

.drag-handle:hover {
  color: var(--brand);
  background: #f3f3fe;
}

.drag-handle:active {
  cursor: grabbing;
}

.header-main {
  display: flex;
  min-width: 0;
  flex: 1;
  align-items: center;
  gap: 9px;
  padding: 0;
  text-align: left;
  background: transparent;
  border: 0;
  cursor: pointer;
}

.account-index {
  display: grid;
  width: 26px;
  height: 26px;
  flex: none;
  place-items: center;
  color: #6d67cf;
  background: #f0f1fe;
  border-radius: 7px;
  font-family: var(--font-mono);
  font-size: 9px;
  font-weight: 650;
}

.account-title {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 1px;
  line-height: 1.35;
}

.account-title strong {
  overflow: hidden;
  color: #4b566e;
  font-size: 11.5px;
  font-weight: 620;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.account-title small {
  color: #a6aebf;
  font-size: 8.5px;
}

.expand-icon {
  margin-left: auto;
  color: #a4acbc;
  font-size: 12px;
  transition: transform 0.18s ease;
}

.expand-icon.rotated {
  transform: rotate(180deg);
}

.header-actions {
  display: flex;
  flex: none;
  gap: 1px;
}

.tiny-btn {
  display: grid;
  width: 24px;
  height: 24px;
  place-items: center;
  color: #a0a8ba;
  background: transparent;
  border: 0;
  border-radius: 5px;
  font-size: 11px;
  cursor: pointer;
}

.tiny-btn:hover:not(:disabled) {
  color: #6260c8;
  background: #f0f1fe;
}

.tiny-btn.danger:hover:not(:disabled) {
  color: #c44747;
  background: #fdf1f1;
}

.tiny-btn:disabled {
  opacity: 0.35;
  cursor: not-allowed;
}

.account-body {
  padding: 3px 14px 16px 40px;
  border-top: 1px dashed #eef0f6;
}

.account-label-field {
  padding: 12px 0 4px;
}

.account-label-field > label {
  display: block;
  margin-bottom: 5px;
  color: #59647c;
  font-size: 10.5px;
  font-weight: 600;
}

.account-label-field > label span {
  color: #a4acbc;
  font-weight: 400;
}

.account-label-field p {
  margin-top: 4px;
  color: #a6aebe;
  font-size: 8.5px;
}

.account-fields {
  display: flex;
  flex-direction: column;
  gap: 13px;
  margin-top: 10px;
}

.field-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 5px;
}

.field-head label {
  color: #59647c;
  font-size: 10.5px;
  font-weight: 600;
}

.required {
  color: #e05555;
  font-style: normal;
}

.secret-badge {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  color: #8d91cf;
  font-size: 8px;
}

.field-help {
  display: flex;
  align-items: flex-start;
  gap: 4px;
  margin-top: 4px;
  color: #a2abbc;
  font-size: 9px;
  line-height: 1.55;
}

.add-account-dashed {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 5px;
  min-height: 38px;
  color: #777fcc;
  background: #fafbff;
  border: 1px dashed #d6d9ec;
  border-radius: 10px;
  font-size: 10.5px;
  font-weight: 550;
  cursor: pointer;
  transition: all 0.16s ease;
}

.add-account-dashed:hover:not(:disabled) {
  color: var(--brand);
  background: #f5f5fe;
  border-color: #b9bbec;
}

.add-account-dashed:disabled {
  color: #aeb5c4;
  cursor: not-allowed;
}

.account-list-enter-active,
.account-list-leave-active {
  transition: opacity 0.16s ease, transform 0.16s ease;
}

.account-list-enter-from,
.account-list-leave-to {
  opacity: 0;
  transform: translateY(-4px);
}

@media (max-width: 720px) {
  .account-header {
    flex-wrap: wrap;
  }

  .account-body {
    padding-left: 12px;
    padding-right: 12px;
  }

  .header-actions {
    margin-left: 31px;
  }
}
</style>
