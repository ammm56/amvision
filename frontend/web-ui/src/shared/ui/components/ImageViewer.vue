<template>
  <Teleport to="body">
    <div v-if="open && image" class="image-viewer" role="dialog" aria-modal="true" @keydown.esc="emit('close')">
      <div class="image-viewer__toolbar">
        <div class="image-viewer__title">
          <strong>{{ image.title }}</strong>
          <span>{{ image.width || '-' }} × {{ image.height || '-' }} / {{ image.mediaType || 'unknown' }}</span>
        </div>
        <div class="image-viewer__actions">
          <div v-if="interactionAvailable" class="image-viewer__interaction-actions">
            <Button size="sm" :variant="interactionActive ? 'primary' : 'secondary'" type="button" title="在图片上取参" @click="toggleInteraction">
              <Crosshair :size="15" />
              {{ interactionActive ? '退出取参' : '取参' }}
            </Button>
            <div v-if="availableInteractionTools.length > 1" class="image-viewer__tool-tabs">
              <Button
                v-for="toolItem in availableInteractionTools"
                :key="toolItem.tool"
                size="sm"
                :variant="toolItem.tool === interactionTool ? 'primary' : 'secondary'"
                type="button"
                :title="`切换到 ${readInteractionToolItemLabel(toolItem)}`"
                @click="selectInteractionTool(toolItem.tool)"
              >
                {{ readInteractionToolItemLabel(toolItem) }}
              </Button>
            </div>
            <Button v-if="interactionTool === 'circle'" size="sm" variant="secondary" type="button" title="切换圆取参方式" @click="toggleCircleDraftMode">
              {{ circleDraftMode === 'center-radius' ? '中心半径' : '三点圆' }}
            </Button>
            <div v-if="interactionTool === 'template-region'" class="image-viewer__tool-tabs">
              <Button size="sm" :variant="templateRegionStage === 'template' ? 'primary' : 'secondary'" type="button" title="绘制模板 ROI" @click="selectTemplateRegionStage('template')">
                模板 ROI
              </Button>
              <Button size="sm" :variant="templateRegionStage === 'search' ? 'primary' : 'secondary'" type="button" title="绘制搜索 ROI" @click="selectTemplateRegionStage('search')">
                搜索 ROI
              </Button>
            </div>
            <Button size="sm" variant="secondary" type="button" title="清除当前取参草稿" :disabled="!hasInteractionDraft" @click="clearInteractionDraft">
              <Trash2 :size="15" />
              清除
            </Button>
            <Button size="sm" variant="primary" type="button" title="应用到节点参数" :disabled="!canApplyInteraction" @click="applyInteractionDraft">
              <Check :size="15" />
              应用参数
            </Button>
            <Button
              size="sm"
              variant="primary"
              type="button"
              :title="hasInteractionDraft ? '应用当前取参并重新 Preview Run' : '重新执行 Preview Run'"
              :disabled="previewActionDisabled"
              @click="runPreviewFromViewer"
            >
              <Play :size="15" />
              {{ previewRunning ? 'Preview 中' : (hasInteractionDraft ? '应用并 Preview' : 'Preview Run') }}
            </Button>
            <span
              v-if="interactionFeedback"
              class="image-viewer__interaction-feedback"
              :class="`image-viewer__interaction-feedback--${interactionFeedback.tone}`"
            >
              {{ interactionFeedback.text }}
            </span>
          </div>
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
        :class="{ 'image-viewer__viewport--interacting': interactionActive }"
        @wheel.prevent="handleWheel"
        @mousedown="handleViewportMouseDown"
        @dblclick="handleViewportDoubleClick"
      >
        <div v-if="tuningControls.length" class="image-viewer__tuning-panel">
          <div class="image-viewer__tuning-header">
            <strong>算法调参</strong>
            <label class="image-viewer__tuning-auto">
              <input v-model="autoPreviewEnabled" type="checkbox">
              自动 Preview
            </label>
          </div>
          <div class="image-viewer__tuning-list">
            <label v-for="control in tuningControls" :key="control.parameterName" class="image-viewer__tuning-control">
              <span>{{ control.label || control.parameterName }}</span>
              <template v-if="control.control === 'checkbox'">
                <input
                  type="checkbox"
                  :checked="readTuningBooleanValue(control)"
                  @change="updateTuningControlFromEvent(control, $event, true)"
                >
              </template>
              <template v-else>
                <input
                  v-if="control.control === 'slider'"
                  type="range"
                  :min="control.min ?? 0"
                  :max="control.max ?? 100"
                  :step="control.step ?? 1"
                  :value="readTuningControlInputValue(control)"
                  @input="updateTuningControlFromEvent(control, $event, false)"
                  @change="updateTuningControlFromEvent(control, $event, true)"
                >
                <input
                  type="number"
                  :min="control.min ?? undefined"
                  :max="control.max ?? undefined"
                  :step="control.step ?? 'any'"
                  :value="readTuningControlInputValue(control)"
                  @change="updateTuningControlFromEvent(control, $event, true)"
                >
              </template>
            </label>
          </div>
          <Button size="sm" variant="primary" type="button" title="写回参数并重新 Preview" @click="applyTuningParameters(true)">
            <Check :size="15" />
            应用并 Preview
          </Button>
        </div>
        <div v-if="image.src" class="image-viewer__image-frame" :style="imageStyle">
          <img
            ref="imageRef"
            :src="image.src"
            :alt="image.title"
            draggable="false"
            @load="handleImageLoad"
          />
          <svg
            v-if="overlayViewBox && hasVisibleOverlay"
            class="image-viewer__overlay"
            :viewBox="overlayViewBox"
            preserveAspectRatio="none"
            aria-hidden="true"
          >
            <template v-for="(overlay, index) in imageOverlays" :key="overlayKey(overlay, index)">
              <polygon
                v-if="overlay.pointsXy.length >= 2"
                class="image-viewer__overlay-shape image-viewer__overlay-shape--polygon"
                :points="overlayPoints(overlay)"
              />
              <rect
                v-else-if="overlay.bboxXyxy"
                class="image-viewer__overlay-shape image-viewer__overlay-shape--bbox"
                :x="overlay.bboxXyxy[0]"
                :y="overlay.bboxXyxy[1]"
                :width="bboxWidth(overlay)"
                :height="bboxHeight(overlay)"
              />
              <line
                v-else-if="overlay.lineXyxy"
                class="image-viewer__overlay-shape image-viewer__overlay-shape--line"
                :x1="overlay.lineXyxy[0]"
                :y1="overlay.lineXyxy[1]"
                :x2="overlay.lineXyxy[2]"
                :y2="overlay.lineXyxy[3]"
              />
              <circle
                v-else-if="overlay.circle"
                class="image-viewer__overlay-shape image-viewer__overlay-shape--circle"
                :cx="overlay.circle.centerX"
                :cy="overlay.circle.centerY"
                :r="overlay.circle.radius"
              />
            </template>
            <rect
              v-if="draftTemplateBboxXyxy"
              class="image-viewer__overlay-shape image-viewer__overlay-shape--template-region"
              :x="draftTemplateBboxXyxy[0]"
              :y="draftTemplateBboxXyxy[1]"
              :width="draftTemplateBboxXyxy[2] - draftTemplateBboxXyxy[0]"
              :height="draftTemplateBboxXyxy[3] - draftTemplateBboxXyxy[1]"
            />
            <text
              v-if="draftTemplateBboxXyxy"
              class="image-viewer__overlay-label image-viewer__overlay-label--template-region"
              :x="draftTemplateBboxXyxy[0]"
              :y="Math.max(14, draftTemplateBboxXyxy[1] - 6)"
            >
              Template
            </text>
            <rect
              v-if="draftSearchBboxXyxy"
              class="image-viewer__overlay-shape image-viewer__overlay-shape--search-region"
              :x="draftSearchBboxXyxy[0]"
              :y="draftSearchBboxXyxy[1]"
              :width="draftSearchBboxXyxy[2] - draftSearchBboxXyxy[0]"
              :height="draftSearchBboxXyxy[3] - draftSearchBboxXyxy[1]"
            />
            <text
              v-if="draftSearchBboxXyxy"
              class="image-viewer__overlay-label image-viewer__overlay-label--search-region"
              :x="draftSearchBboxXyxy[0]"
              :y="Math.max(14, draftSearchBboxXyxy[1] - 6)"
            >
              Search
            </text>
            <rect
              v-if="draftBboxXyxy"
              class="image-viewer__overlay-shape image-viewer__overlay-shape--draft"
              :x="draftBboxXyxy[0]"
              :y="draftBboxXyxy[1]"
              :width="draftBboxXyxy[2] - draftBboxXyxy[0]"
              :height="draftBboxXyxy[3] - draftBboxXyxy[1]"
            />
            <line
              v-if="draftLineXyxy"
              class="image-viewer__overlay-shape image-viewer__overlay-shape--draft-line"
              :x1="draftLineXyxy[0]"
              :y1="draftLineXyxy[1]"
              :x2="draftLineXyxy[2]"
              :y2="draftLineXyxy[3]"
            />
            <circle
              v-if="draftCircle"
              class="image-viewer__overlay-shape image-viewer__overlay-shape--draft-line"
              :cx="draftCircle.centerX"
              :cy="draftCircle.centerY"
              :r="draftCircle.radius"
            />
            <polygon
              v-if="interactionTool === 'polygon' && draftPointPairs.length >= 3"
              class="image-viewer__overlay-shape image-viewer__overlay-shape--draft"
              :points="draftPointsText"
            />
            <polyline
              v-else-if="draftPointPairs.length >= 2"
              class="image-viewer__overlay-shape image-viewer__overlay-shape--draft-line"
              :points="draftPointsText"
            />
            <circle
              v-for="(point, index) in draftPointPairs"
              :key="`draft-point-${index}`"
              class="image-viewer__overlay-point"
              :cx="point[0]"
              :cy="point[1]"
              r="4"
            />
          </svg>
        </div>
        <div v-else class="image-viewer__empty">当前图片没有可浏览的 src</div>
      </div>
      <div class="image-viewer__status">
        <span>{{ Math.round(scale * 100) }}%</span>
        <span v-if="interactionStatusText">{{ interactionStatusText }}</span>
        <span>{{ image.objectKey || 'inline-base64' }}</span>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import { Check, Crosshair, Maximize2, Play, RotateCcw, Trash2, X, ZoomIn, ZoomOut } from '@lucide/vue'

