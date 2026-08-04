<template>
  <EmptyState
    v-if="events.length === 0"
    :title="t('tasks.emptyEventsTitle')"
    :description="t('tasks.emptyEventsDescription')"
  />
  <ol v-else class="task-event-timeline">
    <li v-for="event in events" :key="String(event.sequence ?? event.event_id ?? event.created_at ?? event.occurred_at)">
      <span class="task-event-timeline__marker" aria-hidden="true" />
      <div class="task-event-timeline__content">
        <div class="task-event-timeline__heading">
          <strong>{{ event.event_type || t('tasks.eventFallback') }}</strong>
          <time>{{ formatSystemDateTime(event.created_at || event.occurred_at) }}</time>
        </div>
        <p>{{ event.message || '-' }}</p>
      </div>
    </li>
  </ol>
</template>

<script setup lang="ts">
import { useI18n } from 'vue-i18n'

import type { TaskEvent } from '@/shared/contracts'
import { formatSystemDateTime } from '@/shared/formatters/date-time'
import EmptyState from '@/shared/ui/feedback/EmptyState.vue'

defineProps<{ events: TaskEvent[] }>()

const { t } = useI18n()
</script>

<style scoped>
.task-event-timeline {
  display: grid;
  gap: 0;
  margin: 0;
  padding: 0;
  list-style: none;
}

.task-event-timeline li {
  position: relative;
  display: grid;
  grid-template-columns: 14px minmax(0, 1fr);
  gap: var(--am-space-md);
  padding-bottom: var(--am-space-lg);
}

.task-event-timeline li:not(:last-child)::before {
  position: absolute;
  top: 12px;
  bottom: 0;
  left: 5px;
  width: 1px;
  background: var(--am-border);
  content: '';
}

.task-event-timeline__marker {
  position: relative;
  z-index: 1;
  width: 11px;
  height: 11px;
  margin-top: 4px;
  border: 2px solid var(--am-info-text);
  border-radius: var(--am-radius-pill);
  background: var(--am-surface);
}

.task-event-timeline__content {
  display: grid;
  gap: 3px;
  min-width: 0;
}

.task-event-timeline__heading {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--am-space-md);
}

.task-event-timeline__heading strong,
.task-event-timeline__heading time,
.task-event-timeline p {
  min-width: 0;
  overflow-wrap: anywhere;
}

.task-event-timeline__heading time,
.task-event-timeline p {
  color: var(--am-text-muted);
  font-size: 12px;
}

.task-event-timeline p {
  margin: 0;
  line-height: 1.5;
}

@media (max-width: 640px) {
  .task-event-timeline__heading {
    display: grid;
    gap: 2px;
  }
}
</style>
