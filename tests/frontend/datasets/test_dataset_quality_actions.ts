import { flushPromises, mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { expect, it, vi } from 'vitest'
import DatasetQualityPanel from '../../../frontend/web-ui/src/modules/datasets/components/DatasetQualityPanel.vue'
import type { DatasetWorkspace } from '../../../frontend/web-ui/src/modules/datasets/services/dataset-workspace.service'

vi.mock('../../../frontend/web-ui/src/modules/datasets/services/dataset-workspace.service', () => ({
  listDatasetJobs: async () => ({ items: [{ task_id: 'q1' }] }),
  getDatasetJob: async () => ({
    task_id: 'q1', state: 'succeeded',
    result: {
      sample_count: 2, issue_count: 2, checked: ['image_size', 'bounding_geometry', 'exact_duplicates'],
      counts: { invalid_geometry: 1, duplicate_image: 1 },
      issues: [{ kind: 'invalid_geometry', sample_id: 's1', file_name: 'edge.jpg', message: '越界' }],
    },
  }),
}))

it('有问题样本时可查看明细；未保留样本时只提供报告，未执行项不显示通过', async () => {
  const page = mount(DatasetQualityPanel, {
    props: { workspace: { dataset_id: 'd', dataset_version_id: 'v', metadata: {} } as DatasetWorkspace },
    global: {
      plugins: [createI18n({ legacy: false, locale: 'zh-CN', messages: {} })],
      stubs: { RouterLink: true, SideDrawer: { props: ['open'], template: '<aside v-if="open"><slot /></aside>' } },
    },
  })
  try {
    await flushPromises()
    const rows = page.findAll('tbody tr')
    const bounds = rows.find(row => row.text().includes('图像尺寸'))!
    expect(bounds.text()).toContain('待复核')
    expect(bounds.get('button').text()).toBe('查看样本')
    await bounds.get('button').trigger('click')
    expect(page.get('aside').text()).toContain('edge.jpg')
    const duplicates = rows.find(row => row.text().includes('重复样本'))!
    expect(duplicates.text()).toContain('待复核')
    expect(duplicates.get('button').text()).toBe('查看报告')
    expect(rows.find(row => row.text().includes('类别引用'))!.text()).toContain('未检查')
  } finally {
    page.unmount()
  }
})