import Button from './Button.vue'

interface ViewerImageCircleOverlay {
  centerX: number
  centerY: number
  radius: number
}

interface ViewerImageOverlay {
  kind: string
  id: string | null
  label: string | null
  pointsXy: Array<[number, number]>
  bboxXyxy: [number, number, number, number] | null
  lineXyxy: [number, number, number, number] | null
  circle: ViewerImageCircleOverlay | null
  targetParameters: string[]
}

interface ViewerImageInteractionControl {
  parameterName: string
  label: string
  control: string
  min: number | null
  max: number | null
  step: number | null
  value: unknown
  defaultValue: unknown
}

interface ViewerImageInteractionTool {
  tool: string
  label?: string | null
  targetParameters: string[]
  minPoints?: number | null
  maxPoints?: number | null
}

interface ViewerImageInteraction {
  mode: string
  coordinateSpace: string
  controls?: ViewerImageInteractionControl[]
  tools: ViewerImageInteractionTool[]
}

interface ViewerImage {
  nodeId?: string
  title: string
  src: string | null
  mediaType?: string | null
  width?: number | null
  height?: number | null
  objectKey?: string | null
  overlays?: ViewerImageOverlay[]
  interaction?: ViewerImageInteraction | null
}

interface ViewerImageInteractionApplyEvent {
  nodeId: string
  tool: string
  coordinateSpace: string
  targetParameters: string[]
  parameters?: Record<string, unknown>
  bboxXyxy?: [number, number, number, number]
  templateBboxXyxy?: [number, number, number, number]
  searchBboxXyxy?: [number, number, number, number]
  pointsXy?: Array<[number, number]>
  circle?: ViewerImageCircleOverlay
  lineXyxy?: [number, number, number, number]
}

