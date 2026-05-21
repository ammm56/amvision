<template>
  <span class="info-hint" tabindex="0" :aria-label="text">
    <CircleAlert :size="14" />
    <span class="info-hint__bubble" role="tooltip">{{ text }}</span>
  </span>
</template>

<script setup lang="ts">
import { CircleAlert } from '@lucide/vue'

defineProps<{
  text: string
}>()
</script>