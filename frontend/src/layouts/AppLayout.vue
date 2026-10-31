<template>
  <div class="app-shell">
    <aside class="sidebar">
      <router-link to="/dashboard" class="brand">
        <span class="brand-mark">
          <svg viewBox="0 0 32 32" aria-hidden="true">
            <path
              d="M8.5 16.6 13.4 21.5 23.6 10.7"
              fill="none"
              stroke="currentColor"
              stroke-width="3.2"
              stroke-linecap="round"
              stroke-linejoin="round"
            />
          </svg>
        </span>
        <span class="brand-copy">
          <strong>签到云台</strong>
          <small>CHECK-IN CLOUD</small>
        </span>
      </router-link>

      <nav class="navigation" aria-label="主导航">
        <span class="nav-caption">工作台</span>
        <router-link
          v-for="item in navItems"
          :key="item.name"
          :to="{ name: item.name }"
          class="nav-item"
          :class="{ active: isActive(item) }"
        >
          <el-icon class="nav-icon"><component :is="item.icon" /></el-icon>
          <span>{{ item.label }}</span>
        </router-link>
      </nav>

      <div class="sidebar-bottom">
        <div class="scheduler-card">
          <div class="scheduler-head">
            <span class="scheduler-dot" :class="{ online: isOnline }"></span>
            <span>{{ isOnline ? '调度服务运行中' : '正在连接服务' }}</span>
          </div>
          <p>{{ appStore.meta?.timezone || 'Asia/Shanghai' }} · 随机时间调度</p>
        </div>
        <div class="sidebar-foot">
          <span>Self-hosted</span>
          <span class="version">v{{ appStore.meta?.version || '1.0.6' }}</span>
        </div>
      </div>
    </aside>

    <div class="main">
      <header class="topbar">
        <div class="topbar-left">
          <button
            type="button"
            class="mobile-menu"
            aria-label="打开菜单"
            @click="mobileNavOpen = true"
          >
            <span class="hamburger"><i></i><i></i><i></i></span>
          </button>
          <div class="breadcrumb">
            <span v-if="route.meta.parent" class="crumb-parent">
              {{ route.meta.parent }}
              <span class="crumb-divider">/</span>
            </span>
            <span class="crumb-current">{{ route.meta.title || '控制台' }}</span>
          </div>
        </div>

        <div class="topbar-right">
          <span class="date-chip">{{ todayLabel() }}</span>
          <span class="status-chip" :class="{ offline: !isOnline }">
            <i></i>
            {{ isOnline ? 'SYSTEM ONLINE' : 'CONNECTING' }}
          </span>
          <el-dropdown trigger="click" @command="handleUserCommand">
            <button type="button" class="user-trigger">
              <span class="avatar">{{ initialOf(auth.user?.username) }}</span>
              <span class="user-name">{{ auth.user?.username || 'admin' }}</span>
              <el-icon class="chevron"><ArrowDown /></el-icon>
            </button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="settings">
                  <el-icon><Setting /></el-icon>
                  用户设置
                </el-dropdown-item>
                <el-dropdown-item command="logout" divided>
                  <el-icon><SwitchButton /></el-icon>
                  退出登录
                </el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </header>

      <main class="content">
        <router-view v-slot="{ Component }">
          <transition name="route-fade" mode="out-in">
            <component :is="Component" />
          </transition>
        </router-view>
      </main>
    </div>

    <el-drawer
      v-model="mobileNavOpen"
      direction="ltr"
      size="268px"
      :with-header="false"
      class="mobile-nav"
    >
      <div class="mobile-nav-inner">
        <router-link to="/dashboard" class="brand" @click="mobileNavOpen = false">
          <span class="brand-mark">
            <svg viewBox="0 0 32 32" aria-hidden="true">
              <path
                d="M8.5 16.6 13.4 21.5 23.6 10.7"
                fill="none"
                stroke="currentColor"
                stroke-width="3.2"
                stroke-linecap="round"
                stroke-linejoin="round"
              />
            </svg>
          </span>
          <span class="brand-copy">
            <strong>签到云台</strong>
            <small>CHECK-IN CLOUD</small>
          </span>
        </router-link>
        <nav class="navigation" aria-label="移动端导航">
          <span class="nav-caption">工作台</span>
          <router-link
            v-for="item in navItems"
            :key="item.name"
            :to="{ name: item.name }"
            class="nav-item"
            :class="{ active: isActive(item) }"
            @click="mobileNavOpen = false"
          >
            <el-icon class="nav-icon"><component :is="item.icon" /></el-icon>
            <span>{{ item.label }}</span>
          </router-link>
        </nav>
        <div class="mobile-foot">
          <span class="scheduler-dot" :class="{ online: isOnline }"></span>
          {{ isOnline ? '调度服务运行中' : '正在连接服务' }}
        </div>
      </div>
    </el-drawer>

  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  ArrowDown,
  Grid,
  Odometer,
  Reading,
  Setting,
  SwitchButton,
  Tickets,
  Promotion,
  Document,
} from '@element-plus/icons-vue'
import { useAppStore } from '@/stores/app'
import { useAuthStore } from '@/stores/auth'
import { initialOf, todayLabel } from '@/utils/format'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const appStore = useAppStore()

