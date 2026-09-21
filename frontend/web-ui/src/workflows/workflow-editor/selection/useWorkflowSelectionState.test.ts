import { nextTick, ref } from 'vue'
import { describe, expect, it, vi } from 'vitest'
import { useWorkflowSelectionState } from './useWorkflowSelectionState'
import type { WorkflowGraphGroup } from '../types'

describe('workflow multi selection', () => {
  it('同步恢复组选择，取消成员、删除组或选择连线会清理失效组选择', async () => {
    const graphGroups = ref([{ group_id: 'g', member_node_ids: ['a', 'b'] }] as WorkflowGraphGroup[])
    const state = useWorkflowSelectionState({ graphNodes: ref([{ id: 'a' }, { id: 'b' }]), graphGroups, graphEdges: ref([]), readNodeId: n => n.id,
      clearConnectionDraft: vi.fn(), clearContextMenu: vi.fn(), clearNodePicker: vi.fn() })
    state.selectNodes(['a', 'b'], ['g'])
    const saved = state.readSelection()
    state.handleNodeClick('a', new MouseEvent('click', { ctrlKey: true }))
    expect(state.selectedGroupIds.value.size).toBe(0)
    state.restoreSelectionAfterGraphRefresh(saved, null)
    expect([...state.selectedGroupIds.value]).toEqual(['g'])
    state.selectEdge('e')
    expect(state.selectedGroupIds.value.size).toBe(0)
    state.restoreSelectionAfterGraphRefresh(saved, null)
    graphGroups.value = []
    await nextTick()
    expect(state.selectedGroupIds.value.size).toBe(0)
  })
  it('keeps a single source for selection, restores surviving IDs and excludes edge selection', async () => {
    const graphNodes = ref([{ id: 'a' }, { id: 'b' }])
    const state = useWorkflowSelectionState({ graphNodes, graphEdges: ref([]), readNodeId: n => n.id,
      clearConnectionDraft: vi.fn(), clearContextMenu: vi.fn(), clearNodePicker: vi.fn() })
    state.selectNode('a')
    state.handleNodeClick('b', new MouseEvent('click', { ctrlKey: true }))
    expect([...state.selectedNodeIds.value]).toEqual(['a', 'b'])
    expect(state.selectedNode.value).toBeNull()
    const saved = state.readSelection()
    state.selectEdge('e')
    expect(state.selectedNodeIds.value.size).toBe(0)
    state.restoreSelectionAfterGraphRefresh(saved, null)
    expect(state.selectedNodeIds.value.size).toBe(2)
    graphNodes.value = [{ id: 'b' }]
    await nextTick()
    expect(state.selectedNodeId.value).toBe('b')
    state.handleNodeClick('b', new MouseEvent('click', { ctrlKey: true }))
    expect(state.selectedNodeIds.value.size).toBe(0)
  })
})
