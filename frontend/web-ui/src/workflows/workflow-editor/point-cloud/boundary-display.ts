import { object } from './preview-data'
import type { CloudRendererPolicy } from '../services/measurement-resource.service'

export interface CurveDisplay {
  feature_id: string; kind: 'boundary' | 'line' | 'circle'; valid: boolean; reason: string | null
  geometry: Record<string, unknown> | null; method: Record<string, unknown>; quality: Record<string, unknown>
  points: number[][]; topology: { segments: Segment[]; point_count: number } | null
  intervals?: Record<string, unknown>[]; vertex_kind: 'source' | 'generated' | null
  failed_segment_id?: string | null; segments?: Record<string, unknown>[]; groups?: Record<string, unknown>[]
  profile_kinds?: number[]
  inlier_flags?:boolean[]; solver?:Record<string,unknown>
  radial_residuals?:number[]; angular_weights?:number[]; angular_sectors?:number[]
}
export interface Segment { segment_id: string; group_id?:string; start: number; count: number; closed: boolean; role: string; orientation: string; profile?: {side:string;breaks:number[]} }
const invalid = () => new Error('cloud_preview_invalid')
export function xyz(value: unknown): number[] {
  if (!Array.isArray(value) || value.length !== 3 || value.some(v => typeof v !== 'number' || !Number.isFinite(v))) throw invalid()
  return value as number[]
}
function finite(value: unknown): number { if (typeof value !== 'number' || !Number.isFinite(value)) throw invalid(); return value }

