import { computed, shallowRef, type Ref } from 'vue'
import { cloneWorkflowJson } from '../documents/workflow-app-document'
import { portsCanConnect } from '../connections/useWorkflowConnectionRules'
import type { WorkflowGraphEdge, WorkflowGraphNode, WorkflowGraphGroup } from '../types'
import type { WorkflowGraphNodeView } from './useWorkflowGraphNodeViews'

export interface NodePastePosition { x: number; y: number }
export interface WorkflowNodeClipboardOptions {
  graphNodes: Ref<WorkflowGraphNodeView[]>
  graphEdges: Ref<WorkflowGraphEdge[]>
  graphGroups?: Ref<WorkflowGraphGroup[]>
  isBusy: () => boolean
  commitParameters: (nodes: WorkflowGraphNodeView[]) => boolean
  createNodeId: (nodeTypeId: string) => string
  buildView: (node: WorkflowGraphNode) => WorkflowGraphNodeView
  readHeight: (node: WorkflowGraphNodeView) => number
  readPastePosition: (size: { width: number; height: number }) => NodePastePosition
  onCopied: () => void
  onPasted: (nodes: WorkflowGraphNodeView[], groups: WorkflowGraphGroup[]) => void
  onError: () => void
}
interface Fragment {
  nodes: WorkflowGraphNode[]
  edges: WorkflowGraphEdge[]
  groups: WorkflowGraphGroup[]
  x: number; y: number; width: number; height: number
}

/** 当前文档内的配置快照，不包含预览数据、应用公开绑定或系统剪贴板。 */
export function useWorkflowNodeClipboard(options: WorkflowNodeClipboardOptions) {
  const snapshot = shallowRef<Fragment | null>(null)
  let previousPosition: NodePastePosition | null = null
  let pasteCount = 0
  const canPaste = computed(() => snapshot.value !== null)
  function clear(): void { snapshot.value = null; previousPosition = null; pasteCount = 0 }

  function copy(nodeIds: readonly string[] | ReadonlySet<string>, groupIds: Iterable<string> = []): boolean {
    if (options.isBusy()) return false
    const ids = new Set(nodeIds)
    const sources = options.graphNodes.value.filter(view => ids.has(view.node.node_id))
    if (!sources.length || sources.length !== ids.size || !options.commitParameters(sources)) return false
    try {
      const requestedGroups = new Set(groupIds)
      const groups = (options.graphGroups?.value ?? []).filter(group => requestedGroups.has(group.group_id)
        && group.member_node_ids.length > 0 && group.member_node_ids.every(id => ids.has(id)))
      const x = Math.min(...sources.map(n => n.x), ...groups.map(g => g.rect.x)), y = Math.min(...sources.map(n => n.y), ...groups.map(g => g.rect.y))
      const next: Fragment = {
        nodes: sources.map(source => ({ ...cloneWorkflowJson(source.node), ui_state: { ...cloneWorkflowJson(source.node.ui_state), x: source.x, y: source.y, width: source.width } })),
        edges: cloneWorkflowJson(options.graphEdges.value.filter(edge => ids.has(edge.source_node_id) && ids.has(edge.target_node_id))),
        // 便签不属于节点片段，不能留下指向原便签的引用。
        groups: groups.map(group => ({ ...cloneWorkflowJson(group), member_note_ids: [] })),
        x, y,
        width: Math.max(...sources.map(n => n.x + n.width), ...groups.map(g => g.rect.x + g.rect.width)) - x,
        height: Math.max(...sources.map(n => n.y + options.readHeight(n)), ...groups.map(g => g.rect.y + g.rect.height)) - y,
      }
      snapshot.value = next
      previousPosition = null
      pasteCount = 0
      options.onCopied()
      return true
    } catch { options.onError(); return false }
  }

  function paste(position?: NodePastePosition): boolean {
    if (options.isBusy() || !snapshot.value) return false
    // 整批构造完成前不能修改图，包含同类型节点的批次也必须预留唯一 ID。
    let views: WorkflowGraphNodeView[]
    let edges: WorkflowGraphEdge[]
    let groups: WorkflowGraphGroup[]
    let target: NodePastePosition
    let count: number
    try {
      const fragment = cloneWorkflowJson(snapshot.value)
      target = position ?? options.readPastePosition(fragment)
      if (!Number.isFinite(target.x) || !Number.isFinite(target.y)) return false
      count = previousPosition?.x === target.x && previousPosition.y === target.y ? pasteCount : 0
      const used = new Set(options.graphNodes.value.map(n => n.node.node_id))
      const ids = new Map<string, string>()
      for (const node of fragment.nodes) {
        const base = options.createNodeId(node.node_type_id)
        let id = base, suffix = 2
        while (used.has(id)) id = `${base}_${suffix++}`
        used.add(id)
        ids.set(node.node_id, id)
      }
      const dx = Math.round(target.x + count * 32 - fragment.x)
      const dy = Math.round(target.y + count * 32 - fragment.y)
      const groupIds = new Set(options.graphGroups?.value.map(g => g.group_id) ?? [])
      groups = fragment.groups.map(group => {
        const base = `${group.group_id}_copy`
        let id = base, suffix = 2
        while (groupIds.has(id)) id = `${base}_${suffix++}`
        groupIds.add(id)
        return { ...group, group_id: id, rect: { ...group.rect, x: group.rect.x + dx, y: group.rect.y + dy }, member_node_ids: group.member_node_ids.map(id => ids.get(id)!) }
      })
      views = fragment.nodes.map(node => {
        node.node_id = ids.get(node.node_id)!
        node.ui_state = { ...node.ui_state, x: Number(node.ui_state.x) + dx, y: Number(node.ui_state.y) + dy }
        const view = options.buildView(node)
        if (!view.definition) throw new Error('missing node definition')
        return view
      })
      const byId = new Map(views.map(n => [n.node.node_id, n]))
      const edgeIds = new Set(options.graphEdges.value.map(e => e.edge_id))
      const inputs = new Map<string, number>()
      edges = fragment.edges.map(edge => {
        edge.source_node_id = ids.get(edge.source_node_id)!
        edge.target_node_id = ids.get(edge.target_node_id)!
        const source = byId.get(edge.source_node_id)?.outputs.find(p => p.name === edge.source_port)
        const targetPort = byId.get(edge.target_node_id)?.inputs.find(p => p.name === edge.target_port)
        if (!source || !targetPort || !portsCanConnect(source, targetPort) || edge.source_node_id === edge.target_node_id) throw new Error('invalid fragment edge')
        const inputKey = JSON.stringify([edge.target_node_id, edge.target_port])
        const incoming = (inputs.get(inputKey) ?? 0) + 1
        if (!targetPort.multiple && incoming > 1) throw new Error('duplicate input')
        inputs.set(inputKey, incoming)
        const base = `${edge.edge_id}_copy`
        let id = base, suffix = 2
        while (edgeIds.has(id)) id = `${base}_${suffix++}`
        edgeIds.add(id)
        return { ...edge, edge_id: id }
      })
    } catch { options.onError(); return false }
    options.graphNodes.value.push(...views)
    options.graphEdges.value.push(...edges)
    options.graphGroups?.value.push(...groups)
    previousPosition = { ...target }
    pasteCount = count + 1
    options.onPasted(views, groups)
    return true
  }
  return { canPaste, copy, paste, clear }
}
