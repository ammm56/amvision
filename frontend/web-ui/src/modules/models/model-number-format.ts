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

export function modelChartValueFormatter(format: (value: number) => string = formatModelNumber) {
  const formatValue = (value: unknown): string => typeof value === 'number' ? format(value) : '—'
  return (value: unknown): string | string[] => Array.isArray(value) ? value.map(formatValue) : formatValue(value)
}
