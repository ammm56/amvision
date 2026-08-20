import { beforeEach, describe, expect, it, vi } from 'vitest'

import { apiRequest, apiRequestWithHeaders } from '@/shared/api/http-client'
import {
  compareWorkflowAppVersionToDraft,
  listWorkflowAppVersions,
  publishWorkflowAppVersion,
  transitionWorkflowAppVersionState,
} from './workflow-application.service'

vi.mock('@/shared/api/http-client', () => ({
  apiRequest: vi.fn(),
  apiRequestWithHeaders: vi.fn(),
}))

describe('workflow application version service', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(apiRequest).mockResolvedValue({} as never)
    vi.mocked(apiRequestWithHeaders).mockResolvedValue({
      payload: [],
      headers: new Headers({ 'x-total-count': '0' }),
    } as never)
  })

  it('publishes the exact draft fingerprint with release metadata', async () => {
    await publishWorkflowAppVersion('project one', 'app/one', {
      expectedDraftFingerprint: 'sha256:draft',
      displayVersion: '2026.08.19',
      releaseNotes: 'validated production release',
    })

    const [path, options] = vi.mocked(apiRequest).mock.calls[0]
    expect(path).toBe('/workflows/projects/project%20one/applications/app%2Fone/versions')
    expect(options?.body).toEqual({
      expected_draft_fingerprint: 'sha256:draft',
      release_notes: 'validated production release',
      display_version: '2026.08.19',
      allow_duplicate_content: false,
    })
  })

  it('lists immutable versions and compares one version to the current draft', async () => {
    await listWorkflowAppVersions('project-1', 'app-1', { offset: 10, limit: 20 })
    await compareWorkflowAppVersionToDraft('project-1', 'app-1', 'version-2')

    expect(vi.mocked(apiRequestWithHeaders).mock.calls[0]).toEqual([
      '/workflows/projects/project-1/applications/app-1/versions',
      { query: { offset: 10, limit: 20 } },
    ])
    expect(vi.mocked(apiRequest).mock.calls[0]?.[0]).toBe(
      '/workflows/projects/project-1/applications/app-1/versions/version-2/compare',
    )
  })

  it('archives and restores versions with an explicit expected-state CAS', async () => {
    await transitionWorkflowAppVersionState('project one', 'app/one', 'version 2', 'archive')
    await transitionWorkflowAppVersionState('project one', 'app/one', 'version 2', 'restore')

    expect(vi.mocked(apiRequest).mock.calls[0]).toEqual([
      '/workflows/projects/project%20one/applications/app%2Fone/versions/version%202/archive',
      { method: 'POST', body: { expected_state: 'published' } },
    ])
    expect(vi.mocked(apiRequest).mock.calls[1]).toEqual([
      '/workflows/projects/project%20one/applications/app%2Fone/versions/version%202/restore',
      { method: 'POST', body: { expected_state: 'archived' } },
    ])
  })
})
