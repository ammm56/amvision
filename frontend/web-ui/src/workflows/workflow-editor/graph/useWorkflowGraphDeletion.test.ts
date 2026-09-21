import { ref } from 'vue'
import { describe, expect, it } from 'vitest'

import type { WorkflowGraphGroup } from '../types'
import { useWorkflowGraphDeletion } from './useWorkflowGraphDeletion'

function createGroup(memberNodeIds: string[]): WorkflowGraphGroup {
  return {
    group_id: 'group-1',
    name: '检测流程',
    enabled: true,
    rect: { x: 0, y: 0, width: 640, height: 480 },
    member_node_ids: memberNodeIds,
    member_note_ids: [],
    membership_policy: 'full-containment',
    color: '#22b8cf',
    collapsed: false,
    locked: false,
    metadata: {},
  }
}

describe('useWorkflowGraphDeletion', () => {
  it('删除明确选择的完整组片段，同时保留未选组框', () => {
    const graphNodes = ref(['a', 'b'].map(node_id => ({ node: { node_id } })))
    const graphGroups = ref([createGroup(['a']), { ...createGroup(['b']), group_id: 'keep' }])
    const deletion = useWorkflowGraphDeletion({ graphNodes, graphGroups, graphEdges: ref([]), templateInputs: ref([]), templateOutputs: ref([]), applicationBindingsDraft: ref([]),
      removePreviewInputStates: () => {}, setSelection: () => {}, clearTransientUi: () => {}, setStatusMessage: () => {} })
    deletion.deleteGraphNodes(['a', 'b'], ['group-1'])
    expect(graphGroups.value.map(g => g.group_id)).toEqual(['keep'])
    expect(graphGroups.value[0]!.member_node_ids).toEqual([])
  })
  it('批量清理内部及外部连线、公开绑定和组引用', () => {
    const graphNodes = ref(['a', 'b', 'c'].map(node_id => ({ node: { node_id } })))
    const graphEdges = ref(['a', 'b'].map((id, i) => ({ edge_id: id, source_node_id: id, target_node_id: i ? 'c' : 'b', source_port: 'out', target_port: 'in', metadata: {} })))
    const templateInputs = ref([{ input_id: 'input', target_node_id: 'a' }] as import('../types').WorkflowGraphInput[])
    const templateOutputs = ref([{ output_id: 'output', source_node_id: 'b' }] as import('../types').WorkflowGraphOutput[])
    const applicationBindingsDraft = ref([{ binding_id: 'binding', template_port_id: 'output' }] as import('../types').FlowApplicationBinding[])
    const graphGroups = ref([createGroup(['a', 'b', 'c'])])
    let removed = new Set<string>()
    const deletion = useWorkflowGraphDeletion({ graphNodes, graphEdges, graphGroups, templateInputs, templateOutputs, applicationBindingsDraft,
      removePreviewInputStates: ids => { removed = ids }, setSelection: () => {}, clearTransientUi: () => {}, setStatusMessage: () => {} })
    expect(deletion.deleteGraphNodes(['a', 'b'])).toBe(true)
    expect(graphNodes.value.map(n => n.node.node_id)).toEqual(['c'])
    expect(graphEdges.value).toEqual([])
    expect(templateInputs.value).toEqual([])
    expect(templateOutputs.value).toEqual([])
    expect(applicationBindingsDraft.value).toEqual([])
    expect([...removed]).toEqual(['binding'])
    expect(graphGroups.value[0]!.member_node_ids).toEqual(['c'])
  })
  it('删除节点时同步清理节点组引用', () => {
    const graphGroups = ref([createGroup(['node-1', 'node-2'])])
    const graphNodes = ref([
      { node: { node_id: 'node-1' } },
      { node: { node_id: 'node-2' } },
    ])
    const deletion = useWorkflowGraphDeletion({
      graphNodes,
      graphEdges: ref([]),
      graphGroups,
      templateInputs: ref([]),
      templateOutputs: ref([]),
      applicationBindingsDraft: ref([]),
      removePreviewInputStates: () => undefined,
      setSelection: () => undefined,
      clearTransientUi: () => undefined,
      setStatusMessage: () => undefined,
    })

    expect(deletion.deleteGraphNode('node-1')).toBe(true)
    expect(graphNodes.value.map((node) => node.node.node_id)).toEqual(['node-2'])
    expect(graphGroups.value[0]?.member_node_ids).toEqual(['node-2'])
  })
})
