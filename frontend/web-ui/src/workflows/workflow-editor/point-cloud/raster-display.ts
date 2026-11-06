/** 只读原始像素身份，不将显示点或生成顶点重新编号。 */
export function rasterIdentity(value: unknown, sourceCount: unknown) {
  if (value === null || value === undefined) return null
  if (typeof value !== 'object' || Array.isArray(value)) throw new Error('cloud_preview_invalid')
  const r = value as Record<string, unknown>
  const { width, height, calibration_id: id, calibration_revision: revision } = r
  if (typeof width !== 'number' || !Number.isSafeInteger(width) || width < 1 ||
      typeof height !== 'number' || !Number.isSafeInteger(height) || height < 1 ||
      !Number.isSafeInteger(width * height) || width * height !== sourceCount ||
      typeof id !== 'string' || !id || typeof revision !== 'string' || !revision) {
    throw new Error('cloud_preview_invalid')
  }
  return { width, height, id, revision }
}

export function sourcePixel(sourceIndex: string | null | undefined, grid: ReturnType<typeof rasterIdentity>) {
  if (sourceIndex == null || !grid || !/^(0|[1-9][0-9]*)$/.test(sourceIndex)) return null
  const index = Number(sourceIndex)
  if (!Number.isSafeInteger(index) || index >= grid.width * grid.height) return null
  return { row: Math.floor(index / grid.width), column: index % grid.width }
}
