export interface ConversionValidationFailureRow {
  sample_name?: string
  profile?: string
  input_shape: number[]
  input_dtype: string
  output_name: string
  output_shape: number[]
  output_dtype: string
  index: number[]
  source_value: number
  target_value: number
  max_error: number
  mean_error: number
  absolute_error?: number
  allowed_error?: number
}

export interface ConversionValidationFailureDetails {
  source_runtime: string
  target_runtime: string
  input_kind: 'validation_image' | 'generated_tensor'
  rule: 'normalized_error' | 'absolute_relative_tolerance'
  sample_count?: number
  check_count: number
  failed_check_count?: number
  peak_rule?: 'p99'
  max_error_limit?: number
  mean_error_limit?: number
  absolute_tolerance?: number
  relative_tolerance?: number
  failures: ConversionValidationFailureRow[]
}

const record = (value: unknown): Record<string, unknown> | undefined =>
  value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : undefined
const text = (value: unknown): value is string => typeof value === 'string' && value.length > 0
const numeric = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value)
const dimensions = (value: unknown): value is number[] => Array.isArray(value) && value.every(Number.isInteger)

export function readConversionValidationFailure(value: unknown): ConversionValidationFailureDetails | null {
  const details = record(value)
  const child = record(record(details?.child_error)?.details)
  const evidence = record(details?.numeric_validation) ?? record(record(record(details?.build_error)?.details)?.numeric_validation)
    ?? record(child?.numeric_validation) ?? record(record(record(child?.build_error)?.details)?.numeric_validation)
  if (!evidence || !text(evidence.source_runtime) || !text(evidence.target_runtime) ||
    !numeric(evidence.check_count) || !Number.isSafeInteger(evidence.check_count)
    || !Array.isArray(evidence.failures) || !evidence.failures.length || evidence.failures.length > evidence.check_count) return null
  if (evidence.failed_check_count !== undefined && (!numeric(evidence.failed_check_count)
    || !Number.isSafeInteger(evidence.failed_check_count)
    || evidence.failed_check_count < evidence.failures.length || evidence.failed_check_count > evidence.check_count)) return null
  const image = evidence.input_kind === 'validation_image' && evidence.rule === 'normalized_error'
  const tensor = evidence.input_kind === 'generated_tensor' && evidence.rule === 'absolute_relative_tolerance'
  if ((!image && !tensor) ||
    (image && ![evidence.sample_count, evidence.max_error_limit, evidence.mean_error_limit].every(numeric)) ||
    (tensor && ![evidence.absolute_tolerance, evidence.relative_tolerance].every(numeric))) return null
  if (!evidence.failures.every((value: unknown) => {
    const row = record(value)
    return row && [row.input_shape, row.output_shape, row.index].every(dimensions) &&
      [row.output_name, row.input_dtype, row.output_dtype].every(text) &&
      [row.source_value, row.target_value, row.max_error, row.mean_error].every(numeric) &&
      (image ? [row.sample_name, row.profile].every(text) : [row.absolute_error, row.allowed_error].every(numeric))
  })) return null
  return evidence as unknown as ConversionValidationFailureDetails
}
