<template>
  <section class="startup-view">
    <img class="brand-mark brand-mark--large" src="/favicon.svg" alt="AM" />
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

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Loader2, RotateCcw } from '@lucide/vue'
import { useI18n } from 'vue-i18n'

import { useProjectStore } from '@/app/stores/project.store'
import { useFeedbackStore } from '@/app/stores/feedback.store'
import { usePreferencesStore } from '@/app/stores/preferences.store'
import { useSessionStore } from '@/app/stores/session.store'
import { resolvePostAuthenticationRoute } from '@/app/startup/startup-route'
import Button from '@/shared/ui/components/Button.vue'
import InlineError from '@/shared/ui/feedback/InlineError.vue'

const route = useRoute()
const router = useRouter()
const sessionStore = useSessionStore()
const projectStore = useProjectStore()
const preferencesStore = usePreferencesStore()
const feedbackStore = useFeedbackStore()
const { t } = useI18n()
const starting = ref(false)

async function start(): Promise<void> {
  starting.value = true
  await sessionStore.initializeSession()
  if (sessionStore.isAuthenticated) {
    await projectStore.loadProjects({ includeSummary: false })
    const destination = await resolvePostAuthenticationRoute({
      user: sessionStore.currentUser,
      explicitRedirect: route.query.redirect,
      preference: preferencesStore.startupPage,
    })
    if (destination.resetPreference) {
      preferencesStore.resetStartupPage()
      feedbackStore.warning(t('startupPage.targetReset'))
    }
    await router.replace(destination.path)
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
