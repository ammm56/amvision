import { ref, type Ref } from 'vue'

import type { WorkflowGraphGroup, WorkflowGraphNote, WorkflowGraphNoteRect } from '../types'
import { isPrimaryMouseButtonPressed } from '../canvas/workflowMouseDrag'

interface PointerPosition {
  x: number
  y: number
}

interface NoteDragState {
  noteId: string
  start: PointerPosition
  initialRect: WorkflowGraphNoteRect
}

interface NoteResizeState {
  noteId: string
  start: PointerPosition
  initialRect: WorkflowGraphNoteRect
}

export interface WorkflowGraphNotesOptions {
  graphNotes: Ref<WorkflowGraphNote[]>
  graphGroups: Ref<WorkflowGraphGroup[]>
  screenToWorld: (clientX: number, clientY: number) => PointerPosition
  clearOtherSelection: () => void
}

const maximumNoteCount = 128
const minimumNoteWidth = 220
const minimumNoteHeight = 120
const maximumNoteWidth = 1600
const maximumNoteHeight = 1200

export function useWorkflowGraphNotes(options: WorkflowGraphNotesOptions) {
  const selectedNoteId = ref<string | null>(null)
  const editingNoteId = ref<string | null>(null)
  const dragState = ref<NoteDragState | null>(null)
  const resizeState = ref<NoteResizeState | null>(null)

  function createNoteAt(x: number, y: number): WorkflowGraphNote | null {
    if (options.graphNotes.value.length >= maximumNoteCount) return null
    const note: WorkflowGraphNote = {
      note_id: createUniqueNoteId(),
      title: '说明',
      content: '双击编辑 Markdown 说明。',
      content_format: 'markdown',
      rect: { x: Math.round(x), y: Math.round(y), width: 360, height: 240 },
      tone: 'neutral',
      collapsed: false,
      locked: false,
      metadata: {},
    }
    options.graphNotes.value = [...options.graphNotes.value, note]
    selectNote(note.note_id)
    editingNoteId.value = note.note_id
    syncNoteMembership(note.note_id)
    return note
  }

  function selectNote(noteId: string): void {
    selectedNoteId.value = noteId
    options.clearOtherSelection()
  }

  function clearNoteSelection(): void {
    selectedNoteId.value = null
    editingNoteId.value = null
  }

  function beginEdit(noteId: string): void {
    const note = findNote(noteId)
    if (!note || note.locked) return
    selectNote(noteId)
    editingNoteId.value = noteId
  }

  function finishEdit(noteId: string, title: string, content: string): void {
    const note = findNote(noteId)
    if (!note || note.locked) return
    note.title = title.trim() || '说明'
    note.content = content
    editingNoteId.value = null
  }

  function cancelEdit(noteId: string): void {
    if (editingNoteId.value === noteId) editingNoteId.value = null
  }

  function toggleCollapsed(note: WorkflowGraphNote): void {
    note.collapsed = !note.collapsed
    selectNote(note.note_id)
  }

  function toggleLocked(note: WorkflowGraphNote): void {
    note.locked = !note.locked
    if (note.locked && editingNoteId.value === note.note_id) editingNoteId.value = null
    selectNote(note.note_id)
  }

  function updateTone(note: WorkflowGraphNote, tone: WorkflowGraphNote['tone']): void {
    if (note.locked) return
    note.tone = tone
    selectNote(note.note_id)
  }

  function copyNote(noteId: string): WorkflowGraphNote | null {
    const source = findNote(noteId)
    if (!source || options.graphNotes.value.length >= maximumNoteCount) return null
    const copyTitleSuffix = ' 副本'
    const copy: WorkflowGraphNote = {
      ...source,
      note_id: createUniqueNoteId(),
      title: `${source.title.slice(0, 128 - copyTitleSuffix.length)}${copyTitleSuffix}`,
      rect: { ...source.rect, x: source.rect.x + 28, y: source.rect.y + 28 },
      locked: false,
      metadata: { ...source.metadata },
    }
    options.graphNotes.value = [...options.graphNotes.value, copy]
    selectNote(copy.note_id)
    syncNoteMembership(copy.note_id)
    return copy
  }

  function deleteNote(noteId: string): boolean {
    if (!findNote(noteId)) return false
    options.graphNotes.value = options.graphNotes.value.filter((note) => note.note_id !== noteId)
    for (const group of options.graphGroups.value) {
      group.member_note_ids = group.member_note_ids.filter((id) => id !== noteId)
    }
    if (selectedNoteId.value === noteId) selectedNoteId.value = null
    if (editingNoteId.value === noteId) editingNoteId.value = null
    stopDrag()
    stopResize()
    return true
  }

  function startDrag(event: MouseEvent, note: WorkflowGraphNote): void {
    if (event.button !== 0 || note.locked || editingNoteId.value === note.note_id) return
    selectNote(note.note_id)
    dragState.value = {
      noteId: note.note_id,
      start: options.screenToWorld(event.clientX, event.clientY),
      initialRect: { ...note.rect },
    }
    event.preventDefault()
    document.addEventListener('mousemove', moveDrag)
    document.addEventListener('mouseup', stopDrag)
    window.addEventListener('blur', stopDrag)
  }

  function moveDrag(event: MouseEvent): void {
    const state = dragState.value
    if (!state) return
    if (!isPrimaryMouseButtonPressed(event)) {
      stopDrag()
      return
    }
    const note = findNote(state.noteId)
    if (!note) return stopDrag()
    const pointer = options.screenToWorld(event.clientX, event.clientY)
    note.rect.x = Math.round(state.initialRect.x + pointer.x - state.start.x)
    note.rect.y = Math.round(state.initialRect.y + pointer.y - state.start.y)
  }

  function stopDrag(): void {
    const noteId = dragState.value?.noteId ?? null
    dragState.value = null
    document.removeEventListener('mousemove', moveDrag)
    document.removeEventListener('mouseup', stopDrag)
    window.removeEventListener('blur', stopDrag)
    if (noteId) syncNoteMembership(noteId)
  }

  function startResize(event: MouseEvent, note: WorkflowGraphNote): void {
    if (event.button !== 0 || note.locked || note.collapsed) return
    selectNote(note.note_id)
    resizeState.value = {
      noteId: note.note_id,
      start: options.screenToWorld(event.clientX, event.clientY),
      initialRect: { ...note.rect },
    }
    event.preventDefault()
    event.stopPropagation()
    document.addEventListener('mousemove', moveResize)
    document.addEventListener('mouseup', stopResize)
    window.addEventListener('blur', stopResize)
  }

  function moveResize(event: MouseEvent): void {
    const state = resizeState.value
    if (!state) return
    if (!isPrimaryMouseButtonPressed(event)) {
      stopResize()
      return
    }
    const note = findNote(state.noteId)
    if (!note) return stopResize()
    const pointer = options.screenToWorld(event.clientX, event.clientY)
    note.rect.width = clamp(Math.round(state.initialRect.width + pointer.x - state.start.x), minimumNoteWidth, maximumNoteWidth)
    note.rect.height = clamp(Math.round(state.initialRect.height + pointer.y - state.start.y), minimumNoteHeight, maximumNoteHeight)
  }

  function stopResize(): void {
    const noteId = resizeState.value?.noteId ?? null
    resizeState.value = null
    document.removeEventListener('mousemove', moveResize)
    document.removeEventListener('mouseup', stopResize)
    window.removeEventListener('blur', stopResize)
    if (noteId) syncNoteMembership(noteId)
  }

  function syncAllNoteMemberships(preferredNoteId: string | null = null): void {
    const orderedGroups = [...options.graphGroups.value].sort((left, right) => {
      const leftHasPreferred = preferredNoteId ? left.member_note_ids.includes(preferredNoteId) : false
      const rightHasPreferred = preferredNoteId ? right.member_note_ids.includes(preferredNoteId) : false
      if (leftHasPreferred !== rightHasPreferred) return leftHasPreferred ? -1 : 1
      return left.rect.width * left.rect.height - right.rect.width * right.rect.height
    })
    const assignedNoteIds = new Set<string>()
    for (const group of orderedGroups) {
      group.member_note_ids = options.graphNotes.value
        .filter((note) => !assignedNoteIds.has(note.note_id) && isRectInside(note.rect, group.rect))
        .map((note) => note.note_id)
      group.member_note_ids.forEach((id) => assignedNoteIds.add(id))
    }
  }

  function syncNoteMembership(noteId: string): void {
    syncAllNoteMemberships(noteId)
  }

  function findNote(noteId: string): WorkflowGraphNote | null {
    return options.graphNotes.value.find((note) => note.note_id === noteId) ?? null
  }

  function createUniqueNoteId(): string {
    const ids = new Set(options.graphNotes.value.map((note) => note.note_id))
    let index = options.graphNotes.value.length + 1
    while (ids.has(`note-${index}`)) index += 1
    return `note-${index}`
  }

  return {
    selectedNoteId,
    editingNoteId,
    createNoteAt,
    selectNote,
    clearNoteSelection,
    beginEdit,
    finishEdit,
    cancelEdit,
    toggleCollapsed,
    toggleLocked,
    updateTone,
    copyNote,
    deleteNote,
    startDrag,
    startResize,
    syncAllNoteMemberships,
  }
}

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.min(maximum, Math.max(minimum, value))
}

function isRectInside(rect: WorkflowGraphNoteRect, container: WorkflowGraphNoteRect): boolean {
  return rect.x >= container.x
    && rect.y >= container.y
    && rect.x + rect.width <= container.x + container.width
    && rect.y + rect.height <= container.y + container.height
}
