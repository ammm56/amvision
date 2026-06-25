import { computed, type ComputedRef, type Ref } from 'vue'

import type { WorkflowBoundaryKind, WorkflowBoundaryPosition } from './useWorkflowPublicBindings'
import type { FlowApplicationBinding, WorkflowGraphInput, WorkflowGraphOutput } from '../types'

export interface WorkflowBoundaryNodeGraphNode {
  node: {
    node_id: string
  }
  x: number
  y: number
  width: number
}

export interface WorkflowBoundaryNodeView {
  id: string
  kind: WorkflowBoundaryKind
  portDirection: 'input' | 'output'
  title: string
  description: string
  x: number
  y: number
  width: number
  bindings: FlowApplicationBinding[]
}

export interface WorkflowBoundaryNodeOptions<NodeView extends WorkflowBoundaryNodeGraphNode> {
  graphNodes: Ref<NodeView[]>
  selectedBoundaryKind: Ref<WorkflowBoundaryKind | null>
  boundaryPositions: Ref<Partial<Record<WorkflowBoundaryKind, WorkflowBoundaryPosition>>>
  appInputBindings: ComputedRef<FlowApplicationBinding[]>
  appOutputBindings: ComputedRef<FlowApplicationBinding[]>
  templateInputById: ComputedRef<Map<string, WorkflowGraphInput>>
  templateOutputById: ComputedRef<Map<string, WorkflowGraphOutput>>
}

const appEntryBoundaryId = 'app-entry-boundary'
const appResultBoundaryId = 'app-result-boundary'
const graphBoundaryHeaderHeight = 64
const graphBoundaryPortRowHeight = 44
const graphBoundaryPortInsetX = 16

export function useWorkflowBoundaryNodes<NodeView extends WorkflowBoundaryNodeGraphNode>(options: WorkflowBoundaryNodeOptions<NodeView>) {
  const appBoundaryNodes = computed<WorkflowBoundaryNodeView[]>(() => {
    if (options.graphNodes.value.length === 0) return []
    const minNodeX = Math.min(...options.graphNodes.value.map((node) => node.x))
    const minNodeY = Math.min(...options.graphNodes.value.map((node) => node.y))
    const maxNodeX = Math.max(...options.graphNodes.value.map((node) => node.x + node.width))
    const entryPosition = options.boundaryPositions.value.entry ?? { x: minNodeX - 320, y: minNodeY }
    const resultPosition = options.boundaryPositions.value.result ?? { x: maxNodeX + 140, y: minNodeY }
    return [
      {
        id: appEntryBoundaryId,
        kind: 'entry',
        portDirection: 'output',
        title: 'App Entry',
        description: `公开输入 ${options.appInputBindings.value.length}`,
        x: entryPosition.x,
        y: entryPosition.y,
        width: 250,
        bindings: options.appInputBindings.value,
      },
      {
        id: appResultBoundaryId,
        kind: 'result',
        portDirection: 'input',
        title: 'App Result',
        description: `公开输出 ${options.appOutputBindings.value.length}`,
        x: resultPosition.x,
        y: resultPosition.y,
        width: 250,
        bindings: options.appOutputBindings.value,
      },
    ]
  })

  const selectedBoundaryBindings = computed(() => {
    if (options.selectedBoundaryKind.value === 'entry') return options.appInputBindings.value
    if (options.selectedBoundaryKind.value === 'result') return options.appOutputBindings.value
    return []
  })

  const selectedBoundaryTitle = computed(() => {
    if (options.selectedBoundaryKind.value === 'entry') return 'App Entry'
    if (options.selectedBoundaryKind.value === 'result') return 'App Result'
    return ''
  })

  function boundaryNodeHeight(boundary: WorkflowBoundaryNodeView): number {
    return Math.max(116, graphBoundaryHeaderHeight + Math.max(boundary.bindings.length, 1) * graphBoundaryPortRowHeight + 16)
  }

  function boundaryPortY(boundary: WorkflowBoundaryNodeView, bindingId: string): number {
    const index = Math.max(boundary.bindings.findIndex((binding) => binding.binding_id === bindingId), 0)
    return boundary.y + graphBoundaryHeaderHeight + index * graphBoundaryPortRowHeight + graphBoundaryPortRowHeight / 2
  }

  function boundaryPortX(boundary: WorkflowBoundaryNodeView): number {
    return boundary.kind === 'entry'
      ? boundary.x + boundary.width - graphBoundaryPortInsetX - 1
      : boundary.x + graphBoundaryPortInsetX + 1
  }

  function isBoundaryPortConnected(kind: WorkflowBoundaryKind, binding: FlowApplicationBinding): boolean {
    if (kind === 'entry') {
      const templateInput = options.templateInputById.value.get(binding.template_port_id)
      return Boolean(templateInput && options.graphNodes.value.some((node) => node.node.node_id === templateInput.target_node_id))
    }
    const templateOutput = options.templateOutputById.value.get(binding.template_port_id)
    return Boolean(templateOutput && options.graphNodes.value.some((node) => node.node.node_id === templateOutput.source_node_id))
  }

  return {
    appEntryBoundaryId,
    appResultBoundaryId,
    appBoundaryNodes,
    selectedBoundaryBindings,
    selectedBoundaryTitle,
    boundaryNodeHeight,
    boundaryPortY,
    boundaryPortX,
    isBoundaryPortConnected,
  }
}
