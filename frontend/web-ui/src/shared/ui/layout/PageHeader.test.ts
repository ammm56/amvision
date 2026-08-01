import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import PageHeader from './PageHeader.vue'

describe('PageHeader', () => {
  it('呈现页面标题、说明和操作区', () => {
    const wrapper = mount(PageHeader, {
      props: {
        title: '数据集',
        description: '管理导入与导出任务。',
      },
      slots: {
        actions: '<button type="button">刷新</button>',
      },
    })

    expect(wrapper.get('h1').text()).toBe('数据集')
    expect(wrapper.get('.page-description').text()).toBe('管理导入与导出任务。')
    expect(wrapper.get('.page-actions button').text()).toBe('刷新')
  })

  it('允许业务页面提供自定义 heading', () => {
    const wrapper = mount(PageHeader, {
      slots: {
        heading: '<div class="custom-heading"><h1>项目</h1><span>project-1</span></div>',
      },
    })

    expect(wrapper.get('.custom-heading h1').text()).toBe('项目')
    expect(wrapper.find('.page-description').exists()).toBe(false)
  })
})
