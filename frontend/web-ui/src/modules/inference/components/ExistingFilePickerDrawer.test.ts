import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { i18n } from '@/platform/i18n'
import {
  getDatasetImage,
  listDatasetCatalog,
  listDatasetSamples,
  listDatasetVersionPage,
} from '@/modules/datasets/services/dataset-workspace.service'
import { fetchAuthorizedProjectFileBlob, listProjectPublicFiles } from '../services/inference.service'
import ExistingFilePickerDrawer from './ExistingFilePickerDrawer.vue'

vi.mock('@/modules/datasets/services/dataset-workspace.service', () => ({
  listDatasetCatalog: vi.fn(),
  listDatasetVersionPage: vi.fn(),
  listDatasetSamples: vi.fn(),
  getDatasetImage: vi.fn(),
}))

vi.mock('../services/inference.service', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../services/inference.service')>()
  return {
    ...actual,
    listProjectPublicFiles: vi.fn(),
    fetchAuthorizedProjectFileBlob: vi.fn(),
    getDatasetSampleFileRef: vi.fn(),
  }
})

describe('ExistingFilePickerDrawer', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    const mockVersion = {
      dataset_version_id: 'ver-1',
      dataset_id: 'ds-1',
      project_id: 'project-1',
      version_number: 1,
      display_name: 'v1',
      task_type: 'detection',
      sample_count: 32,
      object_count: 32,
      category_count: 1,
      split_counts: { train: 32 },
      created_at: '2026-11-27T00:00:00Z',
      metadata: {},
    }
    vi.mocked(listDatasetCatalog).mockResolvedValue({
      items: [
        {
          dataset_id: 'ds-1',
          project_id: 'project-1',
          display_name: '4570托盘',
          description: '',
          task_type: 'detection',
          created_at: '2026-11-27T00:00:00Z',
          updated_at: '2026-11-27T00:00:00Z',
          revision: 'rev-1',
          latest_version: mockVersion,
        },
      ],
      total: 1,
      offset: 0,
      limit: 100,
    })
    vi.mocked(listDatasetVersionPage).mockResolvedValue({
      items: [mockVersion],
      total: 1,
      offset: 0,
      limit: 50,
    })
    vi.mocked(listDatasetSamples).mockResolvedValue({
      items: Array.from({ length: 16 }, (_, idx) => ({
        sample_id: `s-${idx + 1}`,
        dataset_version_id: 'ver-1',
        image_id: idx + 1,
        file_name: `sample-${idx + 1}.jpg`,
        split: 'train',
        width: 130,
        height: 140,
        annotations: [],
        metadata: {},
      })),
      total: 32,
      offset: 0,
      limit: 16,
    })
    vi.mocked(getDatasetImage).mockRejectedValue(new DOMException('Aborted', 'AbortError'))
    vi.mocked(listProjectPublicFiles).mockResolvedValue([])
    vi.mocked(fetchAuthorizedProjectFileBlob).mockResolvedValue(new Blob(['img'], { type: 'image/png' }))
  })

  it('opens centered modal on 数据集样本 tab by default and paginates server-side', async () => {
    const wrapper = mount(ExistingFilePickerDrawer, {
      props: { open: false, projectId: 'project-1' },
      global: { plugins: [i18n], stubs: { Teleport: true } },
    })

    await wrapper.setProps({ open: true })
    await flushPromises()

    expect(wrapper.find('.inf-picker-modal').exists()).toBe(true)
    expect(wrapper.findAll('.inf-sample-card')).toHaveLength(16)
    expect(wrapper.text()).toContain('共 32 张图像')

    const nextBtn = wrapper
      .findAll('.inf-picker-modal__pagination button')
      .find((b) => b.text().includes('下一页') || b.text().includes('Next'))
    await nextBtn?.trigger('click')
    await flushPromises()

    expect(listDatasetSamples).toHaveBeenLastCalledWith(
      'ds-1',
      'ver-1',
      expect.objectContaining({ offset: 16, limit: 16 }),
    )
  })

  it('queries inputs and results prefixes cleanly on 项目文件 tab and paginates', async () => {
    vi.mocked(listProjectPublicFiles).mockImplementation(async (_pid, opts) => {
      if (opts?.objectPrefix?.endsWith('/inputs')) {
        return Array.from({ length: 20 }, (_, i) => ({
          project_id: 'project-1',
          file_id: `f-${i + 1}`,
          object_key: `projects/project-1/inputs/img-${i + 1}.png`,
          file_name: `img-${i + 1}.png`,
          media_type: 'image/png',
          size_bytes: 1024,
          last_modified_at: '2026-11-27T00:00:00Z',
          content_url: '',
          download_url: '',
        }))
      }
      return []
    })

    const wrapper = mount(ExistingFilePickerDrawer, {
      props: { open: false, projectId: 'project-1' },
      global: { plugins: [i18n], stubs: { Teleport: true } },
    })
    await wrapper.setProps({ open: true })
    await flushPromises()

    const projectTab = wrapper.findAll('.inf-picker-modal__tab').find((b) => b.text() === '项目文件')
    await projectTab?.trigger('click')
    await flushPromises()

    expect(listProjectPublicFiles).toHaveBeenCalledWith('project-1', {
      objectPrefix: 'projects/project-1/inputs',
      limit: 200,
    })
    expect(listProjectPublicFiles).toHaveBeenCalledWith('project-1', {
      objectPrefix: 'projects/project-1/results',
      limit: 200,
    })
    expect(wrapper.findAll('.inf-sample-card')).toHaveLength(16)
    expect(wrapper.text()).toContain('共 20 个图像文件')
  })
})
