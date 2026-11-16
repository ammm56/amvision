import { expect, it, vi } from 'vitest'
import { flushPromises, shallowMount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import DatasetVersionPanels from '../../../frontend/web-ui/src/modules/datasets/components/DatasetVersionPanels.vue'
const api = vi.hoisted(() => ({
  listDatasetVersionPage: vi.fn(),
  getDatasetCategories: vi.fn(),
  getDatasetReport: vi.fn(),
}))
const navigation = vi.hoisted(() => ({ push: vi.fn() }))
vi.mock(
  '../../../frontend/web-ui/src/modules/datasets/services/dataset-workspace.service',
  () => api,
)
vi.mock('../../../frontend/web-ui/src/app/stores/session.store', () => ({
  useSessionStore: () => ({ hasScopes: () => true }),
}))
vi.mock('vue-router', () => ({ useRouter: () => navigation }))
it('版本列表翻页再返回会恢复正确页，而不是沿用最后一页缓存', async () => {
  api.listDatasetVersionPage.mockImplementation(({ offset }) =>
    Promise.resolve({
      total: 22,
      items: [
        {
          dataset_version_id: `v-${offset}`,
          version_number: offset + 1,
          metadata: {},
        },
      ],
    }),
  )
  const w = shallowMount(DatasetVersionPanels, {
    props: {
      tab: 'lineage',
      workspace: {
        dataset_id: 'd',
        dataset_version_id: 'v',
        project_id: 'p',
        version_number: 1,
        metadata: {},
      } as any,
    },
    global: {
      plugins: [createI18n({ legacy: false, locale: 'zh-CN', messages: {} })],
      renderStubDefaultSlot: true,
    },
  })
  await flushPromises()
  const pager = w.findComponent({ name: 'PaginationControls' })
  pager.vm.$emit('next')
  await flushPromises()
  expect(w.text()).toContain('v21')
  pager.vm.$emit('previous')
  await flushPromises()
  expect(w.text()).not.toContain('v21')
  expect(api.listDatasetVersionPage.mock.calls.map((c) => c[0].offset)).toEqual(
    [0, 20, 0],
  )
  w.unmount()
})

it('类别计数不累加重叠图像，未配置划分不显示为零，查看样本带正确类别', async () => {
  api.getDatasetCategories.mockResolvedValue({ items: [
    { category_id: 4, name: 'bolt', sample_count: 9, object_count: 12, split_objects: { train: 12 } },
    { category_id: 8, name: 'nut', sample_count: 6, object_count: 7, split_objects: { train: 7 } },
  ] })
  const page = shallowMount(DatasetVersionPanels, {
    props: { tab: 'categories', workspace: { dataset_id: 'd', dataset_version_id: 'v', project_id: 'p', metadata: {}, sample_count: 10, split_counts: { train: 10 } } as any },
    global: { plugins: [createI18n({ legacy: false, locale: 'zh-CN', messages: {} })], renderStubDefaultSlot: true },
  })
  await flushPromises()
  expect(page.get('tfoot').text()).toContain('合计—1919——')
  expect(page.findAll('tbody')[1].text()).toContain('val未配置——')
  page.findAllComponents({ name: 'Button' })[1].vm.$emit('click')
  expect(page.emitted('filter')).toEqual([[{ category: 8 }]])
  page.unmount()
})

it('历史行切换保留当前页签，当前版本也可以打开比较选择，更多操作使用该行版本', async () => {
  api.listDatasetVersionPage.mockResolvedValue({ total: 2, items: [
    { dataset_version_id: 'v2', version_number: 2, metadata: {} },
    { dataset_version_id: 'v1', version_number: 1, metadata: {} },
  ] })
  const page = shallowMount(DatasetVersionPanels, {
    props: { tab: 'lineage', workspace: { dataset_id: 'd', dataset_version_id: 'v2', project_id: 'p', metadata: {} } as any },
    global: { plugins: [createI18n({ legacy: false, locale: 'zh-CN', messages: {} })], renderStubDefaultSlot: true },
  })
  await flushPromises()
  await page.get('[aria-label="切换到 v1"]').trigger('click')
  expect(page.emitted('version')).toEqual([['v1', true]])
  await page.findAll('.version-row-actions')[0].findAll('button')[1].trigger('click')
  expect(navigation.push).toHaveBeenLastCalledWith({ path: '/datasets/d/versions/v2/tools/compare', query: {} })
  page.findAllComponents({ name: 'ResourceMenu' })[1].vm.$emit('action', 'export')
  expect(navigation.push).toHaveBeenLastCalledWith({ path: '/datasets/export', query: { dataset: 'd', version: 'v1' } })
  page.unmount()
})
