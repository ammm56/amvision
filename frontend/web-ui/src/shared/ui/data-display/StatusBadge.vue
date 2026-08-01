<template>
  <span class="status-badge" :class="[`status-badge--${resolvedTone}`, { 'status-badge--with-dot': withDot }]">
    <span v-if="withDot" class="status-badge__dot" aria-hidden="true" />
    <span class="status-badge__label"><slot>{{ displayLabel }}</slot></span>
  </span>
</template>

<script setup lang="ts">
import { computed } from 'vue'

import { humanizeStatusText } from './status-text'

export type StatusBadgeTone = 'neutral' | 'success' | 'warning' | 'danger' | 'info'

const props = withDefaults(
  defineProps<{
    tone?: StatusBadgeTone
    status?: string
    label?: string
    withDot?: boolean
  }>(),
  {
    status: '',
    label: '',
    withDot: false,
  },
)

const displayLabel = computed(() => props.label || humanizeStatusText(props.status))
const resolvedTone = computed<StatusBadgeTone>(() => props.tone ?? inferTone(props.status))

function inferTone(status: string): StatusBadgeTone {
  const normalized = status.toLowerCase().trim()
  if (['ok', 'online', 'ready', 'healthy', 'reachable', 'available', 'loaded', 'running', 'active', 'enabled', 'succeeded', 'success', 'registered', 'configured', 'completed', 'finished'].includes(normalized)) {
    return 'success'
  }
  if (['queued', 'pending', 'checking', 'starting', 'stopping', 'warming', 'created', 'probing'].includes(normalized)) return 'info'
  if (['warning', 'warn', 'degraded', 'missing', 'unavailable', 'unregistered', 'not_configured', 'stale', 'partial'].includes(normalized)) return 'warning'
  if (['failed', 'error', 'unhealthy', 'unreachable', 'offline', 'cancelled', 'revoked', 'misconfigured'].includes(normalized)) return 'danger'
  return 'neutral'
}
</script>
