<template>
  <Teleport to="body">
    <Transition name="side-drawer" appear @after-leave="afterLeave">
      <div v-if="open" class="side-drawer__backdrop" :class="{ 'side-drawer__backdrop--plain': plain, 'side-drawer__backdrop--nonmodal': nonmodal }" :style="{ zIndex: order, background: covered || nonmodal ? 'transparent' : undefined }" @mousedown.self="closeDrawer">
        <aside
          ref="drawerRef"
          class="side-drawer"
          :class="[{ 'side-drawer--compact': size === 'compact', 'side-drawer--plain': plain }, panelClass]"
          :aria-busy="busy"
          role="dialog"
          :aria-modal="nonmodal ? undefined : true"
          :aria-labelledby="titleId"
          tabindex="-1"
          @keydown.esc.stop.prevent="closeDrawer"
          @keydown.tab="!nonmodal && trapFocus($event)"
        >
          <header class="side-drawer__header">
            <h2 :id="titleId">{{ title }}</h2>
            <button type="button" class="side-drawer__close" :aria-label="closeLabel" :disabled="busy" @click="closeDrawer">
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
import { nextTick, ref, useId, watch } from 'vue'
import { useModalLayer } from './modal-layer'

const props = defineProps<{
  open: boolean
  title: string
  closeLabel: string
  size?: 'default' | 'compact'
  busy?: boolean
  /** 资源详情使用无边框关闭图标，其他现有抽屉保持原样。 */
  plain?: boolean
  panelClass?: string
  /** 对象检查允许与背景图像同时操作；其他资源抽屉仍为模态。 */
  nonmodal?: boolean
}>()

const emit = defineEmits<{ close: []; 'after-leave': [] }>()

const drawerRef = ref<HTMLElement | null>(null)
let opener: HTMLElement | null = null
const titleId = `${useId()}-title`
const { activate, deactivate, trapFocus, isTop, order, covered } = useModalLayer(drawerRef)

function closeDrawer(): void {
  if (props.open && !props.busy && (props.nonmodal || isTop())) {
    if (props.nonmodal && opener?.isConnected && drawerRef.value?.contains(document.activeElement)) opener.focus({ preventScroll: true })
    emit('close')
  }
}

function afterLeave(): void {
  // 退场结束后再释放背景与焦点，避免动画途中点击穿透或提前卸载。
  if (props.open) return
  deactivate()
  emit('after-leave')
}

// 保存或切换状态会移除当前按钮；仅最上层抽屉接回焦点，不抢内层确认框焦点。
watch(drawerRef, (drawer, _, onCleanup) => {
  if (!drawer) return
  const observer = new MutationObserver(() => {
    const focused = document.activeElement
    if (props.open && isTop() && (focused === document.body || !focused?.isConnected || (drawer.contains(focused) && focused.matches(':disabled')))) {
      drawer.focus({ preventScroll: true })
    }
  })
  observer.observe(drawer, { childList: true, subtree: true, attributes: true, attributeFilter: ['disabled'] })
  onCleanup(() => observer.disconnect())
}, { flush: 'post' })

watch(() => props.open, (open) => {
  if (open) {
    if (props.nonmodal) {
      opener = document.activeElement instanceof HTMLElement ? document.activeElement : null
      void nextTick(() => drawerRef.value?.focus({ preventScroll: true }))
    } else void activate()
  } else if (props.nonmodal && opener?.isConnected && drawerRef.value?.contains(document.activeElement)) {
    opener.focus({ preventScroll: true })
  }
}, { immediate: true, flush: 'pre' })
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

.side-drawer__backdrop--nonmodal { pointer-events:none; }
.side-drawer__backdrop--nonmodal .side-drawer { pointer-events:auto; }

.side-drawer--compact { width: min(520px, 100vw); }
.side-drawer__backdrop--plain { background:color-mix(in srgb, var(--am-overlay) 45%, transparent); }
.side-drawer--plain .side-drawer__header,
.side-drawer--plain .side-drawer__footer { padding: 20px 28px; }
.side-drawer--plain .side-drawer__content { padding: 20px 28px; }
.side-drawer--plain .side-drawer__close { border-color: transparent; background: transparent; }

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
  background: var(--am-hover-surface);
  border-color: var(--am-border-strong);
}

.side-drawer-enter-active,
.side-drawer-leave-active {
  transition: opacity var(--am-motion-panel, 200ms) var(--am-ease-standard, ease);
}

.side-drawer-enter-active .side-drawer,
.side-drawer-leave-active .side-drawer {
  transition: transform var(--am-motion-panel, 200ms) var(--am-ease-standard, ease);
}

.side-drawer-enter-from,
.side-drawer-leave-to {
  opacity: 0;
}

.side-drawer-enter-from .side-drawer,
.side-drawer-leave-to .side-drawer {
  transform: translateX(100%);
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
