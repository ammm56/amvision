<template>
  <form class="auth-form" @submit.prevent="submitLogin">
    <header>
      <p class="page-kicker">{{ t('auth.localAuth') }}</p>
      <h1>{{ t('auth.login') }}</h1>
      <p>{{ t('auth.loginIntro') }}</p>
    </header>

    <InlineError :message="errorMessage || sessionStore.lastAuthError" />

    <label>
      <span>{{ t('auth.username') }}</span>
      <input v-model="username" autocomplete="username" />
    </label>
    <label>
      <span>{{ t('auth.password') }}</span>
      <input v-model="password" type="password" autocomplete="current-password" />
    </label>

    <Button variant="primary" type="submit" :disabled="submitting">
      <LogIn :size="16" />
      {{ submitting ? t('auth.loggingIn') : t('auth.login') }}
    </Button>
  </form>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { LogIn } from '@lucide/vue'
import { useI18n } from 'vue-i18n'

import { useProjectStore } from '@/app/stores/project.store'
import { useSessionStore } from '@/app/stores/session.store'
import { getRuntimeConfig } from '@/platform/runtime/runtime-config'
import Button from '@/shared/ui/components/Button.vue'
import InlineError from '@/shared/ui/feedback/InlineError.vue'

const route = useRoute()
const router = useRouter()
const sessionStore = useSessionStore()
const projectStore = useProjectStore()
const { t } = useI18n()

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
    errorMessage.value = error instanceof Error ? error.message : t('auth.loginFailed')
  } finally {
    submitting.value = false
  }
}
</script>