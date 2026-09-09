import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useSessionStore } from './session.store'
import { useProjectStore } from './project.store'
import { getProjectSummary, listProjects } from '@/modules/projects/services/project.service'

vi.mock('@/modules/projects/services/project.service', () => ({
  bootstrapProject: vi.fn(),
  getProjectSummary: vi.fn(),
  listProjects: vi.fn(),
}))

describe('project store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    useSessionStore().currentUser = { principal_id: 'admin', scopes: ['*'], project_ids: [] } as never
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

  it('同一账号缩小项目范围后，迟到列表不能重新填回已清理的项目', async () => {
    let finish!: (value: Awaited<ReturnType<typeof listProjects>>) => void
    vi.mocked(listProjects).mockReturnValue(new Promise(resolve => { finish = resolve }))
    const store = useProjectStore()
    const pending = store.loadProjects()
    useSessionStore().currentUser = { ...useSessionStore().currentUser!, project_ids: ['project-1'] }
    store.$reset()
    finish({ items: [{ project_id: 'revoked-project' }], pagination: {} } as never)
    await pending
    expect(store.projects).toEqual([])
    expect(store.selectedProjectId).not.toBe('revoked-project')
  })

  it('撤销读取操作后，迟到摘要不能恢复受限数据', async () => {
    let finish!: (value: Awaited<ReturnType<typeof getProjectSummary>>) => void
    vi.mocked(getProjectSummary).mockReturnValue(new Promise(resolve => { finish = resolve }))
    const store = useProjectStore()
    store.selectedProjectId = 'project-1'
    const pending = store.loadSummary('project-1')
    useSessionStore().currentUser = { ...useSessionStore().currentUser!, scopes: ['workflows:read'] }
    store.selectedSummary = null
    finish({ project_id: 'project-1' } as never)
    await pending
    expect(store.selectedSummary).toBeNull()
  })
})
