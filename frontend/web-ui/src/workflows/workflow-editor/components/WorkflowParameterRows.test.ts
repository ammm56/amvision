import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import WorkflowParameterRows from './WorkflowParameterRows.vue'
import WorkflowValueDisplay from './WorkflowValueDisplay.vue'

describe('file display parameter rows', () => {
  it('edits typed match values and keeps order through move/delete', async () => {
    const rows = [{ key: 'ok', condition: { operator: 'in', path: 'label', right: ['a'] } }, { key: 'ng', condition: { operator: 'in', path: 'label', right: ['b'] } }]
    const wrapper = mount(WorkflowParameterRows, { props: { modelValue: rows, schema: { items: { properties: { key: { type: 'string' }, condition: { type: 'object' } } } } } })
    await wrapper.find('textarea[aria-label="Match Values"]').setValue('"custom-label"\n42\nfalse')
    expect((wrapper.emitted('update:modelValue')!.at(-1)![0] as typeof rows)[0]!.condition.right).toEqual(['custom-label', 42, false])
    await wrapper.find('button[aria-label="下移"]').trigger('click')
    expect((wrapper.emitted('update:modelValue')!.at(-1)![0] as typeof rows).map(r => r.key)).toEqual(['ng', 'ok'])
    await wrapper.find('button[aria-label="删除行"]').trigger('click')
    expect((wrapper.emitted('update:modelValue')!.at(-1)![0] as typeof rows).map(r => r.key)).toEqual(['ng'])
    wrapper.unmount()
  })

  it('shows partial summaries explicitly and allows collapsing the overlay', async () => {
    const wrapper = mount(WorkflowValueDisplay, { props: { overlay: true, payload: { context: { complete: false }, fields: [{ label: '良品率', value: .9583, format: 'percent', precision: 2 }] } } })
    expect(wrapper.text()).toContain('95.83%')
    expect(wrapper.get('[role="status"]').text()).toContain('部分结果')
    await wrapper.get('button').trigger('click')
    expect(wrapper.find('dl').exists()).toBe(false)
    expect(wrapper.get('button').attributes('aria-expanded')).toBe('false')
    wrapper.unmount()
  })
})
