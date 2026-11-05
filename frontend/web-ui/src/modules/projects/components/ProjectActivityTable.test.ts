import { mount } from '@vue/test-utils'
import { expect, it } from 'vitest'
import { i18n } from '@/platform/i18n'
import ProjectActivityTable from './ProjectActivityTable.vue'
import type { ProjectOverviewItem } from '../services/project.service'

const item: ProjectOverviewItem = { resource_id: 'runtime-1', name: '检测流程', kind: 'runtime', state: 'running', occurred_at: '2026-11-05T01:00:00Z' }
const props = { items: [item], canOpen: () => true, kindLabel: () => 'Workflow Runtime', stateLabel: () => '运行中' }
const global = { plugins: [i18n] }

it('点击任意数据列打开一次，名称入口不会冒泡重复打开', async () => {
  const wrapper = mount(ProjectActivityTable, { props, global })
  expect(wrapper.findAll('th')).toHaveLength(3)
  expect(wrapper.findAll('td')).toHaveLength(3)
  await wrapper.findAll('td')[1]!.trigger('click')
  expect(wrapper.emitted('open')).toEqual([[item]])
  await wrapper.get('button').trigger('click')
  expect(wrapper.emitted('open')).toEqual([[item], [item]])
  expect(wrapper.get('button').attributes('type')).toBe('button')
  expect(wrapper.get('button').attributes('aria-label')).toBe('查看 检测流程')
  wrapper.unmount()
})

it('无权访问的记录保留内容，不提供按钮或可点击行', async () => {
  const wrapper = mount(ProjectActivityTable, { props: { ...props, canOpen: () => false }, global })
  expect(wrapper.text()).toContain('检测流程')
  expect(wrapper.find('button').exists()).toBe(false)
  expect(wrapper.get('tbody tr').classes()).not.toContain('is-clickable')
  await wrapper.get('tbody tr').trigger('click')
  expect(wrapper.emitted('open')).toBeUndefined()
  wrapper.unmount()
})

it('权限在页面显示后收回，整行入口也立即停止响应', async () => {
  const wrapper = mount(ProjectActivityTable, { props, global })
  await wrapper.setProps({ canOpen: () => false })
  await wrapper.findAll('td')[2]!.trigger('click')
  expect(wrapper.emitted('open')).toBeUndefined()
  expect(wrapper.find('button').exists()).toBe(false)
  wrapper.unmount()
})

it('运行列表保持无表头和图标的布局，保留运行方式、阶段与零进度', () => {
  const wrapper = mount(ProjectActivityTable, { props: { ...props, mode: 'running', items: [{ ...item, runtime_mode: 'sync', progress: { stage: '初始化', percent: 0 } }] }, global })
  expect(wrapper.findAll('th')).toHaveLength(0)
  expect(wrapper.find('svg').exists()).toBe(false)
  expect(wrapper.text()).toContain('同步')
  expect(wrapper.text()).toContain('初始化')
  expect(wrapper.text()).toContain('0%')
  expect(wrapper.get('progress').attributes('value')).toBe('0')
  wrapper.unmount()
})

it('运行进度无效时不显示假进度条，最近更新也不混入运行进度', async () => {
  const wrapper = mount(ProjectActivityTable, { props: { ...props, mode: 'running', items: [{ ...item, progress: { percent: NaN } }] }, global })
  expect(wrapper.find('progress').exists()).toBe(false)
  await wrapper.setProps({ mode: 'recent', items: [{ ...item, progress: { stage: '推理', percent: 50 } }] })
  expect(wrapper.find('progress').exists()).toBe(false)
  expect(wrapper.text()).not.toContain('推理')
  wrapper.unmount()
})
