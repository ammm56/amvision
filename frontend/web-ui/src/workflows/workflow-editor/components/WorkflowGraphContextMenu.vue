<template>
  <div ref="menuElement" class="workflow-graph-context-menu" :style="boundedMenuStyle" @mousedown.stop @contextmenu.prevent.stop>
    <button v-if="contextMenu.noteId" type="button" @click="emit('edit-note')">
      <SquarePen :size="15" />
      {{ t('workflowEditor.editor.editNote') }}
    </button>
    <button v-if="contextMenu.noteId" type="button" @click="emit('copy-note')">
      <Copy :size="15" />
      {{ t('workflowEditor.editor.copyNote') }}
    </button>
    <button v-if="contextMenu.noteId" type="button" @click="emit('toggle-note-lock')">
      <LockKeyhole :size="15" />
      {{ t('workflowEditor.editor.toggleNoteLock') }}
    </button>
    <button v-if="contextMenu.noteId" type="button" @click="emit('toggle-note-collapse')">
      <PanelTopClose :size="15" />
      {{ t('workflowEditor.editor.toggleNoteCollapse') }}
    </button>
    <button v-if="contextMenu.noteId" type="button" @click="emit('delete-note')">
      <Trash2 :size="15" />
      {{ t('workflowEditor.editor.deleteNote') }}
    </button>
    <button
      v-if="!contextMenu.noteId"
      type="button"
      class="workflow-graph-context-menu__submenu-trigger"
      @click="emit('open-node-picker')"
    >
      <Plus :size="15" />
      {{ addNodeLabel }}
      <ChevronRight :size="14" />
    </button>
    <button v-if="contextMenu.nodeId && !contextMenu.port" type="button" :disabled="documentDisabled" @click="emit('copy-node')"><Copy :size="15" />{{ t('workflowEditor.editor.copyNode') }}<kbd>Ctrl+C</kbd></button>
    <button v-if="isBlankCanvas" type="button" @click="emit('add-note')"><NotebookPen :size="15" />{{ t('workflowEditor.editor.addNote') }}</button>
    <button v-if="isBlankCanvas" type="button" :disabled="previewDisabled" @click="emit('preview')"><Play :size="15" />{{ previewLabel }}</button>
    <button v-if="isBlankCanvas" type="button" :disabled="documentDisabled || !canPasteNode" @click="emit('paste-node')"><ClipboardPaste :size="15" />{{ t('workflowEditor.editor.pasteNode') }}<kbd>Ctrl+V</kbd></button>
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
    <button type="button" :disabled="saveDisabled" @click="emit('save')">
      <Save :size="15" />
      {{ saveLabel }}
    </button>
    <button
      v-if="!contextMenu.nodeId && !isBlankCanvas"
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
    <template v-if="isBlankCanvas">
      <hr class="workflow-graph-context-menu__separator" />
      <button type="button" :disabled="documentDisabled" @click="emit('export-document')"><Download :size="15" />{{ t('workflowEditor.document.export') }}</button>
      <button type="button" :disabled="documentDisabled" @click="emit('import-document')"><Upload :size="15" />{{ t('workflowEditor.document.import') }}</button>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ChevronRight, ClipboardPaste, Copy, Download, Upload, LockKeyhole, Map as MapIcon, NotebookPen, PanelTopClose, Play, Plus, RefreshCw, Save, SquarePen, Trash2 } from '@lucide/vue'
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
  noteId?: string | null
  port: PortReference | null
  boundaryKind?: AppBoundaryKind | null
  bindingId?: string | null
}

const props = defineProps<{
  contextMenu: WorkflowGraphContextMenuState
  menuStyle: Record<string, string>
  minimapVisible: boolean
  saveDisabled: boolean
  previewDisabled: boolean
  documentDisabled?: boolean
  canPasteNode?: boolean
  addNodeLabel: string
  saveLabel: string
  previewLabel: string
  previewNodeLabel: string
}>()

const emit = defineEmits<{
  'copy-node': []
  'paste-node': []
  'export-document': []
  'import-document': []
  'open-node-picker': []
  'add-note': []
  'edit-note': []
  'copy-note': []
  'toggle-note-lock': []
  'toggle-note-collapse': []
  'delete-note': []
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
const isBlankCanvas = computed(() => {
  const menu = props.contextMenu
  return !menu.nodeId && !menu.edgeId && !menu.noteId && !menu.port && !menu.boundaryKind && !menu.bindingId
})
const menuElement = ref<HTMLElement | null>(null)
const boundedMenuStyle = ref<Record<string, string>>({ ...props.menuStyle })
function positionMenu(): void {
  const bounds = menuElement.value?.getBoundingClientRect()
  if (!bounds) return
  boundedMenuStyle.value = {
    ...props.menuStyle,
    left: `${Math.max(8, Math.min(props.contextMenu.x, window.innerWidth - bounds.width - 8))}px`,
    top: `${Math.max(8, Math.min(props.contextMenu.y, window.innerHeight - bounds.height - 8))}px`,
  }
}
watch(() => props.contextMenu, async () => { await nextTick(); positionMenu() }, { deep: true })
onMounted(() => { positionMenu(); window.addEventListener('resize', positionMenu) })
onBeforeUnmount(() => window.removeEventListener('resize', positionMenu))
</script>
<style scoped>
.workflow-graph-context-menu { max-height: calc(100vh - 16px); overflow-y: auto; }
.workflow-graph-context-menu__separator { width: 100%; margin: 5px 0; border: 0; border-top: 1px solid var(--graph-line); }
.workflow-graph-context-menu kbd { margin-left: auto; padding-left: 16px; font: inherit; font-size: 11px; color: var(--graph-muted); }
</style>
