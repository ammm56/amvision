import { expect, it, vi } from 'vitest'
import { flushPromises, shallowMount } from '@vue/test-utils'
import { reactive } from 'vue'
import { createI18n } from 'vue-i18n'
import { createPinia } from 'pinia'
import DatasetVersionPage from '../../../frontend/web-ui/src/modules/datasets/pages/DatasetVersionPage.vue'

const route = reactive({
  params: { datasetId: 'd', versionId: 'v1' },
  query: {},
})
const api = vi.hoisted(() => ({
  getDatasetWorkspace: vi.fn(),
  listDatasetSamples: vi.fn(),
  getDatasetSample: vi.fn(),
  getDatasetImage: vi.fn(),
}))
vi.mock(
  '../../../frontend/web-ui/src/modules/datasets/services/dataset-workspace.service',
  () => api,
)
vi.mock('vue-router', () => ({
  useRoute: () => route,
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}))
const workspace = (id: string) => ({
  dataset_id: 'd',
  dataset_version_id: id,
  project_id: 'p',
  dataset: { display_name: '数据集' },
  task_type: 'detection',
  sample_count: 1,
  category_count: 0,
  object_count: 0,
  categories: [],
  split_counts: { train: 1 },
  metadata: {},
})
const page = (id: string) => ({
  items: [
    {
      sample_id: id,
      dataset_version_id: id,
      file_name: `${id}.jpg`,
      split: 'train',
      annotations: [],
    },
  ],
  total: 1,
})

it('版本与图片原子切换，过期版本的迟到响应不能覆盖当前页', async () => {
  let finishV2!: (value: ReturnType<typeof page>) => void
  api.getDatasetWorkspace.mockImplementation((_dataset, version) =>
    Promise.resolve(workspace(version)),
  )
  api.listDatasetSamples.mockImplementation((_dataset, version) =>
    version === 'v2'
      ? new Promise((resolve) => {
          finishV2 = resolve
        })
      : Promise.resolve(page(version)),
  )
  const w = shallowMount(DatasetVersionPage, {
    global: {
      plugins: [
        createPinia(),
        createI18n({ legacy: false, locale: 'zh-CN', messages: {} }),
      ],
    },
  })
  await flushPromises()
  expect(w.text()).toContain('v1.jpg')
  route.params.versionId = 'v2'
  await flushPromises()
  expect(
    w.findComponent({ name: 'DatasetVersionSelect' }).props('workspace')
      .dataset_version_id,
  ).toBe('v1')
  expect(w.find('.dataset-version-content').attributes('inert')).toBeDefined()
  route.params.versionId = 'v3'
  await flushPromises()
  finishV2(page('v2'))
  await flushPromises()
  expect(w.text()).toContain('v3.jpg')
  expect(w.text()).not.toContain('v2.jpg')
  expect(
    w.findComponent({ name: 'DatasetVersionSelect' }).props('workspace')
      .dataset_version_id,
  ).toBe('v3')
  w.unmount()
})
