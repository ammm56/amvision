import { computed, ref, type Ref } from 'vue'
import { cloneWorkflowJson } from '../documents/workflow-app-document'
import type { WorkflowGraphNode } from '../types'
import type { WorkflowGraphNodeView } from './useWorkflowGraphNodeViews'

export interface NodePastePosition { x: number; y: number }

export interface WorkflowNodeClipboardOptions {
  graphNodes: Ref<WorkflowGraphNodeView[]>
  isBusy: () => boolean
  commitParameters: (nodes: WorkflowGraphNodeView[]) => boolean
  createNodeId: (nodeTypeId: string) => string
  buildView: (node: WorkflowGraphNode) => WorkflowGraphNodeView
  readHeight: (node: WorkflowGraphNodeView) => number
  readPastePosition: (size: { width: number; height: number }) => NodePastePosition
  onCopied: () => void
  onPasted: (node: WorkflowGraphNodeView) => void
}

/** 当前编辑图内的单节点快照；不包含连线、预览状态或系统剪贴板。 */
export function useWorkflowNodeClipboard(options: WorkflowNodeClipboardOptions) {
  const snapshot = ref<{ node: WorkflowGraphNode; height: number } | null>(null)
  let previousPosition: NodePastePosition | null = null
  let pasteCount = 0
  const canPaste = computed(() => snapshot.value !== null)

  function clear(): void {
    snapshot.value = null
    previousPosition = null
    pasteCount = 0
  }

  function copy(nodeId: string | null): boolean {
    if (options.isBusy()) return false
    const source = options.graphNodes.value.find(view => view.node.node_id === nodeId)
    if (!source || !options.commitParameters([source])) return false
    const node = cloneWorkflowJson(source.node)
    node.ui_state = { ...node.ui_state, x: source.x, y: source.y, width: source.width }
    snapshot.value = { node, height: options.readHeight(source) }
    previousPosition = null
    pasteCount = 0
    options.onCopied()
    return true
  }

  function paste(position?: NodePastePosition): boolean {
    if (options.isBusy() || !snapshot.value) return false
    const node = cloneWorkflowJson(snapshot.value.node)
    const target = position ?? options.readPastePosition({ width: Number(node.ui_state.width), height: snapshot.value.height })
    if (!Number.isFinite(target.x) || !Number.isFinite(target.y)) return false
    const count = previousPosition?.x === target.x && previousPosition.y === target.y ? pasteCount : 0
    node.node_id = options.createNodeId(node.node_type_id)
    node.ui_state = { ...node.ui_state, x: Math.round(target.x + count * 32), y: Math.round(target.y + count * 32) }
    const view = options.buildView(node)
    options.graphNodes.value.push(view)
    previousPosition = { ...target }
    pasteCount = count + 1
    options.onPasted(view)
    return true
  }

  return { canPaste, copy, paste, clear }
}
