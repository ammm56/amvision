<template>
  <Teleport to="body">
    <Transition name="side-drawer">
      <div v-if="open" class="side-drawer__backdrop" @mousedown.self="closeDrawer">
        <aside
          ref="drawerRef"
          class="side-drawer"
          role="dialog"
          aria-modal="true"
          :aria-labelledby="titleId"
          tabindex="-1"
          @keydown.esc.prevent="closeDrawer"
          @keydown.tab="trapFocus"
        >
          <header class="side-drawer__header">
            <h2 :id="titleId">{{ title }}</h2>
            <button type="button" class="side-drawer__close" :aria-label="closeLabel" @click="closeDrawer">
              <X :size="16" />
            </button>
          </header>
          <div class="side-drawer__content">
            <slot />
          </div>
          <footer v-if="$slots.footer" class="side-drawer__footer">
            <slot name="footer" />
          </footer>
        </aside>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup lang="ts">
import { X } from '@lucide/vue'
import { nextTick, onBeforeUnmount, ref, useId, watch } from 'vue'

const props = defineProps<{
  open: boolean
  title: string
  closeLabel: string
}>()

const emit = defineEmits<{ close: [] }>()

const drawerRef = ref<HTMLElement | null>(null)
const titleId = `${useId()}-title`
let previouslyFocusedElement: HTMLElement | null = null
let previousBodyOverflow = ''
let drawerActive = false

function readFocusableElements(): HTMLElement[] {
  if (!drawerRef.value) return []
  return [...drawerRef.value.querySelectorAll<HTMLElement>(
    'button:not(:disabled), [href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex]:not([tabindex="-1"])',
  )]
}

function trapFocus(event: KeyboardEvent): void {
  const focusableElements = readFocusableElements()
  if (focusableElements.length === 0) {
    event.preventDefault()
    drawerRef.value?.focus()
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

function closeDrawer(): void {
  emit('close')
}

function openDrawer(): void {
  if (drawerActive) return
  drawerActive = true
  previouslyFocusedElement = document.activeElement instanceof HTMLElement ? document.activeElement : null
  previousBodyOverflow = document.body.style.overflow
  document.body.style.overflow = 'hidden'
  void nextTick(() => drawerRef.value?.focus({ preventScroll: true }))
}

function restorePage(): void {
  if (!drawerActive) return
  document.body.style.overflow = previousBodyOverflow
  previouslyFocusedElement?.focus({ preventScroll: true })
  previouslyFocusedElement = null
  drawerActive = false
}

watch(
  () => props.open,
  (open) => {
    if (open) openDrawer()
    else restorePage()
  },
  { immediate: true },
)

onBeforeUnmount(() => {
  restorePage()
})
</script>

<style scoped>
.side-drawer__backdrop {
  position: fixed;
  inset: 0;
  z-index: var(--am-z-modal);
  display: flex;
  justify-content: flex-end;
  background: var(--am-overlay);
}

.side-drawer {
  display: grid;
  grid-template-rows: auto minmax(0, 1fr) auto;
  width: min(680px, calc(100vw - 36px));
  height: 100dvh;
  border-left: 1px solid var(--am-border);
  outline: none;
  background: var(--am-surface-raised);
  box-shadow: var(--am-shadow-modal);
}

.side-drawer__header,
.side-drawer__footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--am-space-md);
  padding: var(--am-space-lg) var(--am-space-xl);
}

.side-drawer__header {
  border-bottom: 1px solid var(--am-border);
}

.side-drawer__header h2 {
  margin: 0;
  color: var(--am-text-strong);
  font-size: 18px;
}

.side-drawer__content {
  min-height: 0;
  overflow: auto;
  padding: var(--am-space-xl);
}

.side-drawer__footer {
  border-top: 1px solid var(--am-border);
}

.side-drawer__close {
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

.side-drawer__close:hover {
  border-color: var(--am-action-primary);
}

.side-drawer-enter-active,
.side-drawer-leave-active {
  transition: opacity 160ms ease;
}

.side-drawer-enter-active .side-drawer,
.side-drawer-leave-active .side-drawer {
  transition: transform 180ms cubic-bezier(.2, 0, 0, 1);
}

.side-drawer-enter-from,
.side-drawer-leave-to {
  opacity: 0;
}

.side-drawer-enter-from .side-drawer,
.side-drawer-leave-to .side-drawer {
  transform: translateX(24px);
}

@media (prefers-reduced-motion: reduce) {
  .side-drawer-enter-active,
  .side-drawer-leave-active,
  .side-drawer-enter-active .side-drawer,
  .side-drawer-leave-active .side-drawer {
    transition: none;
  }
}
</style>
