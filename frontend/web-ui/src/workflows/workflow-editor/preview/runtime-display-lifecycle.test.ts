import { describe, expect, it, vi } from 'vitest'
import { useWorkflowPreviewDisplays } from './useWorkflowPreviewDisplays'
import { readProjectObjectContentBlob } from '../services/workflow-runtime.service'
import type { WorkflowPreviewRun } from '../types'

vi.mock('../services/workflow-runtime.service', () => ({
  readProjectObjectContentBlob: vi.fn(), readWorkflowPreviewRunArtifactBlob: vi.fn(),
}))

describe('runtime display lifecycle', () => {
  it('reads full in-memory table rows instead of displaying paging summaries as cells', async () => {
    const view = useWorkflowPreviewDisplays()
    const complete = {type:'table-preview',columns:[{key:'value',label:'Value'}],rows:[{item_id:'weight',value:.6900000000000001}],row_count:1}
    const readMemoryBlob = vi.fn().mockResolvedValue({size:250,text:async()=>JSON.stringify(complete)})
    await view.refreshDisplayOutputs({project_id:'p',preview_run_id:'r',readMemoryBlob},[{nodeId:'table',nodeTypeId:'core.io.value-preview',outputName:'body',payload:{...complete,rows:[{summary:true}],paged:true,value_descriptor:{transport_kind:'preview-memory',blob_id:'current-blob'}}}])
    expect(readMemoryBlob).toHaveBeenCalledWith('current-blob','application/json')
    expect(view.previewNodeDisplays.value.table!.rows).toEqual(complete.rows)
    expect(view.previewNodeDisplays.value.table!.payload.paged).toBeUndefined()
    view.revokePreviewImageObjectUrls()
  })
  it('moves image and its explicit presentation together, then clears both', async () => {
    const view = useWorkflowPreviewDisplays()
    const output = (count: number) => ({ nodeId: 'image', nodeTypeId: 'core.io.image-preview', outputName: 'body', payload: {
      type: 'image-preview', image: { transport_kind: 'inline-base64', image_base64: 'AA==', media_type: 'image/jpeg' },
      presentation: { type: 'value-display', fields: [{ label: 'Count', value: count }] },
    } })
    await view.refreshDisplayOutputs({ project_id: 'p' }, [output(24)], { keyByOutput: true })
    const oldImage = view.previewNodeDisplays.value['["image","body"]']!.image!
    view.openImageViewer(oldImage)
    await view.refreshDisplayOutputs({ project_id: 'p' }, [output(48)], { keyByOutput: true, reopenImageViewerNodeId: 'image' })
    expect(view.activeImageViewer.value?.presentation?.fields).toEqual([{ label: 'Count', value: 48 }])
    expect(oldImage.presentation?.fields).toEqual([{ label: 'Count', value: 24 }])
    view.revokePreviewImageObjectUrls()
    expect(view.activeImageViewer.value).toBeNull()
    expect(view.previewNodeDisplays.value).toEqual({})
  })
  it('refreshes the open image viewer when runtime displays are keyed by output', async () => {
    const view = useWorkflowPreviewDisplays()
    const outputs = [{ nodeId: 'image', nodeTypeId: 'core.io.image-preview', outputName: 'body', payload: { type: 'image-preview', image: { transport_kind: 'inline-base64', image_base64: 'AA==', media_type: 'image/jpeg' } } }]
    await view.refreshDisplayOutputs({ project_id: 'p' }, outputs, { keyByOutput: true })
    view.openImageViewer(view.previewNodeDisplays.value['["image","body"]']!.image)
    await view.refreshDisplayOutputs({ project_id: 'p' }, outputs, { keyByOutput: true, reopenImageViewerNodeId: 'image' })
    expect(view.activeImageViewer.value?.nodeId).toBe('image')
    view.revokePreviewImageObjectUrls()
  })
  it('recognizes Value Display in preview node records as well as runtime outputs', async () => {
    const view = useWorkflowPreviewDisplays()
    await view.refreshPreviewNodeDisplays({ project_id: 'p', node_records: [{ node_id: 'fields', node_type_id: 'core.io.value-display', outputs: { body: { type: 'value-display', fields: [{ label: 'total', value: 24 }] } } }] } as unknown as WorkflowPreviewRun)
    const display = view.previewNodeDisplays.value.fields!
    expect(display.payload.type).toBe('value-display')
    view.openPreviewDisplayViewer(display)
    expect(view.activePreviewJson.value).toBeNull()
    view.revokePreviewImageObjectUrls()
  })
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
