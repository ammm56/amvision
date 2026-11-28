<template>
  <div class="inf-viewer" :class="{ 'inf-viewer--fullscreen': fullscreen }">
    <slot name="header" />

    <div class="inf-viewer__bar">
      <div class="inf-viewer__bar-group" role="group" aria-label="画布缩放控制">
        <button
          type="button"
          class="inf-tool-btn"
          :class="{ 'is-active': !userAdjustedView && Boolean(imageSrc) }"
          :disabled="!imageSrc"
          title="适应画布"
          @click="resetToFit"
        >
          <Maximize2 :size="13" />
          <span>适配</span>
        </button>
        <button
          type="button"
          class="inf-tool-btn"
          :disabled="!imageSrc"
          title="100% 原始尺寸"
          @click="zoomToOne"
        >
          1:1
        </button>

        <div class="inf-zoom-stepper">
          <button
            type="button"
            class="inf-zoom-stepper__btn"
            :disabled="!imageSrc"
            title="缩小"
            @click="zoomBy(0.8)"
          >
            <Minus :size="13" />
          </button>
          <span class="inf-zoom-stepper__label">
            {{ userAdjustedView ? `${Math.round(zoom * 100)}%` : '适配' }}
          </span>
          <button
            type="button"
            class="inf-zoom-stepper__btn"
            :disabled="!imageSrc"
            title="放大"
            @click="zoomBy(1.25)"
          >
            <Plus :size="13" />
          </button>
        </div>
      </div>

      <div class="inf-viewer__bar-spacer" />

      <div class="inf-viewer__bar-group">
        <template v-if="taskType === 'segmentation'">
          <label class="inf-switch-control" :class="{ 'is-disabled': !hasResult }">
            <button
              type="button"
              role="switch"
              class="inf-switch"
              :class="{ 'is-on': showPredictions && layers.masks }"
              :aria-checked="showPredictions && layers.masks"
              :disabled="!hasResult"
              @click="toggleSegmentationMask"
            >
              <span class="inf-switch__thumb" />
            </button>
            <span>显示掩膜</span>
          </label>
          <select
            v-if="hasResult"
            :value="maskOpacity"
            class="inf-opacity-select"
            aria-label="掩膜透明度"
            @change="emit('update:maskOpacity', Number(($event.target as HTMLSelectElement).value))"
          >
            <option :value="0.2">20%</option>
            <option :value="0.35">35%</option>
            <option :value="0.5">50%</option>
            <option :value="0.7">70%</option>
          </select>
        </template>

        <template v-else-if="taskType === 'pose'">
          <label class="inf-switch-control" :class="{ 'is-disabled': !hasResult }">
            <button
              type="button"
              role="switch"
              class="inf-switch"
              :class="{ 'is-on': showPredictions && layers.keypoints }"
              :aria-checked="showPredictions && layers.keypoints"
              :disabled="!hasResult"
              @click="toggleLayer('keypoints')"
            >
              <span class="inf-switch__thumb" />
            </button>
            <span>显示关键点</span>
          </label>
          <label class="inf-switch-control" :class="{ 'is-disabled': !hasResult }">
            <button
              type="button"
              role="switch"
              class="inf-switch"
              :class="{ 'is-on': showPredictions && layers.skeleton }"
              :aria-checked="showPredictions && layers.skeleton"
              :disabled="!hasResult"
              @click="toggleLayer('skeleton')"
            >
              <span class="inf-switch__thumb" />
            </button>
            <span>显示连线</span>
          </label>
        </template>

        <template v-else-if="taskType !== 'classification'">
          <label class="inf-switch-control" :class="{ 'is-disabled': !hasResult }">
            <button
              type="button"
              role="switch"
              class="inf-switch"
              :class="{ 'is-on': showPredictions }"
              :aria-checked="showPredictions"
              :disabled="!hasResult"
              data-toggle-predictions
              @click="togglePredictions"
            >
              <span class="inf-switch__thumb" />
            </button>
            <span>显示预测</span>
          </label>
        </template>

        <button
          type="button"
          class="inf-tool-btn"
          :class="{ 'is-active': inspectorOpen }"
          :disabled="!hasResult"
          data-toggle-inspector
          @click="emit('toggle-inspector')"
        >
          <List :size="14" />
          <span>结果详情</span>
        </button>

        <span v-if="$slots['bar-end'] || (allowFullscreen && !fullscreen)" class="inf-bar-divider" />

        <slot name="bar-end">
          <button
            v-if="allowFullscreen && !fullscreen"
            type="button"
            class="inf-tool-btn"
            :disabled="!imageSrc"
            data-open-fullscreen
            @click="emit('toggle-fullscreen')"
          >
            <Maximize :size="14" />
            <span>打开大图</span>
          </button>
        </slot>
      </div>
    </div>

    <div class="inf-viewer__body">
      <div
        ref="viewportRef"
        class="inf-viewer__viewport"
      :class="{
        'inf-viewer__viewport--with-image': Boolean(imageSrc),
        'inf-viewer__viewport--empty': !imageSrc,
      }"
      @wheel="handleWheel"
      @pointerdown="handlePointerDown"
      @pointermove="handlePointerMove"
      @pointerup="handlePointerUp"
      @pointercancel="handlePointerUp"
    >
      <div v-if="overloadMessage" class="inf-viewport-banner inf-viewport-banner--warning">
        <div class="inf-viewport-banner__content">
          <AlertCircle :size="16" class="inf-viewport-banner__icon" />
          <div>
            <strong>推理实例已满载</strong>
            <p>{{ overloadMessage }}</p>
          </div>
        </div>
        <button
          type="button"
          class="inf-viewport-banner__close"
          aria-label="关闭提示"
          @click="emit('dismiss-overload')"
        >
          <X :size="14" />
        </button>
      </div>

      <div v-if="noDeployment" class="inf-viewer__empty inf-viewer__empty--dashed">
        <ServerOff :size="38" />
        <strong>请先启动一个部署</strong>
        <div class="inf-empty-actions">
          <Button variant="primary" size="sm" @click="emit('go-deployments')">
            <ExternalLink :size="14" />
            前往部署
          </Button>
          <Button variant="secondary" size="sm" @click="emit('refresh')">
            <RefreshCw :size="14" />
            刷新
          </Button>
        </div>
      </div>

      <div v-else-if="sourceError && !imageSrc" class="inf-viewer__empty inf-viewer__empty--dashed">
        <div class="inf-empty-error-icon">
          <ImageIcon :size="36" />
          <AlertCircle :size="16" class="inf-empty-error-badge" />
        </div>
        <strong>无法载入输入</strong>
        <p>{{ sourceError }}</p>
      </div>

      <div v-else-if="loadingImage && !imageSrc" class="inf-viewer__empty">
        <RefreshCw :size="28" class="inf-spin" />
        <p>加载图像中...</p>
      </div>

      <div v-else-if="!imageSrc" class="inf-viewer__empty">
        <ImageIcon :size="36" />
        <p>选择图片后开始推理</p>
      </div>

      <div v-else class="inf-viewer__stage" :style="stageStyle">
        <img
          :src="imageSrc"
          :alt="imageAlt"
          class="inf-viewer__img"
          draggable="false"
          @load="handleImageLoad"
        />
        <svg
          v-if="showSvgOverlay"
          class="inf-viewer__svg"
          :viewBox="`0 0 ${resolvedWidth} ${resolvedHeight}`"
          preserveAspectRatio="none"
        >
          <g
            v-for="item in visibleItems"
            :key="item.id"
            class="inf-overlay-item"
            :class="{ 'is-selected': selectedItemId === item.id }"
            @click.stop="emit('select-item', item.id)"
          >
            <template v-if="taskType === 'segmentation' && layers.masks && item.segments">
              <polygon
                v-for="(poly, polyIndex) in item.segments"
                :key="`${item.id}-seg-${polyIndex}`"
                :points="pointsToSvgString(poly)"
                :fill="item.color"
                :fill-opacity="selectedItemId === item.id ? Math.min(0.8, maskOpacity + 0.14) : maskOpacity"
                :stroke="showContours ? item.color : 'none'"
                :stroke-width="selectedItemId === item.id ? strokeWidth * 1.4 : strokeWidth * 0.9"
              />
            </template>

            <polygon
              v-if="taskType === 'obb' && layers.boxes && item.obbPolygon"
              :points="pointsToSvgString(item.obbPolygon)"
              :fill="selectedItemId === item.id ? item.color : 'transparent'"
              :fill-opacity="selectedItemId === item.id ? 0.14 : 0"
              :stroke="item.color"
              :stroke-width="selectedItemId === item.id ? strokeWidth * 1.6 : strokeWidth"
            />

            <rect
              v-else-if="taskType !== 'pose' && taskType !== 'segmentation' && layers.boxes && item.bboxXyxy"
              :x="item.bboxXyxy[0]"
              :y="item.bboxXyxy[1]"
              :width="Math.max(1, item.bboxXyxy[2] - item.bboxXyxy[0])"
              :height="Math.max(1, item.bboxXyxy[3] - item.bboxXyxy[1])"
              :fill="selectedItemId === item.id ? item.color : 'transparent'"
              :fill-opacity="selectedItemId === item.id ? 0.12 : 0"
              :stroke="item.color"
              :stroke-width="boxStrokeWidth(item)"
            />

            <template v-if="taskType === 'pose' && item.keypoints">
              <template v-if="layers.skeleton">
                <line
                  v-for="(edge, edgeIdx) in visiblePoseEdges(item)"
                  :key="`${item.id}-edge-${edgeIdx}`"
                  :x1="edge.x1"
                  :y1="edge.y1"
                  :x2="edge.x2"
                  :y2="edge.y2"
                  stroke="#00d992"
                  :stroke-width="strokeWidth * 0.95"
                  stroke-linecap="round"
                />
              </template>
              <template v-if="layers.keypoints">
                <g
                  v-for="(kp, kpIdx) in visibleKeypoints(item)"
                  :key="`${item.id}-kp-${kpIdx}`"
                >
                  <circle
                    :cx="kp.x"
                    :cy="kp.y"
                    :r="keypointRadius"
                    fill="#00d992"
                    stroke="#ffffff"
                    :stroke-width="strokeWidth * 0.6"
                  />
                  <g
                    v-if="layers.labels"
                    :transform="`translate(${kp.x - keypointRadius}, ${Math.max(labelHeight, kp.y - keypointRadius * 1.5)})`"
                  >
                    <rect
                      x="0"
                      :y="-labelHeight"
                      :width="estimateTextWidth(`${kpIdx + 1} ${(kp.confidence ?? 1).toFixed(2)}`)"
                      :height="labelHeight"
                      rx="2"
                      fill="#00d992"
                    />
                    <text
                      :x="labelPadding"
                      :y="-labelPadding * 0.72"
                      fill="#ffffff"
                      :font-size="labelFontSize"
                      font-weight="600"
                    >
                      {{ kpIdx + 1 }} {{ (kp.confidence ?? 1).toFixed(2) }}
                    </text>
                  </g>
                </g>
              </template>
            </template>

            <g
              v-if="taskType !== 'pose' && layers.labels && anchorPosition(item)"
              :transform="`translate(${anchorPosition(item)![0]}, ${anchorPosition(item)![1]})`"
            >
              <path
                :d="
                  labelBoxPath(
                    estimateTextWidth(formatOverlayLabel(item)),
                    labelHeight,
                    Math.min(2, labelHeight * 0.12),
                    labelOverlap(item),
                  )
                "
                :fill="item.color"
              />
              <text
                :x="labelPadding"
                :y="-labelPadding * 0.72"
                fill="#ffffff"
                :font-size="labelFontSize"
                font-weight="600"
              >
                {{ formatOverlayLabel(item) }}
              </text>
            </g>
          </g>
        </svg>
      </div>
      </div>

      <slot name="below-canvas" />
      <slot name="overlay" />
    </div>

    <slot name="footer" />
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import {
  AlertCircle,
  ExternalLink,
  Image as ImageIcon,
  List,
  Maximize,
  Maximize2,
  Minus,
  Plus,
  RefreshCw,
  ServerOff,
  X,
} from '@lucide/vue'

