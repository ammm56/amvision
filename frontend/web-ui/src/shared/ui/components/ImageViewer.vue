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
            <Button
              v-if="interactionTool === 'polygon' && draftPointPairs.length > 0"
              size="sm"
              variant="secondary"
              type="button"
              :title="t('imageViewer.toolbar.deleteVertex')"
              @click="deleteLastDraftPoint"
            >
              {{ t('imageViewer.toolbar.deleteVertex') }}
            </Button>
            <Button
              v-if="interactionTool === 'polygon' && activeInteractionTool?.collection && draftPointPairs.length >= activePolygonMinPoints"
              size="sm"
              variant="secondary"
              type="button"
              :disabled="draftPolygonSelfIntersects"
              @click="finishDraftPolygon"
            >
              {{ t('imageViewer.toolbar.addPolygon') }}
            </Button>
            <div v-if="interactionTool === 'mask'" class="image-viewer__tool-tabs">
              <Button size="sm" :variant="maskDrawMode === 'brush' ? 'primary' : 'secondary'" type="button" @click="maskDrawMode = 'brush'">{{ t('imageViewer.toolbar.brush') }}</Button>
              <Button size="sm" :variant="maskDrawMode === 'eraser' ? 'primary' : 'secondary'" type="button" @click="maskDrawMode = 'eraser'">{{ t('imageViewer.toolbar.eraser') }}</Button>
              <label class="image-viewer__mask-brush-size" :title="t('imageViewer.toolbar.brushSize')">
                <span>{{ maskBrushSize }}</span>
                <input v-model.number="maskBrushSize" type="range" min="1" max="128" step="1">
              </label>
              <Button size="sm" variant="secondary" type="button" :disabled="maskHistoryIndex <= 0" @click="undoMaskEdit">{{ t('imageViewer.toolbar.undo') }}</Button>
              <Button size="sm" variant="secondary" type="button" :disabled="maskHistoryIndex >= maskHistory.length - 1" @click="redoMaskEdit">{{ t('imageViewer.toolbar.redo') }}</Button>
              <Button size="sm" variant="secondary" type="button" @click="fillMaskDraft">{{ t('imageViewer.toolbar.fill') }}</Button>
            </div>
            <div v-if="interactionTool === 'template-region'" class="image-viewer__tool-tabs">
              <Button size="sm" :variant="templateRegionStage === 'template' ? 'primary' : 'secondary'" type="button" :title="t('imageViewer.toolbar.drawTemplateRoi')" @click="selectTemplateRegionStage('template')">
                {{ t('imageViewer.toolbar.templateRoi') }}
              </Button>
              <Button size="sm" :variant="templateRegionStage === 'search' ? 'primary' : 'secondary'" type="button" :title="t('imageViewer.toolbar.drawSearchRoi')" @click="selectTemplateRegionStage('search')">
                {{ t('imageViewer.toolbar.searchRoi') }}
              </Button>
            </div>
            <Button size="sm" variant="secondary" type="button" :title="hasInteractionDraft ? t('imageViewer.toolbar.clearDraft') : t('imageViewer.toolbar.clearGeometry')" :disabled="!hasInteractionDraft && !hasClearableGeometry" @click="handleClearInteraction">
              <Trash2 :size="15" />
              {{ t('imageViewer.toolbar.clear') }}
            </Button>
            <Button
              size="sm"
              variant="primary"
              type="button"
              :title="t('imageViewer.toolbar.applyParams')"
              :disabled="!canApplyInteraction || interactionApplying"
              @click="applyInteractionDraft"
            >
              <Check :size="15" />
              {{ interactionApplyButtonText }}
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
                  :min="readTuningControlAttributes(control).min ?? 0"
                  :max="readTuningControlAttributes(control).max ?? 100"
                  :step="readTuningControlAttributes(control).step"
                  :value="readTuningControlInputValue(control)"
                  @input="updateTuningControlFromEvent(control, $event, false)"
                  @change="updateTuningControlFromEvent(control, $event, true)"
                >
                <input
                  type="number"
                  :min="readTuningControlAttributes(control).min"
                  :max="readTuningControlAttributes(control).max"
                  :step="readTuningControlAttributes(control).step"
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
          <canvas
            v-if="interactionTool === 'mask'"
            ref="maskCanvasRef"
            class="image-viewer__mask-canvas"
            :width="imageCoordinateWidth"
            :height="imageCoordinateHeight"
            @mousedown.stop.prevent="startMaskStroke"
            @mousemove.stop.prevent="continueMaskStroke"
            @mouseup.stop.prevent="finishMaskStroke"
            @mouseleave="finishMaskStroke"
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
              <circle
                v-else-if="overlay.pointsXy.length === 1"
                :class="readOverlayShapeClass(overlay, 'point')"
                :cx="overlay.pointsXy[0][0]"
                :cy="overlay.pointsXy[0][1]"
                r="5"
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
            <ImageGeometryEditorOverlay
              :editable="interactionActive"
              :active-tool="interactionTool"
              :canvas-width="imageCoordinateWidth"
              :canvas-height="imageCoordinateHeight"
              :bboxes="draftBboxesXyxy"
              :polygons="draftPolygonsXy"
              :positive-points="positiveDraftPointPairs"
              :negative-points="negativeDraftPointPairs"
              @update:bboxes="updateDraftBboxes"
              @update:polygons="updateDraftPolygons"
              @update:positive-points="updatePositiveDraftPoints"
              @update:negative-points="updateNegativeDraftPoints"
              @changed="markInteractionDraftDirty"
            />
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
        <ImageGeometryAnnotations
          :view-box="dimensionLayerViewBox"
          :roi-annotations="roiDimensionAnnotations"
          :circle-annotations="circleDimensionAnnotations"
        />
      </div>
      <div class="image-viewer__status">
        <div class="image-viewer__status-group">
          <span>{{ Math.round(scale * 100) }}%</span>
          <span v-for="metric in imageMetricItems" :key="metric">{{ metric }}</span>
        </div>
        <span
          v-if="interactionFeedback"
          class="image-viewer__status-message"
          :class="`image-viewer__status-message--${interactionFeedback.tone}`"
        >
          {{ interactionFeedback.text }}
        </span>
        <span
          v-else-if="interactionApplyStatusText"
          class="image-viewer__status-message"
          :class="interactionDraftState === 'dirty' || interactionDraftState === 'failed'
            ? 'image-viewer__status-message--warning'
            : 'image-viewer__status-message--success'"
        >
          {{ interactionApplyStatusText }}
        </span>
        <span v-else-if="interactionStatusText">{{ interactionStatusText }}</span>
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
import ImageGeometryAnnotations from '../image-viewer/ImageGeometryAnnotations.vue'
import ImageGeometryEditorOverlay from '../image-viewer/ImageGeometryEditorOverlay.vue'
import { useImageGeometryAnnotations } from '../image-viewer/useImageGeometryAnnotations'
import { dispatchImageViewerPreview } from '../image-viewer/dispatchImageViewerPreview'
import {
  normalizeImageInteractionTool,
  type ViewerImageInteractionTool,
} from '../image-viewer/normalizeImageInteractionTool'
import { useImageViewerViewport } from '../image-viewer/useImageViewerViewport'
import { buildNumericInputAttributes, type NumericInputAttributes } from '../numeric-input-step'
import type {
  ImageBboxTuple,
  ImagePointTuple,
} from '../image-viewer/geometryEditing'

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

