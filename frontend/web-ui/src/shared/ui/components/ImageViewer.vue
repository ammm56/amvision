<template>
  <Teleport to="body">
    <div v-if="open && image" class="image-viewer" role="dialog" aria-modal="true" @keydown.esc="emit('close')">
      <div class="image-viewer__toolbar">
        <div class="image-viewer__title">
          <strong>{{ image.title }}</strong>
          <span>{{ sourceImageWidth || '-' }} × {{ sourceImageHeight || '-' }} / {{ image.mediaType || 'unknown' }}</span>
        </div>
        <div class="image-viewer__actions">
          <div v-if="interactionAvailable" class="image-viewer__interaction-actions">
            <Button v-if="hasInteractionTools" size="sm" :variant="interactionActive ? 'primary' : 'secondary'" type="button" :title="t('imageViewer.toolbar.pickOnImage')" @click="toggleInteraction">
              <Crosshair :size="15" />
              {{ interactionActive ? t('imageViewer.toolbar.exitPick') : t('imageViewer.toolbar.pick') }}
            </Button>
            <div v-if="availableInteractionTools.length > 1" class="image-viewer__tool-tabs">
              <Button
                v-for="toolItem in availableInteractionTools"
                :key="toolItem.tool"
                size="sm"
                :variant="toolItem.tool === interactionTool ? 'primary' : 'secondary'"
                type="button"
                :title="t('imageViewer.toolbar.switchTool', { tool: readInteractionToolItemLabel(toolItem) })"
                @click="selectInteractionTool(toolItem.tool)"
              >
                {{ readInteractionToolItemLabel(toolItem) }}
              </Button>
            </div>
            <Button v-if="interactionTool === 'circle'" size="sm" variant="secondary" type="button" :title="t('imageViewer.toolbar.switchCircleMode')" @click="toggleCircleDraftMode">
              {{ circleDraftMode === 'center-radius' ? t('imageViewer.toolbar.centerRadius') : t('imageViewer.toolbar.threePointCircle') }}
            </Button>
            <div v-if="interactionTool === 'template-region'" class="image-viewer__tool-tabs">
              <Button size="sm" :variant="templateRegionStage === 'template' ? 'primary' : 'secondary'" type="button" :title="t('imageViewer.toolbar.drawTemplateRoi')" @click="selectTemplateRegionStage('template')">
                {{ t('imageViewer.toolbar.templateRoi') }}
              </Button>
              <Button size="sm" :variant="templateRegionStage === 'search' ? 'primary' : 'secondary'" type="button" :title="t('imageViewer.toolbar.drawSearchRoi')" @click="selectTemplateRegionStage('search')">
                {{ t('imageViewer.toolbar.searchRoi') }}
              </Button>
            </div>
            <Button size="sm" variant="secondary" type="button" :title="t('imageViewer.toolbar.clearDraft')" :disabled="!hasInteractionDraft" @click="clearInteractionDraft">
              <Trash2 :size="15" />
              {{ t('imageViewer.toolbar.clear') }}
            </Button>
            <Button size="sm" variant="primary" type="button" :title="t('imageViewer.toolbar.applyParams')" :disabled="!canApplyInteraction" @click="applyInteractionDraft">
              <Check :size="15" />
              {{ t('imageViewer.toolbar.applyParams') }}
            </Button>
            <Button
              size="sm"
              variant="primary"
              type="button"
              :title="hasInteractionDraft ? t('imageViewer.toolbar.applyDraftAndPreview') : t('imageViewer.toolbar.rerunPreview')"
              :disabled="previewActionDisabled"
              @click="runPreviewFromViewer"
            >
              <Play :size="15" />
              {{ previewRunning ? t('imageViewer.toolbar.previewRunning') : (hasInteractionDraft ? t('imageViewer.toolbar.applyAndPreview') : 'Preview Run') }}
            </Button>
            <span
              v-if="interactionFeedback"
              class="image-viewer__interaction-feedback"
              :class="`image-viewer__interaction-feedback--${interactionFeedback.tone}`"
            >
              {{ interactionFeedback.text }}
            </span>
          </div>
          <Button size="sm" variant="secondary" type="button" :title="t('imageViewer.toolbar.fit')" @click="fitImage">
            <Maximize2 :size="15" />
            {{ t('imageViewer.toolbar.fitShort') }}
          </Button>
          <Button size="sm" variant="secondary" type="button" :title="t('imageViewer.toolbar.originalSize')" @click="showOriginalSize">
            100%
          </Button>
          <Button size="sm" variant="secondary" type="button" :title="t('imageViewer.toolbar.zoomOut')" @click="zoomOut">
            <ZoomOut :size="15" />
          </Button>
          <Button size="sm" variant="secondary" type="button" :title="t('imageViewer.toolbar.zoomIn')" @click="zoomIn">
            <ZoomIn :size="15" />
          </Button>
          <Button size="sm" variant="secondary" type="button" :title="t('imageViewer.toolbar.resetPosition')" @click="resetView">
            <RotateCcw :size="15" />
          </Button>
          <Button class="image-viewer__close" size="sm" variant="secondary" type="button" :title="t('imageViewer.toolbar.close')" :aria-label="t('imageViewer.toolbar.closeAria')" @click="emit('close')">
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
            <strong>{{ t('imageViewer.tuning.title') }}</strong>
            <label class="image-viewer__tuning-auto">
              <input v-model="autoPreviewEnabled" type="checkbox">
              {{ t('imageViewer.tuning.autoPreview') }}
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
              <template v-else-if="control.control === 'select'">
                <select
                  :value="readTuningControlInputValue(control)"
                  @change="updateTuningControlFromEvent(control, $event, true)"
                >
                  <option
                    v-for="option in control.options ?? []"
                    :key="option.value"
                    :value="option.value"
                  >
                    {{ option.label }}
                  </option>
                </select>
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
          <Button size="sm" variant="primary" type="button" :title="t('imageViewer.tuning.applyAndPreviewTitle')" @click="applyTuningParameters(true)">
            <Check :size="15" />
            {{ t('imageViewer.toolbar.applyAndPreview') }}
          </Button>
        </div>
        <div v-if="viewerImageSrc" class="image-viewer__image-frame" :style="imageFrameStyle">
          <img
            ref="imageRef"
            :src="viewerImageSrc"
            :alt="image.title"
            :style="imageElementStyle"
            draggable="false"
            @load="handleImageLoad"
          />
          <svg
            v-if="overlayViewBox && hasVisibleOverlay"
            class="image-viewer__overlay"
            :class="{ 'image-viewer__overlay--interactive': overlayPickingActive }"
            :viewBox="overlayViewBox"
            preserveAspectRatio="none"
            aria-hidden="true"
          >
            <template v-for="(overlay, index) in imageOverlays" :key="overlayKey(overlay, index)">
              <polygon
                v-if="overlay.pointsXy.length >= 2"
                :class="readOverlayShapeClass(overlay, 'polygon')"
                :points="overlayPoints(overlay)"
                @mousedown="handleOverlayMouseDown(overlay, $event)"
              />
              <rect
                v-else-if="overlay.bboxXyxy"
                :class="readOverlayShapeClass(overlay, 'bbox')"
                :x="overlay.bboxXyxy[0]"
                :y="overlay.bboxXyxy[1]"
                :width="bboxWidth(overlay)"
                :height="bboxHeight(overlay)"
                @mousedown="handleOverlayMouseDown(overlay, $event)"
              />
              <line
                v-else-if="overlay.lineXyxy"
                :class="readOverlayShapeClass(overlay, 'line')"
                :x1="overlay.lineXyxy[0]"
                :y1="overlay.lineXyxy[1]"
                :x2="overlay.lineXyxy[2]"
                :y2="overlay.lineXyxy[3]"
                @mousedown="handleOverlayMouseDown(overlay, $event)"
              />
              <circle
                v-else-if="overlay.circle"
                :class="readOverlayShapeClass(overlay, 'circle')"
                :cx="overlay.circle.centerX"
                :cy="overlay.circle.centerY"
                :r="overlay.circle.radius"
                @mousedown="handleOverlayMouseDown(overlay, $event)"
              />
              <template v-if="overlay.circle && overlay.kind === 'selected-circle'">
                <line
                  class="image-viewer__overlay-shape image-viewer__overlay-shape--selected-center"
                  :x1="overlay.circle.centerX - Math.max(4, overlay.circle.radius * 0.18)"
                  :y1="overlay.circle.centerY"
                  :x2="overlay.circle.centerX + Math.max(4, overlay.circle.radius * 0.18)"
                  :y2="overlay.circle.centerY"
                />
                <line
                  class="image-viewer__overlay-shape image-viewer__overlay-shape--selected-center"
                  :x1="overlay.circle.centerX"
                  :y1="overlay.circle.centerY - Math.max(4, overlay.circle.radius * 0.18)"
                  :x2="overlay.circle.centerX"
                  :y2="overlay.circle.centerY + Math.max(4, overlay.circle.radius * 0.18)"
                />
              </template>
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
            <rect
              v-if="draftLineSearchBboxXyxy"
              class="image-viewer__overlay-shape image-viewer__overlay-shape--line-search-roi"
              :x="draftLineSearchBboxXyxy[0]"
              :y="draftLineSearchBboxXyxy[1]"
              :width="draftLineSearchBboxXyxy[2] - draftLineSearchBboxXyxy[0]"
              :height="draftLineSearchBboxXyxy[3] - draftLineSearchBboxXyxy[1]"
            />
            <line
              v-if="draftLineAngleGuideMin"
              class="image-viewer__overlay-shape image-viewer__overlay-shape--line-angle-guide"
              :x1="draftLineAngleGuideMin[0]"
              :y1="draftLineAngleGuideMin[1]"
              :x2="draftLineAngleGuideMin[2]"
              :y2="draftLineAngleGuideMin[3]"
            />
            <line
              v-if="draftLineAngleGuideMax"
              class="image-viewer__overlay-shape image-viewer__overlay-shape--line-angle-guide"
              :x1="draftLineAngleGuideMax[0]"
              :y1="draftLineAngleGuideMax[1]"
              :x2="draftLineAngleGuideMax[2]"
              :y2="draftLineAngleGuideMax[3]"
            />
            <line
              v-if="draftLineXyxy"
              class="image-viewer__overlay-shape image-viewer__overlay-shape--draft-line"
              :x1="draftLineXyxy[0]"
              :y1="draftLineXyxy[1]"
              :x2="draftLineXyxy[2]"
              :y2="draftLineXyxy[3]"
            />
            <line
              v-for="(pairLine, index) in draftPairLines"
              :key="`draft-pair-line-${index}`"
              class="image-viewer__overlay-shape image-viewer__overlay-shape--kind-point-pair"
              :x1="pairLine[0]"
              :y1="pairLine[1]"
              :x2="pairLine[2]"
              :y2="pairLine[3]"
            />
            <text
              v-if="draftLineGuideLabel"
              class="image-viewer__overlay-label image-viewer__overlay-label--line-guide"
              :x="draftLineGuideLabel.x"
              :y="draftLineGuideLabel.y"
            >
              {{ draftLineGuideLabel.text }}
            </text>
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
        <div v-else class="image-viewer__empty">{{ t('imageViewer.empty') }}</div>
      </div>
      <div class="image-viewer__status">
        <div class="image-viewer__status-group">
          <span>{{ Math.round(scale * 100) }}%</span>
          <span v-for="metric in imageMetricItems" :key="metric">{{ metric }}</span>
        </div>
        <span v-if="interactionStatusText">{{ interactionStatusText }}</span>
        <span>{{ image.sourceObjectKey || image.objectKey || 'inline-base64' }}</span>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { computed, nextTick, onUnmounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
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
  parameters: Record<string, unknown>
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
  options?: ViewerImageInteractionControlOption[]
}

