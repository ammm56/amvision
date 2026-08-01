import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import TabList from './TabList.vue'

const tabs = [
  { id: 'nodes', label: '节点', count: 12 },
  { id: 'packs', label: '节点包', count: 3 },
  { id: 'diagnostics', label: '诊断', disabled: true },
]

describe('TabList', () => {
  it('呈现选中状态和数量', () => {
    const wrapper = mount(TabList, {
      props: { modelValue: 'nodes', tabs, label: '节点目录视图' },
    })

    expect(wrapper.get('[role="tablist"]').attributes('aria-label')).toBe('节点目录视图')
    expect(wrapper.findAll('[role="tab"]')[0]?.attributes('aria-selected')).toBe('true')
    expect(wrapper.get('.local-tabs__count').text()).toBe('12')
  })

  it('点击时更新当前 Tab', async () => {
    const wrapper = mount(TabList, {
      props: { modelValue: 'nodes', tabs, label: '节点目录视图' },
    })

    await wrapper.findAll('[role="tab"]')[1]?.trigger('click')
    expect(wrapper.emitted('update:modelValue')).toEqual([['packs']])
  })

  it('使用方向键切换并跳过禁用项', async () => {
    const wrapper = mount(TabList, {
      attachTo: document.body,
      props: { modelValue: 'packs', tabs, label: '节点目录视图' },
    })

    await wrapper.findAll('[role="tab"]')[1]?.trigger('keydown', { key: 'ArrowRight' })
    expect(wrapper.emitted('update:modelValue')).toEqual([['nodes']])
    expect(document.activeElement).toBe(wrapper.findAll('[role="tab"]')[0]?.element)
    wrapper.unmount()
  })
})
