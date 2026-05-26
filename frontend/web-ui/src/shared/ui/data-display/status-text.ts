export function humanizeStatusText(value: string): string {
  const normalized = value.trim()
  if (!normalized) return '-'
  return normalized.replace(/[_-]+/g, ' ').replace(/\s+/g, ' ').trim()
}