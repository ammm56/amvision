<template>
  <div class="confirm-dialog-backdrop" @click="cancelDialog">
    <section
      ref="dialogRef"
      class="confirm-dialog"
      role="dialog"
      aria-modal="true"
      :aria-labelledby="titleId"
      :aria-describedby="messageId"
      :aria-busy="busy"
      tabindex="-1"
      @click.stop
      @keydown.esc.prevent="cancelDialog"
      @keydown.tab="trapFocus"
    >
      <header class="confirm-dialog__header">
        <div>
          <div class="confirm-dialog__title">
            <h2 :id="titleId">{{ title }}</h2>
            <InfoHint v-if="details" :text="details" />
          </div>
        </div>
        <button type="button" class="confirm-dialog__close" :aria-label="cancelLabel" :disabled="busy" @click="cancelDialog">
          <X :size="16" />
        </button>
      </header>

      <p :id="messageId" class="confirm-dialog__message">{{ message }}</p>

      <footer class="confirm-dialog__actions">
        <Button data-confirm-cancel variant="secondary" :disabled="busy" @click="cancelDialog">{{ cancelLabel }}</Button>
        <Button :variant="confirmVariant" :disabled="busy" :loading="busy" @click="emit('confirm')">{{ confirmLabel }}</Button>
      </footer>
    </section>
  </div>
</template>

<script setup lang="ts">
import { X } from '@lucide/vue'
import { nextTick, onBeforeUnmount, onMounted, ref, useId } from 'vue'

import Button from './Button.vue'
import InfoHint from './InfoHint.vue'

const props = withDefaults(
  defineProps<{
    title: string
    message: string
    confirmLabel: string
    cancelLabel: string
    details?: string
    busy?: boolean
    confirmVariant?: 'primary' | 'danger'
  }>(),
  {
    details: '',
    busy: false,
    confirmVariant: 'danger',
  },
)

const emit = defineEmits<{
  cancel: []
  confirm: []
}>()

const componentId = useId()
const titleId = `${componentId}-title`
const messageId = `${componentId}-message`
const dialogRef = ref<HTMLElement | null>(null)
let previouslyFocusedElement: HTMLElement | null = null
let previousBodyOverflow = ''

function readFocusableElements(): HTMLElement[] {
  if (!dialogRef.value) return []
  return [...dialogRef.value.querySelectorAll<HTMLElement>(
    'button:not(:disabled), [href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex]:not([tabindex="-1"])',
  )]
}

function trapFocus(event: KeyboardEvent): void {
  const focusableElements = readFocusableElements()
  if (focusableElements.length === 0) {
    event.preventDefault()
    dialogRef.value?.focus()
    return
  }
  const firstElement = focusableElements[0]
  const lastElement = focusableElements[focusableElements.length - 1]
  if (event.shiftKey && document.activeElement === firstElement) {
    event.preventDefault()
    lastElement?.focus()
  } else if (!event.shiftKey && document.activeElement === lastElement) {
    event.preventDefault()
    firstElement?.focus()
  }
}

function cancelDialog(): void {
  if (!props.busy) emit('cancel')
}

onMounted(() => {
  previouslyFocusedElement = document.activeElement instanceof HTMLElement ? document.activeElement : null
  previousBodyOverflow = document.body.style.overflow
  document.body.style.overflow = 'hidden'
  void nextTick(() => {
    const cancelButton = dialogRef.value?.querySelector<HTMLElement>('[data-confirm-cancel]')
    ;(cancelButton ?? dialogRef.value)?.focus({ preventScroll: true })
  })
})

onBeforeUnmount(() => {
  document.body.style.overflow = previousBodyOverflow
  previouslyFocusedElement?.focus({ preventScroll: true })
})
</script>

<style scoped>
.confirm-dialog-backdrop {
  position: fixed;
  inset: 0;
  z-index: 90;
  display: grid;
  place-items: center;
  padding: 18px;
  background: var(--am-overlay);
}

.confirm-dialog {
  display: grid;
  gap: 16px;
  width: min(520px, calc(100vw - 36px));
  padding: 18px;
  border: 1px solid var(--line);
  border-radius: var(--am-radius-md);
  background: var(--am-surface-raised);
  box-shadow: var(--am-shadow-modal);
}

.confirm-dialog__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.confirm-dialog__header h2,
.confirm-dialog__message {
  margin: 0;
}

.confirm-dialog__title {
  display: flex;
  align-items: center;
  gap: 8px;
}

.confirm-dialog__message {
  color: var(--muted);
  line-height: 1.6;
}

.confirm-dialog__close {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 34px;
  height: 34px;
  border: 1px solid var(--line-strong);
  border-radius: var(--am-radius-sm);
  color: var(--text);
  background: var(--button-secondary-bg);
  cursor: pointer;
}

.confirm-dialog__close:hover {
  border-color: var(--accent);
}

.confirm-dialog__close:disabled {
  color: var(--am-text-disabled);
  cursor: not-allowed;
}

.confirm-dialog__actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  flex-wrap: wrap;
}
</style>
