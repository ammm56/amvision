import { computed, ref, watch, type Ref } from 'vue'

import type { WorkflowGraphLinkView } from '../geometry/useWorkflowGraphGeometry'
import type { WorkflowGraphEdge, WorkflowGraphGroup } from '../types'
import type { WorkflowBoundaryKind } from '../bindings/useWorkflowPublicBindings'

export interface WorkflowSelectionState {
  nodeId: string | null
  nodeIds?: string[]
  groupIds?: string[]
  edgeId: string | null
  boundaryKind: WorkflowBoundaryKind | null
}

export interface WorkflowSelectionStateOptions<NodeView> {
  graphNodes: Ref<NodeView[]>
  graphEdges: Ref<WorkflowGraphEdge[]>
  graphGroups?: Ref<WorkflowGraphGroup[]>
  readNodeId: (node: NodeView) => string
  clearConnectionDraft: () => void
  clearContextMenu: () => void
  clearNodePicker: () => void
}

interface WorkflowSelectionActionOptions {
  preserveConnectionDraft?: boolean
}

export function useWorkflowSelectionState<NodeView>(options: WorkflowSelectionStateOptions<NodeView>) {
  // 多选集合为唯一节点选择来源，单节点详情只在恰好选中一个时提供。
  const selectedNodeIds = ref<Set<string>>(new Set())
  const selectedGroupIds = ref<Set<string>>(new Set())
  const selectedNodeId = computed(() => selectedNodeIds.value.size === 1 ? [...selectedNodeIds.value][0]! : null)
  const selectedEdgeId = ref<string | null>(null)
  const selectedBoundaryKind = ref<WorkflowBoundaryKind | null>(null)
  const suppressNextNodeClick = ref(false)
  const nodesById = computed(() => new Map(options.graphNodes.value.map(node => [options.readNodeId(node), node])))

  const selectedNode = computed(() => graphNodeById(selectedNodeId.value))
  const selectedEdge = computed(() => graphEdgeById(selectedEdgeId.value))

  function readSelection(): WorkflowSelectionState {
    return {
      nodeId: selectedNodeId.value,
      nodeIds: [...selectedNodeIds.value],
      groupIds: [...selectedGroupIds.value],
      edgeId: selectedEdgeId.value,
      boundaryKind: selectedBoundaryKind.value,
    }
  }

  function setSelection(selection: WorkflowSelectionState): void {
    const ids = selection.edgeId || selection.boundaryKind ? [] : selection.nodeIds ?? (selection.nodeId ? [selection.nodeId] : [])
    const next = new Set(ids.filter(id => nodesById.value.has(id)))
    if (next.size !== selectedNodeIds.value.size || [...next].some(id => !selectedNodeIds.value.has(id))) selectedNodeIds.value = next
    const requestedGroups = new Set(selection.groupIds ?? [])
    const groups = new Set((options.graphGroups?.value ?? []).filter(group => requestedGroups.has(group.group_id)
      && group.member_node_ids.length > 0 && group.member_node_ids.every(id => next.has(id))).map(group => group.group_id))
    if (groups.size !== selectedGroupIds.value.size || [...groups].some(id => !selectedGroupIds.value.has(id))) selectedGroupIds.value = groups
    selectedEdgeId.value = selection.edgeId
    selectedBoundaryKind.value = selection.boundaryKind
  }

  function clearTransientUi(actionOptions: WorkflowSelectionActionOptions = {}): void {
    if (!actionOptions.preserveConnectionDraft) {
      options.clearConnectionDraft()
    }
    options.clearContextMenu()
    options.clearNodePicker()
  }

  function selectNode(nodeId: string, actionOptions: WorkflowSelectionActionOptions = {}): void {
    setSelection({ nodeId, edgeId: null, boundaryKind: null })
    clearTransientUi(actionOptions)
  }

  function handleNodeClick(nodeId: string, event?: MouseEvent): void {
    if (suppressNextNodeClick.value) {
      suppressNextNodeClick.value = false
      return
    }
    if (event?.ctrlKey) {
      const ids = new Set(selectedNodeIds.value)
      if (!ids.delete(nodeId)) ids.add(nodeId)
      selectNodes(ids, selectedGroupIds.value)
    } else selectNode(nodeId)
  }

  function selectNodes(ids: Iterable<string>, groupIds: Iterable<string> = []): void {
    setSelection({ nodeId: null, nodeIds: [...ids], groupIds: [...groupIds], edgeId: null, boundaryKind: null })
    clearTransientUi()
  }

  watch(() => options.graphNodes.value.map(options.readNodeId), ids => {
    const present = new Set(ids)
    if ([...selectedNodeIds.value].some(id => !present.has(id))) {
      selectedNodeIds.value = new Set([...selectedNodeIds.value].filter(id => present.has(id)))
    }
  })

  watch(() => [options.graphGroups?.value.map(group => [group.group_id, ...group.member_node_ids]), [...selectedNodeIds.value]], () => {
    setSelection(readSelection())
  })

  function suppressNodeClickOnce(): void {
    suppressNextNodeClick.value = true
    window.setTimeout(() => {
      suppressNextNodeClick.value = false
    }, 0)
  }

  function selectEdge(edgeId: string, actionOptions: WorkflowSelectionActionOptions = {}): void {
    setSelection({ nodeId: null, edgeId, boundaryKind: null })
    clearTransientUi(actionOptions)
  }

  function selectGraphLink(link: WorkflowGraphLinkView): void {
    if (link.linkKind === 'edge') {
      selectEdge(link.edgeId)
      return
    }
    selectApplicationBoundary(link.linkKind === 'template-input' ? 'entry' : 'result')
  }

  function isGraphLinkSelected(link: WorkflowGraphLinkView): boolean {
    if (link.linkKind === 'edge') return selectedEdgeId.value === link.edgeId
    if (link.linkKind === 'template-input') return selectedBoundaryKind.value === 'entry'
    return selectedBoundaryKind.value === 'result'
  }

  function selectApplicationBoundary(kind: WorkflowBoundaryKind, actionOptions: WorkflowSelectionActionOptions = {}): void {
    setSelection({ nodeId: null, edgeId: null, boundaryKind: kind })
    clearTransientUi(actionOptions)
  }

  function restoreSelectionAfterGraphRefresh(previousSelection: WorkflowSelectionState, fallbackNodeId: string | null): void {
    if (previousSelection.boundaryKind) {
      setSelection({ nodeId: null, edgeId: null, boundaryKind: previousSelection.boundaryKind })
      return
    }
    if (previousSelection.nodeIds?.length) {
      selectNodes(previousSelection.nodeIds, previousSelection.groupIds)
      return
    }
    const nextEdgeId = previousSelection.edgeId && graphEdgeById(previousSelection.edgeId)
      ? previousSelection.edgeId
      : null
    const nextNodeId = nextEdgeId
      ? null
      : previousSelection.nodeId && graphNodeById(previousSelection.nodeId)
        ? previousSelection.nodeId
        : fallbackNodeId
    setSelection({ nodeId: nextNodeId, edgeId: nextEdgeId, boundaryKind: null })
  }

  function graphNodeById(nodeId: string | null): NodeView | null {
    if (!nodeId) return null
    return nodesById.value.get(nodeId) ?? null
  }

  function graphEdgeById(edgeId: string | null): WorkflowGraphEdge | null {
    if (!edgeId) return null
    return options.graphEdges.value.find((edge) => edge.edge_id === edgeId) ?? null
  }

  return {
    selectedNodeId,
    selectedNodeIds,
    selectedGroupIds,
    selectNodes,
    selectedEdgeId,
    selectedBoundaryKind,
    selectedNode,
    selectedEdge,
    readSelection,
    setSelection,
    clearTransientUi,
    selectNode,
    handleNodeClick,
    suppressNodeClickOnce,
    selectEdge,
    selectGraphLink,
    isGraphLinkSelected,
    selectApplicationBoundary,
    restoreSelectionAfterGraphRefresh,
  }
}