interface ViewerImageInteractionControlOption {
  value: string
  label: string
}

interface ViewerImageInteractionTool {
  tool: string
  label?: string | null
  targetParameters: string[]
  minPoints?: number | null
  maxPoints?: number | null
  angleToleranceDeg?: number | null
  searchPaddingRatio?: number | null
  searchPaddingMin?: number | null
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
  displaySrc?: string | null
  sourceSrc?: string | null
  mediaType?: string | null
  width?: number | null
  height?: number | null
  objectKey?: string | null
  displayWidth?: number | null
  displayHeight?: number | null
  displayObjectKey?: string | null
  sourceWidth?: number | null
  sourceHeight?: number | null
  sourceObjectKey?: string | null
  displayScale?: number | null
  previewImageKind?: string | null
  overlays?: ViewerImageOverlay[]
  interaction?: ViewerImageInteraction | null
}

interface ViewerImageInteractionApplyEvent {
  nodeId: string
  tool: string
  coordinateSpace: string
  targetParameters: string[]
  parameters?: Record<string, unknown>
  angleToleranceDeg?: number | null
  searchPaddingRatio?: number | null
  searchPaddingMin?: number | null
  bboxXyxy?: [number, number, number, number]
  templateBboxXyxy?: [number, number, number, number]
  searchBboxXyxy?: [number, number, number, number]
  pointsXy?: Array<[number, number]>
  circle?: ViewerImageCircleOverlay
  lineXyxy?: [number, number, number, number]
  pairLinesXyxy?: Array<[number, number, number, number]>
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

interface LineVisualGuide {
  searchBboxXyxy: [number, number, number, number] | null
  angleGuideMin: [number, number, number, number] | null
  angleGuideMax: [number, number, number, number] | null
  label: { x: number; y: number; text: string } | null
}

type CircleDraftMode = 'center-radius' | 'three-point'
type TemplateRegionStage = 'template' | 'search'
type InteractionToolId =
  | 'bbox'
  | 'rect'
  | 'polygon'
  | 'contour'
  | 'circle'
  | 'line'
  | 'grid'
  | 'template-region'
  | 'match-line'
  | 'point-pair'
  | 'homography-overlay'

const interactionToolRegistry: Record<InteractionToolId, { messageKey: string }> = {
  bbox: { messageKey: 'imageViewer.tools.bbox' },
  rect: { messageKey: 'imageViewer.tools.rect' },
  polygon: { messageKey: 'imageViewer.tools.polygon' },
  contour: { messageKey: 'imageViewer.tools.contour' },
  circle: { messageKey: 'imageViewer.tools.circle' },
  line: { messageKey: 'imageViewer.tools.line' },
  grid: { messageKey: 'imageViewer.tools.grid' },
  'template-region': { messageKey: 'imageViewer.tools.templateRegion' },
  'match-line': { messageKey: 'imageViewer.tools.matchLine' },
  'point-pair': { messageKey: 'imageViewer.tools.pointPair' },
  'homography-overlay': { messageKey: 'imageViewer.tools.homographyOverlay' },
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

const { t } = useI18n()

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
const draftPairLines = ref<Array<[number, number, number, number]>>([])
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
let fitImageAnimationFrame: number | null = null

const viewerImageSrc = computed(() => props.image?.sourceSrc || props.image?.src || null)
const sourceImageWidth = computed(() => {
  const value = props.image?.sourceWidth ?? props.image?.width ?? naturalWidth.value
  return typeof value === 'number' && Number.isFinite(value) ? value : 0
})
const sourceImageHeight = computed(() => {
  const value = props.image?.sourceHeight ?? props.image?.height ?? naturalHeight.value
  return typeof value === 'number' && Number.isFinite(value) ? value : 0
})
const imageCoordinateWidth = computed(() => {
  const value = sourceImageWidth.value || naturalWidth.value
  return value > 0 ? value : 1
})
const imageCoordinateHeight = computed(() => {
  const value = sourceImageHeight.value || naturalHeight.value
  return value > 0 ? value : 1
})
const imageFrameStyle = computed(() => ({
  width: `${imageCoordinateWidth.value}px`,
  height: `${imageCoordinateHeight.value}px`,
  transform: `translate(-50%, -50%) translate(${offsetX.value}px, ${offsetY.value}px) scale(${scale.value})`,
}))
const imageElementStyle = computed(() => ({
  width: `${imageCoordinateWidth.value}px`,
  height: `${imageCoordinateHeight.value}px`,
}))
const displayImageWidth = computed(() => {
  const value = props.image?.displayWidth ?? props.image?.width
  return typeof value === 'number' && Number.isFinite(value) ? value : 0
})
const displayImageHeight = computed(() => {
  const value = props.image?.displayHeight ?? props.image?.height
  return typeof value === 'number' && Number.isFinite(value) ? value : 0
})
const imageOverlays = computed(() => props.image?.overlays ?? [])
const imageInteraction = computed(() => props.image?.interaction ?? null)
const availableInteractionTools = computed(() => readAvailableInteractionTools(imageInteraction.value))
const hasInteractionTools = computed(() => availableInteractionTools.value.length > 0)
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
const activeLineAngleToleranceDeg = computed(() => {
  const value = activeInteractionTool.value?.angleToleranceDeg
  return typeof value === 'number' && Number.isFinite(value) ? Math.max(0, value) : 8
})
const activeLineSearchPaddingRatio = computed(() => {
  const value = activeInteractionTool.value?.searchPaddingRatio
  return typeof value === 'number' && Number.isFinite(value) ? Math.max(0, value) : 0.08
})
const activeLineSearchPaddingMin = computed(() => {
  const value = activeInteractionTool.value?.searchPaddingMin
  return typeof value === 'number' && Number.isFinite(value) ? Math.max(0, value) : 8
})
const tuningControls = computed(() => imageInteraction.value?.controls ?? [])
const interactionAvailable = computed(() => Boolean(
  props.image?.nodeId
  && imageInteraction.value
  && (hasInteractionTools.value || tuningControls.value.length > 0),
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
const draftLineVisualGuide = computed<LineVisualGuide | null>(() => {
  const line = draftLineXyxy.value
  if (!line || interactionTool.value !== 'line') return null
  const [x1, y1, x2, y2] = line
  const targetParameters = new Set(activeTargetParameters.value)
  const length = pointDistance([x1, y1], [x2, y2])
  const angleDeg = normalizeLineAngleDeg((Math.atan2(y2 - y1, x2 - x1) * 180) / Math.PI)
  const centerX = (x1 + x2) / 2
  const centerY = (y1 + y2) / 2
  const angleTolerance = activeLineAngleToleranceDeg.value
  const showSearchBbox = targetParameters.has('search_bbox_xyxy')
  const showAngleRange = targetParameters.has('angle_min_deg') && targetParameters.has('angle_max_deg')
  const searchPadding = Math.max(activeLineSearchPaddingMin.value, length * activeLineSearchPaddingRatio.value)
  const searchBboxXyxy = showSearchBbox
    ? [
        roundImageCoordinate(Math.min(x1, x2) - searchPadding),
        roundImageCoordinate(Math.min(y1, y2) - searchPadding),
        roundImageCoordinate(Math.max(x1, x2) + searchPadding),
        roundImageCoordinate(Math.max(y1, y2) + searchPadding),
      ] as [number, number, number, number]
    : null
  const angleGuideMin = showAngleRange
    ? buildLineFromCenterAngle(centerX, centerY, length, angleDeg - angleTolerance)
    : null
  const angleGuideMax = showAngleRange
    ? buildLineFromCenterAngle(centerX, centerY, length, angleDeg + angleTolerance)
    : null
  const label = (showSearchBbox || showAngleRange)
    ? {
        x: roundImageCoordinate(centerX + 8),
        y: roundImageCoordinate(Math.max(16, centerY - 10)),
        text: showAngleRange ? `${angleDeg}° ±${angleTolerance}°` : 'Search ROI',
      }
    : null
  return { searchBboxXyxy, angleGuideMin, angleGuideMax, label }
})
const draftLineSearchBboxXyxy = computed(() => draftLineVisualGuide.value?.searchBboxXyxy ?? null)
const draftLineAngleGuideMin = computed(() => draftLineVisualGuide.value?.angleGuideMin ?? null)
const draftLineAngleGuideMax = computed(() => draftLineVisualGuide.value?.angleGuideMax ?? null)
const draftLineGuideLabel = computed(() => draftLineVisualGuide.value?.label ?? null)
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
  || draftPairLines.value.length > 0
  || draftCircle.value
  || draftPointPairs.value.length > 0,
))
const canApplyInteraction = computed(() => {
  if (!interactionAvailable.value) return false
  if (interactionTool.value === 'bbox' || interactionTool.value === 'rect' || interactionTool.value === 'grid') return Boolean(draftBboxXyxy.value)
  if (interactionTool.value === 'template-region') {
    const targetParameters = new Set(activeTargetParameters.value)
    const requiresTemplate = targetParameters.has('template_bbox_xyxy')
    const requiresSearch = targetParameters.has('search_bbox_xyxy')
    if (requiresTemplate && !draftTemplateBboxXyxy.value) return false
    if (requiresSearch && !draftSearchBboxXyxy.value) return false
    return Boolean(draftTemplateBboxXyxy.value || draftSearchBboxXyxy.value)
  }
  if (interactionTool.value === 'polygon' || interactionTool.value === 'contour') {
    const pointCount = draftPointPairs.value.length
    return pointCount >= activePolygonMinPoints.value && (activePolygonMaxPoints.value === null || pointCount <= activePolygonMaxPoints.value)
  }
  if (interactionTool.value === 'circle') return Boolean(draftCircle.value)
  if (interactionTool.value === 'line') return Boolean(draftLineXyxy.value)
  if (interactionTool.value === 'point-pair') return draftPairLines.value.length > 0 || Boolean(draftLineXyxy.value)
  return false
})
const previewActionDisabled = computed(() => Boolean(
  props.previewDisabled
  || props.previewRunning
  || (hasInteractionDraft.value && !canApplyInteraction.value),
))
const hasVisibleOverlay = computed(() => imageOverlays.value.length > 0 || hasInteractionDraft.value)
const overlayPickingActive = computed(() => Boolean(interactionActive.value && interactionAvailable.value))
const overlayViewBox = computed(() => {
  const width = sourceImageWidth.value || naturalWidth.value || 0
  const height = sourceImageHeight.value || naturalHeight.value || 0
  return width > 0 && height > 0 ? `0 0 ${width} ${height}` : ''
})
const imageMetricItems = computed(() => {
  const width = sourceImageWidth.value || naturalWidth.value || 0
  const height = sourceImageHeight.value || naturalHeight.value || 0
  if (width <= 0 || height <= 0) return []
  const pixelCount = width * height
  const aspectRatio = readAspectRatio(width, height)
  const metrics = [
    `${width} × ${height}px`,
    `${formatMetricNumber(pixelCount)} pixels`,
    `${formatMegapixels(pixelCount)} MP`,
    aspectRatio ? `ratio ${aspectRatio}` : '',
  ].filter(Boolean)
  const displayWidth = displayImageWidth.value
  const displayHeight = displayImageHeight.value
  if (displayWidth > 0 && displayHeight > 0 && (displayWidth !== width || displayHeight !== height)) {
    metrics.push(`display ${displayWidth} × ${displayHeight}px`)
  }
  return metrics
})
const interactionStatusText = computed(() => {
  if (!interactionAvailable.value) return ''
  if (!interactionActive.value) return tuningControls.value.length ? t('imageViewer.status.tuningAvailableNotEnabled') : t('imageViewer.status.notEnabled')
  if (interactionTool.value === 'bbox') return draftBboxXyxy.value ? t('imageViewer.status.bboxReady') : t('imageViewer.status.bboxHint')
  if (interactionTool.value === 'rect') return draftBboxXyxy.value ? t('imageViewer.status.rectReady') : t('imageViewer.status.rectHint')
  if (interactionTool.value === 'grid') return draftBboxXyxy.value ? t('imageViewer.status.gridReady') : t('imageViewer.status.gridHint')
  if (interactionTool.value === 'template-region') return readTemplateRegionStatusText()
  if (interactionTool.value === 'polygon' || interactionTool.value === 'contour') return readPolygonInteractionStatusText()
  if (interactionTool.value === 'circle') return circleDraftMode.value === 'three-point' ? t('imageViewer.status.circleThreePoint', { count: draftPointPairs.value.length }) : (draftCircle.value ? t('imageViewer.status.circleReady') : t('imageViewer.status.circleHint'))
  if (interactionTool.value === 'line') return readLineInteractionStatusText()
  if (interactionTool.value === 'point-pair') return draftPairLines.value.length > 0
    ? t('imageViewer.status.pointPairsReady', { count: draftPairLines.value.length })
    : t('imageViewer.status.pointPairHint')
  if (interactionTool.value === 'match-line') return t('imageViewer.status.matchLineHint')
  if (interactionTool.value === 'homography-overlay') return t('imageViewer.status.homographyOverlayHint')
  return ''
})

watch(() => [props.open, viewerImageSrc.value, props.image?.nodeId] as const, ([open]) => {
  resetInteractionState()
  initializeTuningParameterValues()
  if (!open) return
  resetView()
  void nextTick(() => {
    if (imageRef.value?.complete) scheduleFitImage()
  })
})

watch(tuningControls, () => {
  initializeTuningParameterValues()
})

function handleImageLoad(): void {
  updateNaturalImageSize()
  scheduleFitImage()
}

function scheduleFitImage(): void {
  if (fitImageAnimationFrame !== null) window.cancelAnimationFrame(fitImageAnimationFrame)
  fitImageAnimationFrame = window.requestAnimationFrame(() => {
    fitImageAnimationFrame = null
    fitImage()
  })
}

function updateNaturalImageSize(): void {
  const image = imageRef.value
  naturalWidth.value = sourceImageWidth.value || image?.naturalWidth || 0
  naturalHeight.value = sourceImageHeight.value || image?.naturalHeight || 0
}

function fitImage(): void {
  const viewport = viewportRef.value
  const image = imageRef.value
  if (!viewport || !image) return
  updateNaturalImageSize()
  const viewportBounds = viewport.getBoundingClientRect()
  const sourceWidth = imageCoordinateWidth.value
  const sourceHeight = imageCoordinateHeight.value
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
  if (isPickOnlyInteractionTool(interactionTool.value)) return false
  event.preventDefault()
  event.stopPropagation()
  const point = readImagePointFromEvent(event)
  if (!point) return true
  if (interactionTool.value === 'bbox' || interactionTool.value === 'rect' || interactionTool.value === 'grid' || interactionTool.value === 'template-region') {
    startBboxDraft(point)
    return true
  }
  if (interactionTool.value === 'polygon' || interactionTool.value === 'contour') {
    addDraftPoint(point, activePolygonMaxPoints.value ?? undefined)
    return true
  }
  if (interactionTool.value === 'circle') {
    if (circleDraftMode.value === 'three-point') addDraftPoint(point, 3)
    else startCircleDraft(point)
    return true
  }
  if (interactionTool.value === 'line' || interactionTool.value === 'point-pair') {
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
      showInteractionFeedback(t('imageViewer.feedback.templateSelectedDrawSearch'), 'info')
    } else {
      draftSearchBboxXyxy.value = draftBboxXyxy.value
      showInteractionFeedback(t('imageViewer.feedback.searchReadyApply'), 'success')
    }
    draftBbox.value = null
  }
}

function startLineDraft(point: ImagePoint): void {
  clearShapeDrafts({ keepPairLines: interactionTool.value === 'point-pair' })
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
  if (!draftLineXyxy.value) return
  if (interactionTool.value === 'point-pair') {
    draftPairLines.value = [...draftPairLines.value, draftLineXyxy.value]
    draftLine.value = null
    showInteractionFeedback(t('imageViewer.feedback.pointPairsAdded', { count: draftPairLines.value.length }), 'success')
    return
  }
  showInteractionFeedback(readLineInteractionStatusText(), 'success')
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
  const sourceWidth = sourceImageWidth.value || naturalWidth.value || image.naturalWidth || 0
  const sourceHeight = sourceImageHeight.value || naturalHeight.value || image.naturalHeight || 0
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
  if (isSupportedInteractionTool(tool)) return t(interactionToolRegistry[tool].messageKey)
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

function clearShapeDrafts(options: { keepPoints?: boolean; keepPairLines?: boolean } = {}): void {
  draftBbox.value = null
  draftLine.value = null
  draftCircleCenter.value = null
  draftCircleEdge.value = null
  if (!options.keepPoints) draftPoints.value = []
  if (!options.keepPairLines) draftPairLines.value = []
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
    showInteractionFeedback(t('imageViewer.feedback.incompleteApply'), 'warning')
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
    angleToleranceDeg: activeInteractionTool.value?.angleToleranceDeg ?? null,
    searchPaddingRatio: activeInteractionTool.value?.searchPaddingRatio ?? null,
    searchPaddingMin: activeInteractionTool.value?.searchPaddingMin ?? null,
  }
  if ((interactionTool.value === 'bbox' || interactionTool.value === 'rect' || interactionTool.value === 'grid') && draftBboxXyxy.value) {
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
  if ((interactionTool.value === 'polygon' || interactionTool.value === 'contour') && canApplyInteraction.value) {
    return { ...baseEvent, pointsXy: draftPointPairs.value }
  }
  if (interactionTool.value === 'circle' && draftCircle.value) {
    return { ...baseEvent, circle: draftCircle.value }
  }
  if (interactionTool.value === 'line' && draftLineXyxy.value) {
    return { ...baseEvent, lineXyxy: draftLineXyxy.value }
  }
  if (interactionTool.value === 'point-pair') {
    const pairLinesXyxy = draftLineXyxy.value
      ? [...draftPairLines.value, draftLineXyxy.value]
      : [...draftPairLines.value]
    return pairLinesXyxy.length > 0 ? { ...baseEvent, pairLinesXyxy } : null
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
  if (control.control === 'select') return control.options?.[0]?.value ?? ''
  if (control.control === 'number') return ''
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
  if (!(target instanceof HTMLInputElement) && !(target instanceof HTMLSelectElement)) return
  let value: unknown
  if (control.control === 'checkbox' && target instanceof HTMLInputElement) {
    value = target.checked
  } else if (control.control === 'select') {
    value = target.value
  } else {
    value = target.value === '' ? '' : Number(target.value)
  }
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
    angleToleranceDeg: activeInteractionTool.value?.angleToleranceDeg ?? null,
    searchPaddingRatio: activeInteractionTool.value?.searchPaddingRatio ?? null,
    searchPaddingMin: activeInteractionTool.value?.searchPaddingMin ?? null,
    parameters,
  }
  emit('applyInteraction', event)
  showInteractionFeedback(requestPreview ? t('imageViewer.feedback.tuningAppliedPreview') : t('imageViewer.feedback.tuningApplied'), 'success')
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
      props.previewRunning ? t('imageViewer.feedback.previewRunning') : t('imageViewer.feedback.incompletePreview'),
      'warning',
    )
    return
  }
  const event = buildInteractionDraftEvent()
  if (hasInteractionDraft.value) {
    if (!event) {
      showInteractionFeedback(t('imageViewer.feedback.incompletePreview'), 'warning')
      return
    }
    emit('applyInteraction', event)
    showInteractionFeedback(t('imageViewer.feedback.appliedStartingPreview', { message: readAppliedFeedbackText(event) }), 'success')
  } else {
    showInteractionFeedback(t('imageViewer.feedback.startingPreview'), 'info')
  }
  emit('runPreview')
}