import type { ModelTaskType } from '@/modules/deployments/services/deployment.service'
import Button from '@/shared/ui/components/Button.vue'
import {
  COCO_POSE_SKELETON_EDGES,
  pointsToSvgString,
  type CanvasViewMode,
  type InferenceLayerVisibility,
  type OverlayRenderItem,
} from './inference-overlay.utils'

const props = withDefaults(
  defineProps<{
    imageSrc: string | null
    imageAlt?: string
    imageWidth?: number
    imageHeight?: number
    taskType: ModelTaskType
    hasResult?: boolean
    loadingImage?: boolean
    inspectorOpen?: boolean
    noDeployment?: boolean
    sourceError?: string | null
    overloadMessage?: string | null
    allItems: OverlayRenderItem[]
    visibleItems: OverlayRenderItem[]
    selectedItemId?: string | null
    viewMode: CanvasViewMode
    layers: InferenceLayerVisibility
    maskOpacity?: number
    showContours?: boolean
    minDisplayScore: number
    selectedClasses: string[]
    fullscreen?: boolean
    allowFullscreen?: boolean
  }>(),
  {
    imageAlt: '推理图像画布',
    imageWidth: 0,
    imageHeight: 0,
    hasResult: false,
    loadingImage: false,
    inspectorOpen: false,
    noDeployment: false,
    sourceError: null,
    overloadMessage: null,
    selectedItemId: null,
    maskOpacity: 0.35,
    showContours: true,
    fullscreen: false,
    allowFullscreen: true,
  },
)

