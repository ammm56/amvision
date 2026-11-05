import {limitRuleError,normalizeLimitRule} from '@/workflows/workflow-editor/parameters/limit-rules'
import {object,type Form} from './form'

const lower:Record<string,number>={correspondence_count:3,source_coverage:0,reference_coverage:0,observability:0,rank:6,converged:1}
export function newRegistration():Form {
  return {pose_id:'',source_frame_id:'',target_frame_id:'',length_unit:'',algorithm:'point-to-point',
    initial_translation:[null,null,null],initial_rotation_degrees:[null,null,null],
    max_correspondence_distance:null,max_iterations:null,fitness_change:null,rmse_change:null,
    quality_policy:{policy_id:'',policy_version:null,rules:[...Object.keys(lower),'rms','max_residual'].map(item_id=>normalizeLimitRule({item_id,unit:item_id in lower?'1':''}))}}
}
export function registrationIssues(p:Form):string[] {
  const issues:string[]=[],identifier=(v:unknown)=>typeof v==='string'&&/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/.test(v)
  const finite=(v:unknown)=>typeof v==='number'&&Number.isFinite(v)
  for(const k of ['pose_id','source_frame_id','target_frame_id'])if(!identifier(p[k]))issues.push(k)
  if(p.source_frame_id===p.target_frame_id)issues.push('source = reference')
  if(!['m','mm','um'].includes(String(p.length_unit)))issues.push('length_unit')
  if(!['point-to-point','point-to-plane'].includes(String(p.algorithm)))issues.push('algorithm')
  for(const k of ['initial_translation','initial_rotation_degrees'])if(!Array.isArray(p[k])||p[k].length!==3||!p[k].every(finite))issues.push(k)
  for(const k of ['max_correspondence_distance','fitness_change','rmse_change'])if(!finite(p[k])||Number(p[k])<=0)issues.push(k)
  if(!Number.isSafeInteger(p.max_iterations)||Number(p.max_iterations)<1||Number(p.max_iterations)>2147483647)issues.push('max_iterations')
  const q=object(p.quality_policy),rules=(Array.isArray(q.rules)?q.rules:[]).map(normalizeLimitRule)
  if(!identifier(q.policy_id)||!Number.isSafeInteger(q.policy_version)||Number(q.policy_version)<1)issues.push('quality_policy / identity')
  if(!rules.length||rules.some(r=>limitRuleError(r))||new Set(rules.map(r=>r.item_id)).size!==rules.length)issues.push('quality_policy / rules')
  for(const [name,min] of Object.entries(lower)){
    const r=rules.find(r=>r.item_id===name&&r.enabled&&r.required)
    if(!r||r.unit!=='1'||r.lower===null||r.lower<min||(min===0&&r.lower<=0))issues.push(`quality / ${name}`)
  }
  for(const name of ['rms','max_residual']){const r=rules.find(r=>r.item_id===name&&r.enabled&&r.required);if(!r||r.unit!==p.length_unit||r.upper===null||r.upper<0)issues.push(`quality / ${name}`)}
  if(Object.keys(p).some(k=>!(k in newRegistration())))issues.push('unknown parameter')
  return issues
}