function readAppliedFeedbackText(event: ViewerImageInteractionApplyEvent): string {
  if (event.tool === 'bbox') return t('imageViewer.applied.bbox')
  if (event.tool === 'rect') return t('imageViewer.applied.rect')
  if (event.tool === 'template-region') return t('imageViewer.applied.templateRegion')
  if (event.tool === 'polygon') return t('imageViewer.applied.polygon')
  if (event.tool === 'contour') return t('imageViewer.applied.contour')
  if (event.tool === 'grid') return t('imageViewer.applied.grid')
  if (event.tool === 'circle') return t('imageViewer.applied.circle')
  if (event.tool === 'line') return t('imageViewer.applied.line')
  if (event.tool === 'point-pair') return t('imageViewer.applied.pointPair')
  if (event.tool === 'match-line') return t('imageViewer.applied.matchLine')
  if (event.tool === 'homography-overlay') return t('imageViewer.applied.homographyOverlay')
  return t('imageViewer.applied.default')
}

function handleOverlayMouseDown(overlay: ViewerImageOverlay, event: MouseEvent): void {
  const pickEvent = buildOverlayPickEvent(overlay)
  if (!pickEvent) return
  event.preventDefault()
  event.stopPropagation()
  clearInteractionDraft()
  emit('applyInteraction', pickEvent)
  showInteractionFeedback(t('imageViewer.feedback.overlaySelected', { label: readOverlayLabel(overlay), message: readAppliedFeedbackText(pickEvent) }), 'success')
}

