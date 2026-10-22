<template>
  <div class="login-page">
    <div class="ambient ambient-one"></div>
    <div class="ambient ambient-two"></div>

    <section class="brand-panel">
      <div class="brand-panel-inner">
        <div class="brand-row">
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
          <div class="brand-copy">
            <strong>签到云台</strong>
            <small>DAILY CHECK-IN CLOUD</small>
          </div>
          <span class="brand-badge">SELF-HOSTED</span>
        </div>

        <div class="hero">
          <span class="hero-eyebrow">
            <i></i>
            YOUR ROUTINE, ON AUTOPILOT
          </span>
          <h1>让每一次签到，<br /><span>都准时发生。</span></h1>
          <p>
            模块化签到任务管理平台。上传你自己的签到模块，在网页端填写参数、
            设置随机时间窗、一键启停，然后安心把重复的事交给它。
          </p>
        </div>

        <div class="feature-grid">
          <div v-for="feature in features" :key="feature.title" class="feature">
            <span class="feature-icon">
              <el-icon><component :is="feature.icon" /></el-icon>
            </span>
            <div>
              <strong>{{ feature.title }}</strong>
              <p>{{ feature.desc }}</p>
            </div>
          </div>
        </div>

        <div class="brand-foot">
          <span><el-icon><Lock /></el-icon> 参数加密存储</span>
          <span><el-icon><Monitor /></el-icon> 数据留存于你的服务器</span>
        </div>
      </div>
    </section>

    <section class="form-panel">
      <div class="form-wrap">
        <div class="mobile-brand">
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
          <div class="brand-copy">
            <strong>签到云台</strong>
            <small>DAILY CHECK-IN CLOUD</small>
          </div>
        </div>

        <div class="form-heading">
          <span class="form-eyebrow">WELCOME BACK</span>
          <h2>登录控制台</h2>
          <p>使用管理员账号，继续打理你的每日签到。</p>
        </div>

        <el-form
          ref="formRef"
          :model="form"
          :rules="rules"
          label-position="top"
          autocomplete="off"
          class="login-form"
          @submit.prevent="submit"
        >
          <el-form-item label="用户名" prop="username">
            <el-input
              v-model="form.username"
              size="large"
              :prefix-icon="User"
              placeholder="请输入用户名"
              autocomplete="off"
              autocapitalize="off"
              spellcheck="false"
              @keyup.enter="submit"
            />
          </el-form-item>
          <el-form-item label="密码" prop="password">
            <el-input
              v-model="form.password"
              size="large"
              type="password"
              show-password
              :prefix-icon="Lock"
              placeholder="请输入密码"
              autocomplete="off"
              autocapitalize="off"
              spellcheck="false"
              @keyup.enter="submit"
            />
          </el-form-item>

          <Transition name="error-fade">
            <div v-if="errorMessage" class="login-error">
              <el-icon><CircleCloseFilled /></el-icon>
              {{ errorMessage }}
            </div>
          </Transition>

          <el-button
            type="primary"
            size="large"
            class="submit-btn"
            :loading="submitting"
            native-type="submit"
          >
            <template v-if="!submitting">
              进入控制台
              <el-icon class="submit-arrow"><Right /></el-icon>
            </template>
            <template v-else>正在验证…</template>
          </el-button>
        </el-form>



        <div class="secure-note">
          <el-icon><Lock /></el-icon>
          Cookie 会话 · 密码不可逆哈希 · AES-256-GCM 加密
        </div>
      </div>

      <footer class="form-footer">
        <span>签到云台 · Daily Check-in Platform</span>
        <span class="footer-dot"></span>
        <span>v{{ version }}</span>
      </footer>
    </section>
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  Connection,
  Key,
  Lock,
  Monitor,
  Right,
  Timer,
  User,
} from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const version = '1.0.2'

const formRef = ref(null)
const submitting = ref(false)
const errorMessage = ref('')

const form = reactive({
  username: '',
  password: '',
})

const rules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
}

const features = [
  {
    icon: Timer,
    title: '随机时间调度',
    desc: '设置时间窗与重复周期，自动随机执行',
  },
  {
    icon: Connection,
    title: '模块热插拔',
    desc: '上传或扫描模块，无需重启服务',
  },
  {
    icon: Lock,
    title: '参数加密',
    desc: '敏感信息不落明文，独立开关控制',
  },
]

function safeRedirect() {
  const target = route.query.redirect
  if (typeof target === 'string' && target.startsWith('/') && !target.startsWith('//')) {
    return target
  }
  return '/dashboard'
}

async function submit() {
  if (!formRef.value) return
  errorMessage.value = ''
  try {
    await formRef.value.validate()
  } catch {
    return
  }
  submitting.value = true
  try {
    const session = await auth.login({
      username: form.username.trim(),
      password: form.password,
    })
    if (session?.force_change_password) {
      ElMessage.warning('首次登录请先修改密码')
      router.replace('/change-password')
      return
    }
    ElMessage.success('欢迎回来')
    router.replace(safeRedirect())
  } catch (error) {
    errorMessage.value = error.message || '登录失败，请检查账号和密码'
  } finally {
    submitting.value = false
  }
}

