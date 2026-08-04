<template>
  <div
    class="inline-message"
    :class="`inline-message--${tone}`"
    :role="tone === 'danger' ? 'alert' : 'status'"
  >
    <component :is="messageIcon" class="inline-message__icon" :size="17" aria-hidden="true" />
    <div class="inline-message__content">
      <strong v-if="title" class="inline-message__title">{{ title }}</strong>
      <div class="inline-message__body">
        <slot>{{ message }}</slot>
      </div>
    </div>
    <div v-if="$slots.actions" class="inline-message__actions">
      <slot name="actions" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { AlertTriangle, CheckCircle2, Info, TriangleAlert } from '@lucide/vue'

export type InlineMessageTone = 'info' | 'success' | 'warning' | 'danger'

const props = withDefaults(
  defineProps<{
    tone?: InlineMessageTone
    title?: string
    message?: string | null
  }>(),
  {
    tone: 'info',
    title: '',
    message: '',
  },
)

const messageIcon = computed(() => {
  if (props.tone === 'success') return CheckCircle2
  if (props.tone === 'warning') return TriangleAlert
  if (props.tone === 'danger') return AlertTriangle
  return Info
})
</script>

<style scoped>
.inline-message {
  display: flex;
  align-items: flex-start;
  gap: var(--am-space-sm);
  min-width: 0;
  padding: var(--am-space-md) var(--am-space-lg);
  border: 1px solid;
  border-radius: var(--am-radius-sm);
}

.inline-message--info {
  color: var(--am-info-text);
  background: var(--am-info-surface);
  border-color: var(--am-info-border);
}

.inline-message--success {
  color: var(--am-success-text);
  background: var(--am-success-surface);
  border-color: var(--am-success-border);
}

.inline-message--warning {
  color: var(--am-warning-text);
  background: var(--am-warning-surface);
  border-color: var(--am-warning-border);
}

.inline-message--danger {
  color: var(--am-danger-text);
  background: var(--am-danger-surface);
  border-color: var(--am-danger-border);
}

.inline-message__icon {
  flex: 0 0 auto;
  margin-top: 1px;
}

.inline-message__content {
  display: grid;
  flex: 1 1 auto;
  gap: 2px;
  min-width: 0;
}

.inline-message__title,
.inline-message__body {
  min-width: 0;
  overflow-wrap: anywhere;
}

.inline-message__title {
  color: currentColor;
  font-size: 13px;
}

.inline-message__body {
  font-size: 13px;
  line-height: 1.5;
}

.inline-message__actions {
  display: flex;
  flex: 0 0 auto;
  align-items: center;
  gap: var(--am-space-sm);
}

@media (max-width: 640px) {
  .inline-message {
    flex-wrap: wrap;
  }

  .inline-message__actions {
    width: 100%;
    padding-left: 25px;
  }
}
</style>
