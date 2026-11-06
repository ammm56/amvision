/** 扫描位移与标定均显式填写；切换模式删除不适用字段。 */
import { type Form, object, vector } from './form'

export function newDisplacement(kind: string): Form {
  return kind === 'encoder-positions'
    ? { kind, dtype: '', scale: null, origin: null }
    : { kind: 'fixed-step', origin_line_id: null, step: null }
}
export function newProfileInput(kind = 'file'): Form {
  return kind === 'local-array' ? { kind } : {
    kind: 'file', file_format: 'npz', has_validity: false,
    profiles: {
      format_id: 'amvision.calibrated-profiles.v1', point_count: null, profile_count: null,
      dtype: '', position_dtype: '', calibration_id: '', calibration_revision: '',
      spatial: { length_unit: null, unit_source: 'configuration', frame_id: '',
        axes: { handedness: 'right', axis_labels: ['X','Y','Z'], definition_source: 'configuration' } },
      origin: [null,null,null], x_direction: [null,null,null], scan_direction: [null,null,null],
      height_direction: [null,null,null], displacement: newDisplacement('fixed-step'),
    },
  }
}
const keys = (v: Form, names: string[]) => Object.keys(v).length === names.length && Object.keys(v).every(k => names.includes(k))
const finite = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v)
const positive = (v: unknown): v is number => finite(v) && v > 0
const integer = (v: unknown): v is number => finite(v) && Number.isSafeInteger(v) && v >= 0
const id = (v: unknown) => typeof v === 'string' && /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/.test(v)
const dtype = (v: unknown) => v === 'float32' || v === 'float64'

export function profilesValid(value: Form): boolean {
  if (value.kind === 'local-array') return keys(value, ['kind'])
  if (value.kind !== 'file' || value.file_format !== 'npz' || typeof value.has_validity !== 'boolean'
    || !keys(value, ['kind','file_format','has_validity','profiles'])) return false
  const p = object(value.profiles), s = object(p.spatial), axes = object(s.axes), d = object(p.displacement)
  if (!keys(p, ['format_id','point_count','profile_count','dtype','position_dtype','calibration_id','calibration_revision','spatial','origin','x_direction','scan_direction','height_direction','displacement'])
    || p.format_id !== 'amvision.calibrated-profiles.v1' || !integer(p.point_count) || !p.point_count
    || !integer(p.profile_count) || !p.profile_count || !dtype(p.dtype) || !dtype(p.position_dtype)
    || !id(p.calibration_id) || !id(p.calibration_revision) || !id(s.frame_id)) return false
  if (!keys(s, ['length_unit','unit_source','frame_id','axes']) || !['m','mm','um'].includes(String(s.length_unit))
    || !['metadata','configuration'].includes(String(s.unit_source))
    || !keys(axes, ['handedness','axis_labels','definition_source']) || axes.handedness !== 'right'
    || !['metadata','configuration'].includes(String(axes.definition_source)) || !Array.isArray(axes.axis_labels)
    || axes.axis_labels.length !== 3 || !axes.axis_labels.every(x => typeof x === 'string' && x.trim().length > 0 && x.length <= 128)) return false
  if (!vector(p.origin)) return false
  const directions = [p.x_direction,p.scan_direction,p.height_direction]
  if (!directions.every(vector)) return false
  const dot = (a: number[], b: number[]) => a.reduce((sum,x,i) => sum+x*b[i]!,0)
  if (!directions.every((a,i) => Math.abs(dot(a,a)-1) <= 1e-8 && directions.slice(i+1).every(b => Math.abs(dot(a,b)) <= 1e-8))) return false
  if (d.kind === 'fixed-step') return keys(d,['kind','origin_line_id','step']) && integer(d.origin_line_id) && positive(d.step)
  return d.kind === 'encoder-positions' && keys(d,['kind','dtype','scale','origin']) && dtype(d.dtype) && positive(d.scale) && finite(d.origin)
}
