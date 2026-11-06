import { afterEach, expect, it, vi } from 'vitest'
import { flushPromises, shallowMount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { createPinia } from 'pinia'
import DatasetVersionPage from '../../../frontend/web-ui/src/modules/datasets/pages/DatasetVersionPage.vue'

const api = vi.hoisted(() => ({
  getDatasetWorkspace: vi.fn(),
  getDatasetSample: vi.fn(),
  listDatasetSamples: vi.fn(),
  getDatasetImage: vi.fn(),
}))
vi.mock(
  '../../../frontend/web-ui/src/modules/datasets/services/dataset-workspace.service',
  () => api,
)
vi.mock('../../../frontend/web-ui/src/modules/datasets/annotations', () => ({
  annotationColor: () => '#00cc99',
  annotatedImage: async (blob: Blob) => ({
    blob,
    width: 100,
    height: 80,
    invalid: 0,
  }),
}))
vi.mock('vue-router', () => ({
  useRoute: () => ({
    params: { datasetId: 'd', versionId: 'v' },
    query: { sample: 's' },
  }),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn() }),
}))

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  vi.clearAllMocks()
})
it('检查结果的样本链接在异步加载工作区后打开真实大图，并释放 Blob URL', async () => {
  const sample = {
    sample_id: 's',
    dataset_version_id: 'v',
    file_name: 'real.jpg',
    width: 100,
    height: 80,
    split: 'train',
    annotations: [],
    metadata: {},
  }
  api.getDatasetWorkspace.mockResolvedValue({
    dataset_id: 'd',
    dataset_version_id: 'v',
    project_id: 'p',
    dataset: { display_name: '测试' },
    display_name: '测试',
    task_type: 'detection',
    sample_count: 1,
    category_count: 0,
    object_count: 0,
    categories: [],
    split_counts: { train: 1 },
    metadata: {},
  })
  api.listDatasetSamples.mockResolvedValue({ items: [sample], total: 1 })
  api.getDatasetSample.mockResolvedValue(sample)
  api.getDatasetImage.mockResolvedValue(
    new Blob(['image'], { type: 'image/jpeg' }),
  )
  const create = vi.fn().mockReturnValue('blob:sample'),
    revoke = vi.fn()
  vi.stubGlobal(
    'URL',
    class extends URL {
      static createObjectURL = create
      static revokeObjectURL = revoke
    },
  )
  const wrapper = shallowMount(DatasetVersionPage, {
    global: {
      plugins: [
        createPinia(),
        createI18n({ legacy: false, locale: 'zh-CN', messages: {} }),
      ],
    },
  })
  await flushPromises()
  expect(api.getDatasetSample).toHaveBeenCalledWith('d', 'v', 's')
  expect(wrapper.findComponent({ name: 'DatasetImageViewer' }).props('open')).toBe(
    true,
  )
  expect(
    wrapper.findComponent({ name: 'DatasetImageViewer' }).props('image').title,
  ).toBe('real.jpg')
  wrapper.unmount()
  expect(revoke).toHaveBeenCalledWith('blob:sample')
})
