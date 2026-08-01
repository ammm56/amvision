<template>
  <div class="workflow-graph-navigation-dock">
    <WorkflowGraphMinimap
      :visible="minimapVisible"
      :nodes="minimapNodes"
      :viewport-style="minimapViewportStyle"
      :is-node-selected="isMinimapNodeSelected"
      @start-navigation="emit('startMinimapNavigation', $event)"
      @toggle="emit('toggleMinimap')"
    />

    <WorkflowGraphViewportControls
      :scale-percent="viewportScalePercent"
      :minimap-visible="minimapVisible"
      @zoom-out="emit('zoomOut')"
      @reset-view="emit('resetView')"
      @zoom-in="emit('zoomIn')"
      @fit-view="emit('fitView')"
      @toggle-minimap="emit('toggleMinimap')"
    />
  </div>

  <WorkflowGraphContextMenu
    v-if="contextMenu"
    :context-menu="contextMenu"
    :menu-style="contextMenuStyle"
    :minimap-visible="minimapVisible"
    :save-disabled="saveDisabled"
    :preview-disabled="previewDisabled"
    :add-node-label="t('workflowEditor.nodePicker.addNode')"
    :save-label="t('workflowEditor.actions.saveWorkflowApp')"
    :preview-label="t('workflowEditor.actions.previewRun')"
    :preview-node-label="t('workflowEditor.actions.previewNodeRun')"
    @open-node-picker="emit('openNodePicker')"
    @expose-app-input="emit('exposeAppInput')"
    @expose-app-output="emit('exposeAppOutput')"
    @delete-binding="emit('deleteBinding')"
    @delete-node="emit('deleteNode')"
    @delete-edge="emit('deleteEdge')"
    @reset-boundary-position="emit('resetBoundaryPosition')"
    @fit-view="emit('fitView')"
    @reset-view="emit('resetView')"
    @toggle-minimap="emit('toggleMinimap')"
    @save="emit('save')"
    @preview="emit('preview')"
    @preview-node="emit('previewNode')"
  />

  <WorkflowNodePicker
    v-if="nodePicker"
    :open="Boolean(nodePicker)"
    :x="nodePicker.x"
    :y="nodePicker.y"
    :definitions="nodePickerDefinitions"
    :mode="nodePicker.mode"
    :title="nodePickerTitle"
    :required-port-direction="nodePickerRequiredPortDirection"
    :required-payload-type-id="nodePickerRequiredPayloadTypeId"
    @select="emit('selectNodeFromPicker', $event)"
    @close="emit('closeNodePicker')"
  />

  <WorkflowCanvasEmptyState :loading="loading" :node-count="nodeCount" :is-new-app="isNewApp" />
</template>

<script setup lang="ts">
import { useI18n } from 'vue-i18n'

import WorkflowCanvasEmptyState from './WorkflowCanvasEmptyState.vue'
import WorkflowGraphContextMenu from './WorkflowGraphContextMenu.vue'
import WorkflowGraphMinimap from './WorkflowGraphMinimap.vue'
import WorkflowGraphViewportControls from './WorkflowGraphViewportControls.vue'
import WorkflowNodePicker from './WorkflowNodePicker.vue'
import type { WorkflowNodePickerState } from '../nodes/useWorkflowNodePicker'
import type { WorkflowContextMenuState } from '../context/useWorkflowContextMenu'
import type { NodeDefinition } from '../types'

interface WorkflowMinimapNode {
  nodeId: string
  style: Record<string, string>
}

defineProps<{
  minimapVisible: boolean
  viewportScalePercent: number
  minimapNodes: WorkflowMinimapNode[]
  minimapViewportStyle: Record<string, string>
  isMinimapNodeSelected: (nodeId: string) => boolean
  contextMenu: WorkflowContextMenuState | null
  contextMenuStyle: Record<string, string>
  saveDisabled: boolean
  previewDisabled: boolean
  nodePicker: WorkflowNodePickerState | null
  nodePickerDefinitions: NodeDefinition[]
  nodePickerTitle: string
  nodePickerRequiredPortDirection: 'input' | 'output' | null
  nodePickerRequiredPayloadTypeId: string | null
  loading: boolean
  nodeCount: number
  isNewApp: boolean
}>()

const emit = defineEmits<{
  startMinimapNavigation: [event: MouseEvent]
  toggleMinimap: []
  openNodePicker: []
  exposeAppInput: []
  exposeAppOutput: []
  deleteBinding: []
  deleteNode: []
  deleteEdge: []
  resetBoundaryPosition: []
  fitView: []
  zoomIn: []
  zoomOut: []
  resetView: []
  save: []
  preview: []
  previewNode: []
  selectNodeFromPicker: [definition: NodeDefinition]
  closeNodePicker: []
}>()

const { t } = useI18n()
</script>
