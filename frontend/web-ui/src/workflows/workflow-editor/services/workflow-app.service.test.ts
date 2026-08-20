import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  getWorkflowApplication,
  listWorkflowApplications,
  listWorkflowAppVersions,
  saveWorkflowApplication,
} from './workflow-application.service'
import { getWorkflowApp, listWorkflowApps, saveWorkflowApp } from './workflow-app.service'
import { listWorkflowAppRuntimes } from './workflow-runtime.service'
import { getWorkflowTemplate } from './workflow-template.service'

vi.mock('./workflow-application.service', () => ({
  getWorkflowApplication: vi.fn(),
  listWorkflowApplications: vi.fn(),
  listWorkflowAppVersions: vi.fn(),
  saveWorkflowApplication: vi.fn(),
}))

vi.mock('./workflow-runtime.service', () => ({
  listWorkflowAppRuntimes: vi.fn(),
}))

vi.mock('./workflow-template.service', () => ({
  getWorkflowTemplate: vi.fn(),
  saveWorkflowTemplate: vi.fn(),
}))

const pagination = {
  offset: 0,
  limit: 25,
  totalCount: 2,
  hasMore: false,
  nextOffset: null,
}

function version(id: string, versionNumber: number, state: 'published' | 'archived') {
  return {
    workflow_app_version_id: id,
    version_number: versionNumber,
    display_version: `v${versionNumber}`,
    state,
  }
}

