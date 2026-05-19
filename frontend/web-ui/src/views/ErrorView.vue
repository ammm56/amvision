<script setup lang="ts">
import { RouterLink } from 'vue-router'
import { Lock, WifiOff } from '@lucide/vue'
import { useI18n } from 'vue-i18n'

const props = defineProps<{
  kind?: 'forbidden' | 'offline'
}>()

const { t } = useI18n()
</script>

<template>
  <section class="error-view">
    <Lock v-if="props.kind === 'forbidden'" :size="36" />
    <WifiOff v-else :size="36" />
    <h1>{{ props.kind === 'forbidden' ? t('errors.forbiddenTitle') : t('errors.offlineTitle') }}</h1>
    <p>{{ props.kind === 'forbidden' ? t('errors.forbiddenDescription') : t('errors.offlineDescription') }}</p>
    <RouterLink to="/projects">{{ t('common.returnWorkbench') }}</RouterLink>
  </section>
</template>