function buildOverlayPickEvent(overlay: ViewerImageOverlay): ViewerImageInteractionApplyEvent | null {
  const interaction = imageInteraction.value
  const nodeId = props.image?.nodeId
  if (!overlayPickingActive.value || !interaction || !nodeId) return null

  const tool = interactionTool.value
  const targetParameters = overlay.targetParameters.length > 0 ? overlay.targetParameters : activeTargetParameters.value
  const baseEvent = {
    nodeId,
    tool,
    coordinateSpace: interaction.coordinateSpace,
    targetParameters,
    angleToleranceDeg: activeInteractionTool.value?.angleToleranceDeg ?? null,
    searchPaddingRatio: activeInteractionTool.value?.searchPaddingRatio ?? null,
    searchPaddingMin: activeInteractionTool.value?.searchPaddingMin ?? null,
    parameters: pickOverlayTargetParameters(overlay.parameters, targetParameters),
  }

  if ((tool === 'bbox' || tool === 'rect' || tool === 'grid') && readOverlayBbox(overlay)) {
    return { ...baseEvent, bboxXyxy: readOverlayBbox(overlay) ?? undefined }
  }

  if (tool === 'template-region') {
    const bboxXyxy = readOverlayBbox(overlay)
    if (!bboxXyxy) return null
    if (targetParameters.includes('template_bbox_xyxy') && !targetParameters.includes('search_bbox_xyxy')) {
      return { ...baseEvent, bboxXyxy, templateBboxXyxy: bboxXyxy }
    }
    if (targetParameters.includes('search_bbox_xyxy') && !targetParameters.includes('template_bbox_xyxy')) {
      return { ...baseEvent, bboxXyxy, searchBboxXyxy: bboxXyxy }
    }
    return templateRegionStage.value === 'template'
      ? { ...baseEvent, bboxXyxy, templateBboxXyxy: bboxXyxy }
      : { ...baseEvent, bboxXyxy, searchBboxXyxy: bboxXyxy }
  }

  if (tool === 'polygon' || tool === 'contour') {
    if (overlay.pointsXy.length >= activePolygonMinPoints.value) {
      return { ...baseEvent, pointsXy: overlay.pointsXy }
    }
    const bboxPoints = readOverlayBboxPoints(overlay)
    if (bboxPoints.length >= activePolygonMinPoints.value) {
      return { ...baseEvent, pointsXy: bboxPoints }
    }
    return null
  }

  if (tool === 'circle' && overlay.circle) {
    return { ...baseEvent, circle: overlay.circle }
  }

  if (tool === 'line' && overlay.lineXyxy) {
    return { ...baseEvent, lineXyxy: overlay.lineXyxy }
  }

  if (tool === 'point-pair' && overlay.lineXyxy) {
    return { ...baseEvent, pairLinesXyxy: [overlay.lineXyxy] }
  }

  if (tool === 'match-line' && (overlay.lineXyxy || overlay.circle)) {
    return { ...baseEvent, lineXyxy: overlay.lineXyxy ?? undefined, circle: overlay.circle ?? undefined }
  }

  if (tool === 'homography-overlay') {
    if (overlay.pointsXy.length >= 3) return { ...baseEvent, pointsXy: overlay.pointsXy }
    const bboxPoints = readOverlayBboxPoints(overlay)
    if (bboxPoints.length >= 3) return { ...baseEvent, pointsXy: bboxPoints }
    return Object.keys(overlay.parameters).length > 0 ? baseEvent : null
  }

  return null
}

