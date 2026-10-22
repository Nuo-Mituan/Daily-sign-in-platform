import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { APP_NAME } from '@/utils/constants'

const routes = [
  {
    path: '/login',
    name: 'login',
    component: () => import('@/views/LoginView.vue'),
    meta: { title: '登录', guestOnly: true },
  },
  {
    path: '/change-password',
    name: 'change-password',
    component: () => import('@/views/ChangePasswordView.vue'),
    meta: { requiresAuth: true, title: '修改密码' },
  },
  {
    path: '/',
    component: () => import('@/layouts/AppLayout.vue'),
    meta: { requiresAuth: true },
    children: [
      { path: '', redirect: '/dashboard' },
      {
        path: 'dashboard',
        name: 'dashboard',
        component: () => import('@/views/DashboardView.vue'),
        meta: { title: '运行概览' },
      },
      {
        path: 'modules',
        name: 'modules',
        component: () => import('@/views/ModulesView.vue'),
        meta: { title: '签到模块' },
      },
      {
        path: 'modules/:id',
        name: 'module-detail',
        component: () => import('@/views/ModuleDetailView.vue'),
        meta: { title: '模块配置', parent: '签到模块' },
      },
      {
        path: 'logs',
        name: 'logs',
        component: () => import('@/views/LogsView.vue'),
        meta: { title: '执行记录' },
      },
      {
        path: 'push-center',
        name: 'push-center',
        component: () => import('@/views/PushCenterView.vue'),
        meta: { title: '推送中心' },
      },
      {
        path: 'system-logs',
        name: 'system-logs',
        component: () => import('@/views/SystemLogsView.vue'),
        meta: { title: '系统日志' },
      },
      {
        path: 'settings',
        name: 'settings',
        component: () => import('@/views/SettingsView.vue'),
        meta: { title: '用户设置' },
      },
      {
        path: 'guide',
        name: 'guide',
        component: () => import('@/views/GuideView.vue'),
        meta: { title: '开发指南' },
      },
    ],
  },
  {
    path: '/:pathMatch(.*)*',
    redirect: '/dashboard',
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior() {
    return { top: 0 }
  },
})

router.beforeEach(async (to) => {
  const auth = useAuthStore()
  document.title = `${to.meta.title || '控制台'} · ${APP_NAME}`

  if (!to.meta.requiresAuth) {
    if (to.meta.guestOnly) {
      if (!auth.user) {
        await auth.fetchSession()
      }
      if (auth.user) {
        return { name: 'dashboard' }
      }
    }
    return true
  }

  if (!auth.user) {
    const current = await auth.fetchSession()
    if (!current) {
      return { name: 'login', query: { redirect: to.fullPath } }
    }
  }

  if (auth.mustChangePassword && to.name !== 'change-password') {
    return { name: 'change-password' }
  }
  if (to.name === 'change-password' && !auth.mustChangePassword) {
    return { name: 'dashboard' }
  }

  return true
})

export default router
