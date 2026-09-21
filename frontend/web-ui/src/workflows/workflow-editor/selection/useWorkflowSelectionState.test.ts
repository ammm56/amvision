import { nextTick, ref } from 'vue'
import { describe, expect, it, vi } from 'vitest'
import { useWorkflowSelectionState } from './useWorkflowSelectionState'

describe('workflow multi selection', () => {
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