function pickOverlayTargetParameters(
  parameters: Record<string, unknown>,
  targetParameters: string[],
): Record<string, unknown> {
  const allowedParameters = new Set(targetParameters)
  const pickedParameters: Record<string, unknown> = {}
  for (const [parameterName, parameterValue] of Object.entries(parameters)) {
    if (allowedParameters.has(parameterName)) pickedParameters[parameterName] = parameterValue
  }
  return pickedParameters
}

function readOverlayShapeClass(overlay: ViewerImageOverlay, shapeKind: string): Array<string | Record<string, boolean>> {
  return [
    'image-viewer__overlay-shape',
    `image-viewer__overlay-shape--${shapeKind}`,
    readOverlayKindClass(overlay.kind),
    { 'image-viewer__overlay-shape--selectable': Boolean(buildOverlayPickEvent(overlay)) },
  ].filter(Boolean)
}

function readOverlayKindClass(kind: string): string {
  const normalizedKind = kind
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
  return normalizedKind ? `image-viewer__overlay-shape--kind-${normalizedKind}` : ''
}

function readOverlayBbox(overlay: ViewerImageOverlay): [number, number, number, number] | null {
  if (overlay.bboxXyxy) return overlay.bboxXyxy
  if (overlay.pointsXy.length === 0) return null
  const xValues = overlay.pointsXy.map(([pointX]) => pointX)
  const yValues = overlay.pointsXy.map(([, pointY]) => pointY)
  return [
    roundImageCoordinate(Math.min(...xValues)),
    roundImageCoordinate(Math.min(...yValues)),
    roundImageCoordinate(Math.max(...xValues)),
    roundImageCoordinate(Math.max(...yValues)),
  ]
}

