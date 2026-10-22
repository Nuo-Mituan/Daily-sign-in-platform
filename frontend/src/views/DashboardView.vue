<template>
  <div v-loading="loading" class="page-shell dashboard-page">
    <section class="hero-band">
      <div class="hero-glow"></div>
      <div class="hero-dots"></div>
      <div class="hero-content">
        <div class="hero-copy">
          <span class="hero-eyebrow">
            <i></i>
            OVERVIEW · {{ todayLabel() }}
          </span>
          <h1>{{ greeting() }}，{{ auth.user?.username || 'admin' }}</h1>
          <p class="hero-desc">
            今天已执行 <strong>{{ stats.today_runs }}</strong> 次签到，
            成功 <strong class="success-text">{{ stats.today_success }}</strong> 次，
            失败 <strong class="fail-text">{{ stats.today_failed }}</strong> 次。
            <template v-if="nextModule">
              下一次任务将在 <strong>{{ timeFromNow(nextModule.current_schedule_at) }}</strong> 触发。
            </template>
            <template v-else-if="stats.enabled_modules === 0">
              目前还没有启用任何模块，去配置一个吧。
            </template>
            <template v-else>
              当前没有待执行的随机计划，等待下一个周期生成。
            </template>
          </p>
          <div class="hero-actions">
            <el-button type="primary" class="hero-primary" @click="router.push('/modules')">
              <el-icon><Grid /></el-icon>
              管理签到模块
            </el-button>
            <button type="button" class="hero-ghost" @click="refresh">
              <el-icon :class="{ 'is-loading': loading }"><Refresh /></el-icon>
              刷新数据
            </button>
          </div>
        </div>

        <div class="hero-aside">
          <div v-if="nextModule" class="next-card">
            <div class="next-head">
              <span class="next-eyebrow"><i></i> NEXT RUN</span>
              <span class="next-cron mono">{{ nextModule.start_time }}–{{ nextModule.end_time }}</span>
            </div>
            <div class="next-main">
              <ModuleIcon :icon="nextModule.icon" :size="46" :tone="nextModule.id" />
              <div class="next-info">
                <strong>{{ nextModule.name }}</strong>
                <span>{{ describeSchedule(nextModule.start_time, nextModule.end_time, nextModule.repeat_cycle, nextModule.repeat_sub_value) }}</span>
              </div>
            </div>
            <div class="next-time-row">
              <span class="next-date">{{ nextDateLabel }}</span>
              <strong class="next-clock">{{ nextClockLabel }}</strong>
            </div>
            <div class="next-foot">
              <span><el-icon><Timer /></el-icon> {{ timeFromNow(nextModule.current_schedule_at) }}</span>
              <span class="next-live">{{ scheduleStatusMeta(nextModule.schedule_status).label }}</span>
            </div>
          </div>
          <div v-else class="next-card next-empty">
            <span class="next-eyebrow"><i></i> NEXT RUN</span>
            <div class="empty-orb">—</div>
            <strong>{{ stats.enabled_modules ? '暂无待执行计划' : '暂无已启用的模块' }}</strong>
            <p v-if="stats.enabled_modules">
              当前周期没有待执行的随机时间，等待下一个周期自动生成。
            </p>
            <p v-else>前往模块管理，填写账号并打开开关，任务会自动排程。</p>
            <button type="button" class="next-link" @click="router.push('/modules')">
              去配置模块 <el-icon><Right /></el-icon>
            </button>
          </div>
        </div>
      </div>
    </section>

    <section class="stats-grid">
      <StatCard
        label="模块总数"
        :value="stats.total_modules"
        :hint="`已启用 ${stats.enabled_modules} 个 · 已禁用 ${Math.max(0, stats.total_modules - stats.enabled_modules)} 个`"
        tone="violet"
      >
        <template #icon><el-icon><Grid /></el-icon></template>
      </StatCard>
      <StatCard
        label="已启用模块"
        :value="stats.enabled_modules"
        hint="独立开关实时生效"
        tone="mint"
      >
        <template #icon><el-icon><CircleCheck /></el-icon></template>
      </StatCard>
      <StatCard
        label="今日执行"
        :value="stats.today_runs"
        :hint="`成功 ${stats.today_success} 次 · 失败 ${stats.today_failed} 次`"
        tone="sky"
      >
        <template #icon><el-icon><Timer /></el-icon></template>
      </StatCard>
      <StatCard
        label="正在运行"
        :value="stats.today_running"
        :hint="`今日成功率 ${stats.success_rate}%`"
        tone="amber"
      >
        <template #icon><el-icon><Loading /></el-icon></template>
      </StatCard>
    </section>

    <div class="dashboard-grid">
      <section class="panel recent-panel">
        <div class="panel-head">
          <div>
            <div class="panel-title">最近执行</div>
            <div class="panel-desc">所有模块最新的运行结果，点击行可查看实时 / 历史日志</div>
          </div>
          <router-link to="/logs" class="text-link">
            全部记录 <el-icon><ArrowRight /></el-icon>
          </router-link>
        </div>
        <div class="panel-body recent-body">
          <div v-if="recent.length && isMobile" class="recent-mobile-list">
            <button
              v-for="row in recent"
              :key="row.id"
              type="button"
              class="recent-mobile-item"
              @click="openLog(row)"
            >
              <span class="mini-avatar">{{ row.module_name.slice(0, 1) }}</span>
              <div class="mobile-recent-main">
                <div class="mobile-recent-title">
                  <strong>{{ row.module_name }}</strong>
                  <StatusTag :status="row.status" />
                </div>
                <span>
                  {{ formatShortDateTime(row.started_at) }} ·
                  {{ triggerLabel(row.trigger) }} ·
                  {{ formatDuration(row.duration_ms) }}
                </span>
              </div>
              <el-icon class="row-arrow"><ArrowRight /></el-icon>
            </button>
          </div>
          <el-table
            v-else-if="recent.length"
            :data="recent"
            class="recent-table"
            @row-click="openLog"
          >
            <el-table-column label="模块" min-width="190">
              <template #default="{ row }">
                <div class="module-cell">
                  <span class="mini-avatar">{{ row.module_name.slice(0, 1) }}</span>
                  <div class="module-cell-copy">
                    <strong>{{ row.module_name }}</strong>
                    <span class="mono">{{ row.module_key }}</span>
                  </div>
                </div>
              </template>
            </el-table-column>
            <el-table-column label="状态" width="104">
              <template #default="{ row }">
                <StatusTag :status="row.status" />
              </template>
            </el-table-column>
            <el-table-column label="触发" width="92">
              <template #default="{ row }">
                <span class="trigger-text">{{ triggerLabel(row.trigger) }}</span>
              </template>
            </el-table-column>
            <el-table-column label="时间" width="155">
              <template #default="{ row }">
                <div class="time-cell">
                  <span>{{ formatShortDateTime(row.started_at) }}</span>
                  <small>{{ timeFromNow(row.started_at) }}</small>
                </div>
              </template>
            </el-table-column>
            <el-table-column label="耗时" width="86" align="right">
              <template #default="{ row }">
                <span class="duration-text">{{ formatDuration(row.duration_ms) }}</span>
              </template>
            </el-table-column>
            <el-table-column width="42" align="right">
              <template #default>
                <el-icon class="row-arrow"><ArrowRight /></el-icon>
              </template>
            </el-table-column>
          </el-table>
          <div v-else class="empty-state">
            <div class="empty-state__icon"><el-icon><Document /></el-icon></div>
            <div class="empty-state__title">还没有执行记录</div>
            <div class="empty-state__desc">配置好模块后点击「立即执行」，或等待定时任务触发。</div>
          </div>
        </div>
      </section>

      <aside class="side-column">
        <section class="panel upcoming-panel">
          <div class="panel-head">
            <div>
              <div class="panel-title">即将执行</div>
              <div class="panel-desc">按下次运行时间排序</div>
            </div>
            <router-link to="/modules" class="text-link">
              管理 <el-icon><ArrowRight /></el-icon>
            </router-link>
          </div>
          <div class="panel-body upcoming-body">
            <div v-if="upcoming.length" class="upcoming-list">
              <button
                v-for="(item, index) in upcoming"
                :key="item.id"
                type="button"
                class="upcoming-item"
                @click="router.push(`/modules/${item.id}`)"
              >
                <ModuleIcon :icon="item.icon" :size="36" :tone="index + item.id" />
                <div class="upcoming-copy">
                  <strong>{{ item.name }}</strong>
                  <span>{{ describeSchedule(item.start_time, item.end_time, item.repeat_cycle, item.repeat_sub_value) }}</span>
                </div>
                <div class="upcoming-time">
                  <strong>{{ formatShortDateTime(item.current_schedule_at) }}</strong>
                  <span>{{ timeFromNow(item.current_schedule_at) }}</span>
                </div>
              </button>
            </div>
            <div v-else class="empty-state compact-empty">
              <div class="empty-state__icon"><el-icon><Calendar /></el-icon></div>
              <div class="empty-state__title">暂无排程</div>
              <div class="empty-state__desc">启用模块后会在这里看到下一次执行时间。</div>
            </div>
          </div>
        </section>

        <section class="panel health-panel">
          <div class="panel-head">
            <div>
              <div class="panel-title">今日健康度</div>
              <div class="panel-desc">基于已完成任务计算</div>
            </div>
            <span class="health-badge" :class="{ healthy: stats.success_rate >= 80 && stats.today_runs > 0 }">
              {{ healthLabel }}
            </span>
          </div>
          <div class="panel-body health-body">
            <div class="ring-wrap">
              <div class="donut" :style="{ background: donutBackground }">
                <div class="donut-inner">
                  <strong>{{ stats.success_rate }}<small>%</small></strong>
                  <span>成功率</span>
                </div>
              </div>
            </div>
            <div class="health-legend">
              <div class="legend-row">
                <span class="legend-dot success"></span>
                <span>成功</span>
                <strong>{{ stats.today_success }}</strong>
              </div>
              <div class="legend-row">
                <span class="legend-dot failed"></span>
                <span>失败</span>
                <strong>{{ stats.today_failed }}</strong>
              </div>
              <div class="legend-row">
                <span class="legend-dot running"></span>
                <span>运行中</span>
                <strong>{{ stats.today_running }}</strong>
              </div>
            </div>
          </div>
          <div class="health-foot">
            <span><el-icon><Connection /></el-icon> 调度器 {{ appStore.health?.scheduler_running ? '在线' : '检测中' }}</span>
            <span>{{ stats.running_modules }} 个模块执行中</span>
          </div>
        </section>
      </aside>
    </div>

    <RunLogDrawer
      v-model="logDrawerOpen"
      :log-id="selectedLogId"
      title="执行日志"
      @finished="refresh"
    />
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import dayjs from 'dayjs'
import {
  ArrowRight,
  Calendar,
  CircleCheck,
  Connection,
  Document,
  Grid,
  Loading,
  Refresh,
  Right,
  Timer,
} from '@element-plus/icons-vue'
import StatCard from '@/components/StatCard.vue'
import StatusTag from '@/components/StatusTag.vue'
import ModuleIcon from '@/components/ModuleIcon.vue'
import RunLogDrawer from '@/components/RunLogDrawer.vue'
import { dashboardApi, modulesApi } from '@/api'
import { useAuthStore } from '@/stores/auth'
import { useAppStore } from '@/stores/app'
import { describeSchedule, scheduleStatusMeta } from '@/utils/schedule'
import {
  formatDuration,
  formatShortDateTime,
  greeting,
  timeFromNow,
  todayLabel,
  triggerLabel,
} from '@/utils/format'