const emit = defineEmits<{
  'update:viewMode': [mode: CanvasViewMode]
  'update:layers': [layers: InferenceLayerVisibility]
  'update:maskOpacity': [value: number]
  'update:minDisplayScore': [score: number]
  'update:selectedClasses': [classes: string[]]
  'select-item': [id: string]
  'toggle-inspector': []
  'toggle-fullscreen': []
  'dismiss-overload': []
  'go-deployments': []
  refresh: []
  'image-loaded': [dims: { width: number; height: number }]
}>()

const viewportRef = ref<HTMLElement | null>(null)
const naturalWidth = ref(0)
const naturalHeight = ref(0)
const zoom = ref(1)
const panX = ref(0)
const panY = ref(0)
const userAdjustedView = ref(false)
const dragging = ref(false)
let dragStartX = 0
let dragStartY = 0
let dragOriginX = 0
let dragOriginY = 0
let resizeObserver: ResizeObserver | null = null

const resolvedWidth = computed(() => Math.max(1, props.imageWidth || naturalWidth.value || 640))
const resolvedHeight = computed(() => Math.max(1, props.imageHeight || naturalHeight.value || 480))
const showPredictions = computed(() => props.viewMode !== 'original')
const showSvgOverlay = computed(
  () => showPredictions.value && props.taskType !== 'classification' && props.visibleItems.length > 0,
)