function readTuningControlAttributes(control: ViewerImageInteractionControl): NumericInputAttributes {
  return buildNumericInputAttributes({
    valueKind: 'number',
    minimum: control.min ?? undefined,
    maximum: control.max ?? undefined,
    explicitStep: control.step ?? undefined,
  })
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
  clearParameterNames?: string[]
  parameters?: Record<string, unknown>
  angleToleranceDeg?: number | null
  searchPaddingRatio?: number | null
  searchPaddingMin?: number | null
  bboxXyxy?: [number, number, number, number]
  bboxesXyxy?: Array<[number, number, number, number]>
  templateBboxXyxy?: [number, number, number, number]
  searchBboxXyxy?: [number, number, number, number]
  pointsXy?: Array<[number, number]>
  polygonsXy?: Array<Array<[number, number]>>
  circle?: ViewerImageCircleOverlay
  lineXyxy?: [number, number, number, number]
  pairLinesXyxy?: Array<[number, number, number, number]>
  maskDataUrl?: string
  maskSourceIdentity?: string
  onApplied?: (success: boolean) => void
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
  | 'point'
  | 'positive-point'
  | 'negative-point'
  | 'mask'
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
  point: { messageKey: 'imageViewer.tools.point' },
  'positive-point': { messageKey: 'imageViewer.tools.positivePoint' },
  'negative-point': { messageKey: 'imageViewer.tools.negativePoint' },
  mask: { messageKey: 'imageViewer.tools.mask' },
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
  interactionApplying?: boolean
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
const naturalWidth = ref(0)
const naturalHeight = ref(0)
const interactionActive = ref(false)
const selectedInteractionTool = ref('')
const draftBbox = ref<{ start: ImagePoint; current: ImagePoint } | null>(null)
const draftBboxesXyxy = ref<Array<[number, number, number, number]>>([])
const draftLine = ref<{ start: ImagePoint; current: ImagePoint } | null>(null)
const draftPairLines = ref<Array<[number, number, number, number]>>([])
const draftCircleCenter = ref<ImagePoint | null>(null)
const draftCircleEdge = ref<ImagePoint | null>(null)
const draftPoints = ref<ImagePoint[]>([])
const draftPolygonsXy = ref<Array<Array<[number, number]>>>([])
const draftPointCollections = ref<Record<string, Array<[number, number]>>>({})
const maskCanvasRef = ref<HTMLCanvasElement | null>(null)
const maskDrawMode = ref<'brush' | 'eraser'>('brush')
const maskBrushSize = ref(24)
const maskDrawing = ref(false)
const maskLastPoint = ref<ImagePoint | null>(null)
const maskHistory = ref<ImageData[]>([])
const maskHistoryIndex = ref(-1)
const maskDirty = ref(false)
const maskHasForeground = ref(false)
let maskInitializationGeneration = 0
const circleDraftMode = ref<CircleDraftMode>('center-radius')
const templateRegionStage = ref<TemplateRegionStage>('template')
const draftTemplateBboxXyxy = ref<[number, number, number, number] | null>(null)
const draftSearchBboxXyxy = ref<[number, number, number, number] | null>(null)
const tuningParameterValues = ref<Record<string, unknown>>({})
const autoPreviewEnabled = ref(true)
const interactionFeedback = ref<{ text: string; tone: 'success' | 'warning' | 'info' } | null>(null)
const interactionDraftState = ref<'idle' | 'applied' | 'dirty' | 'applying' | 'failed'>('idle')
const clearedGeometryLocally = ref(false)
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
const displayImageWidth = computed(() => {
  const value = props.image?.displayWidth ?? props.image?.width
  return typeof value === 'number' && Number.isFinite(value) ? value : 0
})
const displayImageHeight = computed(() => {
  const value = props.image?.displayHeight ?? props.image?.height
  return typeof value === 'number' && Number.isFinite(value) ? value : 0
})
const imageOverlays = computed(() => {
  const overlays = props.image?.overlays ?? []
  if (!clearedGeometryLocally.value) return overlays
  return overlays.filter((overlay) => overlay.kind !== 'search-roi' && overlay.kind !== 'reference-circle')
})
const imageInteraction = computed(() => props.image?.interaction ?? null)
const availableInteractionTools = computed(() => readAvailableInteractionTools(imageInteraction.value))
const hasInteractionTools = computed(() => availableInteractionTools.value.length > 0)
const activeInteractionTool = computed(() => {
  const tools = availableInteractionTools.value
  if (tools.length === 0) return null
  return tools.find((tool) => tool.tool === selectedInteractionTool.value) ?? tools[0]
})
// 交互子工具切换不能重置同一编辑会话中的草稿。例如 Point Prompt
// 需要在 Positive 与 Negative 之间反复切换并共同提交。这里只跟踪服务端
// 下发的初始化数据；只有图片、节点或已保存几何真正变化时才重新初始化。
const interactionInitializationIdentity = computed(() => JSON.stringify(
  availableInteractionTools.value.map((tool) => ({
    tool: tool.tool,
    sourceIdentity: tool.sourceIdentity ?? null,
    maskSrc: tool.maskSrc ?? null,
    initialPointsXy: tool.initialPointsXy ?? null,
    initialBboxesXyxy: tool.initialBboxesXyxy ?? null,
    initialPolygonsXy: tool.initialPolygonsXy ?? null,
  })),
))
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
const tuningPanelReservedWidth = computed(() => tuningControls.value.length > 0 ? 366 : 0)
const {
  scale,
  viewportWidth,
  viewportHeight,
  imageFrameStyle,
  imageElementStyle,
  fitImage,
  showOriginalSize,
  resetView,
  zoomIn,
  zoomOut,
  handleWheel,
  sourceToViewport,
  startPan,
} = useImageViewerViewport({
  viewportRef,
  imageWidth: imageCoordinateWidth,
  imageHeight: imageCoordinateHeight,
  reservedRightPx: tuningPanelReservedWidth,
})
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
const positiveDraftPointPairs = computed<Array<[number, number]>>(
  () => draftPointCollections.value['positive-point'] ?? [],
)
const negativeDraftPointPairs = computed<Array<[number, number]>>(
  () => draftPointCollections.value['negative-point'] ?? [],
)
const activeCollectionPointPairs = computed<Array<[number, number]>>(
  () => draftPointCollections.value[interactionTool.value] ?? [],
)
const collectionPolygonsValid = computed(() => draftPolygonsXy.value.every(
  (polygon) => polygon.length >= activePolygonMinPoints.value
    && !polygonHasSelfIntersection(polygon),
))
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
const {
  roiAnnotations: roiDimensionAnnotations,
  circleAnnotations: circleDimensionAnnotations,
  layerViewBox: dimensionLayerViewBox,
} = useImageGeometryAnnotations({
  overlays: imageOverlays,
  draftBboxXyxy,
  draftCircle,
  interactionTool,
  viewportWidth,
  viewportHeight,
  reservedRightPx: tuningPanelReservedWidth,
  sourceToViewport,
  translate: (key) => t(key),
})
const hasInteractionDraft = computed(() => Boolean(
  draftBbox.value
  || draftBboxesXyxy.value.length > 0
  || draftTemplateBboxXyxy.value
  || draftSearchBboxXyxy.value
  || draftLine.value
  || draftPairLines.value.length > 0
  || draftCircle.value
  || draftPointPairs.value.length > 0
  || positiveDraftPointPairs.value.length > 0
  || negativeDraftPointPairs.value.length > 0
  || draftPolygonsXy.value.length > 0
  || maskDirty.value,
))
const clearableGeometryParameters = computed(() => Array.from(new Set(
  availableInteractionTools.value.flatMap((tool) => tool.clearParameters ?? []),
)))
const hasClearableGeometry = computed(() => clearableGeometryParameters.value.length > 0)
const canApplyInteraction = computed(() => {
  if (!interactionAvailable.value) return false
  if (interactionTool.value === 'bbox' || interactionTool.value === 'rect' || interactionTool.value === 'grid') {
    return activeInteractionTool.value?.collection
      ? draftBboxesXyxy.value.length > 0 || Boolean(draftBboxXyxy.value)
      : Boolean(draftBboxXyxy.value)
  }
  if (interactionTool.value === 'template-region') {
    const targetParameters = new Set(activeTargetParameters.value)
    const requiresTemplate = targetParameters.has('template_bbox_xyxy')
    const requiresSearch = targetParameters.has('search_bbox_xyxy')
    if (requiresTemplate && !draftTemplateBboxXyxy.value) return false
    if (requiresSearch && !draftSearchBboxXyxy.value) return false
    return Boolean(draftTemplateBboxXyxy.value || draftSearchBboxXyxy.value)
  }
  if (interactionTool.value === 'polygon' || interactionTool.value === 'contour') {
    if (activeInteractionTool.value?.collection) {
      if (!collectionPolygonsValid.value) return false
      return draftPolygonsXy.value.length > 0 || (
        draftPointPairs.value.length >= activePolygonMinPoints.value
        && !draftPolygonSelfIntersects.value
      )
    }
    const pointCount = draftPointPairs.value.length
    return pointCount >= activePolygonMinPoints.value
      && (activePolygonMaxPoints.value === null || pointCount <= activePolygonMaxPoints.value)
      && !draftPolygonSelfIntersects.value
  }
  if (interactionTool.value === 'point') return draftPointPairs.value.length === 1
  if (interactionTool.value === 'positive-point') return positiveDraftPointPairs.value.length > 0
  if (interactionTool.value === 'negative-point') {
    // SAM3 允许用 Negative Point 排除区域，但一个对象仍必须至少有一个
    // Positive Point。这里提前阻止仅含负点的无效 Prompt 流入后端。
    return positiveDraftPointPairs.value.length > 0
  }
  if (interactionTool.value === 'mask') {
    return Boolean(
      maskDirty.value
      && maskHasForeground.value
      && activeInteractionTool.value?.sourceIdentity?.trim(),
    )
  }
  if (interactionTool.value === 'circle') return Boolean(draftCircle.value)
  if (interactionTool.value === 'line') return Boolean(draftLineXyxy.value)
  if (interactionTool.value === 'point-pair') return draftPairLines.value.length > 0 || Boolean(draftLineXyxy.value)
  return false
})
const previewActionDisabled = computed(() => Boolean(
  props.previewDisabled
  || props.previewRunning
  || props.interactionApplying
  || (hasInteractionDraft.value && !canApplyInteraction.value),
))
const interactionApplyStatusText = computed(() => {
  if (!hasCollectionInteraction.value) return ''
  if (interactionDraftState.value === 'dirty') return t('imageViewer.status.unsavedChanges')
  if (interactionDraftState.value === 'applying') return t('imageViewer.status.applyingParameters')
  if (interactionDraftState.value === 'failed') return t('imageViewer.status.applyFailed')
  if (interactionDraftState.value === 'applied') return t('imageViewer.status.parametersApplied')
  return ''
})
const interactionApplyButtonText = computed(() => {
  if (interactionDraftState.value === 'applying') return t('imageViewer.status.applyingParameters')
  if (interactionDraftState.value === 'applied') return t('imageViewer.status.parametersApplied')
  return t('imageViewer.toolbar.applyParams')
})
const hasCollectionInteraction = computed(() => Boolean(
  activeInteractionTool.value?.collection
  || interactionTool.value === 'positive-point'
  || interactionTool.value === 'negative-point'
  || interactionTool.value === 'mask'
))
const hasVisibleOverlay = computed(() => imageOverlays.value.length > 0 || hasInteractionDraft.value)
const overlayPickingActive = computed(() => Boolean(interactionActive.value && interactionAvailable.value))
const draftPolygonSelfIntersects = computed(() => (
  interactionTool.value === 'polygon' && polygonHasSelfIntersection(draftPointPairs.value)
))
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
  if (interactionTool.value === 'point') return draftPointPairs.value.length === 1 ? t('imageViewer.status.pointReady') : t('imageViewer.status.pointHint')
  if (interactionTool.value === 'positive-point' || interactionTool.value === 'negative-point') {
    return activeCollectionPointPairs.value.length > 0
      ? t('imageViewer.status.pointsReady', { count: activeCollectionPointPairs.value.length })
      : t('imageViewer.status.pointsHint')
  }
  if (interactionTool.value === 'mask') return maskHasForeground.value ? t('imageViewer.status.maskReady') : t('imageViewer.status.maskHint')
  if (interactionTool.value === 'polygon' && draftPolygonSelfIntersects.value) return t('imageViewer.status.polygonSelfIntersecting')
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

watch(() => [
  props.open,
  viewerImageSrc.value,
  props.image?.nodeId,
  interactionInitializationIdentity.value,
] as const, ([open]) => {
  clearedGeometryLocally.value = false
  resetInteractionState()
  initializeCollectionDrafts()
  initializeTuningParameterValues()
  if (!open) return
  resetView()
  void nextTick(() => {
    if (!imageRef.value?.complete) return
    updateNaturalImageSize()
    scheduleFitImage()
    if (interactionTool.value === 'mask') void initializeMaskCanvas()
  })
})

watch(tuningControls, () => {
  initializeTuningParameterValues()
})

function handleImageLoad(): void {
  updateNaturalImageSize()
  scheduleFitImage()
  if (interactionTool.value === 'mask') void nextTick(initializeMaskCanvas)
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
  if (interactionTool.value === 'point') {
    addDraftPoint(point, 1)
    return true
  }
  if (interactionTool.value === 'positive-point' || interactionTool.value === 'negative-point') {
    const tool = interactionTool.value
    draftPointCollections.value = {
      ...draftPointCollections.value,
      [tool]: [
        ...(draftPointCollections.value[tool] ?? []),
        [roundImageCoordinate(point.x), roundImageCoordinate(point.y)],
      ],
    }
    markInteractionDraftDirty()
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
  clearShapeDrafts({
    keepBboxCollection: activeInteractionTool.value?.collection === true,
  })
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
    return
  }
  if (
    interactionTool.value === 'bbox'
    && activeInteractionTool.value?.collection
    && draftBboxXyxy.value
  ) {
    draftBboxesXyxy.value = [
      ...draftBboxesXyxy.value,
      draftBboxXyxy.value,
    ]
    draftBbox.value = null
    markInteractionDraftDirty()
    showInteractionFeedback(
      t('imageViewer.feedback.boxesAdded', { count: draftBboxesXyxy.value.length }),
      'success',
    )
    return
  }
  if (draftBboxXyxy.value) markInteractionDraftDirty()
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
    x: clampNumber(((event.clientX - imageBounds.left) / imageBounds.width) * sourceWidth, 0, Math.max(0, sourceWidth - 1)),
    y: clampNumber(((event.clientY - imageBounds.top) / imageBounds.height) * sourceHeight, 0, Math.max(0, sourceHeight - 1)),
  }
}

