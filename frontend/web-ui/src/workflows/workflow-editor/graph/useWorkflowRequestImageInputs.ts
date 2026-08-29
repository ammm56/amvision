import type { ComputedRef, Ref } from 'vue'

import { translate } from '@/platform/i18n'
import type { WorkflowBoundaryNodeView } from '../bindings/useWorkflowBoundaryNodes'
import { createUniquePublicId, type WorkflowBoundaryKind, type WorkflowBoundaryPosition } from '../bindings/useWorkflowPublicBindings'
import type { WorkflowPortReference } from '../canvas/useWorkflowPortConnections'
import type { FlowApplicationBinding, NodeDefinition, NodePortDefinition, WorkflowGraphEdge, WorkflowGraphNode } from '../types'

export interface WorkflowRequestImageNodeView {
  node: WorkflowGraphNode
  x: number
  y: number
  width: number
  inputs: NodePortDefinition[]
  outputs: NodePortDefinition[]
}

interface RequestInputConfig {
  bindingId: string
  displayName: string
  nodeTypeId: string
  portName: string
}

export interface WorkflowRequestImageInputOptions<NodeView extends WorkflowRequestImageNodeView> {
  workflowApp: Ref<unknown | null>
  graphNodes: Ref<NodeView[]>
  graphEdges: Ref<WorkflowGraphEdge[]>
  appBoundaryNodes: ComputedRef<WorkflowBoundaryNodeView[]>
  appInputBindings: ComputedRef<FlowApplicationBinding[]>
  applicationBindingsDraft: Ref<FlowApplicationBinding[]>
  nodeDefinitionsById: ComputedRef<Map<string, NodeDefinition>>
  boundaryPositions: Ref<Partial<Record<WorkflowBoundaryKind, WorkflowBoundaryPosition>>>
  stageSize: Ref<{ width: number; height: number }>
  viewportX: Ref<number>
  viewportY: Ref<number>
  viewportScale: Ref<number>
  addGraphNode: (definition: NodeDefinition, x: number, y: number) => NodeView
  deleteGraphNode: (nodeId: string | null | undefined) => void
  exposeNodeInputAsAppInput: (node: NodeView, port: NodePortDefinition, options?: { required?: boolean }) => void
  renameApplicationBinding: (binding: FlowApplicationBinding, nextBindingId: string) => boolean
  setBindingDisplayName: (binding: FlowApplicationBinding, displayName: string) => void
  updateApplicationBindingRequired: (binding: FlowApplicationBinding, required: boolean) => void
  connectOutputToInput: (source: WorkflowPortReference, target: WorkflowPortReference) => boolean
  selectApplicationBoundary: (kind: WorkflowBoundaryKind) => void
  setStatusMessage: (message: string | null) => void
  setErrorMessage: (message: string | null) => void
}

