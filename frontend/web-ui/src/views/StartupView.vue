<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Loader2, RotateCcw } from '@lucide/vue'
import { useI18n } from 'vue-i18n'

import { useProjectStore } from '@/app/stores/project.store'
import { useSessionStore } from '@/app/stores/session.store'
import Button from '@/shared/ui/components/Button.vue'
import InlineError from '@/shared/ui/feedback/InlineError.vue'

const route = useRoute()
const router = useRouter()
const sessionStore = useSessionStore()
const projectStore = useProjectStore()
const { t } = useI18n()
const starting = ref(false)

async function start(): Promise<void> {
  starting.value = true
  await sessionStore.initializeSession()
  if (sessionStore.isAuthenticated) {
    await projectStore.loadProjects()
    const redirect = typeof route.query.redirect === 'string' ? route.query.redirect : '/projects'
    await router.replace(redirect)
  } else if (sessionStore.loginState === 'offline') {
    starting.value = false
  } else {
    await router.replace('/login')
  }
}

onMounted(() => {
  void start()
})
</script>

<template>
  <section class="startup-view">
    <span class="brand-mark brand-mark--large">AM</span>
    <h1>{{ t('common.appName') }}</h1>
    <p>{{ t('startup.checkingSession') }}</p>
    <div class="startup-view__status">
      <Loader2 v-if="starting" class="spin" :size="20" />
      <span>{{ sessionStore.loginState }}</span>
    </div>
    <InlineError :message="sessionStore.lastAuthError" />
    <Button v-if="sessionStore.loginState === 'offline'" variant="primary" @click="start">
      <RotateCcw :size="16" />
      {{ t('common.retry') }}
    </Button>
  </section>
</template>