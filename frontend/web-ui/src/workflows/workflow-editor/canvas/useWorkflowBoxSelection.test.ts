import { mount } from '@vue/test-utils'
import { defineComponent } from 'vue'
import { describe, expect, it } from 'vitest'
import { useWorkflowBoxSelection } from './useWorkflowBoxSelection'

describe('box selection', () => {
  it('selects fully enclosed nodes in world coordinates, cancels and suppresses the trailing click', () => {
    let selected = ['old']
    let box!: ReturnType<typeof useWorkflowBoxSelection>
    const wrapper = mount(defineComponent({ setup() {
      box = useWorkflowBoxSelection({ candidates: () => [{ id: 'inside', x: 10, y: 10, width: 10, height: 10 }, { id: 'partial', x: 18, y: 18, width: 10, height: 10 }],
        readSelection: () => selected, select: ids => { selected = [...ids] }, screenToWorld: (x, y) => ({ x: x / 2, y: y / 2 }), blocked: () => false })
      return () => null
    } }))
    expect(box.start(new MouseEvent('mousedown', { ctrlKey: true, button: 0, clientX: 42, clientY: 42 }))).toBe(true)
    document.dispatchEvent(new MouseEvent('mouseup', { clientX: 18, clientY: 18 }))
    expect(selected).toEqual(['inside'])
    expect(box.consumeClick(new MouseEvent('click'))).toBe(true)
    expect(box.consumeClick(new MouseEvent('click'))).toBe(false)
    box.start(new MouseEvent('mousedown', { ctrlKey: true }))
    window.dispatchEvent(new Event('blur'))
    expect(selected).toEqual(['inside'])
    expect(box.rect.value).toBeNull()
    const input = document.createElement('input')
    input.addEventListener('mousedown', event => expect(box.start(event)).toBe(false))
    input.dispatchEvent(new MouseEvent('mousedown', { ctrlKey: true }))
    wrapper.unmount()
  })
})
