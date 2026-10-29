import { describe, expect, it } from 'vitest'
import { arrayStepUpdates, interactionToolKey } from './arrayInteraction'

describe('array image interaction', () => {
  it('distinguishes two line tools by the parameters they edit', () => {
    expect(interactionToolKey({ tool: 'line', targetParameters: ['row_step_xy'] }))
      .not.toBe(interactionToolKey({ tool: 'line', targetParameters: ['column_step_xy'] }))
  })
  it('keeps direction and cross-axis components for grid and array nodes', () => {
    expect(arrayStepUpdates(['column_step_xy'], [100, 50, 443, 47])).toEqual({ column_step_xy: [343, -3] })
    expect(arrayStepUpdates(['row_step_xy'], [100, 50, 104, 550])).toEqual({ row_step_xy: [4, 500] })
    expect(arrayStepUpdates(['step_x', 'column_step_y'], [100, 50, 443, 47])).toEqual({ step_x: 343, column_step_y: -3 })
    expect(arrayStepUpdates(['row_step_x', 'step_y'], [100, 50, 104, 550])).toEqual({ row_step_x: 4, step_y: 500 })
  })
  it('does not reinterpret an unrelated line or a degenerate vector', () => {
    expect(arrayStepUpdates(['angle'], [0, 0, 30, 20])).toBeNull()
    expect(arrayStepUpdates(['row_step_xy'], [2, 3, 2, 3])).toBeNull()
    expect(arrayStepUpdates(['row_step_xy'], [0, 0, Infinity, 3])).toBeNull()
  })
})
