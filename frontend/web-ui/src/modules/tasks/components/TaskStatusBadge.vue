<script setup lang="ts">
import StatusBadge from '@/shared/ui/data-display/StatusBadge.vue'
import type { TaskRecord } from '@/shared/contracts'
import { normalizeTaskState } from '../stores/task.store'

const props = defineProps<{ task: TaskRecord }>()

const stateTone = {
  queued: 'neutral',
  running: 'info',
  succeeded: 'success',
  failed: 'danger',
  cancelled: 'warning',
  unknown: 'neutral',
} as const
</script>

<template>
  <StatusBadge :tone="stateTone[normalizeTaskState(props.task)]">
    {{ props.task.state || props.task.status || 'unknown' }}
  </StatusBadge>
</template>