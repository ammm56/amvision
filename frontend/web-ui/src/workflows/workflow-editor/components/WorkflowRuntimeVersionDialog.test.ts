import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import { i18n } from '@/platform/i18n'
import WorkflowRuntimeVersionDialog from './WorkflowRuntimeVersionDialog.vue'

describe('WorkflowRuntimeVersionDialog', () => {
  it('在弹窗中显示当前版本和目标版本并提交切换', async () => {
    const wrapper = mount(WorkflowRuntimeVersionDialog, {
      global: { plugins: [i18n] },
      props: {
        open: true,
        busy: false,
        confirmDisabled: false,
        currentVersionLabel: 'v1 (#1)',
        targetVersionId: 'version-2',
        targetVersionLabel: 'v2 (#2)',
        versionOptions: [{ label: 'v2 (#2)', value: 'version-2' }],
        showBreakingOverride: false,
        allowBreakingContract: false,
        breakingChangeReason: '',
      },
    })

    expect(wrapper.get('.workflow-runtime-version-route').text()).toContain('v1 (#1)')
    expect(wrapper.get('.workflow-runtime-version-route').text()).toContain('v2 (#2)')
    await wrapper.get('.ui-button--primary').trigger('click')

    expect(wrapper.emitted('confirm')).toHaveLength(1)
    wrapper.unmount()
  })

  it('只有契约变化时显示显式确认字段', () => {
    const wrapper = mount(WorkflowRuntimeVersionDialog, {
      global: { plugins: [i18n] },
      props: {
        open: true,
        busy: false,
        confirmDisabled: true,
        currentVersionLabel: 'v1 (#1)',
        targetVersionId: 'version-2',
        targetVersionLabel: 'v2 (#2)',
        versionOptions: [{ label: 'v2 (#2)', value: 'version-2' }],
        showBreakingOverride: true,
        allowBreakingContract: false,
        breakingChangeReason: '',
      },
    })

    expect(wrapper.find('input[type="checkbox"]').exists()).toBe(true)
    expect(wrapper.get('.ui-button--primary').attributes('disabled')).toBeDefined()
    wrapper.unmount()
  })
})
