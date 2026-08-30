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
    membership_policy: 'full-containment',
    color: '#22b8cf',
    collapsed: false,
    locked: false,
    metadata: {},
  }
}

describe('useWorkflowGraphDeletion', () => {
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
