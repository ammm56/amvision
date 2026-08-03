<template>
  <div class="workflow-graph-context-menu" :style="menuStyle" @mousedown.stop @contextmenu.prevent>
    <button
      type="button"
      class="workflow-graph-context-menu__submenu-trigger"
      @click="emit('open-node-picker')"
    >
      <Plus :size="15" />
      {{ addNodeLabel }}
      <ChevronRight :size="14" />
    </button>
    <button v-if="contextMenu.port?.direction === 'input'" type="button" @click="emit('expose-app-input')">
      <Plus :size="15" />
      {{ t('workflowEditor.editor.exposeAppInput') }}
    </button>
    <button v-if="contextMenu.port?.direction === 'output'" type="button" @click="emit('expose-app-output')">
      <Plus :size="15" />
      {{ t('workflowEditor.editor.exposeAppOutput') }}
    </button>
    <button v-if="contextMenu.bindingId" type="button" @click="emit('delete-binding')">
      <Trash2 :size="15" />
      {{ t('workflowEditor.editor.deletePublicBinding') }}
    </button>
    <button v-if="contextMenu.nodeId" type="button" @click="emit('delete-node')">
      <Trash2 :size="15" />
      {{ t('workflowEditor.editor.deleteNode') }}
    </button>
    <button v-if="contextMenu.edgeId" type="button" @click="emit('delete-edge')">
      <Trash2 :size="15" />
      {{ t('workflowEditor.editor.deleteEdge') }}
    </button>
    <button v-if="contextMenu.boundaryKind" type="button" @click="emit('reset-boundary-position')">
      <RefreshCw :size="15" />
      {{ t('workflowEditor.editor.resetBoundaryPosition') }}
    </button>
    <button type="button" @click="emit('fit-view')">
      <MapIcon :size="15" />
      {{ t('workflowEditor.editor.fitView') }}
    </button>
    <button type="button" @click="emit('reset-view')">
      <RefreshCw :size="15" />
      {{ t('workflowEditor.editor.resetView') }}
    </button>
    <button type="button" @click="emit('toggle-minimap')">
      <MapIcon :size="15" />
      {{ minimapVisible ? t('workflowEditor.editor.hideMinimap') : t('workflowEditor.editor.showMinimap') }}
    </button>
    <button type="button" :disabled="saveDisabled" @click="emit('save')">
      <Save :size="15" />
      {{ saveLabel }}
    </button>
    <button
      v-if="!contextMenu.nodeId"
      type="button"
      :disabled="previewDisabled"
      @click="emit('preview')"
    >
      <Play :size="15" />
      {{ previewLabel }}
    </button>
    <button
      v-if="contextMenu.nodeId"
      type="button"
      :disabled="previewDisabled"
      @click="emit('preview-node')"
    >
      <Play :size="15" />
      {{ previewNodeLabel }}
    </button>
  </div>
</template>

<script setup lang="ts">
import { ChevronRight, Map as MapIcon, Play, Plus, RefreshCw, Save, Trash2 } from '@lucide/vue'
import { useI18n } from 'vue-i18n'

type AppBoundaryKind = 'entry' | 'result'
type PortDirection = 'input' | 'output'

interface PortReference {
  nodeId: string
  portName: string
  direction: PortDirection
}

interface WorkflowGraphContextMenuState {
  x: number
  y: number
  worldX: number
  worldY: number
  nodeId: string | null
  edgeId: string | null
  port: PortReference | null
  boundaryKind?: AppBoundaryKind | null
  bindingId?: string | null
}

defineProps<{
  contextMenu: WorkflowGraphContextMenuState
  menuStyle: Record<string, string>
  minimapVisible: boolean
  saveDisabled: boolean
  previewDisabled: boolean
  addNodeLabel: string
  saveLabel: string
  previewLabel: string
  previewNodeLabel: string
}>()

const emit = defineEmits<{
  'open-node-picker': []
  'expose-app-input': []
  'expose-app-output': []
  'delete-binding': []
  'delete-node': []
  'delete-edge': []
  'reset-boundary-position': []
  'fit-view': []
  'reset-view': []
  'toggle-minimap': []
  save: []
  preview: []
  'preview-node': []
}>()

const { t } = useI18n()
</script>
