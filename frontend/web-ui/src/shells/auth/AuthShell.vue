<template>
  <main class="auth-shell">
    <section class="auth-shell__brand">
      <img class="brand-mark" src="/favicon.svg" alt="AM" />
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

<script setup lang="ts">
import { useI18n } from 'vue-i18n'

const { t } = useI18n()
</script>
