import { computed, type ComputedRef, type Ref } from 'vue'

import type { WorkflowBoundaryNodeView } from '../bindings/useWorkflowBoundaryNodes'
import type { WorkflowConnectionDraftState, WorkflowPortDirection } from '../canvas/useWorkflowPortConnections'
import type { FlowApplicationBinding, NodeParameterUiField, NodePortDefinition, WorkflowGraphEdge, WorkflowGraphInput, WorkflowGraphNode, WorkflowGraphOutput } from '../types'

export interface WorkflowGraphGeometryNodeView {
  node: WorkflowGraphNode
  x: number
  y: number
  width: number
  inputs: NodePortDefinition[]
  outputs: NodePortDefinition[]
}

export interface WorkflowGraphLinkView {
  linkKind: 'edge' | 'template-input' | 'template-output'
  edgeId: string
  edge: WorkflowGraphEdge | null
  sourceX: number
  sourceY: number
  targetX: number
  targetY: number
  bindingId?: string
  templatePortId?: string
}

export interface WorkflowGraphGeometryLayout {
  nodeHeaderHeight: number
  portRowHeight: number
  portInsetX: number
  nodePreviewFrameHeight: number
  nodePreviewImageHeight: number
  nodePreviewDataHeight: number
  nodePreviewGalleryColumns: number
  nodePreviewGalleryItemHeight: number
  nodePreviewGalleryGap: number
  nodeWidgetRowHeight: number
}

interface WorkflowGraphPreviewDisplay {
  kind: string
  galleryItems?: unknown[]
}

export interface WorkflowGraphGeometryOptions<NodeView extends WorkflowGraphGeometryNodeView> {
  graphNodes: Ref<NodeView[]>
  graphEdges: Ref<WorkflowGraphEdge[]>
  templateInputs: Ref<WorkflowGraphInput[]>
  templateOutputs: Ref<WorkflowGraphOutput[]>
  appBoundaryNodes: ComputedRef<WorkflowBoundaryNodeView[]>
  appInputBindings: ComputedRef<FlowApplicationBinding[]>
  appOutputBindings: ComputedRef<FlowApplicationBinding[]>
  templateInputById: ComputedRef<Map<string, WorkflowGraphInput>>
  templateOutputById: ComputedRef<Map<string, WorkflowGraphOutput>>
  connectionDraft: Ref<WorkflowConnectionDraftState | null>
  readPreviewDisplay: (nodeId: string) => WorkflowGraphPreviewDisplay | null
  readParameterFields: (node: NodeView) => NodeParameterUiField[]
  isJsonParameter: (field: NodeParameterUiField) => boolean
  boundaryPortX: (boundary: WorkflowBoundaryNodeView) => number
  boundaryPortY: (boundary: WorkflowBoundaryNodeView, bindingId: string) => number
  layout: WorkflowGraphGeometryLayout
  clampNumber: (value: number, minValue: number, maxValue: number) => number
}