function toggleInteraction(): void {
  interactionActive.value = !interactionActive.value
  if (!interactionActive.value) stopActiveDraftListeners()
}

function selectInteractionTool(tool: string): void {
  if (!isSupportedInteractionTool(tool)) return
  selectedInteractionTool.value = tool
  clearTransientShapeDrafts()
  if (tool === 'mask') {
    const configuredBrushSize = activeInteractionTool.value?.brushSize
    if (typeof configuredBrushSize === 'number' && configuredBrushSize > 0) {
      maskBrushSize.value = Math.min(128, Math.max(1, configuredBrushSize))
    }
    void nextTick(initializeMaskCanvas)
  }
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
  draftBboxesXyxy.value = []
  draftPolygonsXy.value = []
  draftPointCollections.value = {}
  draftTemplateBboxXyxy.value = null
  draftSearchBboxXyxy.value = null
  templateRegionStage.value = 'template'
  stopActiveDraftListeners()
  if (interactionTool.value === 'mask') clearMaskDraft()
}

function handleClearInteraction(): void {
  if (hasInteractionDraft.value) {
    if (interactionTool.value === 'mask' && maskHasForeground.value) {
      clearMaskDraft(true)
      return
    }
    if (interactionTool.value === 'mask' && !maskHasForeground.value) {
      // 空 Mask 不能应用；再次清除时删除已保存的 ObjectStore 引用。
    } else {
      clearInteractionDraft()
      markInteractionDraftDirty()
      return
    }
  }
  const nodeId = props.image?.nodeId
  const interaction = imageInteraction.value
  const clearParameterNames = clearableGeometryParameters.value
  if (!nodeId || !interaction || clearParameterNames.length === 0) return
  emit('applyInteraction', {
    nodeId,
    tool: 'clear-geometry',
    coordinateSpace: interaction.coordinateSpace,
    targetParameters: clearParameterNames,
    clearParameterNames,
  })
  clearedGeometryLocally.value = true
  showInteractionFeedback(t('imageViewer.feedback.geometryCleared'), 'success')
}

