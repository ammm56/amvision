<template>
  <span
    ref="triggerRef"
    class="info-hint"
    tabindex="0"
    :aria-label="text"
    @mouseenter="showBubble"
    @mouseleave="hideBubble"
    @focus="showBubble"
    @blur="hideBubble"
  >
    <CircleAlert :size="14" />
  </span>
  <Teleport to="body">
    <span v-if="open" ref="bubbleRef" class="info-hint__bubble is-visible" :style="bubbleStyle" role="tooltip">{{ text }}</span>
  </Teleport>
</template>

<script setup lang="ts">
import { nextTick, onBeforeUnmount, ref } from 'vue'
import { CircleAlert } from '@lucide/vue'

defineProps<{
  text: string
}>()

const triggerRef = ref<HTMLElement | null>(null)
const bubbleRef = ref<HTMLElement | null>(null)
const open = ref(false)
const bubbleStyle = ref<Record<string, string>>({})

let stopViewportListeners: (() => void) | null = null

function bindViewportListeners(): void {
  if (stopViewportListeners) return
  const handleViewportChange = () => updatePosition()
  window.addEventListener('scroll', handleViewportChange, true)
  window.addEventListener('resize', handleViewportChange)
  stopViewportListeners = () => {
    window.removeEventListener('scroll', handleViewportChange, true)
    window.removeEventListener('resize', handleViewportChange)
  }
}

function unbindViewportListeners(): void {
  stopViewportListeners?.()
  stopViewportListeners = null
}

async function showBubble(): Promise<void> {
  open.value = true
  bindViewportListeners()
  await nextTick()
  updatePosition()
}

function hideBubble(): void {
  open.value = false
  unbindViewportListeners()
}

function updatePosition(): void {
  if (!triggerRef.value || !bubbleRef.value) return
  const triggerRect = triggerRef.value.getBoundingClientRect()
  const bubbleRect = bubbleRef.value.getBoundingClientRect()
  const viewportPadding = 8
  const bubbleOffset = 10

  let top = triggerRect.top - bubbleRect.height - bubbleOffset
  if (top < viewportPadding) {
    top = triggerRect.bottom + bubbleOffset
  }

  const centeredLeft = triggerRect.left + triggerRect.width / 2 - bubbleRect.width / 2
  const maxLeft = window.innerWidth - bubbleRect.width - viewportPadding
  const left = Math.min(Math.max(viewportPadding, centeredLeft), Math.max(viewportPadding, maxLeft))

  bubbleStyle.value = {
    top: `${Math.round(top)}px`,
    left: `${Math.round(left)}px`,
  }
}

onBeforeUnmount(() => {
  unbindViewportListeners()
})
</script>