/** 只读取同版显示证据；未知格式或不完整连接不回退成普通点集。 */
export function curveItems(payload: Record<string, unknown>): CurveDisplay[] {
  if (!payload.geometry) return []
  const g = object(payload.geometry)
  if (g.format_id !== 'amvision.geometry-preview.v1' || !Array.isArray(g.curves) || g.curves.length > 8192) throw invalid()
  const ids = new Set<string>()
  return g.curves.map(raw => {
    const f = object(raw)
    if (typeof f.feature_id !== 'string' || !f.feature_id || ids.has(f.feature_id) || !['boundary','line','circle'].includes(String(f.kind)) || typeof f.valid !== 'boolean') throw invalid()
    ids.add(f.feature_id)
    const method = object(f.method), evaluation = object(object(method.parameters).evaluation), spatial = object(payload.spatial)
    const visible=f.kind==='boundary'&&object(object(method.parameters).method).kind==='visible-envelope'
    if (method.method_id !== ({ boundary: 'extract-boundary', line: 'fit-line', circle: 'fit-circle' }[String(f.kind)]) || method.method_version !== 1) throw invalid()
    if (evaluation.frame_id !== spatial.frame_id || evaluation.length_unit !== spatial.length_unit || object(object(f.quality).metrics).observation_id !== payload.observation_id) throw invalid()
    const resolved = f.kind==='boundary'?object(method.resolution).evaluation:method.evaluation
    if(resolved!==null){
      const e=object(resolved)
      if(e.frame_id!==spatial.frame_id||e.length_unit!==spatial.length_unit||!Array.isArray(e.rotation)||e.rotation.length!==3)throw invalid()
      xyz(e.origin); e.rotation.forEach(xyz)
    }else if(f.valid)throw invalid()
    if (!Array.isArray(f.points)) throw invalid()
    const points = f.points.map(xyz)
    if (!f.valid) {
      if (typeof f.reason !== 'string' || f.geometry !== null || f.topology !== null || points.length) throw invalid()
    } else {
      if (f.reason !== null || object(f.quality).usable !== true || !f.geometry) throw invalid()
      const t = object(f.topology)
      if (t.point_count !== points.length || f.support_point_count !== points.length || !Array.isArray(t.segments)) throw invalid()
      let cursor = 0; const seen = new Set<string>()
      for (const rawSegment of t.segments) {
        const s = object(rawSegment)
        const profile=s.profile?object(s.profile):null
        if (typeof s.segment_id !== 'string' || seen.has(s.segment_id) || s.start !== cursor || !Number.isSafeInteger(s.count) || typeof s.closed !== 'boolean' || Number(s.count) < (s.closed ? 3 : profile?1:2)) throw invalid()
        if(s.group_id!==undefined&&(typeof s.group_id!=='string'||!s.group_id||s.closed||s.role!=='open'||profile))throw invalid()
        if(profile){
          if(!visible||profile.side!==s.segment_id||!['u-min','u-max','v-min','v-max'].includes(String(profile.side))||s.closed||s.role!=='open'||s.orientation!=='open'||!Array.isArray(profile.breaks))throw invalid()
          let previous=0
          for(const index of profile.breaks){if(!Number.isSafeInteger(index)||index<=previous||index>=Number(s.count))throw invalid();previous=index}
        }else if(visible)throw invalid()
        seen.add(s.segment_id); cursor += Number(s.count)
      }
      if (cursor !== points.length) throw invalid()
      const segments = t.segments
      if (f.kind !== 'boundary' && (!Array.isArray(f.intervals) || f.intervals.length !== segments.length || f.intervals.some((v,i)=>object(v).segment_id!==object(segments[i]).segment_id))) throw invalid()
      if(f.kind==='circle')for(const interval of f.intervals as unknown[])arcPieces(object(interval),!!object(method.parameters).robust)
    }
    const profile=f.valid&&visible
    if(profile?(!Array.isArray(f.profile_kinds)||f.profile_kinds.length!==points.length||f.profile_kinds.some(k=>!Number.isInteger(k)||Number(k)<0||Number(k)>3)):f.profile_kinds!==undefined)throw invalid()
    const robust=f.valid&&f.kind==='circle'&&!!object(method.parameters).robust
    if(robust?(!Array.isArray(f.inlier_flags)||f.inlier_flags.length!==points.length||f.inlier_flags.some(v=>typeof v!=='boolean')):f.inlier_flags!==undefined)throw invalid()
    for(const key of ['radial_residuals','angular_weights','angular_sectors']){
      const values=f[key]
      if(!robust){if(values!==undefined)throw invalid();continue}
      if(!Array.isArray(values)||values.length!==points.length||values.some(v=>typeof v!=='number'||!Number.isFinite(v)||key==='angular_weights'&&v<=0||key==='angular_sectors'&&(!Number.isSafeInteger(v)||v<0||v>=Number(object(object(method.parameters).robust).sector_count))))throw invalid()
    }
    return { ...f, points } as unknown as CurveDisplay
  })
}

/** 分段角域保持空隙；不使用首末角将部分圆弧重建为整段。 */
function arcPieces(interval:Record<string,unknown>,robust:boolean):{start_angle:number;sweep:number}[]{
  const pieces=interval.pieces
  if(robust){
    if(interval.start_angle!==null||interval.sweep!==null||!Array.isArray(pieces)||!pieces.length||pieces.length>8192)throw invalid()
    let end=-1
    return pieces.map(raw=>{const p=object(raw),start=finite(p.start_angle),sweep=finite(p.sweep);if(start<0||start>=2*Math.PI||sweep<=0||start+sweep>2*Math.PI+1e-14||start<end)throw invalid();end=start+sweep;return {start_angle:start,sweep}})
  }
  if(pieces!==undefined&&(!Array.isArray(pieces)||pieces.length))throw invalid()
  const start=finite(interval.start_angle),sweep=finite(interval.sweep)
  if(Math.abs(sweep)>2*Math.PI+1e-14)throw invalid()
  return [{start_angle:start,sweep}]
}

