<template>
  <span class="status-pill" :class="[`status-pill--${resolvedTone}`, { 'status-pill--with-dot': withDot }]" :title="titleText">
    <span v-if="withDot" class="status-pill__dot" aria-hidden="true" />
    <span class="status-pill__label">{{ displayLabel }}</span>
  </span>
</template>

<script setup lang="ts">
import { computed } from 'vue'

import { humanizeStatusText } from './status-text'

export type StatusPillTone = 'neutral' | 'success' | 'warning' | 'danger' | 'info'

const props = withDefaults(
  defineProps<{
    status: string
    label?: string
    tone?: StatusPillTone
    withDot?: boolean
  }>(),
  {
    withDot: false,
  },
)

const displayLabel = computed(() => props.label ?? humanizeStatusText(props.status))
const titleText = computed(() => props.status || displayLabel.value)
const resolvedTone = computed<StatusPillTone>(() => props.tone ?? inferTone(props.status))

function inferTone(status: string): StatusPillTone {
  const normalized = status.toLowerCase().trim()
  if (['ok', 'online', 'ready', 'healthy', 'reachable', 'available', 'loaded', 'running', 'active', 'enabled', 'succeeded', 'success', 'registered', 'configured', 'completed', 'finished'].includes(normalized)) {
    return 'success'
  }
  if (['queued', 'pending', 'checking', 'starting', 'stopping', 'warming', 'created', 'probing'].includes(normalized)) {
    return 'info'
  }
  if (['warning', 'warn', 'pending', 'queued', 'degraded', 'missing', 'unavailable', 'unregistered', 'not_configured', 'disabled', 'stopped', 'offline', 'stale', 'partial'].includes(normalized)) {
    return 'warning'
  }
  if (['failed', 'error', 'unhealthy', 'cancelled', 'revoked', 'misconfigured'].includes(normalized)) {
    return 'danger'
  }
  return 'neutral'
}
</script>
