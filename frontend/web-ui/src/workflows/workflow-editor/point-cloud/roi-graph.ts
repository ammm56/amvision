/** ROI 编辑与显示共用有限依赖图规则；没有点云运算。 */
export type RoiRecord = Record<string, unknown>
const object = (value: unknown): RoiRecord => value && typeof value === 'object' && !Array.isArray(value) ? value as RoiRecord : {}
const identifier = (value: unknown): value is string => typeof value === 'string' && /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/.test(value)

export function roiDependencies(roi: RoiRecord): string[] {
  const g = object(roi.geometry)
  if (roi.kind === 'section-band') return typeof g.bounds_roi_id === 'string' ? [g.bounds_roi_id] : []
  return roi.kind === 'union' && Array.isArray(g.roi_ids) ? g.roi_ids.filter((v): v is string => typeof v === 'string') : []
}

export function roiGraphIssues(rois: RoiRecord[]): string[] {
  const issues: string[] = [], byId = new Map<string, RoiRecord>()
  if (rois.length > 8192) return ['ROI count']
  for (const roi of rois) {
    const id = String(roi.roi_id || '?'), g = object(roi.geometry)
    if (!identifier(roi.roi_id) || byId.has(id) || !identifier(roi.frame_id) || !['m', 'mm', 'um'].includes(String(roi.length_unit))) issues.push(`${id}: ID / frame / unit`)
    byId.set(id, roi)
    if (rois[0] && (roi.frame_id !== rois[0].frame_id || roi.length_unit !== rois[0].length_unit)) issues.push(`${id}: space`)
    if (roi.kind === 'union' && (!Array.isArray(g.roi_ids) || !g.roi_ids.length || g.roi_ids.length > 8192 || !g.roi_ids.every(identifier) || new Set(g.roi_ids).size !== g.roi_ids.length)) issues.push(`${id}: union members`)
    if (roi.kind === 'section-band' && !identifier(g.bounds_roi_id)) issues.push(`${id}: bounds_roi_id`)
    if (!['box', 'cylinder', 'section-band', 'union'].includes(String(roi.kind))) issues.push(`${id}: kind`)
  }
  const state = new Map<string, number>()
  for (const id of byId.keys()) {
    if (state.get(id) === 2) continue
    state.set(id, 1)
    const stack = [{ id, children: roiDependencies(byId.get(id)!), index: 0 }]
    while (stack.length) {
      const item = stack.at(-1)!
      if (item.index === item.children.length) { state.set(item.id, 2); stack.pop(); continue }
      const child = item.children[item.index++]!
      if (!byId.has(child)) { issues.push(`${item.id}: missing ${child}`); continue }
      if (state.get(child) === 1) { issues.push(`${item.id}: cycle ${child}`); continue }
      if (state.get(child) === 2) continue
      state.set(child, 1)
      stack.push({ id: child, children: roiDependencies(byId.get(child)!), index: 0 })
    }
  }
  return issues
}

export function renameRoiReference(roi: RoiRecord, previous: string, next: string): RoiRecord {
  const geometry = object(roi.geometry)
  if (roi.kind === 'union') return { ...roi, geometry: { ...geometry, roi_ids: roiDependencies(roi).map(id => id === previous ? next : id) } }
  if (roi.kind === 'section-band' && geometry.bounds_roi_id === previous) return { ...roi, geometry: { ...geometry, bounds_roi_id: next } }
  return roi
}

/** 只投影显式目标的依赖；未选成员仍留在草稿，不冒充选中区域。 */
export function roiDependencyClosure(rois: RoiRecord[], roots: string[]): RoiRecord[] {
  const byId = new Map(rois.map(r => [String(r.roi_id), r])), seen = new Set<string>(), pending = [...roots]
  while (pending.length) {
    const id = pending.pop()!
    if (seen.has(id)) continue
    const roi = byId.get(id)
    if (!roi) continue
    seen.add(id)
    pending.push(...roiDependencies(roi))
  }
  return rois.filter(r => seen.has(String(r.roi_id)))
}
