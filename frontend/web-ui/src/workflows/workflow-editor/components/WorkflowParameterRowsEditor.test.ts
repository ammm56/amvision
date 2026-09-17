import { mount, type VueWrapper } from '@vue/test-utils'
import { nextTick } from 'vue'
import { afterEach, describe, expect, it } from 'vitest'
import WorkflowParameterRowsEditor from './WorkflowParameterRowsEditor.vue'
import ConfirmDialog from '@/shared/ui/components/ConfirmDialog.vue'

const props = {
  label: 'Rules',
  modelValue: [{ key: 'ok', condition: { operator: 'in', path: 'label', right: ['empty'] } }],
  schema: { items: { properties: { key: { type: 'string' }, condition: { type: 'object' } } } },
}
let wrapper: VueWrapper
function element<T extends HTMLElement>(selector: string): T { return document.body.querySelector<T>(selector)! }
async function change(selector: string, value: string, event: string) {
  const input = element<HTMLInputElement>(selector)
  input.value = value
  input.dispatchEvent(new Event(event, { bubbles: true }))
  await nextTick()
}
async function open() { await wrapper.get('.parameter-rows-summary').trigger('click'); await nextTick() }
afterEach(() => { wrapper?.unmount(); document.body.innerHTML = '' })

describe('规则编辑对话框', () => {
  it('画布只显示摘要，取消不修改参数，应用一次提交草稿', async () => {
    wrapper = mount(WorkflowParameterRowsEditor, { attachTo: document.body, props })
    expect(wrapper.find('textarea').exists()).toBe(false)
    expect(wrapper.text()).toContain('已配置 1 项')
    await open()
    await change('input[aria-label="Path"]', 'result.label', 'input')
    expect(wrapper.emitted('update:modelValue')).toBeUndefined()
    wrapper.getComponent(ConfirmDialog).vm.$emit('cancel')
    await nextTick()
    await open()
    expect(element<HTMLInputElement>('input[aria-label="Path"]').value).toBe('label')
    await change('textarea[aria-label="Match Values"]', '"custom-empty"\n42', 'change')
    wrapper.getComponent(ConfirmDialog).vm.$emit('confirm')
    await nextTick()
    expect(wrapper.emitted('update:modelValue')).toHaveLength(1)
    expect((wrapper.emitted('update:modelValue')![0]![0] as typeof props.modelValue)[0]!.condition.right).toEqual(['custom-empty', 42])
  })

  it('无效 JSON 阻止应用，修改其他字段不能清除错误', async () => {
    wrapper = mount(WorkflowParameterRowsEditor, { attachTo: document.body, props })
    await open()
    ;[...document.body.querySelectorAll<HTMLButtonElement>('.parameter-rows button')].find(b => b.textContent === '编辑条件 JSON')!.click()
    await nextTick()
    await change('.parameter-rows textarea', '{ invalid', 'change')
    expect(element('[role="alert"]')).not.toBeNull()
    await change('.parameter-rows input', 'renamed', 'input')
    expect(wrapper.getComponent(ConfirmDialog).props('confirmDisabled')).toBe(true)
    wrapper.getComponent(ConfirmDialog).vm.$emit('confirm')
    expect(wrapper.emitted('update:modelValue')).toBeUndefined()
    await change('.parameter-rows textarea', '{"operator":"in","path":"label","right":["empty"]}', 'change')
    expect(wrapper.getComponent(ConfirmDialog).props('confirmDisabled')).toBe(false)
  })
})
