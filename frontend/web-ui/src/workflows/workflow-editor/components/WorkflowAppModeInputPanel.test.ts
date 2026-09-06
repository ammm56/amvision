import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import { i18n } from '@/platform/i18n'
import WorkflowAppModeInputPanel from './WorkflowAppModeInputPanel.vue'

describe('WorkflowAppModeInputPanel', () => {
  it('uses the compact run bar when the Workflow has no public inputs', () => {
    const wrapper = mount(WorkflowAppModeInputPanel, {
      props: {
        inputs: [],
        labels: {},
        states: {},
        running: false,
        disabled: false,
      },
      global: { plugins: [i18n] },
    })

    expect(wrapper.get('form').classes()).toContain('app-mode-inputs--empty')
    expect(wrapper.get('button[type="submit"]').attributes('type')).toBe('submit')
  })
})
