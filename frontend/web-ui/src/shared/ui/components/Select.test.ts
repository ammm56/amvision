import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import Select from './Select.vue'

describe('Select', () => {
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