const router = useRouter()
const auth = useAuthStore()
const appStore = useAppStore()

const loading = ref(false)
const isMobile = ref(typeof window !== 'undefined' && window.innerWidth < 760)
const modules = ref([])
const recent = ref([])
const stats = ref({
  total_modules: 0,
  enabled_modules: 0,
  today_runs: 0,
  today_success: 0,
  today_failed: 0,
  today_running: 0,
  success_rate: 0,
  running_modules: 0,
})

const logDrawerOpen = ref(false)
const selectedLogId = ref(null)

const upcoming = computed(() => {
  const now = Date.now()
  return modules.value
    .filter(
      (item) =>
        item.enabled &&
        item.current_schedule_at &&
        ['pending', 'fallback'].includes(item.schedule_status) &&
        new Date(item.current_schedule_at).getTime() > now,
    )
    .sort(
      (a, b) =>
        new Date(a.current_schedule_at).getTime() -
        new Date(b.current_schedule_at).getTime(),
    )
    .slice(0, 4)
})

const nextModule = computed(() => upcoming.value[0] || null)
const nextDateLabel = computed(() => {
  if (!nextModule.value) return '—'
  return dayjs(nextModule.value.current_schedule_at).format('MM月DD日 ddd')
})
const nextClockLabel = computed(() => {
  if (!nextModule.value) return '—'
  return dayjs(nextModule.value.current_schedule_at).format('HH:mm')
})