const scaleReference = computed(() => Math.max(resolvedWidth.value, resolvedHeight.value))
const strokeWidth = computed(() => Math.max(2, scaleReference.value * 0.0032))
const keypointRadius = computed(() => Math.max(3.5, scaleReference.value * 0.0055))
const labelFontSize = computed(() => Math.max(14, Math.round(scaleReference.value * 0.022)))
const labelPadding = computed(() => Math.max(5, Math.round(labelFontSize.value * 0.38)))
const labelHeight = computed(() => Math.round(labelFontSize.value + labelPadding.value * 1.5))

const stageStyle = computed(() => ({
  width: `${resolvedWidth.value}px`,
  height: `${resolvedHeight.value}px`,
  transform: `translate(${panX.value}px, ${panY.value}px) scale(${zoom.value})`,
  transformOrigin: '0 0',
}))

onMounted(() => {
  if (typeof ResizeObserver !== 'undefined' && viewportRef.value) {
    resizeObserver = new ResizeObserver(() => {
      if (!dragging.value && !userAdjustedView.value) {
        fitToContainer()
      }
    })
    resizeObserver.observe(viewportRef.value)
  }
})

onBeforeUnmount(() => {
  resizeObserver?.disconnect()
})

watch(
  () => props.imageSrc,
  async () => {
    userAdjustedView.value = false
    naturalWidth.value = 0
    naturalHeight.value = 0
    await nextTick()
    fitToContainer()
  },
)

function handleImageLoad(event: Event): void {
  const img = event.target as HTMLImageElement | null
  if (!img) return
  naturalWidth.value = img.naturalWidth || 0
  naturalHeight.value = img.naturalHeight || 0
  if (naturalWidth.value > 0 && naturalHeight.value > 0) {
    emit('image-loaded', { width: naturalWidth.value, height: naturalHeight.value })
  }
  userAdjustedView.value = false
  fitToContainer()
}

function fitToContainer(): void {
  const viewport = viewportRef.value
  if (!viewport) return
  const vw = viewport.clientWidth
  const vh = viewport.clientHeight
  const availWidth = vw - 24
  const availHeight = vh - 24
  if (availWidth <= 0 || availHeight <= 0) return
  const w = resolvedWidth.value
  const h = resolvedHeight.value
  const nextZoom = Math.min(availWidth / w, availHeight / h, 4)
  zoom.value = Number(Math.max(0.05, nextZoom).toFixed(4))
  panX.value = Math.round((vw - w * zoom.value) / 2)
  panY.value = Math.round((vh - h * zoom.value) / 2)
}