function clearShapeDrafts(
  options: {
    keepPoints?: boolean
    keepPairLines?: boolean
    keepBboxCollection?: boolean
  } = {},
): void {
  draftBbox.value = null
  draftLine.value = null
  draftCircleCenter.value = null
  draftCircleEdge.value = null
  if (!options.keepPoints) draftPoints.value = []
  if (!options.keepPairLines) draftPairLines.value = []
  if (!options.keepBboxCollection) draftBboxesXyxy.value = []
}

function deleteLastDraftPoint(): void {
  if (draftPoints.value.length === 0) return
  draftPoints.value = draftPoints.value.slice(0, -1)
}

function finishDraftPolygon(): void {
  if (
    draftPointPairs.value.length < activePolygonMinPoints.value
    || draftPolygonSelfIntersects.value
  ) return
  draftPolygonsXy.value = [
    ...draftPolygonsXy.value,
    draftPointPairs.value.map(([pointX, pointY]) => [pointX, pointY]),
  ]
  draftPoints.value = []
  markInteractionDraftDirty()
  showInteractionFeedback(
    t('imageViewer.feedback.polygonsAdded', { count: draftPolygonsXy.value.length }),
    'success',
  )
}

function clearTransientShapeDrafts(): void {
  draftBbox.value = null
  draftLine.value = null
  draftCircleCenter.value = null
  draftCircleEdge.value = null
  draftPoints.value = []
  draftPairLines.value = []
  stopActiveDraftListeners()
}

