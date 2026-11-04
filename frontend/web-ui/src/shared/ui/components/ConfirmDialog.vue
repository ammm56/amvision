<template>
  <Transition name="confirm-dialog" appear>
    <div class="confirm-dialog-backdrop" :style="{ zIndex: order, background: covered ? 'transparent' : undefined }" @click="cancelDialog">
      <section
        ref="dialogRef"
        class="confirm-dialog"
        :class="{ 'confirm-dialog--wide': size === 'wide', 'confirm-dialog--medium': size === 'medium', 'confirm-dialog--scroll-body': scrollBody }"
        role="dialog"
        aria-modal="true"
        :aria-labelledby="titleId"
        :aria-describedby="describedBy"
        :aria-busy="busy"
        tabindex="-1"
        @click.stop
        @keydown.esc.stop.prevent="cancelDialog"
        @keydown.tab.stop="trapFocus"
      >
        <header class="confirm-dialog__header">
          <div>
            <h2 :id="titleId">{{ title }}</h2>
          </div>
          <button type="button" class="confirm-dialog__close" :aria-label="cancelLabel" :disabled="busy" @click="cancelDialog">
            <X :size="16" />
          </button>
        </header>

        <p v-if="message" :id="messageId" class="confirm-dialog__message">{{ message }}</p>
        <p v-if="details" :id="detailsId" class="confirm-dialog__details">{{ details }}</p>
        <div v-if="$slots.default" class="confirm-dialog__content" :inert="scrollBody && busy">
          <slot />
        </div>

        <footer class="confirm-dialog__actions">
          <div v-if="$slots['leading-actions']" class="confirm-dialog__leading-actions"><slot name="leading-actions" /></div>
          <Button data-confirm-cancel variant="secondary" :disabled="busy" @click="cancelDialog">{{ cancelLabel }}</Button>
          <Button v-if="showConfirm" :variant="confirmVariant" :disabled="busy || confirmDisabled" :loading="busy" @click="emit('confirm')">{{ confirmLabel }}</Button>
        </footer>
      </section>
    </div>
  </Transition>
</template>

<script setup lang="ts">
import { X } from '@lucide/vue'
import { computed, onMounted, ref, useId, watch } from 'vue'

import Button from './Button.vue'
import { useModalLayer } from './modal-layer'

const props = withDefaults(
  defineProps<{
    title: string
    message?: string
    confirmLabel: string
    cancelLabel: string
    details?: string
    busy?: boolean
    confirmDisabled?: boolean
    confirmVariant?: 'primary' | 'danger'
    initialFocus?: 'cancel' | 'first-field'
    size?: 'default' | 'medium' | 'wide'
    scrollBody?: boolean
    showConfirm?: boolean
  }>(),
  {
    message: '',
    details: '',
    busy: false,
    showConfirm: true,
    confirmDisabled: false,
    confirmVariant: 'danger',
    initialFocus: 'cancel',
    size: 'default',
    scrollBody: false,
  },
)

const emit = defineEmits<{
  cancel: []
  confirm: []
}>()

const componentId = useId()
const titleId = `${componentId}-title`
const messageId = `${componentId}-message`
const detailsId = `${componentId}-details`
const describedBy = computed(() => {
  const ids = [props.message ? messageId : '', props.details ? detailsId : ''].filter(Boolean)
  return ids.join(' ') || undefined
})
const dialogRef = ref<HTMLElement | null>(null)
const { activate, trapFocus, isTop, order, covered } = useModalLayer(dialogRef)

// 禁用提交按钮可能让浏览器把焦点移到 body；保持 Esc/Tab 属于当前对话框。
watch(() => props.busy, () => {
  if (isTop() && dialogRef.value && !dialogRef.value.contains(document.activeElement)) dialogRef.value.focus({ preventScroll: true })
}, { flush: 'post' })

function cancelDialog(): void {
  if (!props.busy && isTop()) emit('cancel')
}

onMounted(() => void activate(() => {
  const cancelButton = dialogRef.value?.querySelector<HTMLElement>('[data-confirm-cancel]')
  const firstField = dialogRef.value?.querySelector<HTMLElement>(
    '[data-dialog-initial-focus], input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [aria-haspopup="listbox"]:not(:disabled)',
  )
  return (props.initialFocus === 'first-field' ? firstField : cancelButton) ?? cancelButton
}))
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
  max-height: calc(100dvh - 36px);
  overflow: auto;
  padding: 18px;
  border: 1px solid var(--am-border);
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

.confirm-dialog--medium {
  width: min(640px, calc(100vw - 36px));
}

.confirm-dialog--wide {
  width: min(760px, calc(100vw - 36px));
  max-height: min(760px, calc(100dvh - 36px));
}

.confirm-dialog__header h2,
.confirm-dialog__message {
  margin: 0;
}

.confirm-dialog__message {
  color: var(--am-text-muted);
  line-height: 1.6;
}

.confirm-dialog__details {
  margin: -8px 0 0;
  color: var(--am-text-subtle);
  font-size: 13px;
  line-height: 1.55;
}

.confirm-dialog__content {
  display: grid;
  gap: 12px;
  min-width: 0;
}

.confirm-dialog--scroll-body { display: flex; flex-direction: column; overflow: hidden; }
.confirm-dialog--scroll-body .confirm-dialog__content { min-height: 0; overflow: auto; padding-right: 4px; }
.confirm-dialog--scroll-body > :not(.confirm-dialog__content) { flex-shrink: 0; }

.confirm-dialog__leading-actions { margin-right: auto; }

.confirm-dialog__close {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 34px;
  height: 34px;
  border: 1px solid var(--am-border-strong);
  border-radius: var(--am-radius-sm);
  color: var(--am-text);
  background: var(--am-surface);
  cursor: pointer;
}

.confirm-dialog__close:hover {
  background: var(--am-hover-surface);
  border-color: var(--am-border-strong);
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

.confirm-dialog-enter-active,
.confirm-dialog-leave-active {
  transition: opacity 160ms ease;
}

.confirm-dialog-enter-active .confirm-dialog,
.confirm-dialog-leave-active .confirm-dialog {
  transition:
    opacity 160ms ease,
    transform 180ms cubic-bezier(0.2, 0.8, 0.2, 1);
}

.confirm-dialog-enter-from,
.confirm-dialog-leave-to,
.confirm-dialog-enter-from .confirm-dialog,
.confirm-dialog-leave-to .confirm-dialog {
  opacity: 0;
}

.confirm-dialog-enter-from .confirm-dialog,
.confirm-dialog-leave-to .confirm-dialog {
  transform: translateY(8px) scale(0.985);
}

@media (prefers-reduced-motion: reduce) {
  .confirm-dialog-enter-active,
  .confirm-dialog-leave-active,
  .confirm-dialog-enter-active .confirm-dialog,
  .confirm-dialog-leave-active .confirm-dialog {
    transition-duration: 0.01ms;
  }
}
</style>
