import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useProjectStore } from './project.store'
import { listProjects } from '@/modules/projects/services/project.service'

vi.mock('@/modules/projects/services/project.service', () => ({
  bootstrapProject: vi.fn(),
  getProjectSummary: vi.fn(),
  listProjects: vi.fn(),
}))

describe('project store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('已选项目删除后回退到仍存在的首个项目', async () => {
    vi.mocked(listProjects).mockResolvedValue({
      items: [
        {
          project_id: 'project-3',
          display_name: 'Project 3',
          description: null,
          metadata: {},
          project_source: 'local_disk',
          storage_prefix: 'projects/project-3',
        },
      ],
      pagination: { offset: 0, limit: 100, totalCount: 1, hasMore: false, nextOffset: null },
    })
    const store = useProjectStore()
    store.selectedProjectId = 'deleted-project'

    await store.loadProjects()

    expect(store.selectedProjectId).toBe('project-3')
  })

  it('项目列表为空时不保留不存在的默认项目', async () => {
    vi.mocked(listProjects).mockResolvedValue({
      items: [],
      pagination: { offset: 0, limit: 100, totalCount: 0, hasMore: false, nextOffset: null },
    })
    const store = useProjectStore()

    await store.loadProjects()

    expect(store.selectedProjectId).toBe('')
    expect(store.selectedSummary).toBeNull()
  })
})
