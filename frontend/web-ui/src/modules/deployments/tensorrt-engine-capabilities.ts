export type TensorRtInputShapeMode = 'static' | 'dynamic'

export interface TensorRtOptimizationProfileInput {
  inputName: string
  minShape: number[]
  optShape: number[]
  maxShape: number[]
}

export interface TensorRtOptimizationProfile {
  index: number
  inputs: TensorRtOptimizationProfileInput[]
}

export interface TensorRtEngineCapabilities {
  inputShapeMode: TensorRtInputShapeMode
  optimizationProfiles: TensorRtOptimizationProfile[]
}

export function parseTensorRtEngineCapabilities(
  metadata: Record<string, unknown>,
): TensorRtEngineCapabilities | null {
  const mode = metadata.input_shape_mode
  const count = metadata.optimization_profile_count
  const rawProfiles = metadata.optimization_profiles
  if (
    (mode !== 'static' && mode !== 'dynamic')
    || !isPositiveInteger(count)
    || !Array.isArray(rawProfiles)
    || rawProfiles.length !== count
  ) {
    return null
  }

  const profiles: TensorRtOptimizationProfile[] = []
  for (const [expectedIndex, rawProfile] of rawProfiles.entries()) {
    const profile = readRecord(rawProfile)
    if (
      profile === null
      || profile.index !== expectedIndex
      || !Array.isArray(profile.inputs)
      || profile.inputs.length === 0
    ) {
      return null
    }
    const inputs: TensorRtOptimizationProfileInput[] = []
    for (const rawInput of profile.inputs) {
      const input = readRecord(rawInput)
      if (input === null || typeof input.input_name !== 'string' || !input.input_name.trim()) {
        return null
      }
      const minShape = readShape(input.min_shape)
      const optShape = readShape(input.opt_shape)
      const maxShape = readShape(input.max_shape)
      if (
        minShape === null
        || optShape === null
        || maxShape === null
        || minShape.length !== optShape.length
        || minShape.length !== maxShape.length
        || minShape.some((value, index) => value > optShape[index]! || optShape[index]! > maxShape[index]!)
        || (mode === 'static' && !sameShapeRange(minShape, optShape, maxShape))
      ) {
        return null
      }
      inputs.push({
        inputName: input.input_name.trim(),
        minShape,
        optShape,
        maxShape,
      })
    }
    profiles.push({ index: expectedIndex, inputs })
  }
  return {
    inputShapeMode: mode,
    optimizationProfiles: profiles,
  }
}

export function formatTensorRtShape(shape: number[]): string {
  return shape.join(' × ')
}

function readRecord(value: unknown): Record<string, unknown> | null {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null
}

function readShape(value: unknown): number[] | null {
  if (!Array.isArray(value) || value.length === 0 || !value.every(isPositiveInteger)) {
    return null
  }
  return value as number[]
}

function isPositiveInteger(value: unknown): value is number {
  return typeof value === 'number' && Number.isInteger(value) && value > 0
}

function sameShapeRange(minShape: number[], optShape: number[], maxShape: number[]): boolean {
  return minShape.every(
    (value, index) => value === optShape[index] && value === maxShape[index],
  )
}
