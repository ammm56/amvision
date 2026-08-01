import { describe, expect, it } from 'vitest'

import {
  compareNodeCategories,
  readNodeCategoryLabel,
  readNodeCategoryParts,
  readNodeVisualCategory,
} from './node-taxonomy'

describe('workflow node taxonomy', () => {
  it('shows a root heading and a concise child category', () => {
    expect(readNodeCategoryParts('core.model.inference')).toEqual({
      rootId: 'model',
      rootLabel: 'Model',
      childLabel: 'Inference',
    })
    expect(readNodeCategoryParts('opencv.image.color')).toEqual({
      rootId: 'image',
      rootLabel: 'Image',
      childLabel: 'Color',
    })
    expect(readNodeCategoryLabel('opencv.matching.registration')).toBe('Matching / Registration')
    expect(readNodeCategoryLabel('core.vision.roi')).toBe('Vision / ROI')
  })

  it('uses the confirmed OpenCV category order', () => {
    const categories = [
      'opencv.output.workflow',
      'opencv.image.color',
      'opencv.measurement.geometry',
    ]

    expect(categories.sort((left, right) => compareNodeCategories('custom:opencv.nodes', left, right))).toEqual([
      'opencv.image.color',
      'opencv.measurement.geometry',
      'opencv.output.workflow',
    ])
  })

  it('maps node definitions to stable visual categories', () => {
    expect(readNodeVisualCategory('core.io.image')).toBe('input-output')
    expect(readNodeVisualCategory('core.model.inference')).toBe('model')
    expect(readNodeVisualCategory('core.logic.condition')).toBe('logic')
    expect(readNodeVisualCategory('opencv.matching.template')).toBe('vision')
    expect(readNodeVisualCategory('custom', 'vendor.protocol.http')).toBe('integration')
    expect(readNodeVisualCategory('custom.utility')).toBe('utility')
  })
})
