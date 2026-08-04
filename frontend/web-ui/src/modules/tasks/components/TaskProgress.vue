<template>
  <div class="task-progress" :class="{ 'task-progress--compact': compact }">
    <div v-if="!compact || label" class="task-progress__header">
      <span v-if="label">{{ label }}</span>
      <strong>{{ percentText }}</strong>
    </div>
    <div
      class="task-progress__track"
      role="progressbar"
      :aria-label="ariaLabel || label"
      :aria-valuenow="normalizedPercent ?? undefined"
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
const percentText = computed(() => normalizedPercent.value === null ? '-' : `${normalizedPercent.value.toFixed(props.compact ? 0 : 1)}%`)
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
  }
}
</style>