function initializeCollectionDrafts(): void {
  const pointCollections: Record<string, Array<[number, number]>> = {}
  let initialBboxes: Array<[number, number, number, number]> = []
  let initialPolygons: Array<Array<[number, number]>> = []
  for (const tool of availableInteractionTools.value) {
    if (tool.tool === 'positive-point' || tool.tool === 'negative-point') {
      pointCollections[tool.tool] = (tool.initialPointsXy ?? []).map(
        ([pointX, pointY]) => [pointX, pointY],
      )
    }
    if (tool.tool === 'bbox' && tool.collection) {
      initialBboxes = (tool.initialBboxesXyxy ?? []).map(
        (bbox) => [...bbox] as [number, number, number, number],
      )
    }
    if (tool.tool === 'polygon' && tool.collection) {
      initialPolygons = (tool.initialPolygonsXy ?? []).map(
        (polygon) => polygon.map(([pointX, pointY]) => [pointX, pointY]),
      )
    }
  }
  draftPointCollections.value = pointCollections
  draftBboxesXyxy.value = initialBboxes
  draftPolygonsXy.value = initialPolygons
  const hasInitialGeometry = initialBboxes.length > 0
    || initialPolygons.length > 0
    || Object.values(pointCollections).some((points) => points.length > 0)
    || availableInteractionTools.value.some(
      (tool) => tool.tool === 'mask' && Boolean(tool.maskSrc),
    )
  interactionDraftState.value = hasInitialGeometry ? 'applied' : 'idle'
}

