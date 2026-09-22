<template>
  <div v-if="nodeCount === 0" class="workflow-graph-empty">
    <AnimatedBrand />
  </div>
</template>

<script setup lang="ts">
import AnimatedBrand from '@/shared/ui/components/AnimatedBrand.vue'

defineProps<{
  nodeCount: number
}>()

</script>
