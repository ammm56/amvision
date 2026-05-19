<script setup lang="ts">
import { useI18n } from 'vue-i18n'

const { t } = useI18n()
</script>

<template>
  <main class="auth-shell">
    <section class="auth-shell__brand">
      <span class="brand-mark">AM</span>
      <div>
        <strong>{{ t('common.appName') }}</strong>
        <small>{{ t('common.tagline') }}</small>
      </div>
    </section>
    <section class="auth-shell__content">
      <slot />
    </section>
  </main>
</template>