function resetToFit(): void {
  userAdjustedView.value = false
  fitToContainer()
}

function zoomToOne(): void {
  const viewport = viewportRef.value
  userAdjustedView.value = true
  zoom.value = 1
  if (!viewport) return
  panX.value = Math.round((viewport.clientWidth - resolvedWidth.value) / 2)
  panY.value = Math.round((viewport.clientHeight - resolvedHeight.value) / 2)
}

function zoomBy(factor: number): void {
  const viewport = viewportRef.value
  userAdjustedView.value = true
  const nextZoom = Math.min(12, Math.max(0.05, zoom.value * factor))
  if (!viewport) {
    zoom.value = nextZoom
    return
  }
  const cx = viewport.clientWidth / 2
  const cy = viewport.clientHeight / 2
  const scaleRatio = nextZoom / zoom.value
  panX.value = cx - (cx - panX.value) * scaleRatio
  panY.value = cy - (cy - panY.value) * scaleRatio
  zoom.value = Number(nextZoom.toFixed(4))
}

function handleWheel(event: WheelEvent): void {
  if (!props.imageSrc) return
  const target = event.target as HTMLElement | null
  if (target?.closest('[data-inspector-panel]')) return
  event.preventDefault()
  userAdjustedView.value = true
  const rect = (event.currentTarget as HTMLElement).getBoundingClientRect()
  const localX = event.clientX - rect.left
  const localY = event.clientY - rect.top
  const factor = event.deltaY < 0 ? 1.12 : 0.89
  const nextZoom = Math.min(12, Math.max(0.05, zoom.value * factor))
  const scaleRatio = nextZoom / zoom.value
  panX.value = localX - (localX - panX.value) * scaleRatio
  panY.value = localY - (localY - panY.value) * scaleRatio
  zoom.value = Number(nextZoom.toFixed(4))
}

function handlePointerDown(event: PointerEvent): void {
  if (event.button !== 0 || !props.imageSrc) return
  const target = event.target as HTMLElement | null
  if (target?.closest('[data-inspector-panel]') || target?.closest('.inf-overlay-item')) {
    return
  }
  dragging.value = true
  userAdjustedView.value = true
  dragStartX = event.clientX
  dragStartY = event.clientY
  dragOriginX = panX.value
  dragOriginY = panY.value
  ;(event.currentTarget as HTMLElement).setPointerCapture?.(event.pointerId)
}

function handlePointerMove(event: PointerEvent): void {
  if (!dragging.value) return
  panX.value = dragOriginX + (event.clientX - dragStartX)
  panY.value = dragOriginY + (event.clientY - dragStartY)
}

function handlePointerUp(event: PointerEvent): void {
  if (!dragging.value) return
  dragging.value = false
  ;(event.currentTarget as HTMLElement).releasePointerCapture?.(event.pointerId)
}

function togglePredictions(): void {
  emit('update:viewMode', showPredictions.value ? 'original' : 'overlay')
}

function toggleSegmentationMask(): void {
  if (!showPredictions.value) {
    emit('update:viewMode', 'overlay')
    emit('update:layers', { ...props.layers, masks: true })
    return
  }
  emit('update:layers', { ...props.layers, masks: !props.layers.masks })
}

function toggleLayer(key: keyof InferenceLayerVisibility): void {
  if (!showPredictions.value) {
    emit('update:viewMode', 'overlay')
  }
  emit('update:layers', {
    ...props.layers,
    [key]: !props.layers[key],
  })
}

function boxStrokeWidth(item: OverlayRenderItem): number {
  return props.selectedItemId === item.id ? strokeWidth.value * 1.6 : strokeWidth.value
}

function anchorPosition(item: OverlayRenderItem): [number, number] | null {
  if (item.obbPolygon && item.obbPolygon.length > 0) {
    let topPt = item.obbPolygon[0]
    for (const pt of item.obbPolygon) {
      if (pt[1] < topPt[1]) topPt = pt
    }
    return [topPt[0], Math.max(labelHeight.value, topPt[1])]
  }
  if (item.bboxXyxy) {
    // SVG stroke 居中绘制，外左/外上边缘位于坐标 - halfStroke
    const halfStroke = boxStrokeWidth(item) / 2
    return [item.bboxXyxy[0] - halfStroke, Math.max(labelHeight.value, item.bboxXyxy[1] - halfStroke)]
  }
  return null
}

