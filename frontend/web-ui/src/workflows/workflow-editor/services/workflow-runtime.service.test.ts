import { beforeEach, describe, expect, it, vi } from 'vitest'

import { apiRequest, apiRequestWithHeaders } from '@/shared/api/http-client'
import {
  createWorkflowAppRuntime,
  createWorkflowPreviewRun,
  listWorkflowAppRuntimes,
  selectWorkflowAppRuntimeVersion,
} from './workflow-runtime.service'

vi.mock('@/shared/api/http-client', () => ({
  apiRequest: vi.fn(),
  apiRequestWithHeaders: vi.fn(),
}))

describe('workflow Preview runtime service', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(apiRequest).mockResolvedValue({} as never)
    vi.mocked(apiRequestWithHeaders).mockResolvedValue({
      payload: [],
      headers: new Headers({
        'x-offset': '0',
        'x-limit': '100',
        'x-total-count': '0',
        'x-has-more': 'false',
      }),
    } as never)
  })

  it('uploads Preview images as multipart files bound to image-ref inputs', async () => {
    const imageFile = new File(['bmp-bytes'], 'tray.bmp', { type: 'image/bmp' })

    await createWorkflowPreviewRun({
      projectId: 'project-1',
      applicationId: 'app-1',
      inputBindings: { threshold: { value: 0.5 } },
      imageUploads: [{ bindingId: 'request_image_ref', file: imageFile }],
    })

    const [path, options] = vi.mocked(apiRequest).mock.calls[0]
    expect(path).toBe('/workflows/preview-runs/multipart')
    expect(options?.method).toBe('POST')
    expect(options?.body).toBeInstanceOf(FormData)
    const form = options?.body as FormData
    const request = JSON.parse(String(form.get('request'))) as Record<string, unknown>
    expect(request.input_bindings).toEqual({ threshold: { value: 0.5 } })
    expect(form.getAll('image_binding_id')).toEqual(['request_image_ref'])
    const submittedFile = form.get('image_file') as File
    expect(submittedFile.name).toBe('tray.bmp')
    expect(submittedFile.type).toBe('image/bmp')
    expect(submittedFile.size).toBe(imageFile.size)
  })

  it('keeps JSON transport when Preview has no image upload', async () => {
    await createWorkflowPreviewRun({
      projectId: 'project-1',
      applicationId: 'app-1',
      inputBindings: { value: { value: 'ok' } },
    })

    const [path, options] = vi.mocked(apiRequest).mock.calls[0]
    expect(path).toBe('/workflows/preview-runs')
    expect(options?.body).not.toBeInstanceOf(FormData)
  })

  it('creates new runtimes from an explicit immutable app version', async () => {
    await createWorkflowAppRuntime({
      projectId: 'project-1',
      workflowAppVersionId: 'workflow-app-version-v2',
      displayName: 'Stable runtime',
    })

    const [path, options] = vi.mocked(apiRequest).mock.calls[0]
    expect(path).toBe('/workflows/app-runtimes')
    expect(options?.body).toMatchObject({
      project_id: 'project-1',
      application_id: null,
      workflow_app_version_id: 'workflow-app-version-v2',
      display_name: 'Stable runtime',
    })
  })

  it('passes the exact application filter to the Runtime list endpoint', async () => {
    await listWorkflowAppRuntimes({
      projectId: 'project one',
      applicationId: 'app/one',
      offset: 100,
      limit: 50,
    })

    expect(vi.mocked(apiRequestWithHeaders)).toHaveBeenCalledWith('/workflows/app-runtimes', {
      query: {
        project_id: 'project one',
        application_id: 'app/one',
        offset: 100,
        limit: 50,
      },
    })
  })

  it('passes an application id set to the Runtime list endpoint', async () => {
    await listWorkflowAppRuntimes({
      projectId: 'project-1',
      applicationIds: ['app-1', 'app-2'],
      offset: 0,
      limit: 100,
    })

    expect(vi.mocked(apiRequestWithHeaders)).toHaveBeenCalledWith('/workflows/app-runtimes', {
      query: {
        project_id: 'project-1',
        application_ids: 'app-1,app-2',
        offset: 0,
        limit: 100,
      },
    })
  })

  it('selects a stopped runtime version with generation CAS and explicit breaking reason', async () => {
    await selectWorkflowAppRuntimeVersion('runtime-stable', {
      workflowAppVersionId: 'workflow-app-version-v3',
      expectedGeneration: 2,
      allowBreakingContract: true,
      breakingChangeReason: 'external client migration approved',
    })

    const [path, options] = vi.mocked(apiRequest).mock.calls[0]
    expect(path).toBe('/workflows/app-runtimes/runtime-stable/select-version')
    expect(options?.body).toEqual({
      workflow_app_version_id: 'workflow-app-version-v3',
      expected_generation: 2,
      allow_breaking_contract: true,
      breaking_change_reason: 'external client migration approved',
    })
  })
})
