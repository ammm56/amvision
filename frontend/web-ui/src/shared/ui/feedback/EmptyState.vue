<script setup lang="ts">
defineProps<{
  title: string
  description?: string
}>()
</script>

<template>
  <section class="empty-state">
    <h2>{{ title }}</h2>
    <p v-if="description">{{ description }}</p>
    <div class="empty-state__actions">
      <slot />
    </div>
  </section>
</template>