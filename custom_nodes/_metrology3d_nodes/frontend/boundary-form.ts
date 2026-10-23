import {identity,newRoi,object,roiIssues,vector,type Form} from './form'
import {normalizeLimitRule,limitRuleError} from '@/workflows/workflow-editor/parameters/limit-rules'
import type {RecipeValidator} from '@/workflows/workflow-editor/parameters/recipe-validation'

export const boundaryRecipeValidator:RecipeValidator=(node,sources,zh)=>{
  const kind=node.node_type_id.split('.').at(-1)!,p=object(node.parameters.settings),issues=boundaryIssues(kind,p)
  if(kind==='extract-boundary'&&((object(p.method).kind==='contour')!==!!sources.features?.length))issues.push(zh?'仅等高提取连接基准特征':'Only contour extraction connects datum features')
  if(kind!=='extract-boundary'&&!sources.features?.length)issues.push(zh?'必须连接边界特征':'Boundary features input is required')
  return issues
}

export const boundaryMetrics:Record<string,string[]>={
  'extract-boundary':['support_count','length'],
  'fit-line':['support_count','span','direction_gap','plane_max_residual','rms','max_residual'],
  'fit-circle':['support_count','angular_coverage','jacobian_ratio','max_gap','plane_max_residual','rms','max_residual'],
}
export function newRegion():Form{return {roi_id:'',rois:[newRoi()]}}
export function regionSource(value:unknown):Form{const p=object(value),rois=Array.isArray(p.rois)?p.rois.map(object):[];return {kind:'parameters',roi:rois.find(r=>r.roi_id===p.roi_id)??newRoi(),bounds:rois.filter(r=>r.roi_id!==p.roi_id)}}
export function regionValue(value:Form):Form{if(value.kind!=='parameters')throw new Error('boundary_roi_source');return {roi_id:object(value.roi).roi_id,rois:[value.roi,...(Array.isArray(value.bounds)?value.bounds:[])]}}
export function newBoundaryMethod(kind:string):Form{return kind==='projection'?{kind}:kind==='section'?{kind,origin:[null,null,null],normal:[null,null,null],numeric_tolerance:null}:{kind,reference_feature_id:'',positive_normal:[null,null,null],min_orientation_cosine:null,height:null,numeric_tolerance:null}}
export function newBoundarySettings(kind:string):Form{
  const common={feature_id:'',evaluation:{frame_id:'',length_unit:null,origin:[null,null,null],rotation:identity()},quality_policy:{policy_id:'',policy_version:null,rules:(boundaryMetrics[kind]??[]).map(item_id=>normalizeLimitRule({item_id,unit:['support_count','direction_gap','jacobian_ratio'].includes(item_id)?'1':item_id==='angular_coverage'||kind==='fit-circle'&&item_id==='max_gap'?'rad':''}))}}
  if(kind==='extract-boundary')return {...common,region:newRegion(),surface:{alpha_radius:null,max_edge_length:null,max_normal_step:null,min_projected_area:null},method:{kind:null},targets:[]}
  return {...common,selection:{feature_id:'',segment_ids:[]},...(kind==='fit-line'?{positive_direction:[null,null,null],min_orientation_cosine:null}:{radius_range:[null,null],max_arc_step:null,solver:{ftol:null,xtol:null,gtol:null,max_nfev:null,x_scale:[null,null,null]}})}
}
const finite=(v:unknown):v is number=>typeof v==='number'&&Number.isFinite(v)
const positive=(v:unknown)=>finite(v)&&v>0
const id=(v:unknown)=>typeof v==='string'&&/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/.test(v)
const unit=(v:unknown)=>vector(v)&&Math.abs(v.reduce((a,b)=>a+b*b,0)-1)<=1e-8
function regionErrors(value:unknown,e:Form):string[]{const r=object(value),rois=Array.isArray(r.rois)?r.rois.map(object):[];return !rois.length||!rois.some(i=>i.roi_id===r.roi_id)?['ROI']: [...roiIssues(rois),...(rois.some(i=>i.frame_id!==e.frame_id||i.length_unit!==e.length_unit)?['ROI / space']:[])]}
/** 表单只做现有规则的前置反馈，最终完整 Schema 与算法准入由后端校验。 */
export function boundaryIssues(kind:string,value:unknown):string[]{
  const p=object(value),e=object(p.evaluation),q=object(p.quality_policy),issues:string[]=[]
  if(!id(p.feature_id)||!id(e.frame_id)||!['m','mm','um'].includes(String(e.length_unit))||!vector(e.origin))issues.push('feature / evaluation')
  if(roiIssues([{...newRoi(),roi_id:'evaluation',frame_id:e.frame_id,length_unit:e.length_unit,geometry:{center:[0,0,0],size:[1,1,1],rotation:e.rotation}}]).length)issues.push('evaluation / rotation')
  const rules=Array.isArray(q.rules)?q.rules.map(normalizeLimitRule):[],byId=new Map(rules.filter(r=>r.enabled&&r.required).map(r=>[r.item_id,r]))
  if(!id(q.policy_id)||!Number.isSafeInteger(q.policy_version)||Number(q.policy_version)<1||rules.some(limitRuleError)||new Set(rules.map(r=>r.item_id)).size!==rules.length)issues.push('quality / policy')
  for(const key of boundaryMetrics[kind]??[]){const rule=byId.get(key),upper=['plane_max_residual','rms','max_residual','max_gap'].includes(key);if(!rule||(upper?rule.upper===null||rule.upper<0:rule.lower===null||rule.lower<=0||key==='support_count'&&rule.lower<(kind==='fit-circle'?3:2)))issues.push(`quality / ${key}`)}
  if(kind==='extract-boundary'){
    issues.push(...regionErrors(p.region,e));const s=object(p.surface),m=object(p.method),targets=Array.isArray(p.targets)?p.targets.map(object):[]
    if(['alpha_radius','max_edge_length','max_normal_step','min_projected_area'].some(k=>!positive(s[k])))issues.push('surface')
    if(!['projection','section','contour'].includes(String(m.kind)))issues.push('method')
    if(m.kind!=='projection'&&!positive(m.numeric_tolerance))issues.push('numeric_tolerance')
    if(m.kind==='section'&&(!vector(m.origin)||!unit(m.normal)))issues.push('section')
    if(m.kind==='contour'&&(!id(m.reference_feature_id)||!unit(m.positive_normal)||!finite(m.height)||!positive(m.min_orientation_cosine)||Number(m.min_orientation_cosine)>1))issues.push('contour')
    if(!targets.length||new Set(targets.map(t=>t.segment_id)).size!==targets.length)issues.push('targets')
    for(const t of targets){if(!id(t.segment_id)||typeof t.closed!=='boolean'||!['outer','inner','open','unknown'].includes(String(t.role))||(t.closed?t.role==='open':['outer','inner'].includes(String(t.role))))issues.push('target / identity');issues.push(...regionErrors(t.region,e))}
  }else{
    const s=object(p.selection),ids=s.segment_ids
    if(!id(s.feature_id)||!Array.isArray(ids)||!ids.length||ids.some(v=>!id(v))||new Set(ids).size!==ids.length)issues.push('selection')
    if(kind==='fit-line'){if(!unit(p.positive_direction)||!positive(p.min_orientation_cosine)||Number(p.min_orientation_cosine)>1)issues.push('direction')}
    else{const r=p.radius_range,solver=object(p.solver);if(!Array.isArray(r)||r.length!==2||!r.every(positive)||!(r[0]<r[1])||!positive(p.max_arc_step)||Number(p.max_arc_step)>=Math.PI)issues.push('circle / radius / arc');if(['ftol','xtol','gtol'].some(k=>!finite(solver[k])||Number(solver[k])<=Number.EPSILON||Number(solver[k])>=1)||!Number.isSafeInteger(solver.max_nfev)||Number(solver.max_nfev)<1||!vector(solver.x_scale)||!solver.x_scale.every(positive))issues.push('solver')}
  }
  return issues
}
