import {identity,newRoi,object,roiIssues,vector,type Form} from './form'
import {normalizeLimitRule,limitRuleError} from '@/workflows/workflow-editor/parameters/limit-rules'
import type {RecipeValidator} from '@/workflows/workflow-editor/parameters/recipe-validation'
import {evaluationIssues,axisDirection} from './evaluation-form'

export const boundaryRecipeValidator:RecipeValidator=(node,sources,zh)=>{
  const kind=node.node_type_id.split('.').at(-1)!,p=object(node.parameters.settings),issues=boundaryIssues(kind,p)
  if(kind==='extract-boundary'){
    const m=object(p.method),e=object(p.evaluation),h=object(m.height),dynamic=m.kind==='pose-contour',ratio=dynamic&&h.kind==='measurement-ratio'
    if((m.kind==='contour'||dynamic)!==!!sources.features?.length)issues.push(zh?'等高提取需要当前平面特征':'Contour extraction requires current plane features')
    if(dynamic?(sources.pose?.length!==1):!!sources.pose?.length)issues.push(zh?'评价来源与位姿连接不一致':'Evaluation source and pose connection differ')
    if(ratio?!sources.evidence?.length:!!sources.evidence?.length)issues.push(zh?'等高来源与测量证据连接不一致':'Contour source and measurement evidence differ')
    const pose=sources.pose?.[0]
    if(dynamic&&pose?.nodeTypeId==='custom.metrology3d.build-frame'){
      const q=object(pose.parameters.settings)
      if(e.pose_id!==q.pose_id||e.target_frame_id!==q.target_frame_id)issues.push(zh?'位姿身份与当前连线不一致':'Pose identity differs from current connection')
    }
    const known=(sources.features??[]).every(s=>['custom.metrology3d.fit-plane','custom.metrology3d.height-query'].includes(s.nodeTypeId))
    const ids=(sources.features??[]).map(s=>object(s.nodeTypeId.endsWith('height-query')?object(s.parameters.settings).plane_fit:s.parameters.settings).feature_id)
    if(known&&(new Set(ids).size!==ids.length||[...((m.kind==='contour'||dynamic)?[m.reference_feature_id]:[]),...(ratio?[h.reference_feature_id,h.target_feature_id]:[])].some(id=>!ids.includes(id))))issues.push(zh?'平面来源缺失或重复':'Plane sources are missing or duplicated')
    if(ratio&&(sources.evidence??[]).every(s=>['custom.metrology3d.measure-step','custom.metrology3d.height-query'].includes(s.nodeTypeId))&&!(sources.evidence??[]).some(s=>object(s.parameters.settings).item_id===h.item_id))issues.push(zh?'测量量不在当前证据输入中':'Measurement item is not in current evidence inputs')
  }
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
export function newContourHeight(kind:string):Form{return kind==='fixed'?{kind,value:null}:{kind:'measurement-ratio',item_id:'',reference_feature_id:'',target_feature_id:'',ratio:null,order:null}}
export function newBoundaryMethod(kind:string):Form{return kind==='projection'?{kind}:kind==='section'?{kind,origin:[null,null,null],normal:[null,null,null],numeric_tolerance:null}:kind==='pose-contour'?{kind,reference_feature_id:'',height:newContourHeight('fixed'),numeric_tolerance:null}:{kind,reference_feature_id:'',positive_normal:[null,null,null],min_orientation_cosine:null,height:null,numeric_tolerance:null}}
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
  if(!id(p.feature_id))issues.push('feature')
  issues.push(...evaluationIssues(e,kind==='extract-boundary'?['pose']:['feature']))
  const rules=Array.isArray(q.rules)?q.rules.map(normalizeLimitRule):[],byId=new Map(rules.filter(r=>r.enabled&&r.required).map(r=>[r.item_id,r]))
  if(!id(q.policy_id)||!Number.isSafeInteger(q.policy_version)||Number(q.policy_version)<1||rules.some(limitRuleError)||new Set(rules.map(r=>r.item_id)).size!==rules.length)issues.push('quality / policy')
  for(const key of boundaryMetrics[kind]??[]){const rule=byId.get(key),upper=['plane_max_residual','rms','max_residual','max_gap'].includes(key);if(!rule||(upper?rule.upper===null||rule.upper<0:rule.lower===null||rule.lower<=0||key==='support_count'&&rule.lower<(kind==='fit-circle'?3:2)))issues.push(`quality / ${key}`)}
  if(kind==='extract-boundary'){
    issues.push(...regionErrors(p.region,e));const s=object(p.surface),m=object(p.method),targets=Array.isArray(p.targets)?p.targets.map(object):[]
    if(['alpha_radius','max_edge_length','max_normal_step','min_projected_area'].some(k=>!positive(s[k])))issues.push('surface')
    if(!['projection','section','contour','pose-contour'].includes(String(m.kind)))issues.push('method')
    if((m.kind==='pose-contour')!==(e.kind==='pose'))issues.push('method / evaluation source')
    if(m.kind!=='projection'&&!positive(m.numeric_tolerance))issues.push('numeric_tolerance')
    if(m.kind==='section'&&(!vector(m.origin)||!unit(m.normal)))issues.push('section')
    if(m.kind==='contour'&&(!id(m.reference_feature_id)||!unit(m.positive_normal)||!finite(m.height)||!positive(m.min_orientation_cosine)||Number(m.min_orientation_cosine)>1))issues.push('contour')
    if(m.kind==='pose-contour'){
      const h=object(m.height)
      if(!id(m.reference_feature_id))issues.push('contour / datum')
      if(h.kind==='fixed'?(!finite(h.value)||Object.keys(h).length!==2):h.kind==='measurement-ratio'?(!id(h.item_id)||!id(h.reference_feature_id)||!id(h.target_feature_id)||h.reference_feature_id===h.target_feature_id||!finite(h.ratio)||h.ratio<=0||h.ratio>=1||!['target-above','target-below'].includes(String(h.order))||Object.keys(h).length!==6):true)issues.push('contour / height source')
    }
    if(!targets.length||new Set(targets.map(t=>t.segment_id)).size!==targets.length)issues.push('targets')
    for(const t of targets){if(!id(t.segment_id)||typeof t.closed!=='boolean'||!['outer','inner','open','unknown'].includes(String(t.role))||(t.closed?t.role==='open':['outer','inner'].includes(String(t.role))))issues.push('target / identity');issues.push(...regionErrors(t.region,e))}
  }else{
    const s=object(p.selection),ids=s.segment_ids
    if(!id(s.feature_id)||!Array.isArray(ids)||!ids.length||ids.some(v=>!id(v))||new Set(ids).size!==ids.length)issues.push('selection')
    if(kind==='fit-line'){if((!unit(p.positive_direction)&&!axisDirection(p.positive_direction))||!positive(p.min_orientation_cosine)||Number(p.min_orientation_cosine)>1)issues.push('direction')}
    else{const r=p.radius_range,solver=object(p.solver);if(!Array.isArray(r)||r.length!==2||!r.every(positive)||!(r[0]<r[1])||!positive(p.max_arc_step)||Number(p.max_arc_step)>=Math.PI)issues.push('circle / radius / arc');if(['ftol','xtol','gtol'].some(k=>!finite(solver[k])||Number(solver[k])<=Number.EPSILON||Number(solver[k])>=1)||!Number.isSafeInteger(solver.max_nfev)||Number(solver.max_nfev)<1||!vector(solver.x_scale)||!solver.x_scale.every(positive))issues.push('solver')}
  }
  return issues
}