function readOverlayBboxPoints(overlay: ViewerImageOverlay): Array<[number, number]> {
  const bboxXyxy = readOverlayBbox(overlay)
  if (!bboxXyxy) return []
  const [x1, y1, x2, y2] = bboxXyxy
  return [
    [x1, y1],
    [x2, y1],
    [x2, y2],
    [x1, y2],
  ]
}

function readOverlayLabel(overlay: ViewerImageOverlay): string {
  return overlay.label || overlay.id || readInteractionToolLabel(interactionTool.value)
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
    angleToleranceDeg: toolItem.angleToleranceDeg ?? null,
    searchPaddingRatio: toolItem.searchPaddingRatio ?? null,
    searchPaddingMin: toolItem.searchPaddingMin ?? null,
  }]
}

function readTemplateRegionStatusText(): string {
  const templateReady = Boolean(draftTemplateBboxXyxy.value)
  const searchReady = Boolean(draftSearchBboxXyxy.value)
  const currentStageText = templateRegionStage.value === 'template' ? t('imageViewer.toolbar.templateRoi') : t('imageViewer.toolbar.searchRoi')
  if (templateReady && searchReady) return t('imageViewer.status.templateAndSearchReady')
  if (templateReady) return t('imageViewer.status.templateReadyContinueSearch')
  if (searchReady) return t('imageViewer.status.searchReadyContinueTemplate')
  return t('imageViewer.status.dragStage', { stage: currentStageText })
}

