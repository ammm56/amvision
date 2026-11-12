import { afterEach, expect, it, vi } from 'vitest'
import { flushPromises, shallowMount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import DatasetSampleStructure from '../../../frontend/web-ui/src/modules/datasets/components/DatasetSampleStructure.vue'
const api = vi.hoisted(() => ({ listDatasetSamples: vi.fn() }))
vi.mock('../../../frontend/web-ui/src/modules/datasets/services/dataset-workspace.service', () => api)
const workspace = (id: string) => ({ dataset_id: 'd', dataset_version_id: id, dataset: { display_name: '样本' }, version_number: 1, split_counts: { test: 1, train: 41 }, metadata: {}, categories: [] } as any)
const sample = (id: string) => ({ sample_id: id, file_name: `${id}.jpg`, split: 'train', annotations: [], width: 100, height: 80 })
const mountView = () => shallowMount(DatasetSampleStructure, { props: { workspace: workspace('v1') }, global: { plugins: [createI18n({ legacy: false, locale: 'zh-CN', messages: {} })] } })
afterEach(() => vi.resetAllMocks())
it('按训练集优先展示，展开与加载更多采用有界分页，不重复读取已展开分组', async () => {
  api.listDatasetSamples.mockImplementation(async (_d, _v, query) => ({ items: Array.from({ length: query.offset ? 1 : 40 }, (_, i) => sample(String(query.offset + i))), total: 41 }))
  const w = mountView(); await flushPromises()
  expect(api.listDatasetSamples.mock.calls[0][2]).toMatchObject({ split: 'train', offset: 0, limit: 40 })
  await w.findAll('button').find(b => b.text() === '加载更多')!.trigger('click'); await flushPromises()
  expect(api.listDatasetSamples.mock.calls[1][2]).toMatchObject({ offset: 40, limit: 40 })
  const split = w.findAll('.dataset-structure-split').find(b => b.text().startsWith('train'))!
  await split.trigger('click'); await split.trigger('click'); await flushPromises()
  expect(api.listDatasetSamples).toHaveBeenCalledTimes(2)
  expect(w.findAll('.dataset-structure-leaves button')).toHaveLength(41)
  w.unmount()
})
it('版本切换中迟到的样本响应不能写回新版本的树与预览', async () => {
  let finish!: (value: any) => void
  api.listDatasetSamples.mockImplementation((_d, version) => version === 'v1' ? new Promise(resolve => finish = resolve) : Promise.resolve({ items: [sample('new')], total: 1 }))
  const w = mountView()
  await w.setProps({ workspace: workspace('v2') }); await flushPromises()
  finish({ items: [sample('old')], total: 1 }); await flushPromises()
  expect(w.text()).toContain('new.jpg'); expect(w.text()).not.toContain('old.jpg')
  w.unmount()
})