interface ImagePoint {
  x: number
  y: number
}

interface CircleDraft {
  centerX: number
  centerY: number
  radius: number
}

type CircleDraftMode = 'center-radius' | 'three-point'
type TemplateRegionStage = 'template' | 'search'
type InteractionToolId = 'bbox' | 'polygon' | 'circle' | 'line' | 'grid' | 'template-region'

const interactionToolRegistry: Record<InteractionToolId, { label: string }> = {
  bbox: { label: '矩形 ROI' },
  polygon: { label: '多边形 ROI' },
  circle: { label: '圆' },
  line: { label: '线段' },
  grid: { label: '网格' },
  'template-region': { label: '模板区域' },
}

const props = defineProps<{
  open: boolean
  image: ViewerImage | null
  previewDisabled?: boolean
  previewRunning?: boolean
}>()

const emit = defineEmits<{
  close: []
  applyInteraction: [event: ViewerImageInteractionApplyEvent]
  previewInteraction: [event: ViewerImageInteractionApplyEvent]
  runPreview: []
}>()

const viewportRef = ref<HTMLElement | null>(null)
const imageRef = ref<HTMLImageElement | null>(null)
const scale = ref(1)
const offsetX = ref(0)
const offsetY = ref(0)
const panState = ref<{ startX: number; startY: number; offsetX: number; offsetY: number } | null>(null)
const naturalWidth = ref(0)
const naturalHeight = ref(0)
const interactionActive = ref(false)
const selectedInteractionTool = ref('')
const draftBbox = ref<{ start: ImagePoint; current: ImagePoint } | null>(null)
const draftLine = ref<{ start: ImagePoint; current: ImagePoint } | null>(null)
const draftCircleCenter = ref<ImagePoint | null>(null)
const draftCircleEdge = ref<ImagePoint | null>(null)
const draftPoints = ref<ImagePoint[]>([])
const circleDraftMode = ref<CircleDraftMode>('center-radius')
const templateRegionStage = ref<TemplateRegionStage>('template')
const draftTemplateBboxXyxy = ref<[number, number, number, number] | null>(null)
const draftSearchBboxXyxy = ref<[number, number, number, number] | null>(null)
const tuningParameterValues = ref<Record<string, unknown>>({})
const autoPreviewEnabled = ref(true)
const interactionFeedback = ref<{ text: string; tone: 'success' | 'warning' | 'info' } | null>(null)
let tuningPreviewTimer: ReturnType<typeof window.setTimeout> | null = null
let interactionFeedbackTimer: ReturnType<typeof window.setTimeout> | null = null

