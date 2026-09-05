import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import { i18n } from '@/platform/i18n'
import WorkflowRuntimeCreateDialog from './WorkflowRuntimeCreateDialog.vue'

describe('WorkflowRuntimeCreateDialog', () => {
  it('默认使用最新版本、none 记录和关闭诊断', async () => {
    const wrapper = mount(WorkflowRuntimeCreateDialog, {
      global: { plugins: [i18n] },
      props: {
        open: true,
        busy: false,
        defaultVersionId: 'version-2',
        versionOptions: [{ label: 'v2 (#2)', value: 'version-2' }],
      },
    })

    await wrapper.get('.ui-button--primary').trigger('click')
    expect(wrapper.emitted('create')?.[0]?.[0]).toEqual({
      workflowAppVersionId: 'version-2',
      workflowRunRecordMode: 'none',
      returnDiagnostics: false,
    })
    wrapper.unmount()
  })
})
