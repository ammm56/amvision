import { describe, expect, it } from 'vitest'

import { calculateAnchoredOffset } from './useImageViewerViewport'

describe('calculateAnchoredOffset', () => {
  it('keeps the image coordinate under the mouse fixed while zooming', () => {
    const pointer = 240
    const oldOffset = -35
    const oldScale = 0.5
    const nextScale = 1.25
    const sourceDistanceFromCenter = (pointer - oldOffset) / oldScale
    const nextOffset = calculateAnchoredOffset(pointer, oldOffset, nextScale / oldScale)

    expect(nextOffset + sourceDistanceFromCenter * nextScale).toBeCloseTo(pointer)
  })
})
