import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import StatusPill from './StatusPill.vue'

describe('StatusPill', () => {
  it.each([
    ['running', 'success'],
    ['queued', 'info'],
    ['degraded', 'warning'],
    ['offline', 'danger'],
    ['disabled', 'neutral'],
  ])('maps %s to the %s semantic tone', (status, tone) => {
    const wrapper = mount(StatusPill, { props: { status } })
    expect(wrapper.classes()).toContain(`status-pill--${tone}`)
  })
})