const mobileNavOpen = ref(false)
let healthTimer = null

const navItems = [
  { name: 'dashboard', label: '运行概览', icon: Odometer },
  { name: 'modules', label: '签到模块', icon: Grid },
  { name: 'logs', label: '执行记录', icon: Tickets },
  { name: 'push-center', label: '推送中心', icon: Promotion },
  { name: 'system-logs', label: '系统日志', icon: Document },
  { name: 'settings', label: '用户设置', icon: Setting },
  { name: 'guide', label: '开发指南', icon: Reading },
]

const isOnline = computed(() => Boolean(appStore.health?.scheduler_running))

function isActive(item) {
  if (item.name === 'modules') {
    return route.name === 'modules' || route.name === 'module-detail'
  }
  return route.name === item.name
}

async function handleUserCommand(command) {
  if (command === 'settings') {
    router.push({ name: 'settings' })
  } else if (command === 'logout') {
    try {
      await ElMessageBox.confirm('确定要退出当前账号吗？', '退出登录', {
        confirmButtonText: '退出',
        cancelButtonText: '取消',
        type: 'warning',
      })
    } catch {
      return
    }
    await auth.logout()
    router.replace({ name: 'login' })
    ElMessage.success('已安全退出')
  }
}

onMounted(async () => {
  await Promise.all([appStore.fetchMeta(), appStore.fetchHealth()])
  healthTimer = window.setInterval(() => {
    appStore.fetchHealth()
  }, 30000)
})

onBeforeUnmount(() => {
  if (healthTimer) window.clearInterval(healthTimer)
})
</script>

<style scoped>
.app-shell {
  display: flex;
  min-height: 100vh;
  background:
    radial-gradient(circle at 92% -10%, rgba(99, 102, 241, 0.08), transparent 32%),
    var(--bg);
}

