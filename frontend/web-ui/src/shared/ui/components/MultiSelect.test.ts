import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

import { i18n } from '@/platform/i18n'
import MultiSelect from './MultiSelect.vue'

describe('MultiSelect', () => {
  it('teleports its menu outside scrollable containers and keeps it aligned with the trigger', async () => {
    const wrapper = mount(MultiSelect, {
      attachTo: document.body,
      props: {
        modelValue: ['workflows:read'],
        options: [
          { label: '所有权限', value: '*', description: '*' },
          { label: 'workflows:read', value: 'workflows:read' },
        ],
      },
      global: { plugins: [i18n] },
    })
    vi.spyOn(wrapper.element, 'getBoundingClientRect').mockReturnValue({
      top: 100,
      right: 260,
      bottom: 140,
      left: 20,
      width: 240,
      height: 40,
      x: 20,
      y: 100,
      toJSON: () => ({}),
    })

    await wrapper.get('.ui-multi-select__button').trigger('click')
    await flushPromises()

    const menu = document.body.querySelector<HTMLElement>('.ui-multi-select__menu')
    expect(menu).not.toBeNull()
    expect(wrapper.element.contains(menu)).toBe(false)
    expect(menu?.style.position).toBe('')
    expect(menu?.style.top).toBe('144px')
    expect(menu?.style.left).toBe('20px')
    expect(menu?.style.width).toBe('240px')

    wrapper.unmount()
  })

  it('keeps a teleported menu inside a scrollable dialog and closes it when the trigger scrolls away', async () => {
    const dialogContent = document.createElement('div')
    dialogContent.className = 'confirm-dialog__content'
    document.body.appendChild(dialogContent)
    vi.spyOn(dialogContent, 'getBoundingClientRect').mockReturnValue({
      top: 100,
      right: 700,
      bottom: 500,
      left: 100,
      width: 600,
      height: 400,
      x: 100,
      y: 100,
      toJSON: () => ({}),
    })
    const wrapper = mount(MultiSelect, {
      attachTo: dialogContent,
      props: {
        modelValue: [],
        options: [{ label: '默认项目', value: 'project-1' }],
      },
      global: { plugins: [i18n] },
    })
    const triggerRect = vi.spyOn(wrapper.element, 'getBoundingClientRect').mockReturnValue({
      top: 420,
      right: 680,
      bottom: 454,
      left: 120,
      width: 560,
      height: 34,
      x: 120,
      y: 420,
      toJSON: () => ({}),
    })

    await wrapper.get('.ui-multi-select__button').trigger('click')
    await flushPromises()

    const menu = document.body.querySelector<HTMLElement>('.ui-multi-select__menu')
    expect(menu?.style.top).toBe('auto')
    expect(Number.parseFloat(menu?.style.maxHeight ?? '0')).toBeLessThanOrEqual(220)
    expect(Number.parseFloat(menu?.style.left ?? '0')).toBeGreaterThanOrEqual(100)

    triggerRect.mockReturnValue({
      top: 520,
      right: 680,
      bottom: 554,
      left: 120,
      width: 560,
      height: 34,
      x: 120,
      y: 520,
      toJSON: () => ({}),
    })
    window.dispatchEvent(new Event('scroll'))
    await flushPromises()
    expect(document.body.querySelector('.ui-multi-select__menu')).toBeNull()

    wrapper.unmount()
    dialogContent.remove()
  })
})
