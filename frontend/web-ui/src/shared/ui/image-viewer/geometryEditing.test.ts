import { describe, expect, it } from 'vitest'

import {
  moveBbox,
  movePoint,
  movePolygon,
  movePolygonVertex,
  resizeBbox,
  resizePolygon,
} from './geometryEditing'

describe('geometryEditing', () => {
  it('moves a point and clamps it to the image boundary', () => {
    expect(movePoint([10, 20], 25, -30, 80, 60)).toEqual([35, 0])
    expect(movePoint([10, 20], 100, 100, 80, 60)).toEqual([80, 60])
  })

  it('moves bbox without crossing the image boundary', () => {
    expect(moveBbox([10, 20, 40, 60], 100, -50, 120, 90)).toEqual([90, 0, 120, 40])
  })

  it('resizes bbox from an edge while preserving a valid area', () => {
    expect(resizeBbox([10, 20, 40, 60], 'w', [39.5, 0], 120, 90)).toEqual([38, 20, 40, 60])
    expect(resizeBbox([10, 20, 40, 60], 'se', [80, 75], 120, 90)).toEqual([10, 20, 80, 75])
  })

  it('moves an entire polygon and clamps all vertices together', () => {
    expect(movePolygon([[5, 5], [25, 5], [25, 25]], -20, 100, 80, 60)).toEqual([
      [0, 40],
      [20, 40],
      [20, 60],
    ])
  })

  it('resizes and edits polygon vertices independently', () => {
    expect(resizePolygon([[10, 10], [30, 10], [30, 30], [10, 30]], 'se', [50, 60], 80, 80)).toEqual([
      [10, 10],
      [50, 10],
      [50, 60],
      [10, 60],
    ])
    expect(movePolygonVertex([[10, 10], [30, 10], [30, 30]], 1, [42, 8], 80, 80)).toEqual([
      [10, 10],
      [42, 8],
      [30, 30],
    ])
  })
})