.sidebar {
  position: sticky;
  top: 0;
  display: flex;
  width: 248px;
  height: 100vh;
  flex: none;
  flex-direction: column;
  padding: 24px 14px 18px;
  overflow: hidden;
  color: var(--sidebar-ink);
  background:
    radial-gradient(circle at 20% -5%, rgba(99, 102, 241, 0.38), transparent 34%),
    radial-gradient(circle at 100% 15%, rgba(34, 211, 238, 0.1), transparent 30%),
    linear-gradient(180deg, #0d1426 0%, #0a0f1d 100%);
}

.sidebar::before {
  position: absolute;
  top: 0;
  right: 0;
  width: 140px;
  height: 180px;
  background-image: radial-gradient(rgba(255, 255, 255, 0.16) 1px, transparent 1px);
  background-size: 14px 14px;
  opacity: 0.35;
  mask-image: linear-gradient(to bottom left, #000, transparent 75%);
  content: "";
  pointer-events: none;
}

.brand {
  position: relative;
  display: flex;
  align-items: center;
  gap: 11px;
  padding: 5px 10px;
  color: #fff;
}

.brand:hover {
  color: #fff;
}

.brand-mark {
  display: grid;
  width: 38px;
  height: 38px;
  flex: none;
  place-items: center;
  color: #fff;
  background: linear-gradient(140deg, #6d5df2, #4f46e5 55%, #22d3ee);
  border: 1px solid rgba(255, 255, 255, 0.16);
  border-radius: 12px;
  box-shadow: 0 8px 22px rgba(76, 65, 225, 0.35);
}

.brand-mark svg {
  width: 25px;
  height: 25px;
}

.brand-copy {
  display: flex;
  flex-direction: column;
  gap: 1px;
  line-height: 1.25;
}

.brand-copy strong {
  font-size: 16px;
  font-weight: 720;
  letter-spacing: 0.02em;
}

.brand-copy small {
  color: rgba(208, 217, 255, 0.45);
  font-size: 8px;
  font-weight: 700;
  letter-spacing: 0.17em;
}

.navigation {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-top: 36px;
}

.nav-caption {
  padding: 0 12px 8px;
  color: rgba(194, 206, 245, 0.36);
  font-size: 9.5px;
  font-weight: 700;
  letter-spacing: 0.18em;
}

.nav-item {
  position: relative;
  display: flex;
  align-items: center;
  gap: 11px;
  height: 43px;
  padding: 0 12px;
  color: rgba(216, 224, 250, 0.62);
  border: 1px solid transparent;
  border-radius: 11px;
  font-size: 13px;
  font-weight: 550;
  transition: all 0.18s ease;
}

.nav-item:hover {
  color: #fff;
  background: rgba(255, 255, 255, 0.05);
}

.nav-item.active {
  color: #fff;
  background: linear-gradient(
    90deg,
    rgba(99, 102, 241, 0.28),
    rgba(99, 102, 241, 0.08)
  );
  border-color: rgba(139, 140, 255, 0.18);
  box-shadow: inset 2px 0 0 #8b8bff;
}

.nav-icon {
  font-size: 17px;
  opacity: 0.85;
}

.nav-item.active .nav-icon {
  color: #b9b8ff;
  opacity: 1;
}


.sidebar-bottom {
  margin-top: auto;
}

.scheduler-card {
  margin: 0 2px;
  padding: 13px 13px 11px;
  background: rgba(255, 255, 255, 0.035);
  border: 1px solid rgba(255, 255, 255, 0.07);
  border-radius: 12px;
}

.scheduler-head {
  display: flex;
  align-items: center;
  gap: 7px;
  color: rgba(231, 237, 255, 0.78);
  font-size: 11px;
  font-weight: 600;
}

.scheduler-dot {
  width: 6px;
  height: 6px;
  flex: none;
  background: #f59e0b;
  border-radius: 50%;
  box-shadow: 0 0 0 3px rgba(245, 158, 11, 0.12);
}

.scheduler-dot.online {
  background: #34d399;
  box-shadow: 0 0 0 3px rgba(52, 211, 153, 0.12), 0 0 8px rgba(52, 211, 153, 0.7);
}

.scheduler-card p {
  margin-top: 5px;
  color: rgba(196, 207, 241, 0.35);
  font-size: 9.5px;
}

.sidebar-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 12px 0;
  color: rgba(194, 206, 245, 0.25);
  font-size: 9.5px;
  letter-spacing: 0.06em;
}

.version {
  font-family: var(--font-mono);
}

.main {
  display: flex;
  min-width: 0;
  flex: 1;
  flex-direction: column;
}

.topbar {
  position: sticky;
  top: 0;
  z-index: 20;
  display: flex;
  height: 72px;
  flex: none;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  padding: 0 34px;
  background: rgba(244, 246, 251, 0.82);
  border-bottom: 1px solid rgba(226, 231, 240, 0.8);
  backdrop-filter: blur(14px);
}

.topbar-left,
.topbar-right {
  display: flex;
  align-items: center;
  gap: 12px;
}

.breadcrumb {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12.5px;
}

.crumb-parent {
  color: #98a2b6;
}

.crumb-divider {
  padding: 0 3px;
  color: #c3cad8;
}

.crumb-current {
  color: var(--ink-soft);
  font-weight: 650;
}

.date-chip {
  color: #8690a5;
  font-size: 11.5px;
  white-space: nowrap;
}

.status-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 9px;
  color: #0e8c68;
  background: rgba(16, 185, 129, 0.07);
  border: 1px solid rgba(16, 185, 129, 0.14);
  border-radius: 999px;
  font-family: var(--font-mono);
  font-size: 8.5px;
  font-weight: 700;
  letter-spacing: 0.05em;
  white-space: nowrap;
}

.status-chip i {
  width: 5px;
  height: 5px;
  background: #10b981;
  border-radius: 50%;
}

.status-chip.offline {
  color: #b2731a;
  background: rgba(245, 158, 11, 0.08);
  border-color: rgba(245, 158, 11, 0.18);
}

.status-chip.offline i {
  background: #f59e0b;
}

.user-trigger {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 7px 4px 4px;
  color: var(--ink-soft);
  background: transparent;
  border: 1px solid transparent;
  border-radius: 999px;
  font-size: 12.5px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.16s ease;
}

.user-trigger:hover {
  background: #fff;
  border-color: var(--line);
  box-shadow: var(--shadow-sm);
}

.avatar {
  display: grid;
  width: 31px;
  height: 31px;
  place-items: center;
  color: #fff;
  background: linear-gradient(140deg, #6366f1, #8b5cf6);
  border: 2px solid #fff;
  border-radius: 50%;
  box-shadow: 0 2px 8px rgba(99, 102, 241, 0.28);
  font-size: 12px;
  font-weight: 700;
}

.chevron {
  color: #a3abbd;
  font-size: 11px;
}

.mobile-menu {
  display: none;
  width: 34px;
  height: 34px;
  place-items: center;
  color: var(--ink-soft);
  background: #fff;
  border: 1px solid var(--line);
  border-radius: 9px;
  cursor: pointer;
}

.hamburger {
  display: flex;
  width: 14px;
  flex-direction: column;
  gap: 3px;
}

.hamburger i {
  display: block;
  width: 100%;
  height: 1.6px;
  background: currentColor;
  border-radius: 999px;
}

.hamburger i:nth-child(2) {
  width: 72%;
}

.content {
  flex: 1;
  min-width: 0;
}

.mobile-nav-inner {
  display: flex;
  min-height: 100vh;
  flex-direction: column;
  padding: 24px 14px;
  color: var(--sidebar-ink);
  background: linear-gradient(180deg, #0d1426, #0a0f1d);
}

.mobile-foot {
  display: flex;
  align-items: center;
  gap: 7px;
  margin-top: auto;
  padding: 12px;
  color: rgba(211, 221, 250, 0.55);
  border-top: 1px solid rgba(255, 255, 255, 0.06);
  font-size: 11px;
}


@media (max-width: 1200px) {
  .date-chip {
    display: none;
  }
}

@media (max-width: 960px) {
  .sidebar {
    display: none;
  }

  .topbar {
    height: 64px;
    padding: 0 18px;
  }

  .mobile-menu {
    display: grid;
  }

  .status-chip {
    display: none;
  }

  .user-name {
    display: none;
  }

  .content :deep(.page-shell) {
    padding-top: 20px;
  }
}

@media (max-width: 560px) {
  .topbar {
    padding: 0 14px;
  }

  .topbar-right {
    gap: 4px;
  }

  .breadcrumb {
    font-size: 12px;
  }
}
</style>
