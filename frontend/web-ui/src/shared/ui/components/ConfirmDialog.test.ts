import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it } from 'vitest'

import ConfirmDialog from './ConfirmDialog.vue'

describe('ConfirmDialog', () => {
  afterEach(() => {
    document.body.innerHTML = ''
  })

  it('keeps the confirmation concise and exposes details through InfoHint', async () => {
    const wrapper = mount(ConfirmDialog, {
      attachTo: document.body,
      props: {
        title: '删除转换任务',
        message: '确认删除？',
        details: '任务记录、事件和运行磁盘数据会一起删除。',
        confirmLabel: '删除转换任务',
        cancelLabel: '取消',
      },
    })

    expect(wrapper.find('.confirm-dialog__message').text()).toBe('确认删除？')
    expect(wrapper.text()).not.toContain('任务记录、事件和运行磁盘数据会一起删除。')

    await wrapper.find('.info-hint').trigger('mouseenter')
    await flushPromises()

    const tooltip = document.body.querySelector('[role="tooltip"]')
    expect(tooltip?.textContent).toBe('任务记录、事件和运行磁盘数据会一起删除。')

    wrapper.unmount()
  })
})
