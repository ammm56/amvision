import { afterEach, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import DatasetComparison from '../../../frontend/web-ui/src/modules/datasets/components/DatasetComparison.vue'
import TaskProgress from '../../../frontend/web-ui/src/modules/tasks/components/TaskProgress.vue'

const api = vi.hoisted(() => ({ getDatasetWorkspace: vi.fn(), getDatasetCategories: vi.fn(), getDatasetSample: vi.fn() }))
vi.mock('../../../frontend/web-ui/src/modules/datasets/services/dataset-workspace.service', () => api)
const source = { dataset_id: 'd', dataset_version_id: 'v1', version_number: 1, sample_count: 10, object_count: 20, category_count: 1, created_at: '2026-11-16T00:00:00Z', split_counts: { train: 10 }, metadata: { content_revision: 'r1' } }
const target = { ...source, dataset_version_id: 'v2', version_number: 2, split_counts: { train: 8, val: 2 } }
const job = { task_id: 'comparison', operation: 'compare', state: 'succeeded', content_revision: 'r1', result: { compare_version_id: 'v2', counts: { changed_samples: 7, added: 1, removed: 1, split: 5 }, changes: [
  { sample_id: 'new', file_name: 'new.jpg', kinds: ['added'] },
  { sample_id: 'old', file_name: 'old.jpg', kinds: ['removed'] },
  ...Array.from({ length: 5 }, (_, index) => ({ sample_id: `modified-${index}`, file_name: `m${index}.jpg`, kinds: ['split'] })),
] } }
const wrappers: ReturnType<typeof mount>[] = []
function render(overrides = {}) {
  api.getDatasetWorkspace.mockResolvedValue(target)
  api.getDatasetCategories.mockImplementation((_: string, version: string) => Promise.resolve({ items: [{ name: 'bolt', category_id: version === 'v1' ? 0 : 4, object_count: version === 'v1' ? 20 : 22 }] }))
  api.getDatasetSample.mockImplementation((_: string, version: string, sample: string) => Promise.resolve({ sample_id: sample, split: version === 'v1' ? 'train' : 'val', annotations: [{}] }))
  const wrapper = mount(DatasetComparison, { props: { source, versions: [source, target], targetId: 'v2', job, busy: false, canWrite: true, ...overrides } as any, global: { plugins: [createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': { common: { pagination: { previous: '上一页', next: '下一页' } } } } })] } })
  wrappers.push(wrapper)
  return wrapper
}
afterEach(() => { wrappers.splice(0).forEach(wrapper => wrapper.unmount()); vi.resetAllMocks() })

it('返回比较页后异步加载报告仍恢复原差异类型和页码', async () => {
  const wrapper = render({ job: null, initialFilter: 'modified', initialOffset: 4 })
  await wrapper.setProps({ job: job as any })
  await flushPromises()
  expect((wrapper.find('input[value="modified"]').element as HTMLInputElement).checked).toBe(true)
  expect(wrapper.find('table[aria-label="差异样本"]').text()).toContain('m4.jpg')
  expect(wrapper.find('table[aria-label="差异样本"]').text()).not.toContain('m0.jpg')
  await wrapper.find('input[value="added"]').setValue(true)
  await flushPromises()
  expect(wrapper.emitted('viewState')?.at(-1)).toEqual([{ filter: 'added', offset: 0 }])
})

it('差异分页、类型筛选及左右样本定位使用真实版本，类别以名称对齐', async () => {
  const wrapper = render()
  await flushPromises()
  expect(wrapper.findAll('table[aria-label="差异样本"] tbody tr')).toHaveLength(4)
  const view = wrapper.findAll('button').filter(button => button.text() === '查看样本')
  await view[0].trigger('click'); await view[1].trigger('click')
  expect(wrapper.emitted('sample')).toEqual([['new', 'v2'], ['old', 'v1']])
  expect(wrapper.find('table[aria-label="类别对比"]').text()).toContain('+2')
  expect(wrapper.find('table[aria-label="数据划分对比"] tbody tr:nth-child(2) td:last-child').classes()).toContain('comparison-increase')
  await wrapper.find('input[value="modified"]').setValue(true)
  await flushPromises()
  expect(wrapper.find('table[aria-label="差异样本"]').text()).not.toContain('old.jpg')
  await wrapper.findAll('button').find(button => button.text() === '下一页')!.trigger('click')
  await flushPromises()
  expect(wrapper.findAll('table[aria-label="差异样本"] tbody tr')).toHaveLength(1)
  expect(wrapper.find('table[aria-label="差异样本"]').text()).toContain('m4.jpg')
  await wrapper.find('input[value="added"]').setValue(true)
  await flushPromises()
  expect(wrapper.find('table[aria-label="差异样本"]').text()).toContain('new.jpg')
})

it('样本读取失败不伪造零对象，允许重试；截断报告明确分页范围', async () => {
  const wrapper = render({ job: null })
  api.getDatasetSample.mockRejectedValue(new Error('offline'))
  await wrapper.setProps({ job: { ...job, result: { ...job.result, truncated: true } } as any })
  await flushPromises()
  expect(wrapper.text()).toContain('仅保留前 200 条差异')
  expect(wrapper.text()).toContain('部分样本详情读取失败')
  expect(wrapper.find('table[aria-label="差异样本"]').text()).toContain('—')
  api.getDatasetSample.mockResolvedValue({ split: 'test', annotations: [{}, {}] })
  await wrapper.find('.comparison-notice button').trigger('click')
  await flushPromises()
  expect(wrapper.text()).not.toContain('部分样本详情读取失败')
})

it('快速切换比较版本时丢弃旧请求返回结果', async () => {
  const wrapper = render({ targetId: '' })
  await flushPromises()
  let finishOld!: (value: unknown) => void
  api.getDatasetWorkspace.mockImplementationOnce(() => new Promise(resolve => { finishOld = resolve })).mockResolvedValueOnce({ ...target, dataset_version_id: 'v3', version_number: 3 })
  await wrapper.setProps({ targetId: 'v2' }); await wrapper.setProps({ targetId: 'v3' })
  await flushPromises()
  finishOld(target); await flushPromises()
  expect(wrapper.find('[aria-label="右侧版本摘要"]').text()).toContain('v3')
  expect(wrapper.find('[aria-label="右侧版本摘要"]').text()).not.toContain('v2')
})

it('排队或执行时锁定比较方向，未知进度不显示虚构百分比', async () => {
  const wrapper = render({ job: { ...job, state: 'running' } })
  await flushPromises()
  expect(wrapper.find('button[aria-label="左侧版本"]').attributes('disabled')).toBeDefined()
  expect(wrapper.find('button[aria-label="交换比较方向"]').attributes('disabled')).toBeDefined()
  const progress = mount(TaskProgress, { props: { percent: undefined, indeterminate: true, label: '正在处理数据' } })
  wrappers.push(progress)
  expect(progress.find('[role="progressbar"]').attributes('aria-valuenow')).toBeUndefined()
  expect(progress.text()).not.toContain('%')
  await progress.setProps({ percent: 42 })
  expect(progress.find('[role="progressbar"]').attributes('aria-valuenow')).toBe('42')
  expect(progress.find('.is-indeterminate').exists()).toBe(false)
})
