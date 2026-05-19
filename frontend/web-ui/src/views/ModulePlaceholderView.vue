<script setup lang="ts">
defineProps<{
  title: string
  description: string
}>()
</script>

<template>
  <section class="page-stack">
    <header class="page-header">
      <div>
        <p class="page-kicker">Module</p>
        <h1>{{ title }}</h1>
      </div>
    </header>
    <section class="placeholder-panel">
      <p>{{ description }}</p>
    </section>
  </section>
</template>