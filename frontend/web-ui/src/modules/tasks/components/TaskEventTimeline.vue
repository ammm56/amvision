<script setup lang="ts">
import type { TaskEvent } from '@/shared/contracts'

defineProps<{ events: TaskEvent[] }>()
</script>

<template>
  <ol class="event-timeline">
    <li v-for="event in events" :key="String(event.sequence ?? event.event_id ?? event.created_at ?? event.occurred_at)">
      <time>{{ event.created_at || event.occurred_at || '-' }}</time>
      <strong>{{ event.event_type || 'event' }}</strong>
      <span>{{ event.message || '-' }}</span>
    </li>
  </ol>
</template>