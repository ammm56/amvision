import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

import Select from './Select.vue'

describe('Select', () => {
  it('keeps layout attributes on the wrapper and listens globally only while open', async () => {
    const add = vi.spyOn(document, 'addEventListener')
    const remove = vi.spyOn(document, 'removeEventListener')
    const wrapper = mount(Select, { attrs: {
      class: 'compact-field', style: 'max-width: 150px', id: 'choice', 'aria-invalid': 'true',
    }, props: { modelValue: 'a', options: [{ value: 'a', label: 'A' }] } })
    const trigger = wrapper.get('.ui-select__button')
    expect(wrapper.classes()).toContain('compact-field')
    expect(trigger.classes()).not.toContain('compact-field')
    expect(trigger.attributes('id')).toBe('choice')
    expect(trigger.attributes('aria-invalid')).toBe('true')
    expect(add.mock.calls.filter(call => call[0] === 'pointerdown')).toHaveLength(0)
    await trigger.trigger('click')
    const listener = add.mock.calls.find(call => call[0] === 'pointerdown')![1]
    await trigger.trigger('keydown', { key: 'Escape' })
    expect(remove).toHaveBeenCalledWith('pointerdown', listener)
    wrapper.unmount()
    add.mockRestore(); remove.mockRestore()
  })
  it('preserves numeric, boolean and null values and skips disabled options', async () => {
    const wrapper = mount(Select, { props: { modelValue: null, options: [
      { value: null, label: 'Choose', disabled: true },
      { value: 0, label: 'First' }, { value: false, label: 'Off', disabled: true },
      { value: true, label: 'On' },
    ] } })
    const trigger = wrapper.get('button')
    await trigger.trigger('keydown', { key: 'ArrowDown' })
    expect(wrapper.get('.is-active').text()).toBe('First')
    await trigger.trigger('keydown', { key: 'ArrowDown' })
    await trigger.trigger('keydown', { key: 'Enter' })
    expect(wrapper.emitted('change')).toEqual([[true]])
    await trigger.trigger('click')
    await wrapper.findAll('[role=option]')[1]!.trigger('pointerdown')
    await wrapper.findAll('[role=option]')[1]?.trigger('click')
    expect(wrapper.emitted('change')).toEqual([[true], [0]])
    wrapper.unmount()
  })

  it('closes on disable, changed options and unmount without leaving a floating menu', async () => {
    const wrapper = mount(Select, { attachTo: document.body, props: {
      modelValue: 'a', floating: true, options: [{ value: 'a', label: 'A' }],
    } })
    const trigger = wrapper.get('button')
    await trigger.trigger('click'); await wrapper.setProps({ disabled: true })
    expect(document.querySelector('[role=listbox]')).toBeNull()
    await wrapper.setProps({ disabled: false }); await trigger.trigger('click')
    await wrapper.setProps({ options: [{ value: 'b', label: 'B' }] })
    expect(document.querySelector('[role=listbox]')).toBeNull()
    await trigger.trigger('click'); wrapper.unmount()
    expect(document.querySelector('[role=listbox]')).toBeNull()
    expect(wrapper.emitted('change')).toBeUndefined()
  })
  it('renders custom value and option content without changing selection or keyboard behavior', async () => {
    const wrapper = mount(Select, {
      props: { modelValue: 'asc', options: [{ value: 'asc', label: 'Ascending' }, { value: 'desc', label: 'Descending' }] },
      slots: { value: '<template #value="{ option }"><b>{{ option.label }}</b></template>', option: '<template #option="{ option }"><i>{{ option.label }}</i></template>' },
    })
    expect(wrapper.get('.ui-select__value b').text()).toBe('Ascending')
    await wrapper.get('.ui-select__button').trigger('click')
    expect(wrapper.findAll('.ui-select__option i').map(item => item.text())).toEqual(['Ascending', 'Descending'])
    await wrapper.get('.ui-select__button').trigger('keydown', { key: 'ArrowDown' })
    await wrapper.get('.ui-select__button').trigger('keydown', { key: 'Enter' })
    expect(wrapper.emitted('update:modelValue')).toEqual([['desc']])
    wrapper.unmount()
  })
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
