import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import StatusBadge from './StatusBadge.vue'

describe('StatusBadge', () => {
  it.each([
    ['running', 'success'],
    ['queued', 'info'],
    ['degraded', 'warning'],
    ['offline', 'danger'],
    ['disabled', 'neutral'],
  ])('maps %s to the %s semantic tone', (status, tone) => {
    const wrapper = mount(StatusBadge, { props: { status } })
    expect(wrapper.classes()).toContain(`status-badge--${tone}`)
  })

  it('supports the compact dot treatment without a second status component', () => {
    const wrapper = mount(StatusBadge, { props: { status: 'running', label: '运行中', withDot: true } })
    expect(wrapper.find('.status-badge__dot').exists()).toBe(true)
    expect(wrapper.text()).toBe('运行中')
  })
})
