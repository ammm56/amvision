/** 仅组织配方字段；几何计算、完整契约校验仍属于后端。 */
import { limitRuleError, normalizeLimitRule } from '@/workflows/workflow-editor/parameters/limit-rules'
export type Form = Record<string, unknown>
export interface Field { path: string; label: string; type?: 'number' | 'vector' | 'pair' | 'matrix' | 'select'; options?: string[] }
export function object(value: unknown): Form { return value && typeof value === 'object' && !Array.isArray(value) ? value as Form : {} }
export function copy<T>(value: T): T { return JSON.parse(JSON.stringify(value)) as T }
export function get(value: unknown, path: string): unknown { return path.split('.').reduce<unknown>((v,k) => object(v)[k], value) }
export function put(value: Form, path: string, next: unknown): Form {
  const result = copy(value), keys = path.split('.'); let target = result
  for (const key of keys.slice(0,-1)) { target[key] = {...object(target[key])}; target = target[key] as Form }
  target[keys.at(-1)!] = next; return result
}
export const identity = () => [[1,0,0],[0,1,0],[0,0,1]]
export function newRoi(kind='box'): Form {
  return { format_id:'amvision.roi3d.v1', roi_id:'', frame_id:'', length_unit:null, kind, geometry: kind==='box' ? {center:[null,null,null],size:[null,null,null],rotation:identity()} : kind==='cylinder' ? {center:[null,null,null],axis:[null,null,null],radius:null,length:null} : {origin:[null,null,null],normal:[null,null,null],thickness:null,bounds_roi_id:''} }
}
export const planeMetrics = ['inlier_count','tangent_ratio','normal_gap','rms','max_residual']
export const frameMetrics = ['axis_sine','x_alignment','z_alignment']
export function newSettings(plane: boolean): Form {
  const quality_policy = {policy_id:'',policy_version:null,rules:(plane?planeMetrics:frameMetrics).map(item_id=>normalizeLimitRule({item_id,unit:['rms','max_residual'].includes(item_id)?'':'1'}))}
  return plane ? {feature_id:'',positive_normal:[null,null,null],min_orientation_cosine:null,algorithm:{kind:'svd'},quality_policy} : {pose_id:'',target_frame_id:'',primary_feature_id:'',positive_z:[null,null,null],origin:{kind:'anchor-projection',anchor:[null,null,null]},x_axis:{kind:'direction',direction:[null,null,null]},quality_policy}
}
const finite = (v: unknown): v is number => typeof v==='number' && Number.isFinite(v)
const identifier = (v: unknown) => typeof v==='string' && /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/.test(v)
export function vector(v: unknown): v is number[] { return Array.isArray(v) && v.length===3 && v.every(finite) }
function unit(v: unknown) { return vector(v) && Math.abs(v.reduce((a,b)=>a+b*b,0)-1)<=1e-8 }
export function roiIssues(rois: Form[]): string[] {
  const issues: string[] = [], ids = new Set<string>()
  for (const r of rois) {
    const g=object(r.geometry), id=String(r.roi_id||'?')
    if (!identifier(r.roi_id)||ids.has(id)||!identifier(r.frame_id)||!['m','mm','um'].includes(String(r.length_unit))) issues.push(`${id}: ID / frame / unit`)
    ids.add(id)
    if(r.kind==='box') {
      const rows=g.rotation
      if(!vector(g.center)||!vector(g.size)||g.size.some(n=>n<=0)||!Array.isArray(rows)||rows.length!==3||!rows.every(unit)) issues.push(`${id}: box`)
      else {
        const [a,b,c]=rows as number[][]
        const dot=(x:number[],y:number[])=>x.reduce((s,v,i)=>s+v*y[i]!,0)
        const determinant=a![0]!*(b![1]!*c![2]!-b![2]!*c![1]!)-a![1]!*(b![0]!*c![2]!-b![2]!*c![0]!)+a![2]!*(b![0]!*c![1]!-b![1]!*c![0]!)
        if(Math.abs(dot(a!,b!))>1e-8||Math.abs(dot(a!,c!))>1e-8||Math.abs(dot(b!,c!))>1e-8||Math.abs(determinant-1)>1e-8)issues.push(`${id}: rotation`)
      }
    } else if(r.kind==='cylinder') {
      if(!vector(g.center)||!unit(g.axis)||!finite(g.radius)||g.radius<=0||!finite(g.length)||g.length<=0)issues.push(`${id}: cylinder`)
    } else if(r.kind==='section-band') {
      if(!vector(g.origin)||!unit(g.normal)||!finite(g.thickness)||g.thickness<=0)issues.push(`${id}: section-band`)
    } else issues.push(`${id}: kind`)
    if(rois[0]&&(r.frame_id!==rois[0].frame_id||r.length_unit!==rois[0].length_unit))issues.push(`${id}: space`)
    const seen=new Set<unknown>();let next:Form|undefined=r
    while(next?.kind==='section-band') {
      if(seen.has(next.roi_id)){issues.push(`${id}: cycle`);break}
      seen.add(next.roi_id);next=rois.find(x=>x.roi_id===object(next!.geometry).bounds_roi_id)
      if(!next)issues.push(`${id}: bounds_roi_id`)
    }
  }
  return issues
}
export function geometryIssues(kind: string, value: unknown): string[] {
  const p=object(value), issues:string[]=[]
  if(kind==='crop-roi') {
    const bounds=Array.isArray(p.bounds)?p.bounds.map(object):[]
    if(!['parameters','input'].includes(String(p.kind)))return ['source']
    if(p.kind==='input'&&p.roi!==undefined)issues.push('source / roi')
    return [...issues,...roiIssues(p.kind==='parameters'?[object(p.roi),...bounds]:bounds)]
  }
  const plane=kind==='fit-plane', q=object(p.quality_policy), rules=Array.isArray(q.rules)?q.rules.map(normalizeLimitRule):[]
  if(!identifier(q.policy_id)||!Number.isSafeInteger(q.policy_version)||Number(q.policy_version)<1)issues.push('quality_policy / identity')
  if(!rules.length||new Set(rules.map(r=>r.item_id)).size!==rules.length||rules.some(r=>limitRuleError(r)))issues.push('quality_policy / rules')
  const byId=new Map(rules.filter(r=>r.enabled&&r.required).map(r=>[r.item_id,r]))
  const required=plane?planeMetrics:[...frameMetrics,...(object(p.origin).kind==='three-planes'?['origin_condition']:[])]
  for(const id of required) {
    const r=byId.get(id), upper=['rms','max_residual','origin_condition'].includes(id)
    if(!r||(upper?(r.upper===null||r.upper<(id==='origin_condition'?1:0)):(r.lower===null||r.lower<=0||(id==='inlier_count'&&r.lower<3))))issues.push(`quality / ${id}`)
    if(r&&!['rms','max_residual'].includes(id)&&r.unit!=='1')issues.push(`quality / ${id} / unit`)
  }
  if(plane) {
    if(!identifier(p.feature_id)||!unit(p.positive_normal)||!finite(p.min_orientation_cosine)||p.min_orientation_cosine<=0||p.min_orientation_cosine>1)issues.push('plane / identity / direction')
    const a=object(p.algorithm)
    if(a.kind==='ransac-svd') {
      if(!finite(a.distance_threshold)||a.distance_threshold<=0||!Number.isSafeInteger(a.sample_size)||Number(a.sample_size)<3||!Number.isSafeInteger(a.iterations)||Number(a.iterations)<1||!finite(a.probability)||a.probability<=0||a.probability>1)issues.push('RANSAC')
    } else if(a.kind!=='svd')issues.push('algorithm')
  } else {
    const o=object(p.origin),x=object(p.x_axis), ids=[p.primary_feature_id]
    if(!identifier(p.pose_id)||!identifier(p.target_frame_id)||!unit(p.positive_z))issues.push('frame / identity / direction')
    if(x.kind==='direction'){if(!unit(x.direction))issues.push('x_axis / direction')}
    else if(x.kind==='plane-intersection'){ids.push(x.secondary_feature_id);if(!unit(x.positive_direction))issues.push('x_axis / positive_direction')}
    else issues.push('x_axis')
    if(o.kind==='anchor-projection'){if(!vector(o.anchor))issues.push('origin / anchor');if(rules.some(r=>r.item_id==='origin_condition'))issues.push('origin_condition')}
    else if(o.kind==='three-planes'){ids.push(o.tertiary_feature_id);if(x.kind!=='plane-intersection')issues.push('origin / secondary')}
    else issues.push('origin')
    if(ids.some(id=>!identifier(id))||new Set(ids).size!==ids.length)issues.push('datum IDs')
  }
  return issues
}