function labelOverlap(item: OverlayRenderItem): number {
  if (!item.bboxXyxy) return 0
  const halfStroke = boxStrokeWidth(item) / 2
  return item.bboxXyxy[1] - halfStroke >= labelHeight.value ? 0.5 : 0
}

function labelBoxPath(width: number, height: number, radius: number, overlap: number): string {
  const r = Math.min(radius, width / 2, height / 2)
  return [
    `M 0 ${overlap}`,
    `L 0 ${-height + r}`,
    `Q 0 ${-height} ${r} ${-height}`,
    `L ${width - r} ${-height}`,
    `Q ${width} ${-height} ${width} ${-height + r}`,
    `L ${width} ${overlap}`,
    'Z',
  ].join(' ')
}

function formatOverlayLabel(item: OverlayRenderItem): string {
  return `${item.index}  ${item.className}  ${item.score.toFixed(2)}`
}

function estimateTextWidth(text: string): number {
  return Math.max(labelFontSize.value * 2, text.length * labelFontSize.value * 0.62 + labelPadding.value * 2)
}

function visibleKeypoints(item: OverlayRenderItem) {
  if (!item.keypoints) return []
  return item.keypoints.filter((kp) => (kp.confidence ?? 1) >= item.keypointThreshold)
}

function visiblePoseEdges(item: OverlayRenderItem): Array<{ x1: number; y1: number; x2: number; y2: number }> {
  const kps = item.keypoints ?? []
  const edges: Array<{ x1: number; y1: number; x2: number; y2: number }> = []
  for (const [startIdx, endIdx] of COCO_POSE_SKELETON_EDGES) {
    const start = kps[startIdx]
    const end = kps[endIdx]
    if (!start || !end) continue
    if ((start.confidence ?? 1) < item.keypointThreshold || (end.confidence ?? 1) < item.keypointThreshold) {
      continue
    }
    edges.push({ x1: start.x, y1: start.y, x2: end.x, y2: end.y })
  }
  return edges
}

defineExpose({ fitToContainer, resetToFit, zoomToOne })
</script>

<style scoped>
.inf-viewer {
  position: relative;
  display: flex;
  flex-direction: column;
  width: 100%;
  height: 100%;
  min-width: 0;
  min-height: 0;
  background: var(--am-surface);
  border: 1px solid var(--am-border);
  border-radius: var(--am-radius-md);
  overflow: hidden;
}

.inf-viewer--fullscreen {
  border-radius: 0;
  border: none;
}

.inf-viewer__bar {
  display: flex;
  align-items: center;
  flex-wrap: nowrap;
  gap: 8px;
  padding: 8px 14px;
  border-bottom: 1px solid var(--am-border);
  background: var(--am-surface);
  overflow-x: auto;
  scrollbar-width: none;
}

.inf-viewer__bar-group {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  flex: none;
}

.inf-viewer__bar-spacer {
  flex: 1 1 auto;
}

.inf-tool-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  height: 30px;
  padding: 0 10px;
  border-radius: 6px;
  border: 1px solid var(--am-border);
  background: var(--am-surface);
  color: var(--am-text);
  font-size: 12px;
  font-weight: 500;
  white-space: nowrap;
  cursor: pointer;
}

.inf-tool-btn:hover:not(:disabled) {
  background: var(--am-hover-surface);
  color: var(--am-text-strong);
}

.inf-tool-btn.is-active {
  border-color: var(--am-action-primary);
  background: var(--am-action-soft);
  color: var(--am-action-primary);
  font-weight: 600;
}

.inf-tool-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.inf-zoom-stepper {
  display: inline-flex;
  align-items: center;
  height: 30px;
  border: 1px solid var(--am-border);
  border-radius: 6px;
  background: var(--am-surface);
  overflow: hidden;
}

.inf-zoom-stepper__btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 100%;
  border: none;
  background: transparent;
  color: var(--am-text);
  cursor: pointer;
}

.inf-zoom-stepper__btn:hover:not(:disabled) {
  background: var(--am-hover-surface);
}

.inf-zoom-stepper__btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.inf-zoom-stepper__label {
  min-width: 48px;
  padding: 0 8px;
  text-align: center;
  font-size: 12px;
  color: var(--am-text-strong);
  border-left: 1px solid var(--am-border);
  border-right: 1px solid var(--am-border);
  line-height: 28px;
  font-variant-numeric: tabular-nums;
}

