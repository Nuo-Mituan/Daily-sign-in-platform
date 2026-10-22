<template>
  <div class="change-page">
    <el-card class="change-card">
      <h2>修改初始密码</h2>
      <p class="hint">首次登录必须修改密码后才能继续使用系统。</p>
      <el-form ref="formRef" :model="form" :rules="rules" label-position="top">
        <el-form-item label="当前密码" prop="old_password">
          <el-input v-model="form.old_password" type="password" show-password />
        </el-form-item>
        <el-form-item label="新密码" prop="new_password">
          <el-input v-model="form.new_password" type="password" show-password />
        </el-form-item>
        <el-form-item label="确认新密码" prop="confirm_password">
          <el-input v-model="form.confirm_password" type="password" show-password />
        </el-form-item>
        <el-button type="primary" :loading="submitting" class="submit" @click="submit">
          修改密码
        </el-button>
      </el-form>
    </el-card>
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const router = useRouter()
const formRef = ref(null)
const submitting = ref(false)
const form = reactive({ old_password: '', new_password: '', confirm_password: '' })
const rules = {
  old_password: [{ required: true, message: '请输入当前密码', trigger: 'blur' }],
  new_password: [
    { required: true, message: '请输入新密码', trigger: 'blur' },
    { min: 6, message: '新密码长度不能少于 6 位', trigger: 'blur' },
  ],
  confirm_password: [
    {
      validator: (_rule, value, callback) => {
        if (value !== form.new_password) callback(new Error('两次输入的密码不一致'))
        else callback()
      },
      trigger: 'blur',
    },
  ],
}

async function submit() {
  try {
    await formRef.value.validate()
  } catch {
    return
  }
  submitting.value = true
  try {
    await auth.changePassword({
      old_password: form.old_password,
      new_password: form.new_password,
    })
    ElMessage.success('密码修改成功，请重新登录')
    auth.clearSession()
    router.replace({ name: 'login' })
  } catch {
    // HTTP layer reports errors.
  } finally {
    submitting.value = false
  }
}
</script>

<style scoped>
.change-page { display: grid; place-items: center; min-height: 100vh; background: #f7f8fc; padding: 24px; }
.change-card { width: min(420px, 100%); }
.hint { color: #667085; margin: 0 0 20px; }
.submit { width: 100%; margin-top: 8px; }
</style>
