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
    member_note_ids: [],
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
      graphNotes: ref([]),
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

  it('左键释放事件丢失时根据 buttons 状态结束节点组拖动', () => {
    const group = createGroup()
    const groups = useWorkflowGraphGroups({
      graphGroups: ref([group]),
      graphNodes: ref([]),
      graphNotes: ref([]),
      screenToWorld: (clientX, clientY) => ({ x: clientX, y: clientY }),
      readNodeHeight: () => 0,
      setStatusMessage: () => undefined,
      setErrorMessage: () => undefined,
    })

    groups.startGroupDrag(new MouseEvent('mousedown', { button: 0, clientX: 10, clientY: 20, cancelable: true }), group)
    document.dispatchEvent(new MouseEvent('mousemove', { buttons: 1, clientX: 30, clientY: 50 }))
    expect(group.rect).toMatchObject({ x: 30, y: 50 })

    document.dispatchEvent(new MouseEvent('mousemove', { buttons: 0, clientX: 80, clientY: 100 }))
    document.dispatchEvent(new MouseEvent('mousemove', { buttons: 1, clientX: 120, clientY: 140 }))
    expect(group.rect).toMatchObject({ x: 30, y: 50 })
  })

  it('移动节点组时同步移动组内说明节点', () => {
    const group = createGroup()
    group.member_note_ids = ['note-1']
    const note = {
      note_id: 'note-1',
      title: '说明',
      content: '',
      content_format: 'markdown' as const,
      rect: { x: 40, y: 60, width: 320, height: 180 },
      tone: 'neutral' as const,
      collapsed: false,
      locked: false,
      metadata: {},
    }
    const groups = useWorkflowGraphGroups({
      graphGroups: ref([group]),
      graphNodes: ref([]),
      graphNotes: ref([note]),
      screenToWorld: (clientX, clientY) => ({ x: clientX, y: clientY }),
      readNodeHeight: () => 0,
      setStatusMessage: () => undefined,
      setErrorMessage: () => undefined,
    })

    groups.startGroupDrag(new MouseEvent('mousedown', { button: 0, clientX: 10, clientY: 20, cancelable: true }), group)
    document.dispatchEvent(new MouseEvent('mousemove', { buttons: 1, clientX: 40, clientY: 55 }))
    document.dispatchEvent(new MouseEvent('mouseup'))

    expect(group.rect).toMatchObject({ x: 40, y: 55 })
    expect(note.rect).toMatchObject({ x: 70, y: 95 })
    expect(group.member_note_ids).toEqual(['note-1'])
  })
})
