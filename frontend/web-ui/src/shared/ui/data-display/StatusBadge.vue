<template>
  <span class="status-badge" :class="`status-badge--${tone ?? 'neutral'}`">
    <slot />
  </span>
</template>

<script setup lang="ts">
defineProps<{
  tone?: 'neutral' | 'success' | 'warning' | 'danger' | 'info'
}>()
</script>