import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import WorkflowGraphCheckbox from './WorkflowGraphCheckbox.vue'

describe('WorkflowGraphCheckbox', () => {
  it('只在选中时渲染勾号，避免通用文字颜色使 false 看起来已选中', async () => {
    const wrapper = mount(WorkflowGraphCheckbox, { props: { checked: false } })

    expect(wrapper.find('.workflow-graph-checkbox__control svg').exists()).toBe(false)
    await wrapper.setProps({ checked: true })
    expect(wrapper.find('.workflow-graph-checkbox__control svg').exists()).toBe(true)
    await wrapper.setProps({ checked: false })
    expect(wrapper.find('.workflow-graph-checkbox__control svg').exists()).toBe(false)
  })

  it('将受控选中状态和可访问名称传递给原生输入', () => {
    const wrapper = mount(WorkflowGraphCheckbox, {
      props: {
        checked: true,
        ariaLabel: '启用节点',
      },
    })

    const input = wrapper.get('input[type="checkbox"]')
    expect((input.element as HTMLInputElement).checked).toBe(true)
    expect(input.attributes('aria-label')).toBe('启用节点')
    expect(wrapper.get('.workflow-graph-checkbox__control').attributes('aria-hidden')).toBe('true')
  })

  it('保留原生 change 事件，兼容现有节点参数更新逻辑', async () => {
    const wrapper = mount(WorkflowGraphCheckbox)

    await wrapper.get('input[type="checkbox"]').setValue(true)

    expect(wrapper.emitted('change')).toHaveLength(1)
    expect(wrapper.emitted('change')?.[0]?.[0]).toBeInstanceOf(Event)
  })

  it('只读参数不能触发状态变更', async () => {
    const wrapper = mount(WorkflowGraphCheckbox, {
      props: { disabled: true },
    })

    const input = wrapper.get('input[type="checkbox"]')
    expect(input.attributes('disabled')).toBeDefined()
    await input.trigger('change')
    expect(wrapper.emitted('change')).toBeUndefined()
  })
})
