export interface NumericInputStepOptions {
  valueKind: 'integer' | 'number'
  minimum?: number
  maximum?: number
  exclusiveMinimum?: number
  exclusiveMaximum?: number
  explicitStep?: number
}

export interface NumericInputAttributes {
  min?: number
  max?: number
  step: number
}

const GRID_RATIO_TOLERANCE = 1e-9

/** 构建与零点网格对齐的原生数值输入属性。 */
export function buildNumericInputAttributes(options: NumericInputStepOptions): NumericInputAttributes {
  const minimumCandidate = options.minimum ?? options.exclusiveMinimum
  const maximumCandidate = options.maximum ?? options.exclusiveMaximum
  const step = deriveNumericInputStep({
    ...options,
    minimum: minimumCandidate,
    maximum: maximumCandidate,
  })
  const minimum = options.minimum === undefined
    ? alignExclusiveMinimum(options.exclusiveMinimum, step)
    : alignInclusiveMinimum(options.minimum, step)
  const maximum = options.maximum === undefined
    ? alignExclusiveMaximum(options.exclusiveMaximum, step)
    : alignInclusiveMaximum(options.maximum, step)
  return {
    ...(minimum === undefined ? {} : { min: minimum }),
    ...(maximum === undefined ? {} : { max: maximum }),
    step,
  }
}

/** 根据字段类型、显式精度和有限范围生成确定的原生输入步长。 */
export function deriveNumericInputStep(options: NumericInputStepOptions): number {
  if (
    typeof options.explicitStep === 'number'
    && Number.isFinite(options.explicitStep)
    && options.explicitStep > 0
  ) {
    return options.explicitStep
  }
  if (options.valueKind === 'integer') return 1
  if (
    typeof options.minimum !== 'number'
    || !Number.isFinite(options.minimum)
    || typeof options.maximum !== 'number'
    || !Number.isFinite(options.maximum)
  ) {
    return 0.01
  }
  const span = Math.abs(options.maximum - options.minimum)
  if (!Number.isFinite(span) || span === 0) return 0.01
  if (span <= 10) return 0.01
  if (span <= 1_000) return 0.1
  return 1
}

function alignInclusiveMinimum(value: number | undefined, step: number): number | undefined {
  if (!isFiniteNumber(value)) return undefined
  return roundToStep(Math.ceil(value / step - GRID_RATIO_TOLERANCE) * step, step)
}

function alignInclusiveMaximum(value: number | undefined, step: number): number | undefined {
  if (!isFiniteNumber(value)) return undefined
  return roundToStep(Math.floor(value / step + GRID_RATIO_TOLERANCE) * step, step)
}

function alignExclusiveMinimum(value: number | undefined, step: number): number | undefined {
  if (!isFiniteNumber(value)) return undefined
  return roundToStep((Math.floor(value / step + GRID_RATIO_TOLERANCE) + 1) * step, step)
}

function alignExclusiveMaximum(value: number | undefined, step: number): number | undefined {
  if (!isFiniteNumber(value)) return undefined
  return roundToStep((Math.ceil(value / step - GRID_RATIO_TOLERANCE) - 1) * step, step)
}

function roundToStep(value: number, step: number): number {
  const decimals = Math.min(12, Math.max(0, decimalPlaces(step)))
  return Number(value.toFixed(decimals))
}

function decimalPlaces(value: number): number {
  const normalized = value.toString().toLowerCase()
  if (normalized.includes('e-')) {
    const [coefficient, exponentText] = normalized.split('e-')
    const coefficientDecimals = coefficient?.split('.')[1]?.length ?? 0
    return coefficientDecimals + Number(exponentText)
  }
  return normalized.split('.')[1]?.length ?? 0
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value)
}
