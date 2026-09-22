<template>
  <AnimatedBrand class="app-sidebar__brand sidebar-brand" to="/" />
</template>

<script setup lang="ts">
import AnimatedBrand from '@/shared/ui/components/AnimatedBrand.vue'
</script>

<style scoped>
.sidebar-brand { flex: 1 1 0; justify-content: center; }
</style>
