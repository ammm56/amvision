<script setup lang="ts">
import { useRouter } from 'vue-router'
import { LogOut, ShieldCheck } from '@lucide/vue'
import { useI18n } from 'vue-i18n'

import ConnectionStatus from './ConnectionStatus.vue'
import LocaleSwitcher from './LocaleSwitcher.vue'
import ProjectSwitcher from './ProjectSwitcher.vue'
import ThemeToggle from './ThemeToggle.vue'
import { useSessionStore } from '@/app/stores/session.store'
import Button from '@/shared/ui/components/Button.vue'

const router = useRouter()
const { t } = useI18n()
const sessionStore = useSessionStore()

async function logout(): Promise<void> {
  await sessionStore.logout()
  await router.replace('/login')
}
</script>

<template>
  <header class="app-topbar">
    <ProjectSwitcher />
    <div class="app-topbar__right">
      <ConnectionStatus />
      <LocaleSwitcher />
      <ThemeToggle />
      <span class="credential-pill">
        <ShieldCheck :size="15" />
        {{ sessionStore.credentialKind || t('common.none') }}
      </span>
      <span class="user-label">{{ sessionStore.displayName || t('auth.notSignedIn') }}</span>
      <Button variant="ghost" size="sm" @click="logout">
        <LogOut :size="16" />
        {{ t('auth.logout') }}
      </Button>
    </div>
  </header>
</template>