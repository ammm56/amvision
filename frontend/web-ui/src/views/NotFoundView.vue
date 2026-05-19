<script setup lang="ts">
import { RouterLink } from 'vue-router'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()
</script>

<template>
  <section class="error-view">
    <h1>{{ t('errors.notFoundTitle') }}</h1>
    <p>{{ t('errors.notFoundDescription') }}</p>
    <RouterLink to="/projects">{{ t('common.returnWorkbench') }}</RouterLink>
  </section>
</template>