const donutBackground = computed(() => {
  const rate = Math.min(100, Math.max(0, Number(stats.value.success_rate) || 0))
  if (stats.value.today_success + stats.value.today_failed === 0) {
    return 'conic-gradient(#e8ebf4 0 100%)'
  }
  return `conic-gradient(#10b981 0 ${rate}%, #f0f2f8 ${rate}% 100%)`
})

const healthLabel = computed(() => {
  if (stats.value.today_success + stats.value.today_failed === 0) return '待运行'
  if (stats.value.success_rate >= 80) return '状态良好'
  if (stats.value.success_rate >= 50) return '需关注'
  return '异常偏多'
})

async function refresh() {
  loading.value = true
  try {
    const [dashboard, moduleList] = await Promise.all([
      dashboardApi.get({ recent_limit: 7 }),
      modulesApi.list(),
    ])
    stats.value = dashboard.stats
    recent.value = dashboard.recent
    modules.value = moduleList
  } catch {
    // Errors are surfaced by the HTTP interceptor.
  } finally {
    loading.value = false
  }
}

function openLog(row) {
  selectedLogId.value = row.id
  logDrawerOpen.value = true
}

function handleWindowResize() {
  isMobile.value = window.innerWidth < 760
}

onMounted(() => {
  window.addEventListener('resize', handleWindowResize)
  appStore.fetchMeta()
  refresh()
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', handleWindowResize)
})
</script>

