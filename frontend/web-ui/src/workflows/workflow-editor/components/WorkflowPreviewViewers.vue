<template>
  <ImageViewer :open="Boolean(image)" :image="image" @close="emit('closeImage')" />
  <WorkflowPreviewTableViewer :open="Boolean(table)" :table="table" @close="emit('closeTable')" />
  <WorkflowPreviewJsonViewer :open="Boolean(json)" :viewer="json" @close="emit('closeJson')" />
</template>

<script setup lang="ts">
import ImageViewer from '@/shared/ui/components/ImageViewer.vue'

import WorkflowPreviewJsonViewer from './WorkflowPreviewJsonViewer.vue'
import WorkflowPreviewTableViewer from './WorkflowPreviewTableViewer.vue'
import type { PreviewJsonViewerState, PreviewTableViewerState, PreviewViewerImage } from '../preview/useWorkflowPreviewDisplays'

defineProps<{
  image: PreviewViewerImage | null
  table: PreviewTableViewerState | null
  json: PreviewJsonViewerState | null
}>()

const emit = defineEmits<{
  closeImage: []
  closeTable: []
  closeJson: []
}>()
</script>
