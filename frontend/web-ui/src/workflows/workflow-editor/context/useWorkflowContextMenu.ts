import { computed, type Ref } from 'vue'

import {
  buildPublicPortMetadata,
  createUniquePublicId,
  type WorkflowBoundaryKind,
  type WorkflowPublicBindingNodeLike,
} from '../bindings/useWorkflowPublicBindings'
import type { WorkflowPortDirection, WorkflowPortReference } from '../canvas/useWorkflowPortConnections'
import type {
  FlowApplicationBinding,
  NodePortDefinition,
  WorkflowGraphEdge,
  WorkflowGraphInput,
  WorkflowGraphOutput,
} from '../types'

export interface WorkflowContextMenuState<BoundaryKind extends WorkflowBoundaryKind = WorkflowBoundaryKind> {
  x: number
  y: number
  worldX: number
  worldY: number
  nodeId: string | null
  edgeId: string | null
  port: WorkflowPortReference | null
  boundaryKind?: BoundaryKind | null
  bindingId?: string | null
}

export interface WorkflowContextMenuNodeView extends WorkflowPublicBindingNodeLike {
  inputs: NodePortDefinition[]
  outputs: NodePortDefinition[]
}

export interface WorkflowContextMenuBoundaryView<BoundaryKind extends WorkflowBoundaryKind = WorkflowBoundaryKind> {
  kind: BoundaryKind
}

export interface WorkflowContextMenuLinkView {
  linkKind: string
  edgeId: string
  edge: WorkflowGraphEdge | null
  bindingId?: string | null
}

export interface WorkflowContextMenuSelection<BoundaryKind extends WorkflowBoundaryKind = WorkflowBoundaryKind> {
  nodeId: string | null
  edgeId: string | null
  boundaryKind: BoundaryKind | null
}

export interface WorkflowScreenPosition {
  x: number
  y: number
}

export interface WorkflowContextMenuOptions<
  NodeView extends WorkflowContextMenuNodeView,
  BoundaryKind extends WorkflowBoundaryKind = WorkflowBoundaryKind,
> {
  workflowApp: Ref<unknown | null>
  graphNodes: Ref<NodeView[]>
  graphEdges: Ref<WorkflowGraphEdge[]>
  templateInputs: Ref<WorkflowGraphInput[]>
  templateOutputs: Ref<WorkflowGraphOutput[]>
  applicationBindingsDraft: Ref<FlowApplicationBinding[]>
  contextMenu: Ref<WorkflowContextMenuState<BoundaryKind> | null>
  nodePicker: Ref<unknown | null>
  screenToWorld: (screenX: number, screenY: number) => WorkflowScreenPosition
  findInputEdge: (nodeId: string, portName: string) => WorkflowGraphEdge | null | undefined
  findOutputEdge: (nodeId: string, portName: string) => WorkflowGraphEdge | null | undefined
  readSelectedNodeId: () => string | null
  readSelectedEdgeId: () => string | null
  setPreviewInputStateForBinding: (binding: FlowApplicationBinding) => void
  setSelection: (selection: WorkflowContextMenuSelection<BoundaryKind>) => void
  selectNode: (nodeId: string) => void
  selectEdge: (edgeId: string) => void
  selectApplicationBoundary: (kind: BoundaryKind) => void
  deleteGraphNode: (nodeId: string | null | undefined) => boolean
  deleteGraphEdge: (edgeId: string | null | undefined) => boolean
  shouldIgnoreStagePointer: (target: EventTarget | null) => boolean
  setStatusMessage: (message: string | null) => void
  setErrorMessage: (message: string | null) => void
}

export function useWorkflowContextMenu<
  NodeView extends WorkflowContextMenuNodeView,
  BoundaryView extends WorkflowContextMenuBoundaryView<BoundaryKind>,
  LinkView extends WorkflowContextMenuLinkView,
  BoundaryKind extends WorkflowBoundaryKind = WorkflowBoundaryKind,
