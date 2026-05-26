<template>
  <StatusBadge :tone="stateTone[normalizedState]">
    {{ labelText }}
  </StatusBadge>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import StatusBadge from '@/shared/ui/data-display/StatusBadge.vue'
import { humanizeStatusText } from '@/shared/ui/data-display/status-text'
import type { TaskRecord } from '@/shared/contracts'
import { normalizeTaskState } from '../stores/task.store'

const props = defineProps<{ task: TaskRecord }>()
const { t } = useI18n()

const stateTone = {
  queued: 'neutral',
  running: 'info',
  succeeded: 'success',
  failed: 'danger',
  cancelled: 'warning',
  unknown: 'neutral',
} as const

const normalizedState = computed(() => normalizeTaskState(props.task))
const normalizedStateLabelKey = {
  queued: 'tasks.status.queued',
  running: 'tasks.status.running',
  succeeded: 'tasks.status.succeeded',
  failed: 'tasks.status.failed',
  cancelled: 'tasks.status.cancelled',
  unknown: 'tasks.status.unknown',
} as const

const labelText = computed(() => {
  const rawState = String(props.task.state || props.task.status || '').trim()
  if (!rawState) {
    return t('tasks.status.unknown')
  }
  if (normalizedState.value === 'unknown') {
    return humanizeStatusText(rawState)
  }
  return t(normalizedStateLabelKey[normalizedState.value])
})
</script>