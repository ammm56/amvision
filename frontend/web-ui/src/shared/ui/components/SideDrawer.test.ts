import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'

import SideDrawer from './SideDrawer.vue'

describe('SideDrawer', () => {
  afterEach(() => {
    document.body.innerHTML = ''
    document.body.style.overflow = ''
  })

  it('打开时锁定页面滚动，关闭后恢复焦点和滚动状态', async () => {
    const opener = document.createElement('button')
    document.body.append(opener)
    opener.focus()
    document.body.style.overflow = 'auto'
    const wrapper = mount(SideDrawer, {
      attachTo: document.body,
      props: { open: false, title: '公开请求示例', closeLabel: '关闭' },
      slots: { default: '<p>example</p>' },
      global: { stubs: { transition: false } },
    })

    await wrapper.setProps({ open: true })
    await flushPromises()
    expect(document.body.style.overflow).toBe('hidden')
    expect(document.querySelector('[role="dialog"]')).not.toBeNull()

    await wrapper.setProps({ open: false })
    expect(document.body.style.overflow).toBe('hidden')
    expect(opener.inert).toBe(true)
    await vi.waitFor(() => expect(wrapper.emitted('after-leave')).toHaveLength(1))
    expect(document.body.style.overflow).toBe('auto')
    expect(document.activeElement).toBe(opener)
    wrapper.unmount()
  })

  it('退场中重新打开不能释放背景，最终关闭后才完成退场', async () => {
    const wrapper = mount(SideDrawer, {
      attachTo: document.body,
      props: { open: true, title: '项目详情', closeLabel: '关闭' },
      global: { stubs: { transition: false } },
    })
    await flushPromises()
    await wrapper.setProps({ open: false })
    await wrapper.setProps({ open: true })
    await flushPromises()
    expect(document.body.style.overflow).toBe('hidden')
    expect(wrapper.emitted('after-leave')).toBeUndefined()
    await wrapper.setProps({ open: false })
    await vi.waitFor(() => expect(wrapper.emitted('after-leave')).toHaveLength(1))
    expect(document.body.style.overflow).toBe('')
    wrapper.unmount()
  })

  it('遮罩点击只发出关闭事件', async () => {
    const wrapper = mount(SideDrawer, {
      attachTo: document.body,
      props: { open: true, title: '公开请求示例', closeLabel: '关闭' },
    })
    await flushPromises()

    const backdrop = document.querySelector('.side-drawer__backdrop') as HTMLElement
    backdrop.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }))
    await flushPromises()
    expect(wrapper.emitted('close')).toHaveLength(1)
    wrapper.unmount()
  })
})


it('图像对象抽屉不锁定背景交互，关闭后将焦点交还触发按钮', async () => {
  const opener = document.createElement('button')
  document.body.append(opener)
  opener.focus()
  const wrapper = mount(SideDrawer, { attachTo: document.body, props: { open: true, title: '对象', closeLabel: '关闭', nonmodal: true } })
  await flushPromises()
  expect(opener.inert).not.toBe(true)
  expect(document.body.style.overflow).not.toBe('hidden')
  const dialog = document.querySelector('[role="dialog"]')!
  expect(dialog.getAttribute('aria-modal')).toBeNull()
  ;(dialog.querySelector('button') as HTMLButtonElement).click()
  await flushPromises()
  expect(wrapper.emitted('close')).toHaveLength(1)
  expect(document.activeElement).toBe(opener)
  wrapper.unmount()
  opener.remove()
})