function stopActiveDraftListeners(): void {
  stopBboxDraft()
  stopLineDraft()
  stopCircleDraft()
}

function resetInteractionState(): void {
  maskInitializationGeneration += 1
  interactionActive.value = false
  selectedInteractionTool.value = ''
  clearInteractionDraft()
  maskHistory.value = []
  maskHistoryIndex.value = -1
  maskDrawing.value = false
  maskLastPoint.value = null
  interactionDraftState.value = 'idle'
}

function applyInteractionDraft(): void {
  if (props.interactionApplying) return
  const event = buildInteractionDraftEvent()
  if (!event) {
    showInteractionFeedback(t('imageViewer.feedback.incompleteApply'), 'warning')
    return
  }
  interactionDraftState.value = 'applying'
  event.onApplied = (success) => {
    interactionDraftState.value = success ? 'applied' : 'failed'
    showInteractionFeedback(
      success
        ? t('imageViewer.feedback.parametersApplied', {
            message: readAppliedFeedbackText(event),
          })
        : t('imageViewer.feedback.applyFailed'),
      success ? 'success' : 'warning',
    )
  }
  emit('applyInteraction', event)
}

function updateDraftBboxes(value: ImageBboxTuple[]): void {
  draftBboxesXyxy.value = value.map((bbox) => [...bbox] as ImageBboxTuple)
}

function updateDraftPolygons(value: ImagePointTuple[][]): void {
  draftPolygonsXy.value = value.map(
    (polygon) => polygon.map(([pointX, pointY]) => [pointX, pointY]),
  )
}

function updatePositiveDraftPoints(value: ImagePointTuple[]): void {
  draftPointCollections.value = {
    ...draftPointCollections.value,
    'positive-point': value.map(([pointX, pointY]) => [pointX, pointY]),
  }
}

function updateNegativeDraftPoints(value: ImagePointTuple[]): void {
  draftPointCollections.value = {
    ...draftPointCollections.value,
    'negative-point': value.map(([pointX, pointY]) => [pointX, pointY]),
  }
}

