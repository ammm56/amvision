<template>
  <InlineMessage v-if="message" tone="danger" :message="message" />
</template>

<script setup lang="ts">
import InlineMessage from './InlineMessage.vue'

defineProps<{ message: string | null }>()
</script>
