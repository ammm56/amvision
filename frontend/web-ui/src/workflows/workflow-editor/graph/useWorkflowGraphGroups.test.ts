import { ref } from 'vue'
import { describe, expect, it } from 'vitest'

import type { WorkflowGraphGroup } from '../types'
import { useWorkflowGraphGroups } from './useWorkflowGraphGroups'

function createGroup(): WorkflowGraphGroup {
  return {
    group_id: 'group-1',
    name: '检测流程',
    enabled: true,
    rect: { x: 10, y: 20, width: 640, height: 480 },
    member_node_ids: [],
    membership_policy: 'full-containment',
    color: '#22b8cf',
    collapsed: false,
    locked: false,
    metadata: {},
  }
}

describe('useWorkflowGraphGroups', () => {
  it('toggles the persistent group lock state and reports its interaction mode', () => {
    const group = createGroup()
    const graphGroups = ref([group])
    const statusMessages: Array<string | null> = []
    const groups = useWorkflowGraphGroups({
      graphGroups,
      graphNodes: ref([]),
      screenToWorld: (clientX, clientY) => ({ x: clientX, y: clientY }),
      readNodeHeight: () => 0,
      setStatusMessage: (message) => statusMessages.push(message),
      setErrorMessage: () => undefined,
    })

    groups.toggleGroupLocked(group)

    expect(group.locked).toBe(true)
    expect(groups.selectedGroupId.value).toBe(group.group_id)
    expect(statusMessages.at(-1)).toContain('组区域可用于拖动画布')

    groups.toggleGroupLocked(group)

    expect(group.locked).toBe(false)
    expect(statusMessages.at(-1)).toContain('可移动和调整大小')
  })
})