function markInteractionDraftDirty(): void {
  interactionDraftState.value = 'dirty'
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
    parameters: { ...(activeInteractionTool.value?.applyParameters ?? {}) },
  }
  if (
    interactionTool.value === 'bbox'
    && activeInteractionTool.value?.collection
    && (draftBboxesXyxy.value.length > 0 || draftBboxXyxy.value)
  ) {
    return {
      ...baseEvent,
      bboxesXyxy: [
        ...draftBboxesXyxy.value,
        ...(draftBboxXyxy.value ? [draftBboxXyxy.value] : []),
      ],
    }
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
  if (
    interactionTool.value === 'polygon'
    && activeInteractionTool.value?.collection
    && canApplyInteraction.value
  ) {
    const currentPolygon = (
      draftPointPairs.value.length >= activePolygonMinPoints.value
      && !draftPolygonSelfIntersects.value
    ) ? [draftPointPairs.value] : []
    return {
      ...baseEvent,
      polygonsXy: [...draftPolygonsXy.value, ...currentPolygon],
    }
  }
  if ((interactionTool.value === 'polygon' || interactionTool.value === 'contour') && canApplyInteraction.value) {
    return { ...baseEvent, pointsXy: draftPointPairs.value }
  }
  if (interactionTool.value === 'point' && canApplyInteraction.value) {
    return { ...baseEvent, pointsXy: draftPointPairs.value }
  }
  if (
    (interactionTool.value === 'positive-point' || interactionTool.value === 'negative-point')
    && canApplyInteraction.value
  ) {
    return {
      ...baseEvent,
      pointsXy: activeCollectionPointPairs.value,
      parameters: {
        ...baseEvent.parameters,
        positive_points_xy: positiveDraftPointPairs.value,
        negative_points_xy: negativeDraftPointPairs.value,
      },
    }
  }
  if (interactionTool.value === 'mask' && canApplyInteraction.value) {
    const dataUrl = maskCanvasRef.value?.toDataURL('image/png')
    const sourceIdentity = activeInteractionTool.value?.sourceIdentity?.trim()
    return dataUrl && sourceIdentity
      ? {
          ...baseEvent,
          maskDataUrl: dataUrl,
          maskSourceIdentity: sourceIdentity,
        }
      : null
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

async function initializeMaskCanvas(): Promise<void> {
  const generation = ++maskInitializationGeneration
  const canvas = maskCanvasRef.value
  if (!canvas) return
  const context = canvas.getContext('2d', { willReadFrequently: true })
  if (!context) return
  context.clearRect(0, 0, canvas.width, canvas.height)
  const maskSrc = activeInteractionTool.value?.maskSrc
  if (maskSrc) {
    const storedMask = await loadViewerImage(maskSrc)
    if (
      storedMask
      && maskCanvasRef.value === canvas
      && maskInitializationGeneration === generation
    ) {
      const scratchCanvas = document.createElement('canvas')
      scratchCanvas.width = canvas.width
      scratchCanvas.height = canvas.height
      const scratchContext = scratchCanvas.getContext('2d', { willReadFrequently: true })
      if (scratchContext) {
        scratchContext.drawImage(storedMask, 0, 0, canvas.width, canvas.height)
        const storedPixels = scratchContext.getImageData(0, 0, canvas.width, canvas.height)
        const outputPixels = context.createImageData(canvas.width, canvas.height)
        for (let index = 0; index < storedPixels.data.length; index += 4) {
          const foreground = Math.max(
            storedPixels.data[index],
            storedPixels.data[index + 1],
            storedPixels.data[index + 2],
          )
          if (foreground <= 0) continue
          outputPixels.data[index] = 0
          outputPixels.data[index + 1] = 190
          outputPixels.data[index + 2] = 170
          outputPixels.data[index + 3] = 184
        }
        context.putImageData(outputPixels, 0, 0)
      }
    }
  }
  if (
    maskCanvasRef.value !== canvas
    || maskInitializationGeneration !== generation
  ) return
  maskHistory.value = [context.getImageData(0, 0, canvas.width, canvas.height)]
  maskHistoryIndex.value = 0
  maskDirty.value = false
  updateMaskForegroundState()
}

function loadViewerImage(src: string): Promise<HTMLImageElement | null> {
  return new Promise((resolve) => {
    const image = new Image()
    image.onload = () => resolve(image)
    image.onerror = () => resolve(null)
    image.src = src
  })
}

function startMaskStroke(event: MouseEvent): void {
  if (!interactionActive.value) return
  maskDrawing.value = true
  maskLastPoint.value = readMaskCanvasPoint(event)
  drawMaskStroke(maskLastPoint.value, maskLastPoint.value)
}

function continueMaskStroke(event: MouseEvent): void {
  if (!maskDrawing.value) return
  const nextPoint = readMaskCanvasPoint(event)
  drawMaskStroke(maskLastPoint.value, nextPoint)
  maskLastPoint.value = nextPoint
}

function finishMaskStroke(): void {
  if (!maskDrawing.value) return
  maskDrawing.value = false
  maskLastPoint.value = null
  if (maskDrawMode.value === 'eraser') updateMaskForegroundState()
  commitMaskHistory()
}

function drawMaskStroke(start: ImagePoint | null, end: ImagePoint | null): void {
  const canvas = maskCanvasRef.value
  if (!canvas || !start || !end) return
  const context = canvas.getContext('2d', { willReadFrequently: true })
  if (!context) return
  context.save()
  context.lineCap = 'round'
  context.lineJoin = 'round'
  context.lineWidth = maskBrushSize.value
  context.globalCompositeOperation = maskDrawMode.value === 'eraser' ? 'destination-out' : 'source-over'
  context.strokeStyle = 'rgba(0, 190, 170, 0.72)'
  context.beginPath()
  context.moveTo(start.x, start.y)
  context.lineTo(end.x, end.y)
  context.stroke()
  context.restore()
  maskDirty.value = true
  markInteractionDraftDirty()
  if (maskDrawMode.value === 'brush') maskHasForeground.value = true
}

function readMaskCanvasPoint(event: MouseEvent): ImagePoint | null {
  const canvas = maskCanvasRef.value
  if (!canvas) return null
  const bounds = canvas.getBoundingClientRect()
  if (bounds.width <= 0 || bounds.height <= 0) return null
  return {
    x: clampNumber(((event.clientX - bounds.left) / bounds.width) * canvas.width, 0, canvas.width),
    y: clampNumber(((event.clientY - bounds.top) / bounds.height) * canvas.height, 0, canvas.height),
  }
}

function commitMaskHistory(): void {
  const canvas = maskCanvasRef.value
  const context = canvas?.getContext('2d', { willReadFrequently: true })
  if (!canvas || !context) return
  const nextHistory = maskHistory.value.slice(0, maskHistoryIndex.value + 1)
  nextHistory.push(context.getImageData(0, 0, canvas.width, canvas.height))
  maskHistory.value = nextHistory.slice(-12)
  maskHistoryIndex.value = maskHistory.value.length - 1
}

function restoreMaskHistory(index: number): void {
  const canvas = maskCanvasRef.value
  const context = canvas?.getContext('2d', { willReadFrequently: true })
  const snapshot = maskHistory.value[index]
  if (!canvas || !context || !snapshot) return
  context.putImageData(snapshot, 0, 0)
  maskHistoryIndex.value = index
  maskDirty.value = index > 0
  updateMaskForegroundState()
}

function undoMaskEdit(): void {
  if (maskHistoryIndex.value > 0) restoreMaskHistory(maskHistoryIndex.value - 1)
}

function redoMaskEdit(): void {
  if (maskHistoryIndex.value < maskHistory.value.length - 1) restoreMaskHistory(maskHistoryIndex.value + 1)
}

function fillMaskDraft(): void {
  const canvas = maskCanvasRef.value
  const context = canvas?.getContext('2d', { willReadFrequently: true })
  if (!canvas || !context) return
  context.clearRect(0, 0, canvas.width, canvas.height)
  context.fillStyle = 'rgba(0, 190, 170, 0.72)'
  context.fillRect(0, 0, canvas.width, canvas.height)
  maskDirty.value = true
  maskHasForeground.value = true
  markInteractionDraftDirty()
  commitMaskHistory()
}

function clearMaskDraft(commitHistory = false): void {
  const canvas = maskCanvasRef.value
  const context = canvas?.getContext('2d', { willReadFrequently: true })
  if (!canvas || !context) return
  context.clearRect(0, 0, canvas.width, canvas.height)
  maskDirty.value = commitHistory
  maskHasForeground.value = false
  if (commitHistory) {
    markInteractionDraftDirty()
    commitMaskHistory()
  }
}

function updateMaskForegroundState(): void {
  const canvas = maskCanvasRef.value
  const context = canvas?.getContext('2d', { willReadFrequently: true })
  if (!canvas || !context) return
  const alpha = context.getImageData(0, 0, canvas.width, canvas.height).data
  maskHasForeground.value = alpha.some((value, index) => index % 4 === 3 && value > 0)
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
  if (requestPreview) {
    scheduleTuningPreview(event)
  } else {
    emit('applyInteraction', event)
  }
  showInteractionFeedback(requestPreview ? t('imageViewer.feedback.tuningAppliedPreview') : t('imageViewer.feedback.tuningApplied'), 'success')
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
  if (event) {
    interactionDraftState.value = 'applying'
    event.onApplied = (success) => {
      interactionDraftState.value = success ? 'applied' : 'failed'
    }
  }
  const action = dispatchImageViewerPreview(
    hasInteractionDraft.value,
    event,
    {
      previewInteraction: (interactionEvent) => emit('previewInteraction', interactionEvent),
      runPreview: () => emit('runPreview'),
    },
  )
  if (action === 'invalid') {
    showInteractionFeedback(t('imageViewer.feedback.incompletePreview'), 'warning')
    return
  }
  if (action === 'interaction' && event) {
    showInteractionFeedback(t('imageViewer.feedback.appliedStartingPreview', { message: readAppliedFeedbackText(event) }), 'success')
  } else {
    showInteractionFeedback(t('imageViewer.feedback.startingPreview'), 'info')
  }
}

function readAppliedFeedbackText(event: ViewerImageInteractionApplyEvent): string {
  if (event.tool === 'positive-point' || event.tool === 'negative-point') return t('imageViewer.applied.point')
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

function readAvailableInteractionTools(interaction: ViewerImageInteraction | null): ViewerImageInteractionTool[] {
  if (!interaction) return []
  return interaction.tools.flatMap((toolItem) => (
    normalizeImageInteractionTool(toolItem, {
      isSupported: isSupportedInteractionTool,
      fallbackLabel: readInteractionToolLabel,
    })
  ))
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

function polygonHasSelfIntersection(points: Array<[number, number]>): boolean {
  if (points.length < 4) return false
  for (let firstIndex = 0; firstIndex < points.length; firstIndex += 1) {
    const firstStart = points[firstIndex]
    const firstEnd = points[(firstIndex + 1) % points.length]
    if (!firstStart || !firstEnd) continue
    for (let secondIndex = firstIndex + 1; secondIndex < points.length; secondIndex += 1) {
      if (
        secondIndex === firstIndex
        || secondIndex === (firstIndex + 1) % points.length
        || secondIndex === (firstIndex - 1 + points.length) % points.length
        || (firstIndex === 0 && secondIndex === points.length - 1)
      ) continue
      const secondStart = points[secondIndex]
      const secondEnd = points[(secondIndex + 1) % points.length]
      if (
        secondStart
        && secondEnd
        && lineSegmentsStrictlyIntersect(firstStart, firstEnd, secondStart, secondEnd)
      ) return true
    }
  }
  return false
}

function lineSegmentsStrictlyIntersect(
  firstStart: [number, number],
  firstEnd: [number, number],
  secondStart: [number, number],
  secondEnd: [number, number],
): boolean {
  const orientation = (
    pointA: [number, number],
    pointB: [number, number],
    pointC: [number, number],
  ): number => (
    (pointB[0] - pointA[0]) * (pointC[1] - pointA[1])
    - (pointB[1] - pointA[1]) * (pointC[0] - pointA[0])
  )
  const epsilon = 1e-9
  return orientation(firstStart, firstEnd, secondStart)
    * orientation(firstStart, firstEnd, secondEnd) < -epsilon
    && orientation(secondStart, secondEnd, firstStart)
    * orientation(secondStart, secondEnd, firstEnd) < -epsilon
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
  stopActiveDraftListeners()
  if (tuningPreviewTimer !== null) window.clearTimeout(tuningPreviewTimer)
  if (interactionFeedbackTimer !== null) window.clearTimeout(interactionFeedbackTimer)
  if (fitImageAnimationFrame !== null) window.cancelAnimationFrame(fitImageAnimationFrame)
})
</script>
