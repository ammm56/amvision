/** 原采集行与样点直接读取保存字段，不由点序号猜测空行或扫描位移。 */
export const profileNames = ['acquisition_line_id', 'profile_sample_index'] as const
export interface ProfilePoint { line: string; sample: string }
export function profileIdentity(value: unknown, sourceCount: unknown, emptyCount: unknown) {
  if (value == null) {
    if (emptyCount != null) throw new Error('cloud_preview_invalid')
    return null
  }
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('cloud_preview_invalid')
  const p = value as Record<string, unknown>
  const id = (v: unknown) => typeof v === 'string' && /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/.test(v)
  if (p.format_id !== 'amvision.calibrated-profiles.v1' || p.point_count !== sourceCount
    || !Number.isSafeInteger(sourceCount) || Number(sourceCount) < 1
    || !Number.isSafeInteger(p.profile_count) || Number(p.profile_count) < 1
    || !Number.isSafeInteger(emptyCount) || Number(emptyCount) < 0 || Number(emptyCount) >= Number(p.profile_count)
    || !id(p.calibration_id) || !id(p.calibration_revision)) throw new Error('cloud_preview_invalid')
  return { count: Number(p.profile_count), empty: Number(emptyCount), id: String(p.calibration_id), revision: String(p.calibration_revision) }
}
export function profilePoint(line: number | bigint, sample: number | bigint, sourceCount: number): ProfilePoint {
  if (typeof line !== 'bigint' || typeof sample !== 'bigint' || line < 0n || line > BigInt(Number.MAX_SAFE_INTEGER)
    || sample < 0n || sample >= BigInt(sourceCount)) throw new Error('cloud_preview_invalid')
  return { line: line.toString(), sample: sample.toString() }
}
