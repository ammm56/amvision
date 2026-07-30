import { describe, expect, it } from 'vitest'

import {
  readPreviewImageInteractionTools,
  updateMaskInteractionTool,
  updatePreviewInteractionParameterDrafts,
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
    } as unknown as PreviewViewerImage

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

  it('restores applied Point, Box, and Polygon collections when reopened', () => {
    const image = {
      interaction: {
        tools: [
          {
            tool: 'positive-point',
            initialPointsXy: [],
          },
          {
            tool: 'negative-point',
            initialPointsXy: [],
          },
          {
            tool: 'bbox',
            collection: true,
            initialBboxesXyxy: [],
          },
          {
            tool: 'polygon',
            collection: true,
            initialPolygonsXy: [],
          },
        ],
      },
    } as unknown as PreviewViewerImage

    expect(updatePreviewInteractionParameterDrafts(image, {
      positive_points_xy: [[10, 20], [30, 40]],
      negative_points_xy: [[50, 60]],
      bboxes_xyxy: [[1, 2, 100, 120], [140, 160, 240, 260]],
      polygons_xy: [
        [[1, 2], [3, 4], [5, 6]],
        [[10, 20], [30, 40], [50, 60]],
      ],
    })).toBe(true)
    expect(image.interaction?.tools[0]?.initialPointsXy).toEqual([
      [10, 20],
      [30, 40],
    ])
    expect(image.interaction?.tools[1]?.initialPointsXy).toEqual([[50, 60]])
    expect(image.interaction?.tools[2]?.initialBboxesXyxy).toEqual([
      [1, 2, 100, 120],
      [140, 160, 240, 260],
    ])
    expect(image.interaction?.tools[3]?.initialPolygonsXy).toEqual([
      [[1, 2], [3, 4], [5, 6]],
      [[10, 20], [30, 40], [50, 60]],
    ])
  })

  it('clears restored collections when the node parameters are cleared', () => {
    const image = {
      interaction: {
        tools: [{
          tool: 'bbox',
          collection: true,
          initialBboxesXyxy: [[1, 2, 3, 4]],
        }],
      },
    } as PreviewViewerImage

    expect(updatePreviewInteractionParameterDrafts(image, {})).toBe(true)
    expect(image.interaction?.tools[0]?.initialBboxesXyxy).toEqual([])
  })
})
