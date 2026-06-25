import { computed, ref, type Ref } from 'vue'

import type { WorkflowConnectionDraftState } from '../canvas/useWorkflowPortConnections'
import type { NodeDefinition } from '../types'

export interface WorkflowNodePickerNodeView {
  node: {
    node_id: string
  }
}

export interface WorkflowNodePickerContextMenu {
  x: number
  y: number
  worldX: number
  worldY: number
}

export interface WorkflowNodePickerSelection {
  nodeId: string | null
  edgeId: string | null
  boundaryKind: 'entry' | 'result' | null
}

export interface WorkflowNodePickerState {
  x: number
  y: number
  worldX: number
  worldY: number
  mode: 'context-menu' | 'link-drop'
  connectionDraft: WorkflowConnectionDraftState | null
}

export interface WorkflowNodePickerOptions<NodeView extends WorkflowNodePickerNodeView, ContextMenu extends WorkflowNodePickerContextMenu> {
  graphNodes: Ref<NodeView[]>
  contextMenu: Ref<ContextMenu | null>
  createNodeView: (request: { definition: NodeDefinition; nodeId: string; x: number; y: number; index: number }) => NodeView
  screenToWorld: (clientX: number, clientY: number) => { x: number; y: number }
  getConnectionDraftPayloadTypeId: (draft: WorkflowConnectionDraftState) => string | null
  connectConnectionDraftToNewNode: (draft: WorkflowConnectionDraftState, graphNode: NodeView) => boolean
  setSelection: (selection: WorkflowNodePickerSelection) => void
  setStatusMessage: (message: string | null) => void
  setErrorMessage: (message: string | null) => void
  readAddNodeTitle: () => string
  readSelectAndConnectTitle: () => string
}

export function useWorkflowNodePicker<NodeView extends WorkflowNodePickerNodeView, ContextMenu extends WorkflowNodePickerContextMenu>(
  options: WorkflowNodePickerOptions<NodeView, ContextMenu>,
) {
  const nodePicker = ref<WorkflowNodePickerState | null>(null)

  const nodePickerTitle = computed(() => (
    nodePicker.value?.mode === 'link-drop'
      ? options.readSelectAndConnectTitle()
      : options.readAddNodeTitle()
  ))

  const nodePickerRequiredPortDirection = computed<'input' | 'output' | null>(() => {
    const draft = nodePicker.value?.connectionDraft
    if (!draft) return null
    return draft.anchorDirection === 'output' ? 'input' : 'output'
  })

  const nodePickerRequiredPayloadTypeId = computed(() => {
    const draft = nodePicker.value?.connectionDraft
    if (!draft) return null
    return options.getConnectionDraftPayloadTypeId(draft)
  })

  function addGraphNode(definition: NodeDefinition, rawX: number, rawY: number): NodeView {
    const nodeId = createGraphNodeId(definition.node_type_id)
    const x = Math.round(rawX - 115)
    const y = Math.round(rawY - 40)
    const graphNode = options.createNodeView({
      definition,
      nodeId,
      x,
      y,
      index: options.graphNodes.value.length,
    })
    options.graphNodes.value.push(graphNode)
    options.setSelection({ nodeId, edgeId: null, boundaryKind: null })
    options.setStatusMessage('已添加节点')
    return graphNode
  }

  function openNodePickerFromContextMenu(): void {
    const menu = options.contextMenu.value
    if (!menu) return
    const pickerWidth = 640
    const preferredX = menu.x + 198
    const hasRightSpace = typeof window === 'undefined' || preferredX + pickerWidth + 12 <= window.innerWidth
    nodePicker.value = {
      x: hasRightSpace ? preferredX : menu.x - pickerWidth - 8,
      y: menu.y,
      worldX: menu.worldX,
      worldY: menu.worldY,
      mode: 'context-menu',
      connectionDraft: null,
    }
  }

  function openNodePickerFromConnectionDraft(draft: WorkflowConnectionDraftState, event: MouseEvent): void {
    const position = options.screenToWorld(event.clientX, event.clientY)
    options.contextMenu.value = null
    nodePicker.value = {
      x: event.clientX + 8,
      y: event.clientY + 8,
      worldX: position.x,
      worldY: position.y,
      mode: 'link-drop',
      connectionDraft: { ...draft },
    }
    options.setErrorMessage(null)
  }

  function closeNodePicker(): void {
    nodePicker.value = null
    options.contextMenu.value = null
  }

  function selectNodeFromPicker(definition: NodeDefinition): void {
    const picker = nodePicker.value
    if (!picker) return
    const graphNode = addGraphNode(definition, picker.worldX, picker.worldY)
    const connectionResult = picker.connectionDraft ? options.connectConnectionDraftToNewNode(picker.connectionDraft, graphNode) : true
    nodePicker.value = null
    options.contextMenu.value = null
    if (!connectionResult && picker.connectionDraft) {
      options.setSelection({ nodeId: graphNode.node.node_id, edgeId: null, boundaryKind: null })
    }
  }

  function createGraphNodeId(nodeTypeId: string): string {
    const baseId = nodeTypeId.replace(/[^a-zA-Z0-9]+/g, '_').replace(/^_+|_+$/g, '').toLowerCase() || 'node'
    const existingIds = new Set(options.graphNodes.value.map((node) => node.node.node_id))
    let candidateId = baseId
    let suffix = 1
    while (existingIds.has(candidateId)) {
      suffix += 1
      candidateId = `${baseId}_${suffix}`
    }
    return candidateId
  }

  return {
    nodePicker,
    nodePickerTitle,
    nodePickerRequiredPortDirection,
    nodePickerRequiredPayloadTypeId,
    addGraphNode,
    openNodePickerFromContextMenu,
    openNodePickerFromConnectionDraft,
    closeNodePicker,
    selectNodeFromPicker,
    createGraphNodeId,
  }
}
