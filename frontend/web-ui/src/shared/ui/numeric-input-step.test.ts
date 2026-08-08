import { describe, expect, it } from 'vitest'

import { buildNumericInputAttributes, deriveNumericInputStep } from './numeric-input-step'

describe('deriveNumericInputStep', () => {
  it('优先使用正有限显式步长', () => {
    expect(deriveNumericInputStep({
      valueKind: 'number',
      minimum: 0,
      maximum: 1,
      explicitStep: 0.001,
    })).toBe(0.001)
  })

  it('integer 固定使用步长 1', () => {
    expect(deriveNumericInputStep({ valueKind: 'integer', explicitStep: 0 })).toBe(1)
  })

  it.each([
    [0, 1, 0.01],
    [0, 180, 0.1],
    [0, 10_000, 1],
    [undefined, undefined, 0.01],
  ])('number 按有限范围推导步长', (minimum, maximum, expectedStep) => {
    expect(deriveNumericInputStep({
      valueKind: 'number',
      minimum,
      maximum,
    })).toBe(expectedStep)
  })

  it('inclusive 和 exclusive 边界按同一步长网格对齐', () => {
    expect(buildNumericInputAttributes({
      valueKind: 'number',
      exclusiveMinimum: 0,
      exclusiveMaximum: 1,
      explicitStep: 0.1,
    })).toEqual({ min: 0.1, max: 0.9, step: 0.1 })
  })

  it('消除未对齐 epsilon 下限造成的有效值整体偏移', () => {
    expect(buildNumericInputAttributes({
      valueKind: 'number',
      minimum: 0.000001,
      maximum: 10,
      explicitStep: 0.1,
    })).toEqual({ min: 0.1, max: 10, step: 0.1 })
  })

  it('浮点误差不会跳过已经对齐的边界', () => {
    expect(buildNumericInputAttributes({
      valueKind: 'number',
      minimum: 0.30000000000000004,
      maximum: 0.7,
      explicitStep: 0.1,
    })).toEqual({ min: 0.3, max: 0.7, step: 0.1 })
  })
})
