<template>
  <Teleport to="body">
    <div v-if="open && image" class="image-viewer" role="dialog" aria-modal="true" @keydown.esc="emit('close')">
      <div class="image-viewer__toolbar">
        <div class="image-viewer__title">
          <strong>{{ image.title }}</strong>
          <span>{{ image.width || '-' }} × {{ image.height || '-' }} / {{ image.mediaType || 'unknown' }}</span>
        </div>
        <div class="image-viewer__actions">
          <Button size="sm" variant="secondary" type="button" title="适配窗口" @click="fitImage">
            <Maximize2 :size="15" />
            适配
          </Button>
          <Button size="sm" variant="secondary" type="button" title="100% 分辨率" @click="showOriginalSize">
            100%
          </Button>
          <Button size="sm" variant="secondary" type="button" title="缩小" @click="zoomOut">
            <ZoomOut :size="15" />
          </Button>
          <Button size="sm" variant="secondary" type="button" title="放大" @click="zoomIn">
            <ZoomIn :size="15" />
          </Button>
          <Button size="sm" variant="secondary" type="button" title="重置位置" @click="resetView">
            <RotateCcw :size="15" />
          </Button>
          <Button class="image-viewer__close" size="sm" variant="secondary" type="button" title="关闭" aria-label="关闭图片查看器" @click="emit('close')">
            <X :size="17" />
          </Button>
        </div>
      </div>
      <div
        ref="viewportRef"
        class="image-viewer__viewport"
        @wheel.prevent="handleWheel"
        @mousedown="startPan"
        @dblclick="showOriginalSize"
      >
        <img
          v-if="image.src"
          ref="imageRef"
          :src="image.src"
          :alt="image.title"
          draggable="false"
          :style="imageStyle"
          @load="fitImage"
        />
        <div v-else class="image-viewer__empty">当前图片没有可浏览的 src</div>
      </div>
      <div class="image-viewer__status">
        <span>{{ Math.round(scale * 100) }}%</span>
        <span>{{ image.objectKey || 'inline-base64' }}</span>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import { Maximize2, RotateCcw, X, ZoomIn, ZoomOut } from '@lucide/vue'

import Button from './Button.vue'

interface ViewerImage {
  title: string
  src: string | null
  mediaType?: string | null
  width?: number | null
  height?: number | null
  objectKey?: string | null
}

const props = defineProps<{
  open: boolean
  image: ViewerImage | null
}>()

const emit = defineEmits<{
  close: []
}>()

const viewportRef = ref<HTMLElement | null>(null)
const imageRef = ref<HTMLImageElement | null>(null)
const scale = ref(1)
const offsetX = ref(0)
const offsetY = ref(0)
const panState = ref<{ startX: number; startY: number; offsetX: number; offsetY: number } | null>(null)

const imageStyle = computed(() => ({
  transform: `translate(${offsetX.value}px, ${offsetY.value}px) scale(${scale.value})`,
}))

watch(() => props.open, (open) => {
  if (!open) return
  resetView()
})

function fitImage(): void {
  const viewport = viewportRef.value
  const image = imageRef.value
  if (!viewport || !image) return
  const viewportBounds = viewport.getBoundingClientRect()
  const naturalWidth = image.naturalWidth || props.image?.width || 1
  const naturalHeight = image.naturalHeight || props.image?.height || 1
  scale.value = Math.min(viewportBounds.width / naturalWidth, viewportBounds.height / naturalHeight, 1)
  offsetX.value = 0
  offsetY.value = 0
}

function showOriginalSize(): void {
  scale.value = 1
  offsetX.value = 0
  offsetY.value = 0
}

function resetView(): void {
  scale.value = 1
  offsetX.value = 0
  offsetY.value = 0
  panState.value = null
}

function zoomIn(): void {
  scale.value = Math.min(scale.value * 1.25, 8)
}

function zoomOut(): void {
  scale.value = Math.max(scale.value / 1.25, 0.05)
}

function handleWheel(event: WheelEvent): void {
  const factor = event.deltaY < 0 ? 1.12 : 1 / 1.12
  scale.value = Math.min(Math.max(scale.value * factor, 0.05), 8)
}

function startPan(event: MouseEvent): void {
  if (event.button !== 0) return
  panState.value = {
    startX: event.clientX,
    startY: event.clientY,
    offsetX: offsetX.value,
    offsetY: offsetY.value,
  }
  document.addEventListener('mousemove', movePan)
  document.addEventListener('mouseup', stopPan)
}

function movePan(event: MouseEvent): void {
  const pan = panState.value
  if (!pan) return
  offsetX.value = pan.offsetX + event.clientX - pan.startX
  offsetY.value = pan.offsetY + event.clientY - pan.startY
}

function stopPan(): void {
  panState.value = null
  document.removeEventListener('mousemove', movePan)
  document.removeEventListener('mouseup', stopPan)
}

onUnmounted(() => {
  stopPan()
})
</script>