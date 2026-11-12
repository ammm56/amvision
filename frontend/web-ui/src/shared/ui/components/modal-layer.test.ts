import { mount, flushPromises } from '@vue/test-utils'
import { describe, it, expect } from 'vitest'
import SideDrawer from './SideDrawer.vue'
import ConfirmDialog from './ConfirmDialog.vue'
import { defineComponent, ref } from 'vue'

describe('模态层级', () => {
  it('抽屉内聚焦按钮移除后仍可 Esc 退出，内层确认出现后不抢焦点', async () => {
    const show = ref(true)
    const host = mount(defineComponent({
      components: { SideDrawer }, setup: () => ({ show }),
      template: '<SideDrawer open title="编辑" close-label="关闭"><button v-if="show" class="choice" @click="show = false">保留修改</button></SideDrawer>',
    }), { attachTo: document.body })
    await flushPromises()
    const choice = document.querySelector<HTMLButtonElement>('.choice')!
    choice.focus(); choice.click(); await flushPromises()
    expect(document.activeElement).toBe(document.querySelector('.side-drawer'))
    const dialog = mount(ConfirmDialog, { attachTo: document.body, props: { title: '确认', confirmLabel: '确认', cancelLabel: '取消' } })
    await flushPromises()
    const innerFocus = document.activeElement
    show.value = true; await flushPromises()
    expect(document.activeElement).toBe(innerFocus)
    dialog.unmount()
    document.querySelector('.side-drawer')!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
    expect(host.findComponent(SideDrawer).emitted('close')).toHaveLength(1)
    host.unmount()
  })
  it('提交期间按钮失焦后仍将焦点保留在对话框，完成后 Esc 可关闭', async () => {
    const dialog = mount(ConfirmDialog, { attachTo: document.body, props: { title: '生成配置包', confirmLabel: '下载', cancelLabel: '关闭' } })
    await flushPromises()
    ;(document.activeElement as HTMLElement).blur()
    await dialog.setProps({ busy: true })
    expect(document.activeElement).toBe(document.querySelector('.confirm-dialog'))
    await dialog.setProps({ busy: false })
    await dialog.get('.confirm-dialog').trigger('keydown', { key: 'Escape' })
    expect(dialog.emitted('cancel')).toHaveLength(1)
    dialog.unmount()
  })

  it('内层确认关闭后仍锁定背景，外层关闭后恢复原焦点和滚动', async () => {
    const opener = document.createElement('button')
    document.body.append(opener)
    opener.focus()
    document.body.style.overflow = 'auto'
    const drawer = mount(SideDrawer, { attachTo: document.body, props: { open: true, title: '编辑项目', closeLabel: '关闭' } })
    await flushPromises()
    const outer = document.querySelector('.side-drawer') as HTMLElement
    const dialog = mount(ConfirmDialog, { attachTo: document.body, props: { title: '放弃修改？', confirmLabel: '放弃', cancelLabel: '继续编辑' } })
    await flushPromises()
    expect(document.querySelector<HTMLElement>('.side-drawer__backdrop')?.style.background).toBe('transparent')
    expect(opener.inert).toBe(true)
    dialog.unmount()
    expect(document.body.style.overflow).toBe('hidden')
    expect(document.activeElement).toBe(outer)
    drawer.unmount()
    expect(document.body.style.overflow).toBe('auto')
    expect(opener.inert).toBeFalsy()
    expect(document.activeElement).toBe(opener)
    opener.remove()
    document.body.style.overflow = ''
  })

  it('外层先卸载不能解锁仍打开的确认，最后恢复初始滚动', async () => {
    const drawer = mount(SideDrawer, { attachTo: document.body, props: { open: true, title: '编辑', closeLabel: '关闭' } })
    await flushPromises()
    const dialog = mount(ConfirmDialog, { attachTo: document.body, props: { title: '确认', confirmLabel: '确认', cancelLabel: '取消' } })
    await flushPromises()
    drawer.unmount()
    expect(document.body.style.overflow).toBe('hidden')
    dialog.unmount()
    expect(document.body.style.overflow).toBe('')
  })
})
