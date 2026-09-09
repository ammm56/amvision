<template>
  <section class="error-view">
    <Lock v-if="props.kind === 'forbidden'" :size="36" />
    <WifiOff v-else :size="36" />
    <h1>{{ props.kind === 'forbidden' ? t('errors.forbiddenTitle') : t('errors.offlineTitle') }}</h1>
    <p>{{ props.kind === 'forbidden' ? t('errors.forbiddenDescription') : t('errors.offlineDescription') }}</p>
    <RouterLink v-if="destination !== '/forbidden'" :to="destination">{{ t('common.returnWorkbench') }}</RouterLink>
    <Button v-if="session.isAuthenticated" variant="secondary" @click="logout">{{ t('accountMenu.logout') }}</Button>
    <RouterLink v-else to="/login">{{ t('auth.login') }}</RouterLink>
  </section>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import { useSessionStore } from '@/app/stores/session.store'
import { firstAccessiblePath } from '@/platform/auth/page-access'
import Button from '@/shared/ui/components/Button.vue'
import { Lock, WifiOff } from '@lucide/vue'
import { useI18n } from 'vue-i18n'

const props = defineProps<{
  kind?: 'forbidden' | 'offline'
}>()

const { t } = useI18n()
const session = useSessionStore()
const router = useRouter()
const destination = computed(() => props.kind === 'offline' || !session.isAuthenticated ? '/' : firstAccessiblePath(session.currentUser))
async function logout(): Promise<void> {
  await session.logout()
  await router.replace('/login')
}
</script>
