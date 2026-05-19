<template>
  <ol class="event-timeline">
    <li v-for="event in events" :key="String(event.sequence ?? event.event_id ?? event.created_at ?? event.occurred_at)">
      <time>{{ formatSystemDateTime(event.created_at || event.occurred_at) }}</time>
      <strong>{{ event.event_type || t('tasks.eventFallback') }}</strong>
      <span>{{ event.message || '-' }}</span>
    </li>
  </ol>
</template>

<script setup lang="ts">
import { useI18n } from 'vue-i18n'

import type { TaskEvent } from '@/shared/contracts'
import { formatSystemDateTime } from '@/shared/formatters/date-time'

defineProps<{ events: TaskEvent[] }>()

const { t } = useI18n()
</script>