function readPolygonInteractionStatusText(): string {
  const pointCount = draftPointPairs.value.length
  const minPoints = activePolygonMinPoints.value
  const maxPoints = activePolygonMaxPoints.value
  if (maxPoints !== null && maxPoints === minPoints) {
    return pointCount >= maxPoints ? t('imageViewer.status.polygonReadyRatio', { count: pointCount, max: maxPoints }) : t('imageViewer.status.polygonRatio', { count: pointCount, max: maxPoints })
  }
  if (pointCount >= minPoints) return t('imageViewer.status.polygonReady', { count: pointCount })
  return t('imageViewer.status.polygonMinimum', { count: pointCount, min: minPoints })
}

function readLineInteractionStatusText(): string {
  const targetParameters = new Set(activeTargetParameters.value)
  if (!draftLineXyxy.value) {
    if (targetParameters.has('search_bbox_xyxy') && targetParameters.has('angle_min_deg') && targetParameters.has('angle_max_deg')) {
      return t('imageViewer.status.lineDirectionHint')
    }
    if (targetParameters.has('search_bbox_xyxy')) return t('imageViewer.status.lineSearchHint')
    return t('imageViewer.status.lineHint')
  }
  const [x1, y1, x2, y2] = draftLineXyxy.value
  const length = roundImageCoordinate(pointDistance([x1, y1], [x2, y2]))
  const angleDeg = normalizeLineAngleDeg((Math.atan2(y2 - y1, x2 - x1) * 180) / Math.PI)
  return t('imageViewer.status.lineReady', { length, angle: angleDeg })
}

