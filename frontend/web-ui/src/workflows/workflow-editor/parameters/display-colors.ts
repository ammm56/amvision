/** Draw Regions 与显示节点共用的色板及颜色格式。 */
export const paletteColors = [
  '#00C853', '#00B8D4', '#2962FF', '#6200EA', '#AA00FF', '#D500F9', '#D50000', '#FF6D00',
  '#FFB300', '#FFD600', '#64DD17', '#1DE9B6', '#607D8B', '#546E7A', '#37474F', '#FFFFFF',
]
export function isHexColor(value: string): boolean { return /^#[0-9A-Fa-f]{6}$/.test(value.trim()) }
export function normalizeHexColor(value: string): string { return value.trim().toUpperCase() }
export const statePresets: Record<string, { label: string; color: string }> = {
  success: { label: 'Success', color: 'var(--am-success-text, #087847)' },
  danger: { label: 'Danger', color: 'var(--am-danger-text, #b42332)' },
  warning: { label: 'Warning', color: 'var(--am-warning-text, #956000)' },
  neutral: { label: 'Neutral', color: 'var(--am-text)' },
}
export function displayColor(value: unknown): string | undefined {
  if (typeof value !== 'string') return undefined
  return isHexColor(value) ? normalizeHexColor(value) : statePresets[value]?.color
}
