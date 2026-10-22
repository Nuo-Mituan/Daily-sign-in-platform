<template>
  <div class="stat-card" :class="`tone-${tone}`">
    <div class="stat-card__top">
      <span class="stat-card__label">{{ label }}</span>
      <span class="stat-card__icon">
        <slot name="icon">
          <el-icon><DataLine /></el-icon>
        </slot>
      </span>
    </div>
    <div class="stat-card__value">
      {{ value }}
      <small v-if="suffix">{{ suffix }}</small>
    </div>
    <div class="stat-card__hint">{{ hint }}</div>
    <i class="stat-card__glow" aria-hidden="true"></i>
  </div>
</template>

<script setup>
defineProps({
  label: { type: String, required: true },
  value: { type: [Number, String], default: 0 },
  suffix: { type: String, default: '' },
  hint: { type: String, default: '' },
  tone: { type: String, default: 'violet' },
})
</script>

<style scoped>
.stat-card {
  position: relative;
  overflow: hidden;
  padding: 20px 22px 18px;
  background: #fff;
  border: 1px solid var(--line);
  border-radius: 18px;
  box-shadow: var(--shadow-sm);
  transition: transform 0.22s ease, box-shadow 0.22s ease;
}

.stat-card:hover {
  transform: translateY(-3px);
  box-shadow: var(--shadow-md);
}

.stat-card__top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.stat-card__label {
  color: #7d869b;
  font-size: 12.5px;
  font-weight: 600;
}

.stat-card__icon {
  display: grid;
  width: 34px;
  height: 34px;
  place-items: center;
  border-radius: 10px;
  font-size: 16px;
}

.stat-card__value {
  margin-top: 8px;
  color: var(--ink);
  font-size: 32px;
  font-weight: 760;
  letter-spacing: -0.03em;
  line-height: 1.2;
}

.stat-card__value small {
  margin-left: 2px;
  color: #8f98ac;
  font-size: 15px;
  font-weight: 650;
}

.stat-card__hint {
  margin-top: 4px;
  color: #98a1b4;
  font-size: 12px;
}

.stat-card__glow {
  position: absolute;
  right: -28px;
  bottom: -42px;
  width: 104px;
  height: 104px;
  border-radius: 50%;
  opacity: 0.55;
  filter: blur(6px);
  pointer-events: none;
}

.tone-violet .stat-card__icon {
  color: #5f5bd8;
  background: #eeefff;
}

.tone-violet .stat-card__glow {
  background: radial-gradient(circle, #dfe0ff, transparent 68%);
}

.tone-mint .stat-card__icon {
  color: #0b9d70;
  background: var(--mint-soft);
}

.tone-mint .stat-card__glow {
  background: radial-gradient(circle, #d8f7ea, transparent 68%);
}

.tone-sky .stat-card__icon {
  color: #0b83b8;
  background: var(--sky-soft);
}

.tone-sky .stat-card__glow {
  background: radial-gradient(circle, #d9f1ff, transparent 68%);
}

.tone-amber .stat-card__icon {
  color: #bf7d06;
  background: var(--amber-soft);
}

.tone-amber .stat-card__glow {
  background: radial-gradient(circle, #ffefcf, transparent 68%);
}
</style>
