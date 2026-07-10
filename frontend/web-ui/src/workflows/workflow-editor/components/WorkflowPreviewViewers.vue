<template>
  <ImageViewer
    :open="Boolean(image)"
    :image="image"
    :preview-running="previewRunning"
    :preview-disabled="previewDisabled"
    @close="emit('closeImage')"
    @apply-interaction="emit('applyImageInteraction', $event)"
    @preview-interaction="emit('previewImageInteraction', $event)"
    @run-preview="emit('runImagePreview')"
  />
  <WorkflowPreviewTableViewer :open="Boolean(table)" :table="table" @close="emit('closeTable')" />
  <WorkflowPreviewJsonViewer :open="Boolean(json)" :viewer="json" @close="emit('closeJson')" />
</template>

<script setup lang="ts">
import ImageViewer from '@/shared/ui/components/ImageViewer.vue'

import WorkflowPreviewJsonViewer from './WorkflowPreviewJsonViewer.vue'
import WorkflowPreviewTableViewer from './WorkflowPreviewTableViewer.vue'
import type { PreviewImageInteractionApplyEvent, PreviewJsonViewerState, PreviewTableViewerState, PreviewViewerImage } from '../preview/useWorkflowPreviewDisplays'

defineProps<{
  image: PreviewViewerImage | null
  table: PreviewTableViewerState | null
  json: PreviewJsonViewerState | null
  previewRunning?: boolean
  previewDisabled?: boolean
}>()

const emit = defineEmits<{
  closeImage: []
  closeTable: []
  closeJson: []
  applyImageInteraction: [event: PreviewImageInteractionApplyEvent]
  previewImageInteraction: [event: PreviewImageInteractionApplyEvent]
  runImagePreview: []
}>()
</script>
