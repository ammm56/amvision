import {limitRuleError,normalizeLimitRule} from '@/workflows/workflow-editor/parameters/limit-rules'
import {object,type Form} from './form'

const lower:Record<string,number>={correspondence_count:3,source_coverage:0,reference_coverage:0,observability:0,rank:6,converged:1}
export function newRegistration(initialization='explicit'):Form {
  return {pose_id:'',source_frame_id:'',target_frame_id:'',length_unit:'',algorithm:'point-to-point',initialization,
    ...(initialization==='fpfh'?{search:{feature_radius:null,feature_max_neighbors:null,max_correspondence_distance:null,edge_length_ratio:null,samples:null,iterations_per_trial:null,trials:null,equivalent_translation:null,equivalent_rotation_degrees:null}}:initialization==='datum'?{initial_uv:[null,null],initial_angle_degrees:null,max_solver_evaluations:null,solver_tolerance:null}:{initial_translation:[null,null,null],initial_rotation_degrees:[null,null,null]}),
    max_correspondence_distance:null,max_iterations:null,fitness_change:null,rmse_change:null,
    quality_policy:{policy_id:'',policy_version:null,rules:[...Object.keys(lower),'rms','max_residual',...(initialization==='fpfh'?['candidate_consistency']:initialization==='datum'?['datum_valid']:[])].map(item_id=>normalizeLimitRule({item_id,unit:item_id in lower||['candidate_consistency','datum_valid'].includes(item_id)?'1':''}))}}
}
export function changeRegistrationMode(p:Form,mode:string):Form {
  const next=newRegistration(mode)
  for(const key of Object.keys(next))if(key in p&&!['initialization','search','initial_translation','initial_rotation_degrees','initial_uv','initial_angle_degrees','max_solver_evaluations','solver_tolerance','quality_policy'].includes(key))next[key]=p[key]
  const q=object(p.quality_policy),rules=(Array.isArray(q.rules)?q.rules:[]).map(normalizeLimitRule).filter(r=>!['candidate_consistency','datum_valid'].includes(r.item_id))
  if((p.initialization==='datum')!==(mode==='datum')){const rank=rules.find(r=>r.item_id==='rank');if(rank){rank.lower=mode==='datum'?3:6;rank.upper=null;rank.include_lower=true}}
  if(mode==='fpfh')rules.push(normalizeLimitRule({item_id:'candidate_consistency',unit:'1',lower:1,upper:1}))
  if(mode==='datum')rules.push(normalizeLimitRule({item_id:'datum_valid',unit:'1',lower:1,upper:1}))
  next.quality_policy={...q,rules}
  return next
}
export function registrationIssues(p:Form):string[] {
  const issues:string[]=[],identifier=(v:unknown)=>typeof v==='string'&&/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/.test(v)
  const finite=(v:unknown)=>typeof v==='number'&&Number.isFinite(v)
  for(const k of ['pose_id','source_frame_id','target_frame_id'])if(!identifier(p[k]))issues.push(k)
  if(p.source_frame_id===p.target_frame_id)issues.push('source = reference')
  if(!['m','mm','um'].includes(String(p.length_unit)))issues.push('length_unit')
  if(!['point-to-point','point-to-plane'].includes(String(p.algorithm)))issues.push('algorithm')
  const coarse=p.initialization==='fpfh',datum=p.initialization==='datum'
  if(!['explicit','fpfh','datum'].includes(String(p.initialization)))issues.push('initialization')
  if(!coarse&&!datum)for(const k of ['initial_translation','initial_rotation_degrees'])if(!Array.isArray(p[k])||p[k].length!==3||!p[k].every(finite))issues.push(k)
  if(datum){
    if(!Array.isArray(p.initial_uv)||p.initial_uv.length!==2||!p.initial_uv.every(finite))issues.push('initial_uv')
    if(!finite(p.initial_angle_degrees))issues.push('initial_angle_degrees')
    if(!Number.isSafeInteger(p.max_solver_evaluations)||Number(p.max_solver_evaluations)<1||Number(p.max_solver_evaluations)>2147483647)issues.push('max_solver_evaluations')
    if(!finite(p.solver_tolerance)||Number(p.solver_tolerance)<=Number.EPSILON||Number(p.solver_tolerance)>=1)issues.push('solver_tolerance')
  }
  if(coarse){
    const s=object(p.search)
    for(const k of ['feature_radius','max_correspondence_distance','equivalent_translation','edge_length_ratio','equivalent_rotation_degrees'])if(!finite(s[k])||Number(s[k])<=0)issues.push(`search / ${k}`)
    for(const [k,min,max] of [['feature_max_neighbors',3,2147483647],['samples',3,2147483647],['iterations_per_trial',1,2147483647],['trials',2,Math.floor(8192/11)]] as const)if(!Number.isSafeInteger(s[k])||Number(s[k])<min||Number(s[k])>max)issues.push(`search / ${k}`)
    if(Number(s.edge_length_ratio)>1||Number(s.equivalent_rotation_degrees)>180)issues.push('search / range')
    if(Object.keys(s).some(k=>!(k in object(newRegistration('fpfh').search))))issues.push('search / unknown parameter')
  }
  for(const k of ['max_correspondence_distance','fitness_change','rmse_change'])if(!finite(p[k])||Number(p[k])<=0)issues.push(k)
  if(!Number.isSafeInteger(p.max_iterations)||Number(p.max_iterations)<1||Number(p.max_iterations)>2147483647)issues.push('max_iterations')
  const q=object(p.quality_policy),rules=(Array.isArray(q.rules)?q.rules:[]).map(normalizeLimitRule)
  if(!identifier(q.policy_id)||!Number.isSafeInteger(q.policy_version)||Number(q.policy_version)<1)issues.push('quality_policy / identity')
  if(!rules.length||rules.some(r=>limitRuleError(r))||new Set(rules.map(r=>r.item_id)).size!==rules.length)issues.push('quality_policy / rules')
  for(const [name,min] of Object.entries({...lower,rank:datum?3:6})){
    const r=rules.find(r=>r.item_id===name&&r.enabled&&r.required)
    if(!r||r.unit!=='1'||r.lower===null||r.lower<min||(min===0&&r.lower<=0))issues.push(`quality / ${name}`)
  }
  for(const name of ['rms','max_residual']){const r=rules.find(r=>r.item_id===name&&r.enabled&&r.required);if(!r||r.unit!==p.length_unit||r.upper===null||r.upper<0)issues.push(`quality / ${name}`)}
  if(coarse){const r=rules.find(r=>r.item_id==='candidate_consistency');if(!r||!r.enabled||!r.required||r.unit!=='1'||r.lower!==1||!r.include_lower||(r.upper!==null&&(r.upper!==1||!r.include_upper)))issues.push('quality / candidate_consistency');if(rules.some(r=>![...Object.keys(lower),'rms','max_residual','source_count','reference_count','iterations','candidate_consistency'].includes(r.item_id)))issues.push('quality / unknown metric')}
  if(datum){const r=rules.find(r=>r.item_id==='datum_valid');if(!r||!r.enabled||!r.required||r.unit!=='1'||r.lower!==1||!r.include_lower||(r.upper!==null&&(r.upper!==1||!r.include_upper)))issues.push('quality / datum_valid');if(rules.some(r=>![...Object.keys(lower),'rms','max_residual','source_count','reference_count','iterations','datum_valid'].includes(r.item_id)))issues.push('quality / unknown metric')}
  if(Object.keys(p).some(k=>!(k in newRegistration(String(p.initialization)))))issues.push('unknown parameter')
  return issues
}
