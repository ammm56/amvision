import type { Ref } from 'vue'

export interface WorkflowEditorKeyboardOptions {
  selectedNodeId: Ref<string | null>
  selectedEdgeId: Ref<string | null>
  selectedNoteId: Ref<string | null>
  clearConnectionDraft: () => void
  clearContextMenu: () => void
  clearErrorMessage: () => void
  deleteSelectedNode: () => void
  deleteSelectedEdge: () => void
  deleteSelectedNote: () => void
}

export function useWorkflowEditorKeyboard(options: WorkflowEditorKeyboardOptions) {
  function handleKeydown(event: KeyboardEvent): void {
    if (isDeleteShortcut(event) && (options.selectedNodeId.value || options.selectedEdgeId.value || options.selectedNoteId.value)) {
      if (isEditableShortcutTarget(event.target)) return
      event.preventDefault()
      if (options.selectedNoteId.value) {
        options.deleteSelectedNote()
      } else if (options.selectedNodeId.value) {
        options.deleteSelectedNode()
      } else {
        options.deleteSelectedEdge()
      }
      return
    }
    if (event.key === 'Escape') {
      options.clearConnectionDraft()
      options.clearContextMenu()
      options.clearErrorMessage()
    }
  }

  return {
    handleKeydown,
  }
}

function isDeleteShortcut(event: KeyboardEvent): boolean {
  return event.key === 'Delete' || event.key === 'Backspace'
}

function isEditableShortcutTarget(target: EventTarget | null): boolean {
  return target instanceof HTMLInputElement
    || target instanceof HTMLTextAreaElement
    || target instanceof HTMLSelectElement
}
