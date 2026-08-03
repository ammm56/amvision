<template>
  <article
    class="toast-notice"
    :class="`toast-notice--${notice.variant}`"
    :role="notice.variant === 'error' ? 'alert' : 'status'"
    :aria-live="notice.variant === 'error' ? 'assertive' : 'polite'"
    aria-atomic="true"
    @mouseenter="pauseTimer"
    @mouseleave="resumeTimer"
    @focusin="pauseTimer"
    @focusout="resumeTimer"
  >
    <component :is="noticeIcon" class="toast-notice__icon" :size="20" aria-hidden="true" />
    <div class="toast-notice__content">
      <strong>{{ notice.title }}</strong>
      <span v-if="notice.message">{{ notice.message }}</span>
    </div>
    <Button
      class="toast-notice__close"
      variant="ghost"
      size="sm"
      icon-only
      :aria-label="closeLabel"
      @click="emit('dismiss')"
    >
      <X :size="16" aria-hidden="true" />
    </Button>
  </article>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { AlertTriangle, CircleCheck, CircleX, Info, X } from '@lucide/vue'

import type { ToastNotice } from '@/app/stores/feedback.store'
import Button from '@/shared/ui/components/Button.vue'

const props = defineProps<{
  notice: ToastNotice
  closeLabel: string
}>()
const emit = defineEmits<{
  dismiss: []
}>()

const remainingMs = ref(props.notice.durationMs)
let timeoutId: ReturnType<typeof setTimeout> | null = null
let startedAt = 0

const noticeIcon = computed(() => ({
  success: CircleCheck,
  error: CircleX,
  warning: AlertTriangle,
  info: Info,
})[props.notice.variant])

function clearTimer(): void {
  if (timeoutId !== null) {
    clearTimeout(timeoutId)
    timeoutId = null
  }
}

function resumeTimer(): void {
  if (remainingMs.value <= 0 || timeoutId !== null) return
  startedAt = Date.now()
  timeoutId = setTimeout(() => emit('dismiss'), remainingMs.value)
}

function pauseTimer(): void {
  if (timeoutId === null) return
  remainingMs.value = Math.max(0, remainingMs.value - (Date.now() - startedAt))
  clearTimer()
}

onMounted(resumeTimer)
onBeforeUnmount(clearTimer)
</script>

<style scoped>
.toast-notice {
  --toast-text: var(--am-info-text);
  --toast-icon: var(--am-info-icon);
  --toast-surface: var(--am-info-surface);
  --toast-border: var(--am-info-border);
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: start;
  gap: var(--am-space-md);
  width: min(400px, calc(100vw - 32px));
  padding: var(--am-space-md);
  color: var(--toast-text);
  background: var(--toast-surface);
  border: 1px solid var(--toast-border);
  border-radius: var(--am-radius-md);
  box-shadow: var(--am-shadow-floating);
}

.toast-notice--success {
  --toast-text: var(--am-success-text);
  --toast-icon: var(--am-success-icon);
  --toast-surface: var(--am-success-surface);
  --toast-border: var(--am-success-border);
}

.toast-notice--error {
  --toast-text: var(--am-danger-text);
  --toast-icon: var(--am-danger-icon);
  --toast-surface: var(--am-danger-surface);
  --toast-border: var(--am-danger-border);
}

.toast-notice--warning {
  --toast-text: var(--am-warning-text);
  --toast-icon: var(--am-warning-icon);
  --toast-surface: var(--am-warning-surface);
  --toast-border: var(--am-warning-border);
}

.toast-notice__icon {
  margin-top: 1px;
  color: var(--toast-icon);
}

.toast-notice__content {
  display: grid;
  gap: var(--am-space-xs);
  min-width: 0;
  line-height: 1.4;
}

.toast-notice__content strong,
.toast-notice__content span {
  overflow-wrap: anywhere;
}

.toast-notice__content span {
  font-size: 13px;
  opacity: 0.9;
}

.toast-notice__close {
  margin: calc(var(--am-space-xs) * -1);
  color: currentColor;
}
</style>
