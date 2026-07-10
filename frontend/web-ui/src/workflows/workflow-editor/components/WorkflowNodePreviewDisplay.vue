<template>
  <div
    class="workflow-graph-node-preview"
    :title="tooltip"
    @mousedown.stop
    @dblclick.stop="emit('open-display', display)"
  >
    <div
      v-if="display.kind === 'image' && display.image?.src"
      class="workflow-graph-node-preview__image-frame"
    >
      <img
        :src="display.image.src"
        :alt="display.image.title || fallbackTitle"
        draggable="false"
      />
      <svg
        v-if="readOverlayViewBox(display.image) && display.image.overlays.length > 0"
        class="workflow-graph-node-preview__overlay"
        :viewBox="readOverlayViewBox(display.image)"
        preserveAspectRatio="xMidYMid meet"
        aria-hidden="true"
      >
        <template v-for="(overlay, index) in display.image.overlays" :key="overlayKey(overlay, index)">
          <polygon
            v-if="overlay.pointsXy.length >= 2"
            class="workflow-graph-node-preview__overlay-shape workflow-graph-node-preview__overlay-shape--polygon"
            :points="overlayPoints(overlay)"
          />
          <rect
            v-else-if="overlay.bboxXyxy"
            class="workflow-graph-node-preview__overlay-shape workflow-graph-node-preview__overlay-shape--bbox"
            :x="overlay.bboxXyxy[0]"
            :y="overlay.bboxXyxy[1]"
            :width="bboxWidth(overlay)"
            :height="bboxHeight(overlay)"
          />
          <line
            v-else-if="overlay.lineXyxy"
            class="workflow-graph-node-preview__overlay-shape workflow-graph-node-preview__overlay-shape--line"
            :x1="overlay.lineXyxy[0]"
            :y1="overlay.lineXyxy[1]"
            :x2="overlay.lineXyxy[2]"
            :y2="overlay.lineXyxy[3]"
          />
          <circle
            v-else-if="overlay.circle"
            class="workflow-graph-node-preview__overlay-shape workflow-graph-node-preview__overlay-shape--circle"
            :cx="overlay.circle.centerX"
            :cy="overlay.circle.centerY"
            :r="overlay.circle.radius"
          />
        </template>
      </svg>
    </div>
    <div v-else-if="display.kind === 'gallery'" class="workflow-graph-node-preview__gallery">
      <button
        v-for="item in display.galleryItems"
        :key="`${item.nodeId}-${item.objectKey || item.caption}`"
        type="button"
        class="workflow-graph-node-preview__gallery-item"
        @mousedown.stop
        @click.stop="emit('open-image', item)"
      >
        <img v-if="item.src" :src="item.src" :alt="item.caption" draggable="false" />
        <span v-else class="workflow-graph-node-preview__empty">{{ item.statusText }}</span>
      </button>
    </div>
    <WorkflowPreviewTable
      v-else-if="display.kind === 'table'"
      :columns="display.columns"
      :rows="display.rows"
      :empty-text="display.emptyText"
      :max-rows="4"
      compact
    />
    <pre
      v-else-if="display.kind === 'value'"
      class="json-view workflow-graph-node-preview__json"
    >{{ display.formattedValue }}</pre>
    <div v-else class="workflow-graph-node-preview__empty">{{ display.statusText }}</div>
  </div>
</template>

<script setup lang="ts">
import WorkflowPreviewTable from './WorkflowPreviewTable.vue'
import type { PreviewImageOverlay, PreviewNodeDisplay, PreviewViewerImage } from '../preview/useWorkflowPreviewDisplays'

defineProps<{
  display: PreviewNodeDisplay
  tooltip: string
  fallbackTitle: string
}>()

const emit = defineEmits<{
  'open-display': [display: PreviewNodeDisplay]
  'open-image': [image: PreviewViewerImage]
}>()

function readOverlayViewBox(image: PreviewViewerImage | null): string {
  const width = image?.width ?? 0
  const height = image?.height ?? 0
  return width > 0 && height > 0 ? `0 0 ${width} ${height}` : ''
}

function overlayKey(overlay: PreviewImageOverlay, index: number): string {
  return `${overlay.kind}:${overlay.id ?? index}`
}

function overlayPoints(overlay: PreviewImageOverlay): string {
  return overlay.pointsXy.map(([pointX, pointY]) => `${pointX},${pointY}`).join(' ')
}

function bboxWidth(overlay: PreviewImageOverlay): number {
  return overlay.bboxXyxy ? Math.max(0, overlay.bboxXyxy[2] - overlay.bboxXyxy[0]) : 0
}

function bboxHeight(overlay: PreviewImageOverlay): number {
  return overlay.bboxXyxy ? Math.max(0, overlay.bboxXyxy[3] - overlay.bboxXyxy[1]) : 0
}
</script>
