import { mount } from '@vue/test-utils'
import { defineComponent } from 'vue'
import { describe, expect, it } from 'vitest'
import { useWorkflowBoxSelection } from './useWorkflowBoxSelection'

describe('box selection', () => {
  it('只选完整包含且成员全部选中的组，取消恢复组选择', () => {
    let selected: string[] = [], groups: string[] = []
    let box!: ReturnType<typeof useWorkflowBoxSelection>
    const wrapper = mount(defineComponent({ setup() {
      box = useWorkflowBoxSelection({ candidates: () => [{ id: 'a', x: 10, y: 10, width: 10, height: 10 }],
        groups: () => [
          { id: 'full', x: 0, y: 0, width: 30, height: 30, memberIds: ['a'] },
          { id: 'partial', x: 0, y: 0, width: 100, height: 100, memberIds: ['a'] },
          { id: 'missing', x: 0, y: 0, width: 30, height: 30, memberIds: ['a', 'outside'] },
        ], readSelection: () => selected, readGroupSelection: () => groups,
        select: (ids, groupIds) => { selected = [...ids]; groups = [...groupIds] },
        screenToWorld: (x, y) => ({ x: x / 2, y: y / 2 }), blocked: () => false })
      return () => null
    } }))
    box.start(new MouseEvent('mousedown', { ctrlKey: true, clientX: 80, clientY: 80 }))
    document.dispatchEvent(new MouseEvent('mouseup', { clientX: -2, clientY: -2 }))
    expect(selected).toEqual(['a'])
    expect(groups).toEqual(['full'])
    box.start(new MouseEvent('mousedown', { ctrlKey: true }))
    window.dispatchEvent(new Event('blur'))
    expect(groups).toEqual(['full'])
    wrapper.unmount()
  })
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
