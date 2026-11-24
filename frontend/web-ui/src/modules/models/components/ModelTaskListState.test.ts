import { RouterLinkStub, shallowMount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

vi.mock('vue-i18n', async (importOriginal) => ({
  ...await importOriginal<typeof import('vue-i18n')>(),
  useI18n: () => ({ t: (key: string) => key }),
}))

import TrainingTaskList from './TrainingTaskList.vue'
import ConversionTaskList from './ConversionTaskList.vue'
import LoadingPanel from '@/shared/ui/feedback/LoadingPanel.vue'

describe.each([
  ['training', TrainingTaskList, 'trainingTasks', { task_id: 'task-1', progress: {}, state: 'succeeded' }],
  ['conversion', ConversionTaskList, 'conversionTasks', { task_id: 'task-1', state: 'succeeded', produced_formats: [], target_formats: [], builds: [] }],
] as const)('%s task list', (_name, component, key, task) => {
  it('distinguishes loading, failed loading and a genuinely empty list', async () => {
    const wrapper = shallowMount(component, { props: { selectedTaskType: 'detection', [key]: [], loading: true } as never })
    expect(wrapper.getComponent(LoadingPanel).props()).toMatchObject({
      title: 'modelOps.messages.loadingTasks',
      compact: true,
    })
    expect(wrapper.findComponent({ name: 'EmptyState' }).exists()).toBe(false)
    await wrapper.setProps({ loading: false, loadError: true })
    expect(wrapper.text()).toContain('modelOps.messages.tasksUnavailable')
    expect(wrapper.findComponent({ name: 'EmptyState' }).exists()).toBe(false)
    await wrapper.setProps({ loadError: false })
    expect(wrapper.findComponent({ name: 'EmptyState' }).exists()).toBe(true)
    await wrapper.setProps({ [key]: [task], loading: true })
    expect(wrapper.find('table').exists()).toBe(true)
    expect(wrapper.findComponent(LoadingPanel).exists()).toBe(false)
    if (key === 'trainingTasks') {
      await wrapper.setProps({ loading: false, loadError: true })
      expect(wrapper.text()).toContain('刷新失败，当前显示上次加载的任务')
    }
  })
})

it('filters training tasks by name and keeps pagination within the filtered result', async () => {
  const tasks = Array.from({ length: 24 }, (_, index) => ({
    task_id: `task-${index}`, display_name: `Task ${index}`, state: 'succeeded', progress: {}, created_at: '',
  }))
  const wrapper = shallowMount(TrainingTaskList, {
    props: { selectedTaskType: 'detection', trainingTasks: tasks as never },
    global: { stubs: { RouterLink: RouterLinkStub, ModelListToolbar: false } },
  })
  expect(wrapper.findAll('tbody tr')).toHaveLength(20)
  await wrapper.find('input').setValue('Task 23')
  expect(wrapper.findAll('tbody tr')).toHaveLength(1)
  expect(wrapper.findComponent(RouterLinkStub).props('to')).toMatchObject({
    path: '/models/detection/training-tasks/task-23', query: { q: 'Task 23' },
  })
  await wrapper.find('input').setValue('no-match')
  expect(wrapper.text()).toContain('没有符合条件的训练任务')
})

it('filters conversion tasks and exposes their detail action', async () => {
  const tasks = Array.from({ length: 24 }, (_, index) => ({
    task_id: `conversion-${index}`, display_name: `Conversion ${index}`, state: 'succeeded',
    source_model_version_id: 'version-1', target_formats: ['onnx'], produced_formats: [], builds: [], created_at: '',
  }))
  const wrapper = shallowMount(ConversionTaskList, {
    props: { selectedTaskType: 'detection', conversionTasks: tasks as never },
    global: { stubs: { RouterLink: RouterLinkStub, ModelListToolbar: false } },
  })
  expect(wrapper.findAll('tbody tr')).toHaveLength(20)
  await wrapper.find('input').setValue('Conversion 23')
  expect(wrapper.findAll('tbody tr')).toHaveLength(1)
  expect(wrapper.findComponent(RouterLinkStub).props('to')).toMatchObject({
    path: '/models/detection/conversion-tasks/conversion-23', query: { q: 'Conversion 23' },
  })
  await wrapper.find('input').setValue('no-match')
  expect(wrapper.text()).toContain('没有符合条件的转换任务')
})

it('shows readable conversion sources and preserves custom task names', () => {
  const task = {
    task_id: 'conversion-1', model_type: 'yolo11', state: 'succeeded', created_at: '',
    source_model_version_id: 'model-version-1', target_formats: ['onnx'], builds: [], report_summary: {},
    display_name: 'yolo11 conversion model-version-1',
  }
  const wrapper = shallowMount(ConversionTaskList, {
    props: {
      selectedTaskType: 'classification',
      sourceNames: new Map([['model-version-1', '托盘分类 · v1']]),
      conversionTasks: [task, { ...task, task_id: 'conversion-2', display_name: '产线兼容性复核' }] as never,
    },
    global: { stubs: { RouterLink: RouterLinkStub } },
  })
  const [defaultRow, customRow] = wrapper.findAll('tbody tr')
  expect(defaultRow?.text()).toContain('托盘分类 · v1')
  expect(defaultRow?.text()).not.toContain('model-version-1')
  expect(customRow?.text()).toContain('产线兼容性复核')
})