>(options: WorkflowContextMenuOptions<NodeView, BoundaryKind>) {
  const contextMenuStyle = computed<Record<string, string>>(() => {
    if (!options.contextMenu.value) return {} as Record<string, string>
    return {
      left: `${options.contextMenu.value.x}px`,
      top: `${options.contextMenu.value.y}px`,
    }
  })

  function clearContextMenu(): void {
    options.contextMenu.value = null
  }

  function setContextMenuFromEvent(
    event: MouseEvent,
    menu: Omit<WorkflowContextMenuState<BoundaryKind>, 'x' | 'y' | 'worldX' | 'worldY'>,
  ): void {
    const position = options.screenToWorld(event.clientX, event.clientY)
    options.nodePicker.value = null
    options.contextMenu.value = {
      x: event.clientX,
      y: event.clientY,
      worldX: position.x,
      worldY: position.y,
      ...menu,
    }
  }

  function openGraphLinkContextMenu(event: MouseEvent, link: LinkView): void {
    if (link.linkKind === 'edge') {
      openEdgeContextMenu(event, link)
      return
    }
    const boundaryKind = (link.linkKind === 'template-input' ? 'entry' : 'result') as BoundaryKind
    options.setSelection({ nodeId: null, edgeId: null, boundaryKind })
    setContextMenuFromEvent(event, {
      nodeId: null,
      edgeId: null,
      port: null,
      boundaryKind,
      bindingId: link.bindingId ?? null,
    })
  }

  function selectPortEndpoint(node: NodeView, port: NodePortDefinition, direction: WorkflowPortDirection): void {
    const edge = direction === 'input'
      ? options.findInputEdge(node.node.node_id, port.name)
      : options.findOutputEdge(node.node.node_id, port.name)
    if (edge) {
      options.selectEdge(edge.edge_id)
      return
    }
    options.selectNode(node.node.node_id)
  }

  function exposeContextPortAsAppInput(): void {
    const portRef = options.contextMenu.value?.port
    if (!portRef || portRef.direction !== 'input') return
    const node = options.graphNodes.value.find((item) => item.node.node_id === portRef.nodeId)
    const port = node?.inputs.find((item) => item.name === portRef.portName)
    if (!node || !port) return
    exposeNodeInputAsAppInput(node, port)
  }

  function exposeContextPortAsAppOutput(): void {
    const portRef = options.contextMenu.value?.port
    if (!portRef || portRef.direction !== 'output') return
    const node = options.graphNodes.value.find((item) => item.node.node_id === portRef.nodeId)
    const port = node?.outputs.find((item) => item.name === portRef.portName)
    if (!node || !port) return
    exposeNodeOutputAsAppOutput(node, port)
  }

  function exposeNodeInputAsAppInput(node: NodeView, port: NodePortDefinition, inputOptions: { required?: boolean } = {}): void {
    if (!options.workflowApp.value) {
      options.setErrorMessage('当前图还没有应用草稿，暂不能创建公开输入')
      return
    }
    const existingInput = options.templateInputs.value.find((input) => input.target_node_id === node.node.node_id && input.target_port === port.name)
    if (existingInput) {
      options.selectApplicationBoundary('entry' as BoundaryKind)
      options.setStatusMessage(`${existingInput.input_id} 已经是应用输入`)
      return
    }
    if (options.findInputEdge(node.node.node_id, port.name) && !port.multiple) {
      options.setErrorMessage('该输入端口已有普通连线，请先删除连线再公开为应用输入')
      return
    }
    const inputId = createUniquePublicId(
      `${node.node.node_id}_${port.name}`,
      new Set(options.templateInputs.value.map((input) => input.input_id)),
    )
    const displayName = port.display_name || port.name
    const metadata = buildPublicPortMetadata(node, port)
    const required = inputOptions.required ?? port.required
    const templateInput: WorkflowGraphInput = {
      input_id: inputId,
      display_name: displayName,
      payload_type_id: port.payload_type_id,
      target_node_id: node.node.node_id,
      target_port: port.name,
      required,
      metadata,
    }
    const binding: FlowApplicationBinding = {
      binding_id: inputId,
      direction: 'input',
      template_port_id: inputId,
      binding_kind: 'api-request',
      required,
      config: { payload_type_id: port.payload_type_id },
      metadata,
    }
    options.templateInputs.value = [...options.templateInputs.value, templateInput]
    options.applicationBindingsDraft.value = [...options.applicationBindingsDraft.value, binding]
    options.setPreviewInputStateForBinding(binding)
    options.selectApplicationBoundary('entry' as BoundaryKind)
    options.setStatusMessage('已公开为应用输入')
    options.setErrorMessage(null)
  }

  function exposeNodeOutputAsAppOutput(node: NodeView, port: NodePortDefinition): void {
    if (!options.workflowApp.value) {
      options.setErrorMessage('当前图还没有应用草稿，暂不能创建公开输出')
      return
    }
    const existingOutput = options.templateOutputs.value.find((output) => output.source_node_id === node.node.node_id && output.source_port === port.name)
    if (existingOutput) {
      options.selectApplicationBoundary('result' as BoundaryKind)
      options.setStatusMessage(`${existingOutput.output_id} 已经是应用输出`)
      return
    }
    const outputId = createDefaultPublicOutputId(node, port)
    const displayName = port.display_name || port.name
    const metadata = buildPublicPortMetadata(node, port)
    const templateOutput: WorkflowGraphOutput = {
      output_id: outputId,
      display_name: displayName,
      payload_type_id: port.payload_type_id,
      source_node_id: node.node.node_id,
      source_port: port.name,
      metadata,
    }
    const binding: FlowApplicationBinding = {
      binding_id: outputId,
      direction: 'output',
      template_port_id: outputId,
      binding_kind: 'http-response',
      required: false,
      config: { payload_type_id: port.payload_type_id },
      metadata,
    }
    options.templateOutputs.value = [...options.templateOutputs.value, templateOutput]
    options.applicationBindingsDraft.value = [...options.applicationBindingsDraft.value, binding]
    options.selectApplicationBoundary('result' as BoundaryKind)
    options.setStatusMessage('已公开为应用输出')
    options.setErrorMessage(null)
  }

  function createDefaultPublicOutputId(node: NodeView, port: NodePortDefinition): string {
    const shouldUseNodeId = node.node.node_type_id === 'core.output.http-response' && port.name === 'response'
    const baseValue = shouldUseNodeId ? node.node.node_id : `${node.node.node_id}_${port.name}`
    return createUniquePublicId(baseValue, new Set(options.templateOutputs.value.map((output) => output.output_id)))
  }

  function deleteSelectedNode(): void {
    const nodeId = options.readSelectedNodeId() ?? options.contextMenu.value?.nodeId
    options.deleteGraphNode(nodeId)
  }

  function deleteSelectedEdge(): void {
    const edgeId = options.readSelectedEdgeId() ?? options.contextMenu.value?.edgeId
    options.deleteGraphEdge(edgeId)
  }

  function openNodeContextMenu(event: MouseEvent, node: NodeView): void {
    options.setSelection({ nodeId: node.node.node_id, edgeId: null, boundaryKind: null })
    setContextMenuFromEvent(event, {
      nodeId: node.node.node_id,
      edgeId: null,
      port: null,
    })
  }

  function openPortContextMenu(event: MouseEvent, node: NodeView, port: NodePortDefinition, direction: WorkflowPortDirection): void {
    options.setSelection({ nodeId: node.node.node_id, edgeId: null, boundaryKind: null })
    setContextMenuFromEvent(event, {
      nodeId: node.node.node_id,
      edgeId: null,
      port: { nodeId: node.node.node_id, portName: port.name, direction },
    })
  }

  function openBoundaryContextMenu(event: MouseEvent, boundary: BoundaryView): void {
    options.setSelection({ nodeId: null, edgeId: null, boundaryKind: boundary.kind })
    setContextMenuFromEvent(event, {
      nodeId: null,
      edgeId: null,
      port: null,
      boundaryKind: boundary.kind,
      bindingId: null,
    })
  }

  function openBoundaryPortContextMenu(event: MouseEvent, boundary: BoundaryView, binding: FlowApplicationBinding): void {
    options.setSelection({ nodeId: null, edgeId: null, boundaryKind: boundary.kind })
    setContextMenuFromEvent(event, {
      nodeId: null,
      edgeId: null,
      port: null,
      boundaryKind: boundary.kind,
      bindingId: binding.binding_id,
    })
    options.setStatusMessage(`已选择 ${binding.binding_id}`)
  }

  function openEdgeContextMenu(event: MouseEvent, link: LinkView): void {
    if (!link.edge) return
    options.setSelection({ nodeId: null, edgeId: link.edgeId, boundaryKind: null })
    setContextMenuFromEvent(event, {
      nodeId: null,
      edgeId: link.edgeId,
      port: null,
    })
  }

  function openStageContextMenu(event: MouseEvent): void {
    if (options.shouldIgnoreStagePointer(event.target)) return
    setContextMenuFromEvent(event, {
      nodeId: null,
      edgeId: null,
      port: null,
    })
  }

  return {
    contextMenuStyle,
    clearContextMenu,
    openGraphLinkContextMenu,
    selectPortEndpoint,
    exposeContextPortAsAppInput,
    exposeContextPortAsAppOutput,
    exposeNodeInputAsAppInput,
    exposeNodeOutputAsAppOutput,
    deleteSelectedNode,
    deleteSelectedEdge,
    openNodeContextMenu,
    openPortContextMenu,
    openBoundaryContextMenu,
    openBoundaryPortContextMenu,
    openEdgeContextMenu,
    openStageContextMenu,
  }
}
