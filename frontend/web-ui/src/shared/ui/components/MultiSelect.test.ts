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
})