const imageStyle = computed(() => ({
  transform: `translate(${offsetX.value}px, ${offsetY.value}px) scale(${scale.value})`,
}))
const imageOverlays = computed(() => props.image?.overlays ?? [])
const imageInteraction = computed(() => props.image?.interaction ?? null)
const availableInteractionTools = computed(() => readAvailableInteractionTools(imageInteraction.value))
const activeInteractionTool = computed(() => {
  const tools = availableInteractionTools.value
  if (tools.length === 0) return null
  return tools.find((tool) => tool.tool === selectedInteractionTool.value) ?? tools[0]
})
const interactionTool = computed(() => activeInteractionTool.value?.tool ?? '')
const activeTargetParameters = computed(() => activeInteractionTool.value?.targetParameters ?? [])
const activePolygonMinPoints = computed(() => {
  const value = activeInteractionTool.value?.minPoints
  return typeof value === 'number' && Number.isFinite(value) ? Math.max(3, Math.floor(value)) : 3
})
const activePolygonMaxPoints = computed(() => {
  const value = activeInteractionTool.value?.maxPoints
  if (typeof value !== 'number' || !Number.isFinite(value)) return null
  return Math.max(activePolygonMinPoints.value, Math.floor(value))
})
const tuningControls = computed(() => imageInteraction.value?.controls ?? [])
const interactionAvailable = computed(() => Boolean(
  props.image?.nodeId
  && imageInteraction.value
  && availableInteractionTools.value.length > 0
  && (activeTargetParameters.value.length > 0 || tuningControls.value.length > 0),
))
const draftBboxXyxy = computed<[number, number, number, number] | null>(() => {
  const bbox = draftBbox.value
  if (!bbox) return null
  const x1 = Math.min(bbox.start.x, bbox.current.x)
  const y1 = Math.min(bbox.start.y, bbox.current.y)
  const x2 = Math.max(bbox.start.x, bbox.current.x)
  const y2 = Math.max(bbox.start.y, bbox.current.y)
  if (x2 - x1 < 1 || y2 - y1 < 1) return null
  return [roundImageCoordinate(x1), roundImageCoordinate(y1), roundImageCoordinate(x2), roundImageCoordinate(y2)]
})
const draftLineXyxy = computed<[number, number, number, number] | null>(() => {
  const line = draftLine.value
  if (!line) return null
  const length = pointDistance([line.start.x, line.start.y], [line.current.x, line.current.y])
  if (length < 1) return null
  return [
    roundImageCoordinate(line.start.x),
    roundImageCoordinate(line.start.y),
    roundImageCoordinate(line.current.x),
    roundImageCoordinate(line.current.y),
  ]
})
const draftPointPairs = computed<Array<[number, number]>>(() => draftPoints.value.map((point) => [roundImageCoordinate(point.x), roundImageCoordinate(point.y)]))
const draftPointsText = computed(() => draftPointPairs.value.map(([pointX, pointY]) => `${pointX},${pointY}`).join(' '))
const draftCircle = computed<CircleDraft | null>(() => {
  if (circleDraftMode.value === 'three-point') return buildCircleFromThreePoints(draftPoints.value)
  const center = draftCircleCenter.value
  const edge = draftCircleEdge.value
  if (!center || !edge) return null
  const radius = pointDistance([center.x, center.y], [edge.x, edge.y])
  if (radius < 1) return null
  return {
    centerX: roundImageCoordinate(center.x),
    centerY: roundImageCoordinate(center.y),
    radius: roundImageCoordinate(radius),
  }
})
const hasInteractionDraft = computed(() => Boolean(
  draftBbox.value
  || draftTemplateBboxXyxy.value
  || draftSearchBboxXyxy.value
  || draftLine.value
  || draftCircle.value
  || draftPointPairs.value.length > 0,
))
const canApplyInteraction = computed(() => {
  if (!interactionAvailable.value) return false
  if (interactionTool.value === 'bbox' || interactionTool.value === 'grid') return Boolean(draftBboxXyxy.value)
  if (interactionTool.value === 'template-region') {
    const targetParameters = new Set(activeTargetParameters.value)
    const requiresTemplate = targetParameters.has('template_bbox_xyxy')
    const requiresSearch = targetParameters.has('search_bbox_xyxy')
    if (requiresTemplate && !draftTemplateBboxXyxy.value) return false
    if (requiresSearch && !draftSearchBboxXyxy.value) return false
    return Boolean(draftTemplateBboxXyxy.value || draftSearchBboxXyxy.value)
  }
  if (interactionTool.value === 'polygon') {
    const pointCount = draftPointPairs.value.length
    return pointCount >= activePolygonMinPoints.value && (activePolygonMaxPoints.value === null || pointCount <= activePolygonMaxPoints.value)
  }
  if (interactionTool.value === 'circle') return Boolean(draftCircle.value)
  if (interactionTool.value === 'line') return Boolean(draftLineXyxy.value)
  return false
})
const previewActionDisabled = computed(() => Boolean(
  props.previewDisabled
  || props.previewRunning
  || (hasInteractionDraft.value && !canApplyInteraction.value),
))
const hasVisibleOverlay = computed(() => imageOverlays.value.length > 0 || hasInteractionDraft.value)
const overlayViewBox = computed(() => {
  const width = naturalWidth.value || props.image?.width || 0
  const height = naturalHeight.value || props.image?.height || 0
  return width > 0 && height > 0 ? `0 0 ${width} ${height}` : ''
})
const interactionStatusText = computed(() => {
  if (!interactionAvailable.value) return ''
  if (!interactionActive.value) return tuningControls.value.length ? '可调参；取参未启用' : '取参未启用'
  if (interactionTool.value === 'bbox') return draftBboxXyxy.value ? 'bbox 已选择，可应用参数' : '拖拽选择 bbox'
  if (interactionTool.value === 'grid') return draftBboxXyxy.value ? 'grid 区域已选择，可应用参数' : '拖拽选择 grid 区域'
  if (interactionTool.value === 'template-region') return readTemplateRegionStatusText()
  if (interactionTool.value === 'polygon') return readPolygonInteractionStatusText()
  if (interactionTool.value === 'circle') return circleDraftMode.value === 'three-point' ? `三点定圆 ${draftPointPairs.value.length}/3` : (draftCircle.value ? '圆已选择，可应用参数' : '按住圆心拖拽半径')
  if (interactionTool.value === 'line') return draftLineXyxy.value ? '线段已选择，可应用参数' : '拖拽选择线段'
  return ''
})

