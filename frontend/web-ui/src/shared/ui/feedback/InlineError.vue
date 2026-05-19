<script setup lang="ts">
import { AlertTriangle } from '@lucide/vue'

defineProps<{ message: string | null }>()
</script>

<template>
  <div v-if="message" class="inline-error" role="alert">
    <AlertTriangle :size="16" />
    <span>{{ message }}</span>
  </div>
</template>