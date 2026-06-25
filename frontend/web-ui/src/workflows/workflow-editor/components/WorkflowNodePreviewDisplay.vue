<template>
  <div
    class="workflow-graph-node-preview"
    :title="tooltip"
    @mousedown.stop
    @dblclick.stop="emit('open-display', display)"
  >
    <img
      v-if="display.kind === 'image' && display.image?.src"
      :src="display.image.src"
      :alt="display.image.title || fallbackTitle"
      draggable="false"
    />
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

type WorkflowJsonObject = Record<string, unknown>

interface PreviewViewerImage {
  nodeId: string
  title: string
  src: string | null
  statusText: string
  transportKind: string
  mediaType: string
  width: number | null
  height: number | null
  objectKey: string | null
}

interface PreviewGalleryItemView extends PreviewViewerImage {
  caption: string
  cropIndex: number | null
}

interface PreviewTableColumnView {
  key: string
  label: string
}

interface PreviewNodeDisplay {
  nodeId: string
  nodeTypeId: string
  outputName: string
  title: string
  kind: 'image' | 'table' | 'gallery' | 'value'
  payload: WorkflowJsonObject
  statusText: string
  formattedValue: string
  image: PreviewViewerImage | null
  galleryItems: PreviewGalleryItemView[]
  columns: PreviewTableColumnView[]
  rows: WorkflowJsonObject[]
  rowCount: number | null
  emptyText: string | null
}

defineProps<{
  display: PreviewNodeDisplay
  tooltip: string
  fallbackTitle: string
}>()

const emit = defineEmits<{
  'open-display': [display: PreviewNodeDisplay]
  'open-image': [image: PreviewViewerImage]
}>()
</script>