describe('workflow app aggregate service', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(getWorkflowApplication).mockResolvedValue({
      application: {
        application_id: 'app-1',
        template_ref: { template_id: 'graph-1', template_version: '1.0.0' },
      },
    } as never)
    vi.mocked(getWorkflowTemplate).mockResolvedValue({ template: {} } as never)
    vi.mocked(listWorkflowAppRuntimes).mockResolvedValue({ items: [], pagination } as never)
  })

  it('saves the editor Application and Template through one bundle request', async () => {
    const template = {
      template_id: 'graph-1',
      template_version: '1.0.0',
    }
    const application = {
      application_id: 'app-1',
      template_ref: {
        template_id: 'stale-graph',
        template_version: '0.9.0',
      },
    }
    const savedTemplate = { template }
    vi.mocked(saveWorkflowApplication).mockResolvedValue({
      application: {
        ...application,
        template_ref: {
          template_id: 'graph-1',
          template_version: '1.0.0',
        },
      },
      saved_template: savedTemplate,
    } as never)

    const result = await saveWorkflowApp({
      projectId: 'project-1',
      application: application as never,
      template: template as never,
    })

    expect(saveWorkflowApplication).toHaveBeenCalledTimes(1)
    expect(saveWorkflowApplication).toHaveBeenCalledWith(
      'project-1',
      expect.objectContaining({
        application_id: 'app-1',
        template_ref: expect.objectContaining({
          template_id: 'graph-1',
          template_version: '1.0.0',
        }),
      }),
      template,
    )
    expect(result.graphDocument).toBe(savedTemplate)
  })

  it('loads a bounded first version page and never treats an archived version as latest', async () => {
    const archived = version('version-3', 3, 'archived')
    const published = version('version-2', 2, 'published')
    vi.mocked(listWorkflowAppVersions).mockResolvedValue({
      items: [archived, published],
      pagination,
    } as never)

    const result = await getWorkflowApp('project-1', 'app-1')

    expect(listWorkflowAppRuntimes).toHaveBeenCalledWith({
      projectId: 'project-1',
      applicationId: 'app-1',
      offset: 0,
      limit: 100,
    })
    expect(listWorkflowAppVersions).toHaveBeenCalledWith('project-1', 'app-1', { limit: 25 })
    expect(result.latestVersion?.workflow_app_version_id).toBe('version-2')
    expect(result.versionPagination).toEqual(pagination)
  })

  it('reports no latest published version when the loaded page contains archived versions only', async () => {
    vi.mocked(listWorkflowAppVersions).mockResolvedValue({
      items: [version('version-3', 3, 'archived')],
      pagination: { ...pagination, totalCount: 1 },
    } as never)

    const result = await getWorkflowApp('project-1', 'app-1')

    expect(result.latestVersion).toBeNull()
  })

  it('resolves the latest published version sequentially when newer archived versions fill the first page', async () => {
    const archivedPage = {
      ...pagination,
      totalCount: 26,
      hasMore: true,
      nextOffset: 25,
    }
    const published = version('version-1', 1, 'published')
    vi.mocked(listWorkflowAppVersions)
      .mockResolvedValueOnce({ items: [version('version-26', 26, 'archived')], pagination: archivedPage } as never)
      .mockResolvedValueOnce({
        items: [published],
        pagination: { ...pagination, offset: 25, limit: 25, totalCount: 26 },
      } as never)

    const result = await getWorkflowApp('project-1', 'app-1')

    expect(listWorkflowAppVersions).toHaveBeenNthCalledWith(2, 'project-1', 'app-1', { offset: 25, limit: 25 })
    expect(result.latestVersion?.workflow_app_version_id).toBe('version-1')
    expect(result.versions.map((item) => item.workflow_app_version_id)).toContain('version-1')
  })

  it('loads every Runtime for the exact application across more than 100 records', async () => {
    const firstPageRuntimes = Array.from({ length: 100 }, (_, index) => ({
      workflow_runtime_id: `runtime-${index}`,
      application_id: 'app-1',
      observed_state: 'stopped',
    }))
    vi.mocked(listWorkflowAppRuntimes)
      .mockResolvedValueOnce({
        items: firstPageRuntimes,
        pagination: {
          offset: 0,
          limit: 100,
          totalCount: 101,
          hasMore: true,
          nextOffset: 100,
        },
      } as never)
      .mockResolvedValueOnce({
        items: [{
          workflow_runtime_id: 'runtime-100',
          application_id: 'app-1',
          observed_state: 'stopped',
        }],
        pagination: {
          offset: 100,
          limit: 100,
          totalCount: 101,
          hasMore: false,
          nextOffset: null,
        },
      } as never)
    vi.mocked(listWorkflowAppVersions).mockResolvedValue({
      items: [version('version-1', 1, 'published')],
      pagination: { ...pagination, totalCount: 1 },
    } as never)

    const result = await getWorkflowApp('project-1', 'app-1')

    expect(result.runtimes).toHaveLength(101)
    expect(listWorkflowAppRuntimes).toHaveBeenNthCalledWith(1, {
      projectId: 'project-1',
      applicationId: 'app-1',
      offset: 0,
      limit: 100,
    })
    expect(listWorkflowAppRuntimes).toHaveBeenNthCalledWith(2, {
      projectId: 'project-1',
      applicationId: 'app-1',
      offset: 100,
      limit: 100,
    })
  })

  it('loads all Runtime records only for applications on the current list page', async () => {
    vi.mocked(listWorkflowApplications).mockResolvedValue({
      items: [
        { application_id: 'app-1' },
        { application_id: 'app-2' },
      ],
      pagination,
    } as never)
    vi.mocked(listWorkflowAppRuntimes)
      .mockResolvedValueOnce({
        items: Array.from({ length: 100 }, (_, index) => ({
          workflow_runtime_id: `runtime-${index}`,
          application_id: index % 2 === 0 ? 'app-1' : 'app-2',
          observed_state: 'stopped',
        })),
        pagination: {
          offset: 0,
          limit: 100,
          totalCount: 101,
          hasMore: true,
          nextOffset: 100,
        },
      } as never)
      .mockResolvedValueOnce({
        items: [{
          workflow_runtime_id: 'runtime-100',
          application_id: 'app-2',
          observed_state: 'stopped',
        }],
        pagination: {
          offset: 100,
          limit: 100,
          totalCount: 101,
          hasMore: false,
          nextOffset: null,
        },
      } as never)

    const result = await listWorkflowApps('project-1', { offset: 25, limit: 25 })

    expect(result.runtimes).toHaveLength(101)
    expect(listWorkflowAppRuntimes).toHaveBeenNthCalledWith(1, {
      projectId: 'project-1',
      applicationIds: ['app-1', 'app-2'],
      offset: 0,
      limit: 100,
    })
    expect(listWorkflowAppRuntimes).toHaveBeenNthCalledWith(2, {
      projectId: 'project-1',
      applicationIds: ['app-1', 'app-2'],
      offset: 100,
      limit: 100,
    })
    expect(result.items[0]?.runtimes).toHaveLength(50)
    expect(result.items[1]?.runtimes).toHaveLength(51)
  })
})