</script>

<style scoped>
.login-page {
  position: relative;
  display: grid;
  min-height: 100vh;
  grid-template-columns: 1.06fr 0.94fr;
  overflow: hidden;
  background: #f7f8fc;
}

.ambient {
  position: absolute;
  border-radius: 50%;
  filter: blur(10px);
  pointer-events: none;
}

.ambient-one {
  top: -180px;
  right: 22%;
  width: 520px;
  height: 520px;
  background: radial-gradient(circle, rgba(99, 102, 241, 0.1), transparent 68%);
}

.ambient-two {
  right: -140px;
  bottom: -220px;
  width: 560px;
  height: 560px;
  background: radial-gradient(circle, rgba(34, 211, 238, 0.08), transparent 68%);
}

.brand-panel {
  position: relative;
  z-index: 1;
  overflow: hidden;
  color: #f4f6ff;
  background:
    radial-gradient(circle at 8% 6%, rgba(99, 102, 241, 0.42), transparent 34%),
    radial-gradient(circle at 92% 56%, rgba(34, 211, 238, 0.14), transparent 32%),
    linear-gradient(152deg, #0e1528 0%, #0a101e 54%, #090e19 100%);
}

.brand-panel::before {
  position: absolute;
  inset: 0;
  background-image: linear-gradient(rgba(255, 255, 255, 0.028) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255, 255, 255, 0.028) 1px, transparent 1px);
  background-size: 44px 44px;
  mask-image: radial-gradient(ellipse at 50% 30%, #000, transparent 78%);
  content: "";
}

.brand-panel::after {
  position: absolute;
  top: 90px;
  right: -130px;
  width: 380px;
  height: 380px;
  border: 1px solid rgba(139, 143, 255, 0.12);
  border-radius: 50%;
  box-shadow: 0 0 0 50px rgba(139, 143, 255, 0.025),
    0 0 0 100px rgba(139, 143, 255, 0.018);
  content: "";
}

.brand-panel-inner {
  position: relative;
  z-index: 2;
  display: flex;
  max-width: 690px;
  min-height: 100vh;
  flex-direction: column;
  justify-content: center;
  margin-left: auto;
  padding: 42px 58px 30px;
}

.brand-row {
  display: flex;
  align-items: center;
  gap: 11px;
}

.brand-mark {
  display: grid;
  width: 40px;
  height: 40px;
  flex: none;
  place-items: center;
  color: #fff;
  background: linear-gradient(140deg, #7060f5, #4f46e5 58%, #22d3ee);
  border: 1px solid rgba(255, 255, 255, 0.2);
  border-radius: 12px;
  box-shadow: 0 10px 28px rgba(83, 69, 230, 0.4);
}

.brand-mark svg {
  width: 26px;
  height: 26px;
}

.brand-copy {
  display: flex;
  flex-direction: column;
  gap: 1px;
  line-height: 1.3;
}

.brand-copy strong {
  color: #fff;
  font-size: 16px;
  font-weight: 720;
  letter-spacing: 0.03em;
}

.brand-copy small {
  color: rgba(200, 210, 255, 0.4);
  font-size: 8px;
  font-weight: 700;
  letter-spacing: 0.18em;
}

.brand-badge {
  margin-left: auto;
  padding: 5px 9px;
  color: rgba(192, 204, 255, 0.55);
  border: 1px solid rgba(161, 177, 255, 0.16);
  border-radius: 999px;
  font-family: var(--font-mono);
  font-size: 8.5px;
  letter-spacing: 0.12em;
}

.hero {
  margin-top: clamp(60px, 9vh, 104px);
}

.hero-eyebrow {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  color: #8f9bbd;
  font-size: 9.5px;
  font-weight: 700;
  letter-spacing: 0.19em;
}

.hero-eyebrow i {
  width: 5px;
  height: 5px;
  background: #34d399;
  border-radius: 50%;
  box-shadow: 0 0 10px rgba(52, 211, 153, 0.8);
}

.hero h1 {
  margin-top: 17px;
  font-size: clamp(38px, 4.1vw, 58px);
  font-weight: 760;
  letter-spacing: -0.045em;
  line-height: 1.16;
}

.hero h1 span {
  color: transparent;
  background: linear-gradient(100deg, #a5b4fc 0%, #7dd3fc 52%, #6ee7b7 100%);
  -webkit-background-clip: text;
  background-clip: text;
}

.hero > p {
  max-width: 455px;
  margin-top: 22px;
  color: rgba(198, 208, 238, 0.55);
  font-size: 13.5px;
  line-height: 1.85;
}

.feature-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 16px;
  margin-top: 38px;
}

.feature {
  display: flex;
  align-items: flex-start;
  gap: 9px;
}

.feature-icon {
  display: grid;
  width: 30px;
  height: 30px;
  flex: none;
  place-items: center;
  color: #a7b2ff;
  background: rgba(129, 140, 248, 0.09);
  border: 1px solid rgba(129, 140, 248, 0.14);
  border-radius: 9px;
  font-size: 14px;
}

.feature strong {
  display: block;
  color: rgba(240, 244, 255, 0.88);
  font-size: 11.5px;
  font-weight: 600;
  line-height: 1.5;
}

.feature p {
  margin-top: 2px;
  color: rgba(184, 196, 229, 0.38);
  font-size: 10px;
  line-height: 1.55;
}

.brand-foot {
  display: flex;
  gap: 22px;
  margin-top: clamp(36px, 5vh, 56px);
  color: rgba(190, 202, 236, 0.27);
  font-size: 9.5px;
  letter-spacing: 0.03em;
}

.brand-foot span {
  display: inline-flex;
  align-items: center;
  gap: 5px;
}

.form-panel {
  position: relative;
  z-index: 1;
  display: flex;
  min-height: 100vh;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 42px 36px 28px;
  background:
    radial-gradient(circle at 88% 8%, rgba(99, 102, 241, 0.055), transparent 26%),
    #f8f9fd;
}

.form-wrap {
  width: min(100%, 392px);
}

.mobile-brand {
  display: none;
}

.form-heading {
  margin-bottom: 28px;
}

.form-eyebrow {
  color: #929cba;
  font-size: 9.5px;
  font-weight: 750;
  letter-spacing: 0.2em;
}

.form-heading h2 {
  margin-top: 9px;
  color: #161f35;
  font-size: 30px;
  font-weight: 760;
  letter-spacing: -0.035em;
}

.form-heading p {
  margin-top: 7px;
  color: #8c96ab;
  font-size: 12.5px;
}

.login-form :deep(.el-form-item) {
  margin-bottom: 20px;
}

.login-form :deep(.el-form-item__label) {
  padding-bottom: 6px;
  color: #5a6680;
  font-size: 12px;
}

.login-form :deep(.el-input__wrapper) {
  padding: 2px 14px;
  background: #fff;
  border-radius: 11px;
  box-shadow: 0 0 0 1px #e3e7f0 inset, 0 1px 2px rgba(24, 35, 65, 0.02);
}

.login-form :deep(.el-input__inner) {
  height: 44px;
  font-size: 13px;
}

.login-form :deep(.el-input__prefix) {
  color: #9ba4b8;
}

.submit-btn {
  width: 100%;
  height: 48px;
  margin-top: 4px;
  border-radius: 11px;
  font-size: 13.5px;
  font-weight: 650;
  letter-spacing: 0.01em;
  box-shadow: 0 12px 28px rgba(86, 84, 214, 0.26);
}

.submit-arrow {
  margin-left: 6px;
  font-size: 14px;
}

.login-error {
  display: flex;
  align-items: flex-start;
  gap: 7px;
  margin-bottom: 15px;
  padding: 10px 12px;
  color: #c13535;
  background: #fdf0f0;
  border: 1px solid #f8dfdf;
  border-radius: 9px;
  font-size: 12px;
  line-height: 1.55;
}

.error-fade-enter-active,
.error-fade-leave-active {
  transition: opacity 0.18s ease, transform 0.18s ease;
}

.error-fade-enter-from,
.error-fade-leave-to {
  opacity: 0;
  transform: translateY(-4px);
}



.hint-icon {
  display: grid;
  width: 26px;
  height: 26px;
  flex: none;
  place-items: center;
  color: #6366f1;
  background: #eef0ff;
  border-radius: 8px;
  font-size: 13px;
}







.secure-note {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  margin-top: 22px;
  color: #a2aabc;
  font-size: 9.5px;
}

.form-footer {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 42px;
  color: #aab2c5;
  font-size: 9.5px;
}

.footer-dot {
  width: 3px;
  height: 3px;
  background: #c7cddd;
  border-radius: 50%;
}

@media (max-width: 1060px) {
  .login-page {
    grid-template-columns: 1fr 1fr;
  }

  .brand-panel-inner {
    padding: 38px 40px 28px;
  }

  .feature-grid {
    grid-template-columns: 1fr;
    gap: 12px;
  }
}

@media (max-width: 860px) {
  .login-page {
    display: block;
  }

  .brand-panel {
    display: none;
  }

  .form-panel {
    min-height: 100vh;
    padding: 34px 22px 24px;
    background:
      radial-gradient(circle at 50% -10%, rgba(99, 102, 241, 0.14), transparent 38%),
      #f8f9fd;
  }

  .form-wrap {
    width: min(100%, 410px);
  }

  .mobile-brand {
    display: flex;
    align-items: center;
    gap: 10px;
    margin-bottom: 40px;
  }

  .mobile-brand .brand-copy strong {
    color: var(--ink);
  }

  .mobile-brand .brand-copy small {
    color: #a0a8bc;
  }

  .form-heading {
    margin-bottom: 24px;
  }

  .form-heading h2 {
    font-size: 27px;
  }

  .form-footer {
    margin-top: 34px;
  }
}
</style>
