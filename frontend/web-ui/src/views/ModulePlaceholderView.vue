<template>
  <section class="page-stack">
    <header class="page-header">
      <div>
        <h1>{{ t(titleKey) }}</h1>
      </div>
    </header>
    <section class="placeholder-panel">
      <p>{{ t(descriptionKey) }}</p>
    </section>
  </section>
</template>

<script setup lang="ts">
import { useI18n } from 'vue-i18n'

defineProps<{
  titleKey: string
  descriptionKey: string
}>()

const { t } = useI18n()
</script>