export interface CurveStroke { featureId: string; segmentId: string; groupId?:string; fitted: boolean; points: number[][]; markers?:boolean; estimate?:'center'|'edge'; outlier?:boolean }
/** 实测边按实际连接绘制；模型只绘制支持区间，不跨段连接。 */
export function curveStrokes(items: CurveDisplay[], policy: CloudRendererPolicy): CurveStroke[] {
  let count = 0; const result: CurveStroke[] = []
  function push(item: CurveDisplay, segmentId: string, points: number[][], fitted: boolean) {
    count += points.length
    if (count > policy.max_points * 8) throw new Error('cloud_preview_capacity')
    result.push({ featureId: item.feature_id, segmentId, groupId:item.topology?.segments.find(s=>s.segment_id===segmentId)?.group_id, fitted, points })
  }
  for (const f of items) {
    if (!f.valid || !f.topology) continue
    for (const s of f.topology.segments) {
      if(s.profile){
        const breaks=new Set(s.profile.breaks)
        for(const kind of ['center','edge'] as const){
          const markers:number[][]=[],edges:number[][]=[]
          for(let i=0;i<s.count;i++){
            const index=s.start+i,mode=f.profile_kinds?.[index]===0?'center':'edge'
            if(mode===kind)markers.push(f.points[index]!)
            if(i&& !breaks.has(i) && (f.profile_kinds?.[index]===0&&f.profile_kinds?.[index-1]===0?'center':'edge')===kind)edges.push(f.points[index-1]!,f.points[index]!)
          }
          for(const [points,isMarkers] of [[markers,true],[edges,false]] as const){
            if(!points.length)continue
            push(f,s.segment_id,points,false)
            Object.assign(result.at(-1)!,{markers:isMarkers,estimate:kind})
          }
        }
        continue
      }
      if (count + (s.count - 1 + Number(s.closed)) * 2 > policy.max_points * 8) throw new Error('cloud_preview_capacity')
      const points: number[][] = []
      for (let i = 0; i < s.count - 1; i++) points.push(f.points[s.start + i]!, f.points[s.start + i + 1]!)
      if (s.closed) points.push(f.points[s.start + s.count - 1]!, f.points[s.start]!)
      push(f, s.segment_id, points, false)
      if(f.inlier_flags){const rejected=f.points.slice(s.start,s.start+s.count).filter((_,i)=>!f.inlier_flags![s.start+i]);if(rejected.length){push(f,s.segment_id,rejected,false);Object.assign(result.at(-1)!,{markers:true,outlier:true})}}
    }
    if (f.kind === 'boundary') continue
    if (!Array.isArray(f.intervals)) throw invalid()
    const g = object(f.geometry)
    if (f.kind === 'line') {
      const origin = xyz(g.origin), direction = xyz(g.direction)
      for (const interval of f.intervals) push(f, String(interval.segment_id), [finite(interval.start), finite(interval.end)].map(t => origin.map((v, i) => v + t * direction[i]!)), true)
    } else {
      const center = xyz(g.center), radius = finite(g.radius), rotation = f.method.evaluation
      const rows = object(rotation).rotation
      if (radius <= 0 || !Array.isArray(rows) || rows.length !== 3) throw invalid()
      const basis = rows.map(xyz)
      const step = Math.min(Math.PI, 2 * Math.acos(Math.max(-1, 1 - policy.max_position_error / (2 * radius))))
      for (const interval of f.intervals) for(const piece of arcPieces(interval,!!object(f.method.parameters).robust)) {
        const start = piece.start_angle, sweep = piece.sweep, segments = Math.max(1, Math.ceil(Math.abs(sweep) / step))
        if (!Number.isFinite(segments) || count + segments * 2 > policy.max_points * 8) throw new Error('cloud_preview_capacity')
        const point = (angle: number) => center.map((v, i) => v + radius * (basis[i]![0]! * Math.cos(angle) + basis[i]![1]! * Math.sin(angle)))
        const points: number[][] = []
        for (let i = 0; i < segments; i++) points.push(point(start + sweep * i / segments), point(start + sweep * (i + 1) / segments))
        push(f, String(interval.segment_id), points, true)
      }
    }
  }
  return result
}