function isSupportedInteractionTool(tool: string): tool is InteractionToolId {
  return Object.prototype.hasOwnProperty.call(interactionToolRegistry, tool)
}

function isPickOnlyInteractionTool(tool: string): boolean {
  return tool === 'match-line' || tool === 'homography-overlay'
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

function readAspectRatio(width: number, height: number): string {
  const divisor = greatestCommonDivisor(Math.round(width), Math.round(height))
  return divisor > 0 ? `${Math.round(width / divisor)}:${Math.round(height / divisor)}` : ''
}

function greatestCommonDivisor(firstValue: number, secondValue: number): number {
  let leftValue = Math.abs(firstValue)
  let rightValue = Math.abs(secondValue)
  while (rightValue > 0) {
    const nextValue = leftValue % rightValue
    leftValue = rightValue
    rightValue = nextValue
  }
  return leftValue
}

function formatMetricNumber(value: number): string {
  return Math.round(value).toLocaleString('en-US')
}

function formatMegapixels(pixelCount: number): string {
  return (pixelCount / 1_000_000).toFixed(pixelCount >= 10_000_000 ? 1 : 2)
}

function normalizeLineAngleDeg(angleDeg: number): number {
  let normalizedAngle = angleDeg % 180
  if (normalizedAngle >= 90) normalizedAngle -= 180
  if (normalizedAngle < -90) normalizedAngle += 180
  return roundImageCoordinate(normalizedAngle)
}

function buildLineFromCenterAngle(centerX: number, centerY: number, length: number, angleDeg: number): [number, number, number, number] {
  const radians = (angleDeg * Math.PI) / 180
  const halfLength = Math.max(1, length) / 2
  const deltaX = Math.cos(radians) * halfLength
  const deltaY = Math.sin(radians) * halfLength
  return [
    roundImageCoordinate(centerX - deltaX),
    roundImageCoordinate(centerY - deltaY),
    roundImageCoordinate(centerX + deltaX),
    roundImageCoordinate(centerY + deltaY),
  ]
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
  if (fitImageAnimationFrame !== null) window.cancelAnimationFrame(fitImageAnimationFrame)
})
</script>
