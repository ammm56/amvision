import { beforeEach, describe, expect, it, vi } from 'vitest'

import { apiRequest } from '@/shared/api/http-client'
import { createWorkflowPreviewRun } from './workflow-runtime.service'

vi.mock('@/shared/api/http-client', () => ({
  apiRequest: vi.fn(),
  apiRequestWithHeaders: vi.fn(),
}))

describe('workflow Preview runtime service', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(apiRequest).mockResolvedValue({} as never)
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
})