<style scoped>
.dashboard-page {
  padding-top: 26px;
}

.hero-band {
  position: relative;
  overflow: hidden;
  padding: 34px 38px 70px;
  color: #f4f6ff;
  background:
    radial-gradient(circle at 84% 10%, rgba(99, 102, 241, 0.42), transparent 32%),
    radial-gradient(circle at 98% 88%, rgba(34, 211, 238, 0.12), transparent 30%),
    linear-gradient(130deg, #0e1527 0%, #0b1120 52%, #111a30 100%);
  border: 1px solid rgba(255, 255, 255, 0.05);
  border-radius: 24px;
  box-shadow: 0 24px 60px rgba(13, 20, 40, 0.22);
}

.hero-glow {
  position: absolute;
  top: -60px;
  left: 34%;
  width: 280px;
  height: 280px;
  background: radial-gradient(circle, rgba(129, 140, 248, 0.2), transparent 68%);
  pointer-events: none;
}

.hero-dots {
  position: absolute;
  inset: 0;
  background-image: radial-gradient(rgba(255, 255, 255, 0.14) 1px, transparent 1px);
  background-size: 19px 19px;
  mask-image: linear-gradient(105deg, transparent 35%, #000 100%);
  opacity: 0.36;
  pointer-events: none;
}

.hero-content {
  position: relative;
  z-index: 1;
  display: grid;
  grid-template-columns: minmax(0, 1.35fr) minmax(310px, 0.65fr);
  gap: 42px;
  align-items: center;
}

.hero-eyebrow {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  color: rgba(166, 180, 218, 0.55);
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.18em;
}

.hero-eyebrow i {
  width: 5px;
  height: 5px;
  background: #34d399;
  border-radius: 50%;
  box-shadow: 0 0 10px rgba(52, 211, 153, 0.8);
}

.hero-copy h1 {
  margin-top: 12px;
  color: #fff;
  font-size: clamp(26px, 2.6vw, 36px);
  font-weight: 750;
  letter-spacing: -0.035em;
  line-height: 1.25;
}

.hero-desc {
  max-width: 610px;
  margin-top: 12px;
  color: rgba(190, 203, 237, 0.55);
  font-size: 12.5px;
  line-height: 1.85;
}

.hero-desc strong {
  color: rgba(238, 243, 255, 0.94);
  font-weight: 650;
}

.hero-desc .success-text {
  color: #6ee7b7;
}

.hero-desc .fail-text {
  color: #fda4af;
}

.hero-actions {
  display: flex;
  align-items: center;
  gap: 13px;
  margin-top: 22px;
}

.hero-primary {
  height: 39px;
  padding: 0 17px;
  color: #fff;
  background: linear-gradient(135deg, #6465e8, #8b5cf6);
  border: 1px solid rgba(255, 255, 255, 0.12);
  box-shadow: 0 10px 24px rgba(91, 91, 214, 0.3);
  font-size: 12.5px;
}

.hero-ghost {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 39px;
  padding: 0 14px;
  color: rgba(220, 229, 252, 0.68);
  background: rgba(255, 255, 255, 0.045);
  border: 1px solid rgba(255, 255, 255, 0.09);
  border-radius: 9px;
  font-size: 12px;
  font-weight: 550;
  cursor: pointer;
  transition: all 0.16s ease;
}

.hero-ghost:hover {
  color: #fff;
  background: rgba(255, 255, 255, 0.08);
}

.hero-aside {
  min-width: 0;
}

.next-card {
  padding: 17px 18px 13px;
  background: rgba(255, 255, 255, 0.045);
  border: 1px solid rgba(255, 255, 255, 0.085);
  border-radius: 17px;
  box-shadow: 0 22px 46px rgba(0, 0, 0, 0.16);
  backdrop-filter: blur(12px);
}

.next-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-bottom: 12px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.065);
}

.next-eyebrow {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: rgba(180, 195, 235, 0.42);
  font-family: var(--font-mono);
  font-size: 8.5px;
  font-weight: 700;
  letter-spacing: 0.14em;
}

.next-eyebrow i {
  width: 4px;
  height: 4px;
  background: #818cf8;
  border-radius: 50%;
}

.next-cron {
  color: rgba(147, 197, 253, 0.72);
  font-size: 9.5px;
}

.next-main {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 14px;
}

.next-info {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 2px;
}

.next-info strong {
  overflow: hidden;
  color: rgba(245, 248, 255, 0.92);
  font-size: 13.5px;
  font-weight: 650;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.next-info span {
  overflow: hidden;
  color: rgba(186, 200, 236, 0.4);
  font-size: 10.5px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.next-time-row {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 10px;
  margin-top: 14px;
}

.next-date {
  color: rgba(188, 202, 238, 0.5);
  font-size: 10.5px;
}

.next-clock {
  color: #fff;
  font-family: var(--font-mono);
  font-size: 29px;
  font-weight: 600;
  letter-spacing: -0.04em;
  line-height: 1;
}

.next-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 13px;
  padding-top: 10px;
  color: rgba(185, 199, 236, 0.36);
  border-top: 1px solid rgba(255, 255, 255, 0.055);
  font-size: 9.5px;
}

.next-foot span {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.next-live {
  font-family: var(--font-mono);
  font-size: 8px;
  letter-spacing: 0.1em;
}

.next-empty {
  display: flex;
  align-items: center;
  flex-direction: column;
  padding: 23px 18px 18px;
  text-align: center;
}

.next-empty .next-eyebrow {
  align-self: flex-start;
}

.empty-orb {
  display: grid;
  width: 64px;
  height: 64px;
  place-items: center;
  margin: 15px 0 10px;
  color: rgba(194, 207, 245, 0.28);
  background: rgba(255, 255, 255, 0.035);
  border: 1px dashed rgba(255, 255, 255, 0.12);
  border-radius: 50%;
  font-family: var(--font-mono);
  font-size: 23px;
}

.next-empty strong {
  color: rgba(237, 242, 255, 0.75);
  font-size: 12px;
}

.next-empty p {
  max-width: 230px;
  margin-top: 4px;
  color: rgba(185, 199, 236, 0.35);
  font-size: 10px;
  line-height: 1.65;
}

.next-link {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  margin-top: 11px;
  padding: 0;
  color: #a5b4fc;
  background: none;
  border: 0;
  font-size: 10.5px;
  cursor: pointer;
}

.stats-grid {
  position: relative;
  z-index: 2;
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 15px;
  margin-top: -36px;
  padding: 0 18px;
}

.dashboard-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.72fr) minmax(310px, 0.78fr);
  gap: 18px;
  margin-top: 20px;
}

.recent-panel {
  min-width: 0;
}

.text-link {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  color: #7b85a0;
  font-size: 11px;
  font-weight: 600;
  white-space: nowrap;
  transition: color 0.16s ease;
}

.text-link:hover {
  color: var(--brand);
}

.recent-body {
  padding-top: 12px;
  overflow-x: auto;
}

.recent-table {
  width: 100%;
}

.recent-table :deep(.el-table__row) {
  cursor: pointer;
}

.recent-mobile-list {
  display: flex;
  flex-direction: column;
}

.recent-mobile-item {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  padding: 12px 2px;
  text-align: left;
  background: transparent;
  border: 0;
  border-bottom: 1px solid #f1f3f8;
  cursor: pointer;
}

.recent-mobile-item:last-child {
  border-bottom: 0;
}

.recent-mobile-item:hover {
  background: #fafbff;
}

.mobile-recent-main {
  display: flex;
  min-width: 0;
  flex: 1;
  flex-direction: column;
  gap: 4px;
}

.mobile-recent-title {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.mobile-recent-title strong {
  overflow: hidden;
  color: #354057;
  font-size: 12px;
  font-weight: 620;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.mobile-recent-main > span {
  color: #a2abbd;
  font-size: 9.5px;
}

.module-cell {
  display: flex;
  align-items: center;
  gap: 9px;
}

.mini-avatar {
  display: grid;
  width: 29px;
  height: 29px;
  flex: none;
  place-items: center;
  color: #5d58cf;
  background: #f0f1fe;
  border-radius: 8px;
  font-size: 11px;
  font-weight: 700;
}

.module-cell-copy {
  display: flex;
  min-width: 0;
  flex-direction: column;
  line-height: 1.45;
}

.module-cell-copy strong {
  overflow: hidden;
  color: #2f3a52;
  font-size: 12px;
  font-weight: 600;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.module-cell-copy span {
  color: #a2aabd;
  font-size: 9.5px;
}

.trigger-text {
  color: #7f889c;
  font-size: 11px;
}

.time-cell {
  display: flex;
  flex-direction: column;
  line-height: 1.45;
}

.time-cell span {
  color: #5e6980;
  font-size: 11px;
}

.time-cell small {
  color: #a4adbf;
  font-size: 9.5px;
}

.duration-text {
  color: #8e97aa;
  font-family: var(--font-mono);
  font-size: 10px;
}

.row-arrow {
  color: #c3cad9;
  font-size: 12px;
}

.side-column {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 18px;
}

.upcoming-body {
  padding-top: 13px;
}

.upcoming-list {
  display: flex;
  flex-direction: column;
}

.upcoming-item {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  padding: 10px 6px;
  text-align: left;
  background: transparent;
  border: 0;
  border-bottom: 1px solid #f1f3f8;
  cursor: pointer;
  transition: background 0.15s ease;
}

.upcoming-item:last-child {
  border-bottom: 0;
}

.upcoming-item:hover {
  background: #fafbff;
}

.upcoming-copy {
  display: flex;
  min-width: 0;
  flex: 1;
  flex-direction: column;
  line-height: 1.45;
}

.upcoming-copy strong {
  overflow: hidden;
  color: #354057;
  font-size: 11.5px;
  font-weight: 620;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.upcoming-copy span {
  overflow: hidden;
  color: #9ba4b7;
  font-size: 9.5px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.upcoming-time {
  display: flex;
  flex: none;
  flex-direction: column;
  align-items: flex-end;
  line-height: 1.45;
}

.upcoming-time strong {
  color: #5e6980;
  font-family: var(--font-mono);
  font-size: 10px;
  font-weight: 500;
}

.upcoming-time span {
  color: #aab2c3;
  font-size: 9px;
}

.compact-empty {
  padding: 28px 16px;
}

.compact-empty .empty-state__icon {
  width: 46px;
  height: 46px;
  margin-bottom: 10px;
  border-radius: 14px;
  font-size: 19px;
}

.health-panel .panel-body {
  padding-top: 16px;
}

.health-badge {
  padding: 4px 8px;
  color: #9a7a2f;
  background: #fdf7e9;
  border-radius: 999px;
  font-size: 9px;
  font-weight: 650;
}

.health-badge.healthy {
  color: #0b8765;
  background: var(--mint-soft);
}

.health-body {
  display: flex;
  align-items: center;
  gap: 22px;
}

.ring-wrap {
  flex: none;
}

.donut {
  display: grid;
  width: 96px;
  height: 96px;
  place-items: center;
  border-radius: 50%;
  transition: background 0.4s ease;
}

.donut-inner {
  display: flex;
  width: 74px;
  height: 74px;
  align-items: center;
  justify-content: center;
  flex-direction: column;
  background: #fff;
  border-radius: 50%;
  box-shadow: 0 0 0 1px rgba(0, 0, 0, 0.02);
}

.donut-inner strong {
  color: var(--ink);
  font-size: 19px;
  font-weight: 740;
  letter-spacing: -0.03em;
  line-height: 1.1;
}

.donut-inner strong small {
  color: #9ba4b6;
  font-size: 9px;
  font-weight: 600;
}

.donut-inner span {
  color: #a3abbb;
  font-size: 8.5px;
}

.health-legend {
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 8px;
}

.legend-row {
  display: flex;
  align-items: center;
  gap: 7px;
  color: #7e889d;
  font-size: 10.5px;
}

.legend-row strong {
  margin-left: auto;
  color: #4c566e;
  font-family: var(--font-mono);
  font-size: 11px;
  font-weight: 600;
}

.legend-dot {
  width: 6px;
  height: 6px;
  border-radius: 2px;
}

.legend-dot.success {
  background: #10b981;
}

.legend-dot.failed {
  background: #f87171;
}

.legend-dot.running {
  background: #8b8bf1;
}

.health-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 24px 14px;
  color: #a0a9bb;
  border-top: 1px solid #f2f4f8;
  font-size: 9.5px;
}

.health-foot span {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

@media (max-width: 1200px) {
  .hero-content {
    grid-template-columns: minmax(0, 1.2fr) minmax(280px, 0.8fr);
    gap: 28px;
  }

  .dashboard-grid {
    grid-template-columns: minmax(0, 1.55fr) minmax(290px, 0.9fr);
  }
}

@media (max-width: 1060px) {
  .hero-content {
    grid-template-columns: 1fr;
  }

  .hero-aside {
    display: none;
  }

  .hero-band {
    padding-bottom: 66px;
  }

  .stats-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .dashboard-grid {
    grid-template-columns: 1fr;
  }

  .side-column {
    display: grid;
    grid-template-columns: 1fr 1fr;
  }
}

@media (max-width: 720px) {
  .dashboard-page {
    padding-top: 16px;
  }

  .hero-band {
    padding: 24px 22px 60px;
    border-radius: 19px;
  }

  .hero-copy h1 {
    font-size: 25px;
  }

  .hero-actions {
    flex-wrap: wrap;
  }

  .stats-grid {
    gap: 10px;
    padding: 0 8px;
    margin-top: -30px;
  }

  .stats-grid :deep(.stat-card) {
    padding: 16px;
  }

  .stats-grid :deep(.stat-card__value) {
    font-size: 26px;
  }

  .side-column {
    display: flex;
  }

  .dashboard-grid {
    margin-top: 14px;
  }
}
</style>
