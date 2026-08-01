import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import Button from './Button.vue'

describe('Button', () => {
  it('exposes a disabled busy state while loading', () => {
    const wrapper = mount(Button, {
      props: { loading: true },
      slots: { default: '保存' },
    })

    const button = wrapper.get('button')
    expect(button.attributes('aria-busy')).toBe('true')
    expect(button.attributes()).toHaveProperty('disabled')
    expect(wrapper.find('.ui-button__spinner').exists()).toBe(true)
    expect(wrapper.text()).toContain('保存')
  })
})