export function useWorkflowGraphGeometry<NodeView extends WorkflowGraphGeometryNodeView>(options: WorkflowGraphGeometryOptions<NodeView>) {
  const graphLinks = computed(() => buildGraphLinks(options.graphEdges.value))
  const draftLinkPath = computed(() => options.connectionDraft.value ? linkPath(buildDraftLink(options.connectionDraft.value)) : '')

  function nodeVisualHeight(node: NodeView): number {
    const portRowCount = Math.max(node.inputs.length, node.outputs.length)
    const widgetHeight = readNodeWidgetHeight(node)
    const previewHeight = readNodePreviewHeight(node.node.node_id)
    const footerHeight = previewHeight > 0 ? 0 : 22
    return Math.max(116, options.layout.nodeHeaderHeight + portRowCount * options.layout.portRowHeight + widgetHeight + previewHeight + footerHeight)
  }

  function portY(node: NodeView, portName: string, direction: WorkflowPortDirection): number {
    const ports = direction === 'input' ? node.inputs : node.outputs
    const index = Math.max(ports.findIndex((port) => port.name === portName), 0)
    return node.y + options.layout.nodeHeaderHeight + index * options.layout.portRowHeight + options.layout.portRowHeight / 2
  }

  function portX(node: NodeView, direction: WorkflowPortDirection): number {
    return direction === 'input' ? node.x + options.layout.portInsetX : node.x + node.width - options.layout.portInsetX
  }

  function isPortConnected(nodeId: string, portName: string, direction: WorkflowPortDirection): boolean {
    const hasGraphEdge = options.graphEdges.value.some((edge) => direction === 'input'
      ? edge.target_node_id === nodeId && edge.target_port === portName
      : edge.source_node_id === nodeId && edge.source_port === portName)
    if (hasGraphEdge) return true
    return direction === 'input'
      ? options.templateInputs.value.some((input) => input.target_node_id === nodeId && input.target_port === portName)
      : options.templateOutputs.value.some((output) => output.source_node_id === nodeId && output.source_port === portName)
  }

  function buildDraftLink(draft: WorkflowConnectionDraftState): WorkflowGraphLinkView {
    const sourceX = draft.anchorDirection === 'output' ? draft.anchorX : draft.pointerX
    const sourceY = draft.anchorDirection === 'output' ? draft.anchorY : draft.pointerY
    const targetX = draft.anchorDirection === 'input' ? draft.anchorX : draft.pointerX
    const targetY = draft.anchorDirection === 'input' ? draft.anchorY : draft.pointerY
    return {
      edgeId: 'draft',
      linkKind: 'edge',
      edge: {
        edge_id: 'draft',
        source_node_id: draft.anchorDirection === 'output' ? draft.anchorNodeId : '',
        source_port: draft.anchorDirection === 'output' ? draft.anchorPort : '',
        target_node_id: draft.anchorDirection === 'input' ? draft.anchorNodeId : '',
        target_port: draft.anchorDirection === 'input' ? draft.anchorPort : '',
        metadata: {},
      },
      sourceX,
      sourceY,
      targetX,
      targetY,
    }
  }

  function linkPath(link: WorkflowGraphLinkView): string {
    const control = linkControlPoints(link)
    return `M ${link.sourceX} ${link.sourceY} C ${control.sourceControlX} ${control.sourceControlY}, ${control.targetControlX} ${control.targetControlY}, ${link.targetX} ${link.targetY}`
  }

  function linkPointAt(link: WorkflowGraphLinkView, progress: number): { x: number; y: number } {
    const control = linkControlPoints(link)
    const t = options.clampNumber(progress, 0, 1)
    const inverse = 1 - t
    return {
      x: inverse ** 3 * link.sourceX + 3 * inverse ** 2 * t * control.sourceControlX + 3 * inverse * t ** 2 * control.targetControlX + t ** 3 * link.targetX,
      y: inverse ** 3 * link.sourceY + 3 * inverse ** 2 * t * control.sourceControlY + 3 * inverse * t ** 2 * control.targetControlY + t ** 3 * link.targetY,
    }
  }

  function readNodeWidgetHeight(node: NodeView): number {
    const fields = options.readParameterFields(node)
    if (fields.length === 0) return 0
    const editorsHeight = fields.reduce((total, field) => total + (options.isJsonParameter(field) ? 126 : options.layout.nodeWidgetRowHeight), 0)
    return 12 + editorsHeight + Math.max(fields.length - 1, 0) * 6
  }

  function readNodePreviewHeight(nodeId: string): number {
    const display = options.readPreviewDisplay(nodeId)
    if (!display) return 0
    if (display.kind === 'gallery') {
      const galleryItemCount = Array.isArray(display.galleryItems) ? display.galleryItems.length : 0
      const rowCount = Math.max(1, Math.ceil(Math.max(galleryItemCount, 1) / options.layout.nodePreviewGalleryColumns))
      return options.layout.nodePreviewFrameHeight + rowCount * options.layout.nodePreviewGalleryItemHeight + Math.max(0, rowCount - 1) * options.layout.nodePreviewGalleryGap
    }
    if (display.kind === 'table' || display.kind === 'value') return options.layout.nodePreviewDataHeight
    return options.layout.nodePreviewImageHeight
  }

  function buildGraphLinks(edges: WorkflowGraphEdge[]): WorkflowGraphLinkView[] {
    return [
      ...buildGraphEdgeLinks(edges),
      ...buildTemplateInputLinks(),
      ...buildTemplateOutputLinks(),
    ]
  }

  function buildGraphEdgeLinks(edges: WorkflowGraphEdge[]): WorkflowGraphLinkView[] {
    return edges.flatMap((edge) => {
      const sourceNode = options.graphNodes.value.find((node) => node.node.node_id === edge.source_node_id)
      const targetNode = options.graphNodes.value.find((node) => node.node.node_id === edge.target_node_id)
      if (!sourceNode || !targetNode) return []
      return [{
        linkKind: 'edge' as const,
        edgeId: edge.edge_id,
        edge,
        sourceX: portX(sourceNode, 'output'),
        sourceY: portY(sourceNode, edge.source_port, 'output'),
        targetX: portX(targetNode, 'input'),
        targetY: portY(targetNode, edge.target_port, 'input'),
      }]
    })
  }

  function buildTemplateInputLinks(): WorkflowGraphLinkView[] {
    const entryBoundary = options.appBoundaryNodes.value.find((boundary) => boundary.kind === 'entry')
    if (!entryBoundary) return []
    return options.appInputBindings.value.flatMap((binding) => {
      const templateInput = options.templateInputById.value.get(binding.template_port_id)
      const targetNode = templateInput ? options.graphNodes.value.find((node) => node.node.node_id === templateInput.target_node_id) : null
      if (!templateInput || !targetNode) return []
      return [{
        linkKind: 'template-input' as const,
        edgeId: `template-input-${binding.binding_id}`,
        edge: null,
        sourceX: options.boundaryPortX(entryBoundary),
        sourceY: options.boundaryPortY(entryBoundary, binding.binding_id),
        targetX: portX(targetNode, 'input'),
        targetY: portY(targetNode, templateInput.target_port, 'input'),
        bindingId: binding.binding_id,
        templatePortId: templateInput.input_id,
      }]
    })
  }

  function buildTemplateOutputLinks(): WorkflowGraphLinkView[] {
    const resultBoundary = options.appBoundaryNodes.value.find((boundary) => boundary.kind === 'result')
    if (!resultBoundary) return []
    return options.appOutputBindings.value.flatMap((binding) => {
      const templateOutput = options.templateOutputById.value.get(binding.template_port_id)
      const sourceNode = templateOutput ? options.graphNodes.value.find((node) => node.node.node_id === templateOutput.source_node_id) : null
      if (!templateOutput || !sourceNode) return []
      return [{
        linkKind: 'template-output' as const,
        edgeId: `template-output-${binding.binding_id}`,
        edge: null,
        sourceX: portX(sourceNode, 'output'),
        sourceY: portY(sourceNode, templateOutput.source_port, 'output'),
        targetX: options.boundaryPortX(resultBoundary),
        targetY: options.boundaryPortY(resultBoundary, binding.binding_id),
        bindingId: binding.binding_id,
        templatePortId: templateOutput.output_id,
      }]
    })
  }

  function linkControlPoints(link: WorkflowGraphLinkView): { sourceControlX: number; sourceControlY: number; targetControlX: number; targetControlY: number } {
    const distanceX = link.targetX - link.sourceX
    const distanceY = Math.abs(link.targetY - link.sourceY)
    const distanceFactor = distanceX < 0 ? 0.26 : 0.34
    const minControlOffset = distanceX < 0 ? 40 : 48
    const maxControlOffset = distanceX < 0 ? 132 : 180
    const shortDistanceOffset = Math.max(Math.abs(distanceX), distanceY) * distanceFactor
    const controlOffset = options.clampNumber(shortDistanceOffset, minControlOffset, maxControlOffset)
    return {
      sourceControlX: link.sourceX + controlOffset,
      sourceControlY: link.sourceY,
      targetControlX: link.targetX - controlOffset,
      targetControlY: link.targetY,
    }
  }

  return {
    graphLinks,
    draftLinkPath,
    nodeVisualHeight,
    portX,
    portY,
    isPortConnected,
    linkPath,
    linkPointAt,
  }
}
