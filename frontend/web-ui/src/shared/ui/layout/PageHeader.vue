<template>
  <header class="page-header">
    <div class="page-header__heading">
      <slot name="heading">
        <h1 v-if="title">{{ title }}</h1>
      </slot>
      <p v-if="description" class="page-description">{{ description }}</p>
    </div>
    <div v-if="$slots.actions" class="page-actions">
      <slot name="actions" />
    </div>
  </header>
</template>

<script setup lang="ts">
defineProps<{
  title?: string
  description?: string
}>()
</script>
