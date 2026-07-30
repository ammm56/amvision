import { describe, expect, it } from 'vitest'

import { normalizeImageInteractionTool } from './normalizeImageInteractionTool'

describe('normalizeImageInteractionTool', () => {
  it('preserves Mask-specific state while normalizing common fields', () => {
    const [tool] = normalizeImageInteractionTool({
      tool: 'mask',
      targetParameters: ['mask_object_key', 'mask_source_identity'],
      brushSize: 24,
      maskObjectKey: 'projects/project-1/mask.png',
      sourceIdentity: 'content_sha256:abc123',
      maskSrc: 'blob:stored-mask',
      applyParameters: { extra: true },
    }, {
      isSupported: () => true,
      fallbackLabel: () => 'Mask',
    })

    expect(tool).toMatchObject({
      tool: 'mask',
      label: 'Mask',
      brushSize: 24,
      maskObjectKey: 'projects/project-1/mask.png',
      sourceIdentity: 'content_sha256:abc123',
      maskSrc: 'blob:stored-mask',
      applyParameters: { extra: true },
    })
  })

  it('rejects unsupported tools and tools without target parameters', () => {
    expect(normalizeImageInteractionTool({
      tool: 'unknown',
      targetParameters: ['value'],
    }, {
      isSupported: () => false,
      fallbackLabel: (tool) => tool,
    })).toEqual([])
    expect(normalizeImageInteractionTool({
      tool: 'mask',
      targetParameters: [],
    }, {
      isSupported: () => true,
      fallbackLabel: (tool) => tool,
    })).toEqual([])
  })
})
