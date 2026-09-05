import { describe, expect, it, vi } from 'vitest'
import { useWorkflowPreviewDisplays } from './useWorkflowPreviewDisplays'
import { readProjectObjectContentBlob } from '../services/workflow-runtime.service'

vi.mock('../services/workflow-runtime.service', () => ({
  readProjectObjectContentBlob: vi.fn(), readWorkflowPreviewRunArtifactBlob: vi.fn(),
}))

describe('runtime display lifecycle', () => {
  it('keeps two explicit ports of one preview node distinct', async () => {
    const view = useWorkflowPreviewDisplays()
    await view.refreshDisplayOutputs({ project_id: 'p' }, ['a', 'b'].map((port) => ({
      nodeId: 'node', nodeTypeId: 'custom.preview', outputName: port,
      payload: { type: 'value-preview', value: port },
    })), { keyByOutput: true })
    expect(Object.values(view.previewNodeDisplays.value).map((item) => item.outputName)).toEqual(['a', 'b'])
    view.revokePreviewImageObjectUrls()
    expect(view.previewNodeDisplays.value).toEqual({})
  })

  it('aborts an old image fetch and never resurrects its display after close', async () => {
    const view = useWorkflowPreviewDisplays()
    const signals: AbortSignal[] = []
    vi.mocked(readProjectObjectContentBlob).mockImplementation((_project, _key, signal) => {
      signals.push(signal!)
      if (signal!.aborted) return Promise.reject(new DOMException('aborted', 'AbortError'))
      return new Promise((_resolve, reject) => signal!.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError'))))
    })
    const pending = view.refreshDisplayOutputs({ project_id: 'p' }, [{
      nodeId: 'image', nodeTypeId: 'core.io.image-preview', outputName: 'body',
      payload: { type: 'image-preview', image: { transport_kind: 'storage-ref', object_key: 'projects/p/image.jpg' } },
    }])
    expect(signals.length).toBeGreaterThan(0)
    view.revokePreviewImageObjectUrls()
    expect(signals.every((signal) => signal.aborted)).toBe(true)
    await pending
    expect(view.previewNodeDisplays.value).toEqual({})
  })

  it('disables gallery editing in a readonly display context', async () => {
    const view = useWorkflowPreviewDisplays()
    await view.refreshDisplayOutputs({ project_id: 'p', readonly: true }, [{
      nodeId: 'gallery', nodeTypeId: 'custom.preview', outputName: 'body',
      payload: { type: 'gallery-preview', items: [{
        image: { image_base64: 'AA==', media_type: 'image/png', transport_kind: 'inline-base64' },
        interaction: { mode: 'image-edit', coordinate_space: 'image', tools: [{ tool: 'bbox', target_parameters: ['roi'] }] },
      }] },
    }])
    expect(view.previewNodeDisplays.value.gallery!.galleryItems[0]!.interaction).toBeNull()
    view.revokePreviewImageObjectUrls()
  })
})
