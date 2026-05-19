import { createApp } from 'vue'
import { createPinia } from 'pinia'

import App from './App.vue'
import { createAppRouter } from './router'
import { registerRouterGuards } from './router/guards'
import { usePreferencesStore } from './stores/preferences.store'
import { useSessionStore } from './stores/session.store'
import { installI18n } from '@/platform/i18n'
import { configureHttpClient } from '@/shared/api/http-client'
import { loadRuntimeConfig } from '@/platform/runtime/runtime-config'

export async function bootstrapApplication(): Promise<void> {
  await loadRuntimeConfig()

  const app = createApp(App)
  const pinia = createPinia()
  const router = createAppRouter()

  app.use(pinia)
  usePreferencesStore(pinia).initializePreferences()
  installI18n(app)

  configureHttpClient({
    getAccessToken: () => useSessionStore(pinia).accessToken,
    refreshAccessToken: () => useSessionStore(pinia).refreshAccessToken(),
    onUnauthorized: () => useSessionStore(pinia).clearForAuthFailure(),
  })

  registerRouterGuards(router, pinia)
  app.use(router)
  await router.isReady()
  app.mount('#app')
}