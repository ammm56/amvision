<template>
  <div class="workflow-graph-context-menu" :style="menuStyle" @mousedown.stop @contextmenu.prevent>
    <button type="button" class="workflow-graph-context-menu__submenu-trigger" @mouseenter="emit('open-node-picker')" @click="emit('open-node-picker')">
      <Plus :size="15" />
      {{ addNodeLabel }}
      <ChevronRight :size="14" />
    </button>
    <button v-if="contextMenu.port?.direction === 'input'" type="button" @click="emit('expose-app-input')">
      <Plus :size="15" />
      公开为应用输入
    </button>
    <button v-if="contextMenu.port?.direction === 'output'" type="button" @click="emit('expose-app-output')">
      <Plus :size="15" />
      公开为应用输出
    </button>
    <button v-if="contextMenu.bindingId" type="button" @click="emit('delete-binding')">
      <Trash2 :size="15" />
      删除公开接口
    </button>
    <button v-if="contextMenu.nodeId" type="button" @click="emit('delete-node')">
      <Trash2 :size="15" />
      删除节点
    </button>
    <button v-if="contextMenu.edgeId" type="button" @click="emit('delete-edge')">
      <Trash2 :size="15" />
      删除连线
    </button>
    <button v-if="contextMenu.boundaryKind" type="button" @click="emit('reset-boundary-position')">
      <RefreshCw :size="15" />
      重置边界位置
    </button>
    <button type="button" @click="emit('fit-view')">
      <MapIcon :size="15" />
      定位全部节点
    </button>
    <button type="button" @click="emit('reset-view')">
      <RefreshCw :size="15" />
      重置画布位置
    </button>
    <button type="button" @click="emit('toggle-minimap')">
      <MapIcon :size="15" />
      {{ minimapVisible ? '隐藏小地图' : '显示小地图' }}
    </button>
    <button type="button" @click="emit('toggle-theme')">
      <Sun v-if="graphTheme === 'dark'" :size="15" />
      <Moon v-else :size="15" />
      {{ graphTheme === 'dark' ? lightLabel : darkLabel }}
    </button>
    <button type="button" :disabled="saveDisabled" @click="emit('save')">
      <Save :size="15" />
      {{ saveLabel }}
    </button>
    <button type="button" :disabled="previewDisabled" @click="emit('preview')">
      <Play :size="15" />
      {{ previewLabel }}
    </button>
  </div>
</template>

<script setup lang="ts">
import { ChevronRight, Map as MapIcon, Moon, Play, Plus, RefreshCw, Save, Sun, Trash2 } from '@lucide/vue'

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
  graphTheme: string
  saveDisabled: boolean
  previewDisabled: boolean
  addNodeLabel: string
  lightLabel: string
  darkLabel: string
  saveLabel: string
  previewLabel: string
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
  'toggle-theme': []
  save: []
  preview: []
}>()
</script>
