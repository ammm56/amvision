import type { Ref } from 'vue'

export interface WorkflowEditorKeyboardOptions {
  selectedNodeIds?: Ref<Set<string>>
  clearSelection?: () => void
  cancelBoxSelection?: () => boolean
  isBusy?: () => boolean
  selectedNodeId: Ref<string | null>
  selectedEdgeId: Ref<string | null>
  selectedNoteId: Ref<string | null>
  clearConnectionDraft: () => void
  clearContextMenu: () => void
  clearErrorMessage: () => void
  deleteSelectedNode: () => void
  deleteSelectedEdge: () => void
  deleteSelectedNote: () => void
  copySelectedNode?: () => boolean
  pasteNode?: () => boolean
}

export function useWorkflowEditorKeyboard(options: WorkflowEditorKeyboardOptions) {
  function handleKeydown(event: KeyboardEvent): void {
    if (event.defaultPrevented || (event.target instanceof Element && event.target.closest('[role="dialog"], [role="menu"]'))) return
    if (event.isComposing) return
    const key = event.key.toLowerCase()
    const hasNodes = Boolean(options.selectedNodeIds?.value.size || options.selectedNodeId.value)
    if (event.ctrlKey && !event.altKey && !event.shiftKey && (key === 'c' || key === 'v')) {
      if (event.repeat || options.isBusy?.() || isEditableShortcutTarget(event.target)) return
      const handled = key === 'c'
        ? Boolean(hasNodes && !options.selectedNoteId.value && options.copySelectedNode?.())
        : options.pasteNode?.()
      if (handled) event.preventDefault()
      return
    }
    if (isDeleteShortcut(event) && (hasNodes || options.selectedEdgeId.value || options.selectedNoteId.value)) {
      if (options.isBusy?.() || isEditableShortcutTarget(event.target)) return
      event.preventDefault()
      if (options.selectedNoteId.value) {
        options.deleteSelectedNote()
      } else if (hasNodes) {
        options.deleteSelectedNode()
      } else {
        options.deleteSelectedEdge()
      }
      return
    }
    if (event.key === 'Escape') {
      if (isEditableShortcutTarget(event.target)) return
      if (options.cancelBoxSelection?.()) { event.preventDefault(); return }
      options.clearSelection?.()
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
  return target instanceof Element && Boolean(target.closest('input, textarea, select, [contenteditable]:not([contenteditable="false"]), [role="textbox"], [role="combobox"], [role="listbox"]'))
}
