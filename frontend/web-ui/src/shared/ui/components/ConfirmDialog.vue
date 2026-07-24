<template>
  <div class="confirm-dialog-backdrop" @click="emit('cancel')">
    <section
      class="confirm-dialog"
      role="dialog"
      aria-modal="true"
      :aria-label="title"
      @click.stop
      @keydown.esc.prevent="emit('cancel')"
    >
      <header class="confirm-dialog__header">
        <div>
          <div class="confirm-dialog__title">
            <h2>{{ title }}</h2>
            <InfoHint v-if="details" :text="details" />
          </div>
        </div>
        <button type="button" class="confirm-dialog__close" :aria-label="cancelLabel" @click="emit('cancel')">
          <X :size="16" />
        </button>
      </header>

      <p class="confirm-dialog__message">{{ message }}</p>

      <footer class="confirm-dialog__actions">
        <Button variant="secondary" :disabled="busy" @click="emit('cancel')">{{ cancelLabel }}</Button>
        <Button :variant="confirmVariant" :disabled="busy" @click="emit('confirm')">{{ confirmLabel }}</Button>
      </footer>
    </section>
  </div>
</template>

<script setup lang="ts">
import { X } from '@lucide/vue'

import Button from './Button.vue'
import InfoHint from './InfoHint.vue'

withDefaults(
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
</script>

<style scoped>
.confirm-dialog-backdrop {
  position: fixed;
  inset: 0;
  z-index: 90;
  display: grid;
  place-items: center;
  padding: 18px;
  background: rgb(16 20 24 / 0.42);
}

.confirm-dialog {
  display: grid;
  gap: 16px;
  width: min(520px, calc(100vw - 36px));
  padding: 18px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: var(--surface);
  box-shadow: 0 24px 48px rgb(0 0 0 / 0.2);
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
  border-radius: 8px;
  color: var(--text);
  background: var(--button-secondary-bg);
  cursor: pointer;
}

.confirm-dialog__close:hover {
  border-color: var(--accent);
}

.confirm-dialog__actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  flex-wrap: wrap;
}
</style>
