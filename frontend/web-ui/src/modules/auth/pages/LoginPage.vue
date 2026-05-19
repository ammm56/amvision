<script setup lang="ts">
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { LogIn } from '@lucide/vue'

import { useProjectStore } from '@/app/stores/project.store'
import { useSessionStore } from '@/app/stores/session.store'
import { getRuntimeConfig } from '@/platform/runtime/runtime-config'
import Button from '@/shared/ui/components/Button.vue'
import InlineError from '@/shared/ui/feedback/InlineError.vue'

const route = useRoute()
const router = useRouter()
const sessionStore = useSessionStore()
const projectStore = useProjectStore()

const username = ref(getRuntimeConfig().auth.defaultUsername)
const password = ref('')
const submitting = ref(false)
const errorMessage = ref<string | null>(null)

async function submitLogin(): Promise<void> {
  submitting.value = true
  errorMessage.value = null
  try {
    await sessionStore.login({ username: username.value, password: password.value })
    await projectStore.loadProjects()
    const redirect = typeof route.query.redirect === 'string' ? route.query.redirect : '/projects'
    await router.replace(redirect)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '登录失败'
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <form class="auth-form" @submit.prevent="submitLogin">
    <header>
      <p class="page-kicker">Local Auth</p>
      <h1>登录</h1>
      <p>本机已记录退出状态，需要使用本地账号重新进入。</p>
    </header>

    <InlineError :message="errorMessage || sessionStore.lastAuthError" />

    <label>
      <span>用户名</span>
      <input v-model="username" autocomplete="username" />
    </label>
    <label>
      <span>密码</span>
      <input v-model="password" type="password" autocomplete="current-password" />
    </label>

    <Button variant="primary" type="submit" :disabled="submitting">
      <LogIn :size="16" />
      {{ submitting ? '登录中' : '登录' }}
    </Button>
  </form>
</template>