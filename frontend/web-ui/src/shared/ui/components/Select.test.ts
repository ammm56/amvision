import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import Select from './Select.vue'

describe('Select', () => {
  it('keeps a floating menu outside the scroll container and Escape inside the dialog', async () => {
    const wrapper = mount(Select, { attachTo: document.body, props: {
      floating: true, ariaLabel: 'Operation', modelValue: 'sum',
      options: [{ label: 'Sum', value: 'sum' }, { label: 'Count', value: 'count' }],
    } })
    const trigger = wrapper.get('.ui-select__button')
    await trigger.trigger('click')
    const menu = document.body.querySelector('.ui-select__menu--floating')!
    expect(menu.parentElement).toBe(document.body)
    expect(menu.querySelector('[aria-selected="true"]')?.textContent).toContain('Sum')
    const escape = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true })
    trigger.element.dispatchEvent(escape)
    await wrapper.vm.$nextTick()
    expect(escape.defaultPrevented).toBe(true)
    expect(document.body.querySelector('.ui-select__menu--floating')).toBeNull()
    await trigger.trigger('click')
    const count = document.body.querySelectorAll('.ui-select__menu--floating [role="option"]')[1]!
    count.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }))
    await wrapper.vm.$nextTick()
    expect(wrapper.emitted('update:modelValue')).toEqual([['count']])
    await trigger.trigger('click')
    window.dispatchEvent(new Event('resize'))
    await wrapper.vm.$nextTick()
    expect(document.body.querySelector('.ui-select__menu--floating')).toBeNull()
    wrapper.unmount()
  })

  it('can size a compact select from its longest option', () => {
    const wrapper = mount(Select, {
      props: {
        modelValue: 'detection',
        fitOptions: true,
        options: [
          { label: '目标检测', value: 'detection' },
          { label: '旋转框目标检测', value: 'obb' },
        ],
      },
    })

    expect(wrapper.classes()).toContain('ui-select--fit-options')
    expect(wrapper.get('.ui-select__sizer').text()).toContain('旋转框目标检测')
  })

  it('supports arrow navigation and keyboard selection', async () => {
    const wrapper = mount(Select, {
      props: {
        modelValue: null,
        options: [
          { label: 'Light', value: 'light' },
          { label: 'Dark', value: 'dark' },
        ],
      },
    })
    const trigger = wrapper.get('.ui-select__button')

    await trigger.trigger('keydown', { key: 'ArrowDown' })
    await trigger.trigger('keydown', { key: 'ArrowDown' })
    expect(wrapper.get('.ui-select__option.is-active').text()).toContain('Dark')

    await trigger.trigger('keydown', { key: 'Enter' })
    expect(wrapper.emitted('update:modelValue')).toEqual([['dark']])
    expect(wrapper.find('.ui-select__menu').exists()).toBe(false)
  })
})
