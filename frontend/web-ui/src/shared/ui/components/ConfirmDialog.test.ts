import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it } from 'vitest'

import ConfirmDialog from './ConfirmDialog.vue'

describe('ConfirmDialog', () => {
  afterEach(() => {
    document.body.innerHTML = ''
  })

  it('shows important confirmation details without a hidden tooltip', () => {
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
    expect(wrapper.find('.confirm-dialog__details').text()).toBe('任务记录、事件和运行磁盘数据会一起删除。')
    expect(wrapper.find('[role="tooltip"]').exists()).toBe(false)

    wrapper.unmount()
  })

  it('危险操作默认聚焦取消按钮', async () => {
    const wrapper = mount(ConfirmDialog, {
      attachTo: document.body,
      props: {
        title: '删除应用',
        message: '确认删除应用？',
        confirmLabel: '删除',
        cancelLabel: '取消',
      },
    })

    await flushPromises()
    expect(document.activeElement).toBe(wrapper.get('[data-confirm-cancel]').element)
    wrapper.unmount()
  })

  it('busy 状态阻止关闭并显示确认加载状态', async () => {
    const wrapper = mount(ConfirmDialog, {
      attachTo: document.body,
      props: {
        title: '删除应用',
        message: '确认删除应用？',
        confirmLabel: '删除',
        cancelLabel: '取消',
        busy: true,
      },
    })

    await wrapper.get('.confirm-dialog-backdrop').trigger('click')
    await wrapper.get('.confirm-dialog').trigger('keydown', { key: 'Escape' })
    expect(wrapper.emitted('cancel')).toBeUndefined()
    expect(wrapper.get('.ui-button--danger').classes()).toContain('is-loading')
    wrapper.unmount()
  })

  it('支持危险操作的补充输入并可禁用确认按钮', () => {
    const wrapper = mount(ConfirmDialog, {
      attachTo: document.body,
      props: {
        title: '删除 Project',
        message: '确认删除？',
        confirmLabel: '删除',
        cancelLabel: '取消',
        confirmDisabled: true,
      },
      slots: {
        default: '<label><input value="project-2" /></label>',
      },
    })

    expect(wrapper.get('.confirm-dialog__content input').attributes('value')).toBe('project-2')
    expect(wrapper.get('.ui-button--danger').attributes('disabled')).toBeDefined()
    wrapper.unmount()
  })
})
