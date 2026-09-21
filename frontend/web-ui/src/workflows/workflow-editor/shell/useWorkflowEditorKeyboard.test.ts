import { ref } from 'vue'
import { describe, expect, it, vi } from 'vitest'
import { useWorkflowEditorKeyboard } from './useWorkflowEditorKeyboard'

describe('editor multi-selection shortcuts', () => {
  it('copies/deletes the set, respects text focus and busy state, and cancels marquee before clearing selection', () => {
    let busy = false
    const copy = vi.fn(() => true), paste = vi.fn(() => true), remove = vi.fn(), clear = vi.fn(), cancel = vi.fn(() => true)
    const keyboard = useWorkflowEditorKeyboard({ selectedNodeId: ref(null), selectedNodeIds: ref(new Set(['a', 'b'])), selectedEdgeId: ref(null), selectedNoteId: ref(null),
      copySelectedNode: copy, pasteNode: paste, deleteSelectedNode: remove, deleteSelectedEdge: vi.fn(), deleteSelectedNote: vi.fn(),
      clearConnectionDraft: vi.fn(), clearContextMenu: vi.fn(), clearErrorMessage: vi.fn(), clearSelection: clear, cancelBoxSelection: cancel, isBusy: () => busy })
    keyboard.handleKeydown(new KeyboardEvent('keydown', { key: 'c', ctrlKey: true }))
    keyboard.handleKeydown(new KeyboardEvent('keydown', { key: 'Delete' }))
    expect(copy).toHaveBeenCalledOnce()
    expect(remove).toHaveBeenCalledOnce()
    const input = document.createElement('textarea')
    input.addEventListener('keydown', keyboard.handleKeydown)
    input.dispatchEvent(new KeyboardEvent('keydown', { key: 'v', ctrlKey: true }))
    expect(paste).not.toHaveBeenCalled()
    busy = true
    keyboard.handleKeydown(new KeyboardEvent('keydown', { key: 'v', ctrlKey: true }))
    expect(paste).not.toHaveBeenCalled()
    keyboard.handleKeydown(new KeyboardEvent('keydown', { key: 'Escape' }))
    expect(clear).not.toHaveBeenCalled()
    cancel.mockReturnValue(false)
    keyboard.handleKeydown(new KeyboardEvent('keydown', { key: 'Escape' }))
    expect(clear).toHaveBeenCalledOnce()
  })
})
