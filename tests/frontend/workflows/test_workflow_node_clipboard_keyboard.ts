import { ref } from 'vue'
import { describe, expect, it, vi } from 'vitest'
import { useWorkflowEditorKeyboard } from '@/workflows/workflow-editor/shell/useWorkflowEditorKeyboard'

function setup() {
  const copy = vi.fn(() => true), paste = vi.fn(() => true), remove = vi.fn()
  const selectedNodeId = ref<string | null>('node')
  const keyboard = useWorkflowEditorKeyboard({ selectedNodeId, selectedEdgeId: ref(null), selectedNoteId: ref(null),
    clearConnectionDraft: vi.fn(), clearContextMenu: vi.fn(), clearErrorMessage: vi.fn(),
    deleteSelectedNode: remove, deleteSelectedEdge: vi.fn(), deleteSelectedNote: vi.fn(), copySelectedNode: copy, pasteNode: paste })
  function press(key: string, target: Element = document.createElement('div'), extra = {}) {
    const event = new KeyboardEvent('keydown', { key, ctrlKey: true, cancelable: true, ...extra })
    Object.defineProperty(event, 'target', { value: target })
    keyboard.handleKeydown(event)
    return event
  }
  return { copy, paste, remove, selectedNodeId, press }
}

describe('节点复制粘贴快捷键', () => {
  it('只在命令生效时拦截，删除行为保留', () => {
    const { copy, paste, remove, selectedNodeId, press } = setup()
    expect(press('c').defaultPrevented).toBe(true)
    expect(press('V').defaultPrevented).toBe(true)
    expect(copy).toHaveBeenCalledOnce()
    expect(paste).toHaveBeenCalledOnce()
    selectedNodeId.value = null
    expect(press('c').defaultPrevented).toBe(false)
    paste.mockReturnValue(false)
    expect(press('v').defaultPrevented).toBe(false)
    selectedNodeId.value = 'node'
    press('Delete', undefined, { ctrlKey: false })
    expect(remove).toHaveBeenCalledOnce()
  })
  it.each(['input', 'textarea', 'select', '[contenteditable]', '[role=dialog]', '[role=menu]', '[role=listbox]', '[role=combobox]'])('保留 %s 内原生操作', selector => {
    const { copy, paste, press } = setup()
    const container = document.createElement(selector.startsWith('[') ? 'div' : selector)
    if (selector.startsWith('[')) {
      const [key, value = 'true'] = selector.slice(1, -1).split('=')
      container.setAttribute(key!, value)
    }
    const child = selector.startsWith('[') ? container.appendChild(document.createElement('span')) : container
    expect(press('c', child).defaultPrevented).toBe(false)
    expect(press('v', child).defaultPrevented).toBe(false)
    expect(copy).not.toHaveBeenCalled()
    expect(paste).not.toHaveBeenCalled()
  })
  it('忽略输入法、长按和其他快捷键组合', () => {
    const { paste, press } = setup()
    for (const extra of [{ repeat: true }, { isComposing: true }, { altKey: true }, { shiftKey: true }, { ctrlKey: false }]) press('v', undefined, extra)
    expect(paste).not.toHaveBeenCalled()
  })
})
