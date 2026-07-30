import { describe, expect, it } from 'vitest'

import {
  readPreviewImageInteractionTools,
  updateMaskInteractionTool,
  type PreviewViewerImage,
} from './useWorkflowPreviewDisplays'

describe('Workflow Preview image interaction tools', () => {
  it('keeps the explicit Mask source identity and current stored Mask', () => {
    const tools = readPreviewImageInteractionTools([{
      tool: 'mask',
      label: 'Mask',
      target_parameters: ['mask_object_key', 'mask_source_identity'],
      source_identity: 'content_sha256:abc123',
      mask_object_key: 'projects/project-1/mask.png',
      source_changed: false,
      applied: true,
    }])

    expect(tools).toHaveLength(1)
    expect(tools[0]).toMatchObject({
      tool: 'mask',
      sourceIdentity: 'content_sha256:abc123',
      maskObjectKey: 'projects/project-1/mask.png',
    })
  })

  it('does not infer a binding from generic apply parameters', () => {
    const tools = readPreviewImageInteractionTools([{
      tool: 'mask',
      target_parameters: ['mask_object_key', 'mask_source_identity'],
      apply_parameters: {
        mask_source_identity: 'content_sha256:legacy',
      },
    }])

    expect(tools[0]?.sourceIdentity).toBeNull()
  })

  it('replaces the stored Mask used when the editor is opened again', () => {
    const image = {
      interaction: {
        tools: [{
          tool: 'mask',
          maskObjectKey: 'projects/project-1/old-mask.png',
          maskSrc: 'blob:old-mask',
        }],
      },
    } as PreviewViewerImage

    expect(updateMaskInteractionTool(
      image,
      'projects/project-1/new-mask.png',
      'blob:new-mask',
    )).toBe(true)
    expect(image.interaction?.tools[0]).toMatchObject({
      maskObjectKey: 'projects/project-1/new-mask.png',
      maskSrc: 'blob:new-mask',
    })
  })
})
