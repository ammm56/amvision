<template>
  <StatusBadge :tone="statusTone">
    {{ statusLabel }}
  </StatusBadge>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import StatusBadge, { type StatusBadgeTone } from '@/shared/ui/data-display/StatusBadge.vue'
import { humanizeStatusText } from '@/shared/ui/data-display/status-text'

type CanonicalTaskState =
  | 'queued'
  | 'running'
  | 'paused'
  | 'succeeded'
  | 'failed'
  | 'timed_out'
  | 'cancelled'
  | 'unknown'

const props = defineProps<{ state: string | null | undefined }>()
const { t } = useI18n()

const canonicalState = computed<CanonicalTaskState>(() => normalizeTaskState(props.state))
const statusTone = computed<StatusBadgeTone>(() => ({
  queued: 'warning',
  running: 'info',
  paused: 'warning',
  succeeded: 'success',
  failed: 'danger',
  timed_out: 'danger',
  cancelled: 'neutral',
  unknown: 'neutral',
})[canonicalState.value] as StatusBadgeTone)

const statusLabel = computed(() => {
  if (canonicalState.value === 'unknown') {
    return humanizeStatusText(String(props.state ?? '')) || t('tasks.status.unknown')
  }
  return t(`tasks.status.${canonicalState.value}`)
})

function normalizeTaskState(value: string | null | undefined): CanonicalTaskState {
  const state = String(value ?? '').trim().toLowerCase()
  if (!state) return 'unknown'
  if (state === 'paused' || state.includes('pause')) return 'paused'
  if (state === 'timed_out' || state.includes('time_out') || state.includes('timeout')) return 'timed_out'
  if (state.includes('cancel') || state.includes('revoke')) return 'cancelled'
  if (state.includes('fail') || state.includes('error') || state.includes('terminate')) return 'failed'
  if (state.includes('success') || state.includes('succeed') || state.includes('complete') || state.includes('finish')) return 'succeeded'
  if (state.includes('run') || state.includes('process') || state.includes('validat') || state.includes('convert') || state.includes('train')) return 'running'
  if (state.includes('queue') || state.includes('pending') || state.includes('received') || state.includes('created')) return 'queued'
  return 'unknown'
}
</script>
