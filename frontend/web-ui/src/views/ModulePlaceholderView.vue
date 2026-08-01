<template>
  <section class="page-stack">
    <PageHeader :title="t(titleKey)" />
    <section class="placeholder-panel">
      <p>{{ t(descriptionKey) }}</p>
    </section>
  </section>
</template>

<script setup lang="ts">
import { useI18n } from 'vue-i18n'

import PageHeader from '@/shared/ui/layout/PageHeader.vue'

defineProps<{
  titleKey: string
  descriptionKey: string
}>()

const { t } = useI18n()
</script>