watch(() => [props.open, props.image?.src, props.image?.nodeId] as const, ([open]) => {
  resetInteractionState()
  initializeTuningParameterValues()
  if (!open) return
  resetView()
})

watch(tuningControls, () => {
  initializeTuningParameterValues()
})

function handleImageLoad(): void {
  updateNaturalImageSize()
  fitImage()
}

function updateNaturalImageSize(): void {
  const image = imageRef.value
  naturalWidth.value = image?.naturalWidth || props.image?.width || 0
  naturalHeight.value = image?.naturalHeight || props.image?.height || 0
}

function fitImage(): void {
  const viewport = viewportRef.value
  const image = imageRef.value
  if (!viewport || !image) return
  updateNaturalImageSize()
  const viewportBounds = viewport.getBoundingClientRect()
  const sourceWidth = naturalWidth.value || props.image?.width || 1
  const sourceHeight = naturalHeight.value || props.image?.height || 1
  scale.value = Math.min(viewportBounds.width / sourceWidth, viewportBounds.height / sourceHeight, 1)
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

function handleViewportMouseDown(event: MouseEvent): void {
  if (tryHandleInteractionPointerDown(event)) return
  startPan(event)
}

function handleViewportDoubleClick(): void {
  if (interactionActive.value) return
  showOriginalSize()
}

function tryHandleInteractionPointerDown(event: MouseEvent): boolean {
  if (!interactionActive.value || !interactionAvailable.value || event.button !== 0) return false
  event.preventDefault()
  event.stopPropagation()
  const point = readImagePointFromEvent(event)
  if (!point) return true
  if (interactionTool.value === 'bbox' || interactionTool.value === 'grid' || interactionTool.value === 'template-region') {
    startBboxDraft(point)
    return true
  }
  if (interactionTool.value === 'polygon') {
    addDraftPoint(point, activePolygonMaxPoints.value ?? undefined)
    return true
  }
  if (interactionTool.value === 'circle') {
    if (circleDraftMode.value === 'three-point') addDraftPoint(point, 3)
    else startCircleDraft(point)
    return true
  }
  if (interactionTool.value === 'line') {
    startLineDraft(point)
    return true
  }
  return true
}

function startBboxDraft(point: ImagePoint): void {
  clearShapeDrafts()
  draftBbox.value = { start: point, current: point }
  document.addEventListener('mousemove', moveBboxDraft)
  document.addEventListener('mouseup', stopBboxDraft)
}

function moveBboxDraft(event: MouseEvent): void {
  const bbox = draftBbox.value
  if (!bbox) return
  const point = readImagePointFromEvent(event)
  if (!point) return
  draftBbox.value = { ...bbox, current: point }
}

function stopBboxDraft(): void {
  document.removeEventListener('mousemove', moveBboxDraft)
  document.removeEventListener('mouseup', stopBboxDraft)
  if (interactionTool.value === 'template-region' && draftBboxXyxy.value) {
    if (templateRegionStage.value === 'template') {
      draftTemplateBboxXyxy.value = draftBboxXyxy.value
      templateRegionStage.value = 'search'
      showInteractionFeedback('模板 ROI 已选择，请继续绘制搜索 ROI', 'info')
    } else {
      draftSearchBboxXyxy.value = draftBboxXyxy.value
      showInteractionFeedback('搜索 ROI 已选择，可以应用参数', 'success')
    }
    draftBbox.value = null
  }
}

function startLineDraft(point: ImagePoint): void {
  clearShapeDrafts()
  draftLine.value = { start: point, current: point }
  document.addEventListener('mousemove', moveLineDraft)
  document.addEventListener('mouseup', stopLineDraft)
}

function moveLineDraft(event: MouseEvent): void {
  const line = draftLine.value
  if (!line) return
  const point = readImagePointFromEvent(event)
  if (!point) return
  draftLine.value = { ...line, current: point }
}

function stopLineDraft(): void {
  document.removeEventListener('mousemove', moveLineDraft)
  document.removeEventListener('mouseup', stopLineDraft)
}

function startCircleDraft(point: ImagePoint): void {
  clearShapeDrafts()
  draftCircleCenter.value = point
  draftCircleEdge.value = point
  document.addEventListener('mousemove', moveCircleDraft)
  document.addEventListener('mouseup', stopCircleDraft)
}

function moveCircleDraft(event: MouseEvent): void {
  if (!draftCircleCenter.value) return
  const point = readImagePointFromEvent(event)
  if (!point) return
  draftCircleEdge.value = point
}

function stopCircleDraft(): void {
  document.removeEventListener('mousemove', moveCircleDraft)
  document.removeEventListener('mouseup', stopCircleDraft)
}

function addDraftPoint(point: ImagePoint, maxPoints?: number): void {
  clearShapeDrafts({ keepPoints: true })
  const nextPoints = typeof maxPoints === 'number' && draftPoints.value.length >= maxPoints
    ? [point]
    : [...draftPoints.value, point]
  draftPoints.value = nextPoints
}

function readImagePointFromEvent(event: MouseEvent): ImagePoint | null {
  const image = imageRef.value
  if (!image) return null
  updateNaturalImageSize()
  const imageBounds = image.getBoundingClientRect()
  const sourceWidth = naturalWidth.value || props.image?.width || image.naturalWidth || 0
  const sourceHeight = naturalHeight.value || props.image?.height || image.naturalHeight || 0
  if (imageBounds.width <= 0 || imageBounds.height <= 0 || sourceWidth <= 0 || sourceHeight <= 0) return null
  return {
    x: clampNumber(((event.clientX - imageBounds.left) / imageBounds.width) * sourceWidth, 0, sourceWidth),
    y: clampNumber(((event.clientY - imageBounds.top) / imageBounds.height) * sourceHeight, 0, sourceHeight),
  }
}

function toggleInteraction(): void {
  interactionActive.value = !interactionActive.value
  if (!interactionActive.value) stopActiveDraftListeners()
}

function selectInteractionTool(tool: string): void {
  if (!isSupportedInteractionTool(tool)) return
  selectedInteractionTool.value = tool
  clearInteractionDraft()
}

function readInteractionToolItemLabel(toolItem: ViewerImageInteractionTool): string {
  return toolItem.label || readInteractionToolLabel(toolItem.tool)
}

function readInteractionToolLabel(tool: string): string {
  if (isSupportedInteractionTool(tool)) return interactionToolRegistry[tool].label
  return tool
}

function toggleCircleDraftMode(): void {
  circleDraftMode.value = circleDraftMode.value === 'center-radius' ? 'three-point' : 'center-radius'
  clearInteractionDraft()
}

function selectTemplateRegionStage(stage: TemplateRegionStage): void {
  templateRegionStage.value = stage
  draftBbox.value = null
  stopBboxDraft()
}

function clearInteractionDraft(): void {
  clearShapeDrafts()
  draftTemplateBboxXyxy.value = null
  draftSearchBboxXyxy.value = null
  templateRegionStage.value = 'template'
  stopActiveDraftListeners()
}

function clearShapeDrafts(options: { keepPoints?: boolean } = {}): void {
  draftBbox.value = null
  draftLine.value = null
  draftCircleCenter.value = null
  draftCircleEdge.value = null
  if (!options.keepPoints) draftPoints.value = []
}

function stopActiveDraftListeners(): void {
  stopBboxDraft()
  stopLineDraft()
  stopCircleDraft()
}

function resetInteractionState(): void {
  interactionActive.value = false
  selectedInteractionTool.value = ''
  clearInteractionDraft()
}

function applyInteractionDraft(): void {
  const event = buildInteractionDraftEvent()
  if (!event) {
    showInteractionFeedback('当前取参还不完整，不能应用参数', 'warning')
    return
  }
  emit('applyInteraction', event)
  showInteractionFeedback(readAppliedFeedbackText(event), 'success')
}

function buildInteractionDraftEvent(): ViewerImageInteractionApplyEvent | null {
  const interaction = imageInteraction.value
  const nodeId = props.image?.nodeId
  if (!interaction || !nodeId) return null
  const baseEvent = {
    nodeId,
    tool: interactionTool.value,
    coordinateSpace: interaction.coordinateSpace,
    targetParameters: activeTargetParameters.value,
  }
  if ((interactionTool.value === 'bbox' || interactionTool.value === 'grid') && draftBboxXyxy.value) {
    return { ...baseEvent, bboxXyxy: draftBboxXyxy.value }
  }
  if (interactionTool.value === 'template-region' && canApplyInteraction.value) {
    return {
      ...baseEvent,
      bboxXyxy: draftSearchBboxXyxy.value ?? draftTemplateBboxXyxy.value ?? undefined,
      templateBboxXyxy: draftTemplateBboxXyxy.value ?? undefined,
      searchBboxXyxy: draftSearchBboxXyxy.value ?? undefined,
    }
  }
  if (interactionTool.value === 'polygon' && canApplyInteraction.value) {
    return { ...baseEvent, pointsXy: draftPointPairs.value }
  }
  if (interactionTool.value === 'circle' && draftCircle.value) {
    return { ...baseEvent, circle: draftCircle.value }
  }
  if (interactionTool.value === 'line' && draftLineXyxy.value) {
    return { ...baseEvent, lineXyxy: draftLineXyxy.value }
  }
  return null
}

function initializeTuningParameterValues(): void {
  const nextValues: Record<string, unknown> = {}
  for (const control of tuningControls.value) {
    nextValues[control.parameterName] = readInitialTuningValue(control)
  }
  tuningParameterValues.value = nextValues
}

function readInitialTuningValue(control: ViewerImageInteractionControl): unknown {
  if (control.value !== undefined && control.value !== null && control.value !== '') return control.value
  if (control.defaultValue !== undefined && control.defaultValue !== null && control.defaultValue !== '') return control.defaultValue
  if (control.control === 'checkbox') return false
  if (control.min !== null) return control.min
  return 0
}

function readTuningControlInputValue(control: ViewerImageInteractionControl): string | number {
  const value = tuningParameterValues.value[control.parameterName]
  return typeof value === 'number' || typeof value === 'string' ? value : ''
}

function readTuningBooleanValue(control: ViewerImageInteractionControl): boolean {
  return tuningParameterValues.value[control.parameterName] === true
}

function updateTuningControlFromEvent(control: ViewerImageInteractionControl, event: Event, requestPreview: boolean): void {
  const target = event.target
  if (!(target instanceof HTMLInputElement)) return
  const value = control.control === 'checkbox' ? target.checked : Number(target.value)
  tuningParameterValues.value = {
    ...tuningParameterValues.value,
    [control.parameterName]: value,
  }
  applyTuningParameters(requestPreview && autoPreviewEnabled.value)
}

function applyTuningParameters(requestPreview: boolean): void {
  const interaction = imageInteraction.value
  const nodeId = props.image?.nodeId
  if (!interaction || !nodeId) return
  const parameters = Object.fromEntries(
    tuningControls.value.map((control) => [control.parameterName, tuningParameterValues.value[control.parameterName]]),
  )
  const event: ViewerImageInteractionApplyEvent = {
    nodeId,
    tool: interactionTool.value,
    coordinateSpace: interaction.coordinateSpace,
    targetParameters: activeTargetParameters.value,
    parameters,
  }
  emit('applyInteraction', event)
  showInteractionFeedback(requestPreview ? '调参已应用，正在 Preview Run' : '调参已应用到节点参数', 'success')
  if (requestPreview) scheduleTuningPreview(event)
}

function scheduleTuningPreview(event: ViewerImageInteractionApplyEvent): void {
  if (tuningPreviewTimer !== null) window.clearTimeout(tuningPreviewTimer)
  tuningPreviewTimer = window.setTimeout(() => {
    emit('previewInteraction', event)
    tuningPreviewTimer = null
  }, 350)
}

function runPreviewFromViewer(): void {
  if (previewActionDisabled.value) {
    showInteractionFeedback(
      props.previewRunning ? 'Preview Run 正在执行' : '当前取参还不完整，不能 Preview',
      'warning',
    )
    return
  }
  const event = buildInteractionDraftEvent()
  if (hasInteractionDraft.value) {
    if (!event) {
      showInteractionFeedback('当前取参还不完整，不能 Preview', 'warning')
      return
    }
    emit('applyInteraction', event)
    showInteractionFeedback(`${readAppliedFeedbackText(event)}，正在 Preview Run`, 'success')
  } else {
    showInteractionFeedback('正在 Preview Run', 'info')
  }
  emit('runPreview')
}

function readAppliedFeedbackText(event: ViewerImageInteractionApplyEvent): string {
  if (event.tool === 'bbox') return '矩形 ROI 已应用到节点参数'
  if (event.tool === 'template-region') return '模板 ROI / 搜索 ROI 已应用到节点参数'
  if (event.tool === 'polygon') return '多边形 ROI 已应用到节点参数'
  if (event.tool === 'grid') return 'ROI 网格参数已应用'
  if (event.tool === 'circle') return '圆参数已应用'
  if (event.tool === 'line') return '线段参数已应用'
  return '参数已应用到节点'
}

function showInteractionFeedback(text: string, tone: 'success' | 'warning' | 'info'): void {
  interactionFeedback.value = { text, tone }
  if (interactionFeedbackTimer !== null) window.clearTimeout(interactionFeedbackTimer)
  interactionFeedbackTimer = window.setTimeout(() => {
    interactionFeedback.value = null
    interactionFeedbackTimer = null
  }, 2400)
}

function overlayKey(overlay: ViewerImageOverlay, index: number): string {
  return `${overlay.kind}:${overlay.id ?? index}`
}

function overlayPoints(overlay: ViewerImageOverlay): string {
  return overlay.pointsXy.map(([pointX, pointY]) => `${pointX},${pointY}`).join(' ')
}

function bboxWidth(overlay: ViewerImageOverlay): number {
  return overlay.bboxXyxy ? Math.max(0, overlay.bboxXyxy[2] - overlay.bboxXyxy[0]) : 0
}

function bboxHeight(overlay: ViewerImageOverlay): number {
  return overlay.bboxXyxy ? Math.max(0, overlay.bboxXyxy[3] - overlay.bboxXyxy[1]) : 0
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

function readAvailableInteractionTools(interaction: ViewerImageInteraction | null): ViewerImageInteractionTool[] {
  if (!interaction) return []
  return interaction.tools.flatMap(normalizeInteractionTool)
}

function normalizeInteractionTool(toolItem: ViewerImageInteractionTool): ViewerImageInteractionTool[] {
  if (!isSupportedInteractionTool(toolItem.tool) || toolItem.targetParameters.length === 0) return []
  return [{
    tool: toolItem.tool,
    label: toolItem.label ?? readInteractionToolLabel(toolItem.tool),
    targetParameters: toolItem.targetParameters,
    minPoints: toolItem.minPoints ?? null,
    maxPoints: toolItem.maxPoints ?? null,
  }]
}

function readTemplateRegionStatusText(): string {
  const templateReady = Boolean(draftTemplateBboxXyxy.value)
  const searchReady = Boolean(draftSearchBboxXyxy.value)
  const currentStageText = templateRegionStage.value === 'template' ? '模板 ROI' : '搜索 ROI'
  if (templateReady && searchReady) return '模板 ROI 和搜索 ROI 已选择，可应用参数'
  if (templateReady) return '模板 ROI 已选择，继续拖拽选择搜索 ROI'
  if (searchReady) return '搜索 ROI 已选择，继续拖拽选择模板 ROI'
  return `拖拽选择${currentStageText}`
}

function readPolygonInteractionStatusText(): string {
  const pointCount = draftPointPairs.value.length
  const minPoints = activePolygonMinPoints.value
  const maxPoints = activePolygonMaxPoints.value
  if (maxPoints !== null && maxPoints === minPoints) {
    return pointCount >= maxPoints ? `多边形 ${pointCount}/${maxPoints}，可应用参数` : `多边形取参 ${pointCount}/${maxPoints}`
  }
  if (pointCount >= minPoints) return `多边形 ${pointCount} 点，可应用参数`
  return `多边形取参 ${pointCount}/${minPoints}`
}

function isSupportedInteractionTool(tool: string): tool is InteractionToolId {
  return Object.prototype.hasOwnProperty.call(interactionToolRegistry, tool)
}

function buildCircleFromThreePoints(points: ImagePoint[]): CircleDraft | null {
  if (points.length !== 3) return null
  const [a, b, c] = points
  const denominator = 2 * (a.x * (b.y - c.y) + b.x * (c.y - a.y) + c.x * (a.y - b.y))
  if (Math.abs(denominator) < 0.000001) return null
  const a2 = a.x * a.x + a.y * a.y
  const b2 = b.x * b.x + b.y * b.y
  const c2 = c.x * c.x + c.y * c.y
  const centerX = (a2 * (b.y - c.y) + b2 * (c.y - a.y) + c2 * (a.y - b.y)) / denominator
  const centerY = (a2 * (c.x - b.x) + b2 * (a.x - c.x) + c2 * (b.x - a.x)) / denominator
  const radius = pointDistance([centerX, centerY], [a.x, a.y])
  if (!Number.isFinite(centerX) || !Number.isFinite(centerY) || radius < 1) return null
  return {
    centerX: roundImageCoordinate(centerX),
    centerY: roundImageCoordinate(centerY),
    radius: roundImageCoordinate(radius),
  }
}

function pointDistance(pointA: number[], pointB: number[]): number {
  return Math.hypot(pointB[0] - pointA[0], pointB[1] - pointA[1])
}

function roundImageCoordinate(value: number): number {
  return Math.round(value * 1000) / 1000
}

function clampNumber(value: number, minValue: number, maxValue: number): number {
  return Math.min(maxValue, Math.max(minValue, value))
}

onUnmounted(() => {
  stopPan()
  stopActiveDraftListeners()
  if (tuningPreviewTimer !== null) window.clearTimeout(tuningPreviewTimer)
  if (interactionFeedbackTimer !== null) window.clearTimeout(interactionFeedbackTimer)
})
</script>
