import { expect, it, vi } from 'vitest'
import { flushPromises, shallowMount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import DatasetVersionPanels from '../../../frontend/web-ui/src/modules/datasets/components/DatasetVersionPanels.vue'
const api = vi.hoisted(() => ({
  listDatasetVersionPage: vi.fn(),
  getDatasetCategories: vi.fn(),
  getDatasetReport: vi.fn(),
}))
vi.mock(
  '../../../frontend/web-ui/src/modules/datasets/services/dataset-workspace.service',
  () => api,
)
vi.mock('../../../frontend/web-ui/src/app/stores/session.store', () => ({
  useSessionStore: () => ({ hasScopes: () => true }),
}))
vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn() }) }))
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
