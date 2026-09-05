import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it } from 'vitest'

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
    })

    await wrapper.setProps({ open: true })
    await flushPromises()
    expect(document.body.style.overflow).toBe('hidden')
    expect(document.querySelector('[role="dialog"]')).not.toBeNull()

    await wrapper.setProps({ open: false })
    await flushPromises()
    expect(document.body.style.overflow).toBe('auto')
    expect(document.activeElement).toBe(opener)
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
