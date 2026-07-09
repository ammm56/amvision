import { computed, type Ref } from 'vue'

import { applyMissingNodeParameterDefaults } from '../parameters/useWorkflowNodeParameters'
import type {
  NodeDefinition,
  NodePortDefinition,
  WorkflowGraphEdge,
  WorkflowGraphNode,
  WorkflowNodeCatalogResponse,
} from '../types'

export interface WorkflowGraphNodeView {
  node: WorkflowGraphNode
  definition: NodeDefinition | null
  title: string
  x: number
  y: number
  width: number
  inputs: NodePortDefinition[]
  outputs: NodePortDefinition[]
}

export interface WorkflowGraphNodeViewsOptions {
  nodeCatalog: Ref<WorkflowNodeCatalogResponse | null>
  graphEdges: Ref<WorkflowGraphEdge[]>
}

interface WorkflowGraphNodePosition {
  x: number
  y: number
}

function readNumber(value: unknown, fallback: number): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback
}

function readNodePosition(
  node: WorkflowGraphNode,
  index: number,
  fallbackByNodeId: Map<string, WorkflowGraphNodePosition>,
): WorkflowGraphNodePosition {
  const rawX = node.ui_state.x ?? node.ui_state.pos_x ?? node.ui_state.position_x
  const rawY = node.ui_state.y ?? node.ui_state.pos_y ?? node.ui_state.position_y
  const fallback = fallbackByNodeId.get(node.node_id) ?? { x: 360 + (index % 3) * 280, y: 120 + Math.floor(index / 3) * 180 }
  return {
    x: readNumber(rawX, fallback.x),
    y: readNumber(rawY, fallback.y),
  }
}

function buildFallbackPositions(
  nodes: WorkflowGraphNode[],
  edges: WorkflowGraphEdge[],
): Map<string, WorkflowGraphNodePosition> {
  const nodeIds = new Set(nodes.map((node) => node.node_id))
  const incomingCounts = new Map(nodes.map((node) => [node.node_id, 0]))
  const outgoingNodes = new Map(nodes.map((node) => [node.node_id, [] as string[]]))
  for (const edge of edges) {
    if (!nodeIds.has(edge.source_node_id) || !nodeIds.has(edge.target_node_id)) continue
    outgoingNodes.get(edge.source_node_id)?.push(edge.target_node_id)
    incomingCounts.set(edge.target_node_id, (incomingCounts.get(edge.target_node_id) ?? 0) + 1)
  }

  const queue = nodes.filter((node) => (incomingCounts.get(node.node_id) ?? 0) === 0).map((node) => node.node_id)
  const depthByNodeId = new Map(nodes.map((node) => [node.node_id, 0]))
  while (queue.length > 0) {
    const nodeId = queue.shift()
    if (!nodeId) continue
    const nextDepth = (depthByNodeId.get(nodeId) ?? 0) + 1
    for (const targetNodeId of outgoingNodes.get(nodeId) ?? []) {
      depthByNodeId.set(targetNodeId, Math.max(depthByNodeId.get(targetNodeId) ?? 0, nextDepth))
      incomingCounts.set(targetNodeId, (incomingCounts.get(targetNodeId) ?? 1) - 1)
      if ((incomingCounts.get(targetNodeId) ?? 0) === 0) {
        queue.push(targetNodeId)
      }
    }
  }

  const columns = new Map<number, WorkflowGraphNode[]>()
  for (const node of nodes) {
    const depth = depthByNodeId.get(node.node_id) ?? 0
    const columnNodes = columns.get(depth) ?? []
    columnNodes.push(node)
    columns.set(depth, columnNodes)
  }

  const positions = new Map<string, WorkflowGraphNodePosition>()
  for (const [depth, columnNodes] of columns) {
    columnNodes.forEach((node, rowIndex) => {
      positions.set(node.node_id, { x: 360 + depth * 320, y: 120 + rowIndex * 230 })
    })
  }
  return positions
}

function inferPortsFromEdges(
  node: WorkflowGraphNode,
  direction: 'input' | 'output',
  graphEdges: WorkflowGraphEdge[],
): NodePortDefinition[] {
  const edgeNames = new Set<string>()
  for (const edge of graphEdges) {
    if (direction === 'input' && edge.target_node_id === node.node_id) {
      edgeNames.add(edge.target_port)
    }
    if (direction === 'output' && edge.source_node_id === node.node_id) {
      edgeNames.add(edge.source_port)
    }
  }
  return [...edgeNames].map((name) => ({
    name,
    display_name: name,
    payload_type_id: '',
    description: '',
    required: true,
    multiple: false,
    metadata: {},
  }))
}

export function buildDefaultGraphNodeWidth(definition: NodeDefinition): number {
  void definition
  return 256
}

function normalizeGraphNodeWidth(value: unknown, fallbackWidth: number): number {
  const width = readNumber(value, fallbackWidth)
  if ([250, 300, 320, 340].includes(width)) return fallbackWidth
  return width
}

export function useWorkflowGraphNodeViews(options: WorkflowGraphNodeViewsOptions) {
  const nodeDefinitionsById = computed(() => new Map((options.nodeCatalog.value?.node_definitions ?? []).map((definition) => [definition.node_type_id, definition])))
  const nodePickerDefinitions = computed(() => options.nodeCatalog.value?.node_definitions ?? [])

  function buildGraphNodeView(
    node: WorkflowGraphNode,
    index: number,
    fallbackByNodeId: Map<string, WorkflowGraphNodePosition>,
  ): WorkflowGraphNodeView {
    const definition = nodeDefinitionsById.value.get(node.node_type_id) ?? null
    const normalizedNode = {
      ...(definition ? applyMissingNodeParameterDefaults(node, definition) : node),
      enabled: node.enabled !== false,
    }
    const position = readNodePosition(normalizedNode, index, fallbackByNodeId)
    const defaultWidth = definition ? buildDefaultGraphNodeWidth(definition) : 256
    return {
      node: normalizedNode,
      definition,
      title: definition?.display_name || normalizedNode.node_type_id,
      x: position.x,
      y: position.y,
      width: normalizeGraphNodeWidth(normalizedNode.ui_state.width, defaultWidth),
      inputs: definition?.input_ports.length ? definition.input_ports : inferPortsFromEdges(normalizedNode, 'input', options.graphEdges.value),
      outputs: definition?.output_ports.length ? definition.output_ports : inferPortsFromEdges(normalizedNode, 'output', options.graphEdges.value),
    }
  }

  function buildGraphNodeViews(nodes: WorkflowGraphNode[]): WorkflowGraphNodeView[] {
    const fallbackByNodeId = buildFallbackPositions(nodes, options.graphEdges.value)
    return nodes.map((node, index) => buildGraphNodeView(node, index, fallbackByNodeId))
  }

  return {
    nodeDefinitionsById,
    nodePickerDefinitions,
    buildDefaultGraphNodeWidth,
    buildGraphNodeView,
    buildGraphNodeViews,
  }
}
