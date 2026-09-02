import { ref } from 'vue'
import { describe, expect, it } from 'vitest'

import type { WorkflowGraphGroup, WorkflowGraphNote } from '../types'
import { useWorkflowGraphNotes } from './useWorkflowGraphNotes'

function createGroup(): WorkflowGraphGroup {
  return {
    group_id: 'group-1',
    name: '说明组',
    enabled: true,
    rect: { x: 0, y: 0, width: 900, height: 700 },
    member_node_ids: [],
    member_note_ids: [],
    membership_policy: 'full-containment',
    color: '#667085',
    collapsed: false,
    locked: false,
    metadata: {},
  }
}

describe('useWorkflowGraphNotes', () => {
  it('创建、复制和删除说明时同步确定性的分组归属', () => {
    const group = createGroup()
    const graphNotes = ref<WorkflowGraphNote[]>([])
    const notes = useWorkflowGraphNotes({
      graphNotes,
      graphGroups: ref([group]),
      screenToWorld: (x, y) => ({ x, y }),
      clearOtherSelection: () => undefined,
    })

    const created = notes.createNoteAt(40, 60)
    expect(created).not.toBeNull()
    expect(group.member_note_ids).toEqual(['note-1'])

    const copied = notes.copyNote(created!.note_id)
    expect(copied).toMatchObject({ note_id: 'note-2', locked: false })
    expect(group.member_note_ids).toEqual(['note-1', 'note-2'])

    expect(notes.deleteNote(created!.note_id)).toBe(true)
    expect(graphNotes.value.map((note) => note.note_id)).toEqual(['note-2'])
    expect(group.member_note_ids).toEqual(['note-2'])
  })

  it('锁定后不启动拖动，解锁后按世界坐标移动', () => {
    const graphNotes = ref<WorkflowGraphNote[]>([])
    const notes = useWorkflowGraphNotes({
      graphNotes,
      graphGroups: ref([]),
      screenToWorld: (x, y) => ({ x, y }),
      clearOtherSelection: () => undefined,
    })
    const note = notes.createNoteAt(10, 20)!
    note.locked = true
    notes.updateTone(note, 'danger')
    expect(note.tone).toBe('neutral')
    notes.startDrag(new MouseEvent('mousedown', { button: 0, clientX: 10, clientY: 20 }), note)
    document.dispatchEvent(new MouseEvent('mousemove', { buttons: 1, clientX: 80, clientY: 90 }))
    expect(note.rect).toMatchObject({ x: 10, y: 20 })

    note.locked = false
    notes.cancelEdit(note.note_id)
    notes.startDrag(new MouseEvent('mousedown', { button: 0, clientX: 10, clientY: 20, cancelable: true }), note)
    document.dispatchEvent(new MouseEvent('mousemove', { buttons: 1, clientX: 50, clientY: 70 }))
    document.dispatchEvent(new MouseEvent('mouseup'))
    expect(note.rect).toMatchObject({ x: 50, y: 70 })
  })

  it('复制最大长度标题时仍满足公开契约', () => {
    const graphNotes = ref<WorkflowGraphNote[]>([])
    const notes = useWorkflowGraphNotes({
      graphNotes,
      graphGroups: ref([]),
      screenToWorld: (x, y) => ({ x, y }),
      clearOtherSelection: () => undefined,
    })
    const note = notes.createNoteAt(10, 20)!
    note.title = 'a'.repeat(128)

    const copied = notes.copyNote(note.note_id)!

    expect(copied.title).toHaveLength(128)
    expect(copied.title.endsWith(' 副本')).toBe(true)
  })
})
