<template>
  <div class="task-progress" :class="{ 'task-progress--compact': compact, 'task-progress--failed': failed }">
    <div v-if="!compact || label" class="task-progress__header">
      <span v-if="label">{{ label }}</span>
      <strong v-if="!indeterminate || normalizedPercent !== null">{{ percentText }}</strong>
    </div>
    <div
      class="task-progress__track"
      :class="{ 'is-indeterminate': indeterminate && normalizedPercent === null }"
      role="progressbar"
      :aria-label="ariaLabel || label"
      :aria-valuenow="normalizedPercent ?? undefined"
      :aria-valuetext="valueText || undefined"
      aria-valuemin="0"
      aria-valuemax="100"
    >
      <span :style="{ width: `${normalizedPercent ?? 0}%` }" />
    </div>
    <strong v-if="compact && !label" class="task-progress__compact-value">{{ percentText }}</strong>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(
  defineProps<{
    percent: number | null | undefined
    label?: string
    ariaLabel?: string
    compact?: boolean
    indeterminate?: boolean
    failed?: boolean
    valueText?: string
  }>(),
  {
    label: '',
    ariaLabel: '',
    compact: false,
  },
)

const normalizedPercent = computed(() => {
  if (typeof props.percent !== 'number' || !Number.isFinite(props.percent)) return null
  return Math.min(100, Math.max(0, props.percent))
})
const percentText = computed(() => props.valueText || (normalizedPercent.value === null ? '-' : `${normalizedPercent.value.toFixed(props.compact ? 0 : 1)}%`))
</script>

<style scoped>
.task-progress {
  display: grid;
  gap: var(--am-space-sm);
  min-width: 0;
}

.task-progress__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--am-space-md);
  min-width: 0;
}

.task-progress__header span {
  color: var(--am-text-muted);
  overflow-wrap: anywhere;
}

.task-progress__header strong,
.task-progress__compact-value {
  color: var(--am-progress-text);
  font-variant-numeric: tabular-nums;
}

.task-progress__track {
  height: 7px;
  overflow: hidden;
  border-radius: var(--am-radius-pill);
  background: var(--am-progress-track);
}

.task-progress__track span {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: var(--am-progress-fill);
  transition: width 160ms ease;
}
.task-progress--failed .task-progress__track span {
  background: var(--am-danger-icon);
}
.task-progress__track.is-indeterminate span {
  width: 28% !important;
  animation: task-progress-pending 1.6s ease-in-out infinite;
}
@keyframes task-progress-pending {
  from { transform: translateX(-100%); }
  to { transform: translateX(360%); }
}

.task-progress--compact {
  grid-template-columns: minmax(72px, 1fr) 38px;
  align-items: center;
  gap: var(--am-space-sm);
  width: min(160px, 100%);
}

.task-progress__compact-value {
  font-size: 12px;
  text-align: right;
}

@media (prefers-reduced-motion: reduce) {
  .task-progress__track span {
    transition: none;
    animation: none !important;
  }
}
</style>
