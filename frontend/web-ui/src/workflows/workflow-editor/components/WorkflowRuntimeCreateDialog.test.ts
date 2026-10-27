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
      requestTimeoutSeconds: null,
    })
    wrapper.unmount()
  })

  it('显式提交超时，拒绝非正整数，重新打开不带入上一次输入', async () => {
    const wrapper = mount(WorkflowRuntimeCreateDialog, {
      global: { plugins: [i18n] },
      props: { open: true, busy: false, defaultVersionId: 'version-2',
        versionOptions: [{ label: 'v2', value: 'version-2' }] },
    })
    for (const invalid of ['0', '-1', '1.5', '9007199254740992']) {
      await wrapper.get('input[type="number"]').setValue(invalid)
      expect(wrapper.get('.ui-button--primary').attributes('disabled')).toBeDefined()
      await wrapper.get('.ui-button--primary').trigger('click')
      expect(wrapper.emitted('create')).toBeUndefined()
    }
    await wrapper.get('input[type="number"]').setValue('120')
    await wrapper.get('.ui-button--primary').trigger('click')
    expect(wrapper.emitted('create')?.[0]?.[0]).toMatchObject({ requestTimeoutSeconds: 120 })
    await wrapper.setProps({ open: false })
    await wrapper.setProps({ open: true, defaultVersionId: 'version-3' })
    expect((wrapper.get('input[type="number"]').element as HTMLInputElement).value).toBe('')
    await wrapper.get('.ui-button--primary').trigger('click')
    expect(wrapper.emitted('create')?.[1]?.[0]).toMatchObject({ requestTimeoutSeconds: null, workflowAppVersionId: 'version-3' })
    wrapper.unmount()
  })
})
