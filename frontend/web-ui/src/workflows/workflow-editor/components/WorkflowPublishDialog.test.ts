import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import { i18n } from '@/platform/i18n'
import WorkflowPublishDialog from './WorkflowPublishDialog.vue'

describe('WorkflowPublishDialog', () => {
  it('只收集版本说明并交由后端生成版本号', async () => {
    const wrapper = mount(WorkflowPublishDialog, {
      global: { plugins: [i18n] },
      props: {
        open: true,
        busy: false,
      },
    })

    expect(wrapper.find('input').exists()).toBe(false)
    await wrapper.get('textarea').setValue('  修复现场流程  ')
    await wrapper.get('.ui-button--primary').trigger('click')

    expect(wrapper.emitted('publish')?.[0]).toEqual(['修复现场流程'])
    wrapper.unmount()
  })
})
