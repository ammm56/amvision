import { afterEach, expect, it, vi } from 'vitest'
import { flushPromises, shallowMount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { createPinia } from 'pinia'
import { reactive } from 'vue'
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
const router = vi.hoisted(() => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn() }))
const route = reactive({ params: { datasetId: 'd', versionId: 'v' }, query: { sample: 's' } as Record<string, string> })
vi.mock('vue-router', () => ({ useRoute: () => route, useRouter: () => router }))

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  vi.clearAllMocks()
  route.query = { sample: 's' }
  history.replaceState({}, '')
})
async function render() {
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
  return { wrapper, revoke }
}
it('检查结果的样本链接在异步加载工作区后打开真实大图，并释放 Blob URL', async () => {
  const { wrapper, revoke } = await render()
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

it.each(['compare', 'quality'])('从 %s 任务打开的样本返回原任务及其筛选分页', async operation => {
  const origin = `/datasets/d/versions/left/tools/${operation}?task=t&diff=modified&diffOffset=4`
  history.replaceState({ datasetReturnTo: origin, back: origin }, '')
  const { wrapper } = await render()
  wrapper.findComponent({ name: 'DatasetImageViewer' }).vm.$emit('close')
  expect(router.back).toHaveBeenCalledOnce()
  expect(router.push).not.toHaveBeenCalled()
  wrapper.unmount()
})

it('刷新后历史来源不相邻时替换为原任务，直接链接则保留筛选并移除 sample', async () => {
  const origin = '/datasets/d/versions/left/tools/compare?task=t'
  history.replaceState({ datasetReturnTo: origin, back: '/datasets' }, '')
  const { wrapper } = await render()
  wrapper.findComponent({ name: 'DatasetImageViewer' }).vm.$emit('close')
  expect(router.replace).toHaveBeenLastCalledWith(origin)
  history.replaceState({}, '')
  route.query = { sample: 'next', category: '0', tab: 'quality' }
  await flushPromises()
  wrapper.findComponent({ name: 'DatasetImageViewer' }).vm.$emit('close')
  expect(router.replace).toHaveBeenLastCalledWith({ query: { sample: undefined, category: '0', tab: 'quality' } })
  wrapper.unmount()
})

it('浏览器前进后退同步同一版本的样本预览，不重新加载整个工作区', async () => {
  const { wrapper } = await render()
  route.query = {}
  await flushPromises()
  expect(wrapper.findComponent({ name: 'DatasetImageViewer' }).exists()).toBe(false)
  route.query = { sample: 'next' }
  await flushPromises()
  expect(api.getDatasetSample).toHaveBeenLastCalledWith('d', 'v', 'next')
  expect(wrapper.findComponent({ name: 'DatasetImageViewer' }).props('open')).toBe(true)
  expect(api.getDatasetWorkspace).toHaveBeenCalledTimes(1)
  wrapper.unmount()
})

it('比较页打开版本后，版本页返回仍回到原比较页', async () => {
  route.query = {}
  const origin = '/datasets/d/versions/left/tools/compare?task=t&diffOffset=4'
  history.replaceState({ datasetReturnTo: origin, back: origin }, '')
  const { wrapper } = await render()
  wrapper.findAllComponents({ name: 'Button' })[0].vm.$emit('click')
  expect(router.back).toHaveBeenCalledOnce()
  wrapper.unmount()
})