.inf-switch-control {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  font-size: 12px;
  color: var(--am-text-strong);
  white-space: nowrap;
}

.inf-switch-control.is-disabled {
  opacity: 0.5;
}

.inf-switch {
  position: relative;
  width: 34px;
  height: 20px;
  border-radius: 999px;
  border: none;
  padding: 2px;
  background: var(--am-border-strong);
  cursor: pointer;
  transition: background-color 140ms ease;
}

.inf-switch.is-on {
  background: var(--am-action-primary);
}

.inf-switch:disabled {
  cursor: not-allowed;
}

.inf-switch__thumb {
  display: block;
  width: 16px;
  height: 16px;
  border-radius: 50%;
  background: #ffffff;
  transition: transform 140ms ease;
}

.inf-switch.is-on .inf-switch__thumb {
  transform: translateX(14px);
}

.inf-opacity-select {
  height: 28px;
  padding: 0 6px;
  border: 1px solid var(--am-border);
  border-radius: 6px;
  background: var(--am-input);
  color: var(--am-text);
  font-size: 12px;
}

.inf-bar-divider {
  width: 1px;
  height: 18px;
  background: var(--am-border);
}

.inf-viewer__body {
  position: relative;
  flex: 1 1 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.inf-viewer__viewport {
  position: relative;
  flex: 1 1 0;
  min-height: 360px;
  overflow: hidden;
  cursor: grab;
  user-select: none;
}

.inf-viewer__viewport:active {
  cursor: grabbing;
}

.inf-viewer__viewport--with-image {
  background: var(--am-surface-muted);
}

.inf-viewer__viewport--empty {
  cursor: default;
  background: var(--am-surface);
  padding: 12px 14px;
  display: flex;
  flex-direction: column;
}

.inf-viewport-banner {
  position: relative;
  z-index: 6;
  margin: 10px 14px 0;
  padding: 10px 14px;
  border-radius: 8px;
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.inf-viewport-banner--warning {
  border: 1px solid #f59e0b;
  background: color-mix(in srgb, #f59e0b 12%, var(--am-surface));
}

.inf-viewport-banner__content {
  display: flex;
  align-items: flex-start;
  gap: 10px;
}

.inf-viewport-banner__icon {
  color: #d97706;
  margin-top: 2px;
  flex: none;
}

.inf-viewport-banner__content strong {
  display: block;
  font-size: 13px;
  color: #d97706;
}

.inf-viewport-banner__content p {
  margin: 2px 0 0;
  font-size: 12px;
  color: var(--am-text);
}

.inf-viewport-banner__close {
  border: none;
  background: transparent;
  color: var(--am-text-muted);
  cursor: pointer;
  padding: 2px;
}

.inf-viewer__empty {
  width: 100%;
  height: 100%;
  flex: 1 1 auto;
  display: grid;
  place-content: center;
  justify-items: center;
  gap: 10px;
  color: var(--am-text-muted);
  text-align: center;
  background: var(--am-surface-muted);
  border-radius: 6px;
}

.inf-viewer__empty--dashed {
  background: var(--am-surface-soft);
  border: 1px dashed var(--am-border-strong);
}

.inf-viewer__empty strong {
  color: var(--am-text-strong);
  font-size: 15px;
}

.inf-viewer__empty p {
  margin: 0;
  font-size: 13px;
}

.inf-empty-actions {
  display: flex;
  gap: 8px;
  margin-top: 4px;
}

.inf-empty-error-icon {
  position: relative;
  display: inline-flex;
}

.inf-empty-error-badge {
  position: absolute;
  right: -4px;
  bottom: -4px;
  color: #dc2626;
  background: var(--am-surface);
  border-radius: 50%;
}

.inf-viewer__stage {
  position: absolute;
  top: 0;
  left: 0;
  will-change: transform;
}

.inf-viewer__img {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: contain;
}

.inf-viewer__svg {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  overflow: visible;
}

.inf-overlay-item {
  cursor: pointer;
}

.inf-overlay-item.is-selected {
  filter: drop-shadow(0 0 4px rgb(255 255 255 / 0.85));
}

.inf-spin {
  animation: inf-spin 0.9s linear infinite;
}

@keyframes inf-spin {
  from {
    transform: rotate(0deg);
  }
  to {
    transform: rotate(360deg);
  }
}
</style>
