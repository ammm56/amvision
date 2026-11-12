<template>
  <span v-if="appearance === 'icon'" class="task-state-icon" :class="`task-state-icon--${statusTone}`" :title="statusLabel">
    <component :is="stateIcon" :size="20" :stroke-width="2" class="task-state-icon__symbol" :class="{ 'status-disc': statusTone === 'success' || statusTone === 'danger', 'task-state-icon__symbol--loading': canonicalState === 'running' }" aria-hidden="true" />
    <span class="task-state-icon__label">{{ statusLabel }}</span>
  </span>
  <StatusBadge v-else :tone="statusTone">
    {{ statusLabel }}
  </StatusBadge>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { CircleCheck, CircleX, CircleMinus, CircleHelp, Clock3, LoaderCircle, CirclePause } from '@lucide/vue'

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

const props = withDefaults(defineProps<{ state: string | null | undefined; appearance?: 'badge' | 'icon' }>(), { appearance: 'badge' })
const { t } = useI18n()

const canonicalState = computed<CanonicalTaskState>(() => normalizeTaskState(props.state))
const stateIcon = computed(() => ({
  queued: Clock3, running: LoaderCircle, paused: CirclePause,
  succeeded: CircleCheck, failed: CircleX, timed_out: CircleX,
  cancelled: CircleMinus, unknown: CircleHelp,
})[canonicalState.value])
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

<style scoped>
.task-state-icon { display: inline-flex; align-items: center; gap: 7px; max-width: 100%; min-width: 0; color: var(--am-text); font-size: inherit; font-weight: 400; white-space: nowrap; }
.task-state-icon__symbol { flex: 0 0 20px; color: var(--am-text-muted); }
.task-state-icon .task-state-icon__label { min-width: 0; overflow: hidden; text-overflow: ellipsis; font: inherit; color: inherit; }
.task-state-icon--success .task-state-icon__symbol { fill: var(--am-brand-primary); color: #fff; }
.task-state-icon--danger .task-state-icon__symbol { fill: #dc2626; color: #fff; }
.task-state-icon__symbol--loading { animation: task-state-spin 1s linear infinite; }
@keyframes task-state-spin { to { transform: rotate(360deg); } }
@media (prefers-reduced-motion: reduce) { .task-state-icon__symbol--loading { animation: none; } }
</style>
