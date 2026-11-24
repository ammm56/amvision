<template>
  <EmptyState
    v-if="events.length === 0"
    :title="t('tasks.emptyEventsTitle')"
    :description="t('tasks.emptyEventsDescription')"
  />
  <ol v-else class="task-event-timeline" :class="{ 'task-event-timeline--compact': compact }">
    <li v-for="event in events" :key="String(event.sequence ?? event.event_id ?? event.created_at ?? event.occurred_at)">
      <span class="task-event-timeline__marker" :data-tone="eventTone(event)" aria-hidden="true" />
      <div class="task-event-timeline__content">
        <div class="task-event-timeline__heading">
          <strong>{{ (compact && event.message) || event.event_type || t('tasks.eventFallback') }}</strong>
          <time :datetime="event.created_at || event.occurred_at || undefined">{{ formatSystemDateTime(event.created_at || event.occurred_at) }}</time>
        </div>
        <p v-if="!compact">{{ event.message || '-' }}</p>
      </div>
    </li>
  </ol>
</template>

<script setup lang="ts">
import { useI18n } from 'vue-i18n'

import type { TaskEvent } from '@/shared/contracts'
import { formatSystemDateTime } from '@/shared/formatters/date-time'
import EmptyState from '@/shared/ui/feedback/EmptyState.vue'
import { normalizeTaskState } from '../task-state'

defineProps<{ events: TaskEvent[]; compact?: boolean }>()

const { t } = useI18n()

function eventTone(event: TaskEvent): 'neutral' | 'success' | 'warning' | 'danger' {
  const state = event.payload?.state
  switch (normalizeTaskState(typeof state === 'string' ? state : undefined)) {
    case 'succeeded': return 'success'
    case 'failed':
    case 'timed_out': return 'danger'
    case 'paused': return 'warning'
    default: return 'neutral'
  }
}
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
  grid-template-columns: 12px minmax(0, 1fr);
  column-gap: var(--am-space-md);
}

.task-event-timeline li:not(:last-child)::before {
  position: absolute;
  inset-block: 20px -20px;
  inset-inline-start: 5px;
  inline-size: 2px;
  background: var(--am-border);
  content: '';
}

.task-event-timeline__marker {
  position: relative;
  z-index: 1;
  justify-self: center;
  width: 10px;
  height: 10px;
  margin-block-start: 15px;
  border: 1px solid var(--am-surface);
  border-radius: var(--am-radius-pill);
  background: var(--am-neutral-icon);
}

.task-event-timeline__marker[data-tone='success'] {
  background: color-mix(in srgb, var(--am-success-icon) 68%, var(--am-text-strong));
}
.task-event-timeline__marker[data-tone='warning'] { background: var(--am-warning-icon); }
.task-event-timeline__marker[data-tone='danger'] { background: var(--am-danger-icon); }

.task-event-timeline__content {
  display: grid;
  gap: 3px;
  min-width: 0;
  padding-block: 10px;
}

.task-event-timeline li + li .task-event-timeline__content {
  border-block-start: 1px solid var(--am-border);
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

.task-event-timeline--compact strong { font-weight: 500; }
.task-event-timeline__heading time { flex: none; font-variant-numeric: tabular-nums; }

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