export function useWorkflowRequestImageInputs<NodeView extends WorkflowRequestImageNodeView>(options: WorkflowRequestImageInputOptions<NodeView>) {
  function addRequestImageRefInput(): void {
    addRequestInputNode({
      bindingId: 'request_image_ref',
      displayName: 'request_image_ref',
      nodeTypeId: 'core.logic.image-ref-coalesce',
      portName: 'primary',
    })
  }

  function addRequestImageBase64Input(): void {
    addRequestInputNode({
      bindingId: 'request_image_base64',
      displayName: 'request_image_base64',
      nodeTypeId: 'core.io.image-base64-decode',
      portName: 'payload',
    })
  }

  function addRequestJsonInput(): void {
    addRequestInputNode({
      bindingId: 'request_json',
      displayName: 'JSON Parameters',
      nodeTypeId: 'core.io.template-input.object',
      portName: 'payload',
    })
  }

  function addRequestValueInput(): void {
    addRequestInputNode({
      bindingId: 'request_value',
      displayName: 'Value',
      nodeTypeId: 'core.io.template-input.value',
      portName: 'payload',
    })
  }

  function addRequestTextInput(): void {
    addRequestInputNode({
      bindingId: 'request_text',
      displayName: 'Text',
      nodeTypeId: 'core.io.template-input.text',
      portName: 'payload',
    })
  }

  function addRequestFileInput(): void {
    addRequestInputNode({
      bindingId: 'request_file',
      displayName: 'File',
      nodeTypeId: 'core.io.template-input.file',
      portName: 'payload',
    })
  }

  function addRequestFilesInput(): void {
    addRequestInputNode({
      bindingId: 'request_files',
      displayName: 'Files',
      nodeTypeId: 'core.io.template-input.files',
      portName: 'payload',
    })
  }

  function normalizeLoadedRequestImageInputBindings(): void {
    const optionalBindingIds = new Set(['request_image_ref', 'request_image_base64'])
    for (const binding of options.applicationBindingsDraft.value) {
      if (binding.direction !== 'input' || !optionalBindingIds.has(binding.binding_id)) continue
      options.updateApplicationBindingRequired(binding, false)
    }
  }

  function addRequestInputNode(input: RequestInputConfig): void {
    if (!options.workflowApp.value) return
    const existingBinding = options.appInputBindings.value.find((binding) => binding.binding_id === input.bindingId)
    if (existingBinding) {
      options.selectApplicationBoundary('entry')
      options.setStatusMessage(translate('workflowEditor.feedback.bindingAlreadyExists', { id: input.bindingId }))
      return
    }
    const definition = options.nodeDefinitionsById.value.get(input.nodeTypeId)
    if (!definition) {
      options.setErrorMessage(translate('workflowEditor.feedback.nodeTypeMissing', { nodeType: input.nodeTypeId }))
      return
    }
    const previousBindingIds = new Set(options.applicationBindingsDraft.value.map((binding) => binding.binding_id))
    const position = readNextRequestInputNodePosition()
    const graphNode = options.addGraphNode(definition, position.x, position.y)
    const payloadPort = graphNode.inputs.find((port) => port.name === input.portName) ?? graphNode.inputs[0]
    if (!payloadPort) {
      options.deleteGraphNode(graphNode.node.node_id)
      options.setErrorMessage(translate('workflowEditor.feedback.noExposableInput', { node: definition.display_name }))
      return
    }
    options.exposeNodeInputAsAppInput(graphNode, payloadPort, { required: false })
    const binding = options.applicationBindingsDraft.value.find((item) => !previousBindingIds.has(item.binding_id) && item.direction === 'input')
    if (binding) {
      const nextBindingId = createUniquePublicId(input.bindingId, new Set(options.applicationBindingsDraft.value.filter((item) => item !== binding).map((item) => item.binding_id)))
      options.renameApplicationBinding(binding, nextBindingId)
      options.setBindingDisplayName(binding, input.displayName)
      binding.binding_kind = 'api-request'
      options.updateApplicationBindingRequired(binding, false)
    }
    connectRequestImageFallbackIfReady()
    layoutRequestImageNodes()
    options.selectApplicationBoundary('entry')
    options.setStatusMessage(translate('workflowEditor.feedback.bindingAdded', { id: input.bindingId }))
    options.setErrorMessage(null)
  }

  function layoutRequestImageNodes(): void {
    const coalesceNode = findNodeByType('core.logic.image-ref-coalesce')
    const decodeNode = findNodeByType('core.io.image-base64-decode')
    const requestNodes = [coalesceNode, decodeNode].filter((node): node is NodeView => Boolean(node))
    if (requestNodes.length === 0) return
    const entryPosition = options.boundaryPositions.value.entry
    const baseX = entryPosition
      ? entryPosition.x + 250 + 220
      : Math.min(...requestNodes.map((node) => node.x))
    const baseY = entryPosition
      ? entryPosition.y
      : Math.min(...requestNodes.map((node) => node.y))
    if (coalesceNode) moveGraphNodeTo(coalesceNode, baseX, baseY)
    if (decodeNode) {
      const decodeY = coalesceNode ? coalesceNode.y + 180 : baseY
      moveGraphNodeTo(decodeNode, baseX, decodeY)
    }
  }

  function connectRequestImageFallbackIfReady(): void {
    const decodeNode = findNodeByType('core.io.image-base64-decode')
    const coalesceNode = findNodeByType('core.logic.image-ref-coalesce')
    if (!decodeNode || !coalesceNode) return
    const hasDecodeOutput = decodeNode.outputs.some((port) => port.name === 'image')
    const hasCoalesceFallback = coalesceNode.inputs.some((port) => port.name === 'fallback')
    if (!hasDecodeOutput || !hasCoalesceFallback) return
    const hasFallbackInput = options.graphEdges.value.some(
      (edge) => edge.target_node_id === coalesceNode.node.node_id && edge.target_port === 'fallback',
    )
    if (hasFallbackInput) return
    options.connectOutputToInput(
      { nodeId: decodeNode.node.node_id, portName: 'image', direction: 'output' },
      { nodeId: coalesceNode.node.node_id, portName: 'fallback', direction: 'input' },
    )
  }

  function readNextRequestInputNodePosition(): { x: number; y: number } {
    const entryBoundary = options.appBoundaryNodes.value.find((boundary) => boundary.kind === 'entry')
    if (entryBoundary) {
      return {
        x: entryBoundary.x + entryBoundary.width + 240,
        y: entryBoundary.y + options.appInputBindings.value.length * 180 + 40,
      }
    }
    const canvasCenterX = (options.stageSize.value.width / 2 - options.viewportX.value) / options.viewportScale.value
    const canvasCenterY = (options.stageSize.value.height / 2 - options.viewportY.value) / options.viewportScale.value
    return { x: canvasCenterX, y: canvasCenterY }
  }

  function moveGraphNodeTo(node: NodeView, x: number, y: number): void {
    node.x = Math.round(x)
    node.y = Math.round(y)
    node.node.ui_state = { ...node.node.ui_state, x: node.x, y: node.y, width: node.width }
  }

  function findNodeByType(nodeTypeId: string): NodeView | null {
    return options.graphNodes.value.find((node) => node.node.node_type_id === nodeTypeId) ?? null
  }

  return {
    addRequestImageRefInput,
    addRequestImageBase64Input,
    addRequestJsonInput,
    addRequestValueInput,
    addRequestTextInput,
    addRequestFileInput,
    addRequestFilesInput,
    normalizeLoadedRequestImageInputBindings,
  }
}
