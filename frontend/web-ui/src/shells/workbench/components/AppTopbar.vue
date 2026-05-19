<script setup lang="ts">
import { useRouter } from 'vue-router'
import { LogOut, ShieldCheck } from '@lucide/vue'

import ConnectionStatus from './ConnectionStatus.vue'
import ProjectSwitcher from './ProjectSwitcher.vue'
import { useSessionStore } from '@/app/stores/session.store'
import Button from '@/shared/ui/components/Button.vue'

const router = useRouter()
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
      <span class="credential-pill">
        <ShieldCheck :size="15" />
        {{ sessionStore.credentialKind || 'none' }}
      </span>
      <span class="user-label">{{ sessionStore.displayName }}</span>
      <Button variant="ghost" size="sm" @click="logout">
        <LogOut :size="16" />
        退出
      </Button>
    </div>
  </header>
</template>