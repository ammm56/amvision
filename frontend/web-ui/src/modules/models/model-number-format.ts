export function formatModelNumber(value: number, digits = 3): string {
  return Number.isFinite(value) ? String(Number(value.toFixed(digits))) : '—'
}

export function formatSmallModelNumber(value: number): string {
  if (Number.isFinite(value) && value !== 0 && Math.abs(value) < 0.0001) {
    const [significand, exponent] = value.toExponential(3).split('e')
    return `${Number(significand)}e${exponent}`
  }
  return formatModelNumber(value, 4)
}

export const formatLearningRate = formatSmallModelNumber

export function formatTrainingMetric(value: number): string {
  const formatted = formatModelNumber(value)
  if (value === 0 || formatted !== '0') return formatted
  const precise = formatModelNumber(value, 4)
  return precise === '0' ? formatSmallModelNumber(value) : precise
}

export function modelChartValueFormatter(format: (value: number) => string = formatModelNumber) {
  const formatValue = (value: unknown): string => typeof value === 'number' ? format(value) : '—'
  return (value: unknown): string | string[] => Array.isArray(value) ? value.map(formatValue) : formatValue(value)
}
