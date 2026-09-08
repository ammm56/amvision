import { mount, flushPromises } from '@vue/test-utils'
import { beforeEach, describe, expect, it } from 'vitest'
import { i18n, setI18nLocale } from '@/platform/i18n'
import ConfirmDialog from '@/shared/ui/components/ConfirmDialog.vue'
import WorkflowAppModeConfigDialog from '@/workflows/workflow-editor/components/WorkflowAppModeConfigDialog.vue'

const candidate = { node_id: 'preview', output_port: 'body', title: 'Node', size: 'medium' as const, node_title: 'Preview', output_title: 'Body' }
const config = { format_id: 'amvision.workflow-app-mode.v1' as const, title: 'Page', displays: [candidate] }
beforeEach(() => setI18nLocale('zh-CN'))
function mountDialog(candidates = [candidate]) {
  return mount(WorkflowAppModeConfigDialog, { attachTo: document.body, global: { plugins: [i18n] }, props: { applicationTitle: 'App', config, candidates } })
}
describe('App Mode standard dialog', () => {
  it('shares the standard modal, focuses the title, traps Tab and closes with Escape', async () => {
    const wrapper = mountDialog()
    await flushPromises()
    expect(wrapper.findComponent(ConfirmDialog).exists()).toBe(true)
    expect(wrapper.get('[role=dialog]').classes()).toContain('confirm-dialog--wide')
    expect(document.activeElement).toBe(wrapper.get('[data-dialog-initial-focus]').element)
    const last = wrapper.get('.confirm-dialog__actions .ui-button--primary')
    ;(last.element as HTMLElement).focus()
    last.element.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', bubbles: true, cancelable: true }))
    expect(document.activeElement).toBe(wrapper.get('.confirm-dialog__close').element)
    await wrapper.get('[role=dialog]').trigger('keydown', { key: 'Escape' })
    expect(wrapper.emitted('close')).toHaveLength(1)
    expect(wrapper.emitted('apply')).toBeUndefined()
    wrapper.unmount()
  })
  it('blocks missing display references and allows deselection without mutating the source', async () => {
    const wrapper = mountDialog([])
    expect(wrapper.get('.confirm-dialog__actions .ui-button--primary').attributes('disabled')).toBeDefined()
    wrapper.getComponent(ConfirmDialog).vm.$emit('confirm')
    expect(wrapper.emitted('apply')).toBeUndefined()
    await wrapper.get('input[type=checkbox]').setValue(false)
    expect(wrapper.get('.confirm-dialog__actions .ui-button--primary').attributes('disabled')).toBeDefined()
    expect(config.displays).toHaveLength(1)
    wrapper.unmount()
  })
  it('validates title length in the handler and cancels local edits', async () => {
    const wrapper = mountDialog()
    await wrapper.get('[data-dialog-initial-focus]').setValue('x'.repeat(129))
    wrapper.getComponent(ConfirmDialog).vm.$emit('confirm')
    expect(wrapper.emitted('apply')).toBeUndefined()
    await wrapper.get('[data-dialog-initial-focus]').setValue('Changed')
    await wrapper.get('.confirm-dialog__actions .ui-button--secondary').trigger('click')
    expect(wrapper.emitted('close')).toHaveLength(1)
    expect(config.title).toBe('Page')
    wrapper.unmount()
  })
})
