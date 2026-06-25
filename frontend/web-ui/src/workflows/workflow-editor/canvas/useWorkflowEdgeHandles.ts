import { computed, type ComputedRef, type Ref } from 'vue'

import type { WorkflowGraphLinkView } from '../geometry/useWorkflowGraphGeometry'

export interface WorkflowEdgeHandleView {
  key: string
  edgeId: string
  x: number
  y: number
  link: WorkflowGraphLinkView
}

export interface WorkflowEdgeHandleOptions {
  graphLinks: ComputedRef<WorkflowGraphLinkView[]>
  selectedEdgeId: Ref<string | null>
  linkPointAt: (link: WorkflowGraphLinkView, progress: number) => { x: number; y: number }
}

export function useWorkflowEdgeHandles(options: WorkflowEdgeHandleOptions) {
  const graphLinkMidpoints = computed<WorkflowEdgeHandleView[]>(() => options.graphLinks.value.map((link) => ({
    key: `${link.edgeId}-midpoint`,
    edgeId: link.edgeId,
    link,
    ...options.linkPointAt(link, 0.5),
  })))

  const selectedEdgeReconnectHandles = computed<WorkflowEdgeHandleView[]>(() => {
    const link = options.graphLinks.value.find((item) => item.edgeId === options.selectedEdgeId.value && item.linkKind === 'edge')
    if (!link) return []
    return [{ key: `${link.edgeId}-reconnect`, edgeId: link.edgeId, link, ...options.linkPointAt(link, 0.5) }]
  })

  return {
    graphLinkMidpoints,
    selectedEdgeReconnectHandles,
  }
}
