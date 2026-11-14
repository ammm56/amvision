import {identity,newRoi,object,roiIssues,vector,type Form} from './form'
import {normalizeLimitRule,limitRuleError} from '@/workflows/workflow-editor/parameters/limit-rules'
import type {RecipeValidator} from '@/workflows/workflow-editor/parameters/recipe-validation'
import {evaluationIssues,axisDirection} from './evaluation-form'
import {newEnvelope,envelopeIssues} from './envelope-form'
import {fragmentIssues,selectionIssues,robustIssues} from './circle-form'
import {dimensionFeatureChoices} from './dimension-form'
import {edgeIssues,isEdge} from './edge-form'

export const boundaryRecipeValidator:RecipeValidator=(node,sources,zh)=>{
  const kind=node.node_type_id.split('.').at(-1)!,p=object(node.parameters.settings),issues=boundaryIssues(kind,p)
  if(kind==='extract-boundary'){
    if(isEdge(p)){
      if(sources.features?.length||sources.pose?.length||sources.evidence?.length)issues.push(zh?'实测边 / 采样诊断不接受平面、位姿或尺寸端口':'Edge diagnostics do not accept plane, pose or measurement ports')
      if((object(p.method).kind==='height-jump')?(sources.height_map?.length!==1):!!sources.height_map?.length)issues.push(zh?'高度图连接与提取方法不一致':'Height map connection differs from extraction method')
      return issues
    }
    const m=object(p.method),e=object(p.evaluation),h=object(m.height),dynamic=['pose-contour','visible-envelope'].includes(String(m.kind)),ratio=dynamic&&h.kind==='measurement-ratio'
    if((m.kind==='contour'||dynamic)!==!!sources.features?.length)issues.push(zh?'等高提取需要当前平面特征':'Contour extraction requires current plane features')
    if(dynamic?(sources.pose?.length!==1):!!sources.pose?.length)issues.push(zh?'评价来源与位姿连接不一致':'Evaluation source and pose connection differ')
    if(ratio?!sources.evidence?.length:!!sources.evidence?.length)issues.push(zh?'等高来源与测量证据连接不一致':'Contour source and measurement evidence differ')
    const pose=sources.pose?.[0]
    if(dynamic&&pose?.nodeTypeId==='custom.metrology3d.build-frame'){
      const q=object(pose.parameters.settings)
      if(e.pose_id!==q.pose_id||e.target_frame_id!==q.target_frame_id)issues.push(zh?'位姿身份与当前连线不一致':'Pose identity differs from current connection')
    }else if(dynamic&&pose&&['custom.metrology3d.invert-pose','custom.metrology3d.compose-pose'].includes(pose.nodeTypeId)){
      issues.push(zh?'动态等高需要 Build Frame 主基准，不能连接派生坐标':'Dynamic contours require a Build Frame datum, not a derived pose')
    }
    const known=(sources.features??[]).every(s=>['custom.metrology3d.fit-plane','custom.metrology3d.height-query'].includes(s.nodeTypeId))
    const ids=(sources.features??[]).map(s=>object(s.nodeTypeId.endsWith('height-query')?object(s.parameters.settings).plane_fit:s.parameters.settings).feature_id)
    if(known&&(new Set(ids).size!==ids.length||[...((m.kind==='contour'||dynamic)?[m.reference_feature_id]:[]),...(ratio?[h.reference_feature_id,h.target_feature_id]:[])].some(id=>!ids.includes(id))))issues.push(zh?'平面来源缺失或重复':'Plane sources are missing or duplicated')
    if(ratio&&(sources.evidence??[]).every(s=>['custom.metrology3d.measure-step','custom.metrology3d.height-query'].includes(s.nodeTypeId))&&!(sources.evidence??[]).some(s=>object(s.parameters.settings).item_id===h.item_id))issues.push(zh?'测量量不在当前证据输入中':'Measurement item is not in current evidence inputs')
  }
  if(kind!=='extract-boundary'&&!sources.features?.length)issues.push(zh?'必须连接边界特征':'Boundary features input is required')
  if(kind!=='extract-boundary'&&(sources.features??[]).some(s=>object(object(s.parameters.settings).method).kind==='visible-envelope'))issues.push(zh?'格剖面不能作为实测截线拟合':'Grid profiles are not measured sections for fitting')
  if(kind!=='extract-boundary'){
    const choices=dimensionFeatureChoices(sources),selection=object(p.selection),selected=choices.filter(c=>c.id===selection.feature_id&&c.kind==='boundary')
    const complete=(sources.features??[]).every(s=>s.nodeTypeId==='custom.metrology3d.extract-boundary'||object(s.previewOutput).format_id==='amvision.features3d.v1')
    if(complete&&selected.length!==1)issues.push(zh?'边界来源缺失或重复':'Boundary source is missing or duplicated')
    if(selected.length===1){const c=selected[0]!;if(Array.isArray(selection.segment_ids)&&selection.segment_ids.some(id=>!c.segments.includes(String(id)))||Array.isArray(selection.group_ids)&&selection.group_ids.some(id=>!c.groups.includes(String(id))))issues.push(zh?'支持选择不在当前边界中':'Selected support is not in current boundary')}
  }
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
export function newBoundaryMethod(kind:string):Form{return kind==='projection'?{kind}:kind==='section'?{kind,origin:[null,null,null],normal:[null,null,null],numeric_tolerance:null}:['pose-contour','visible-envelope'].includes(kind)?{kind,reference_feature_id:'',height:newContourHeight('fixed'),numeric_tolerance:null,...(kind==='visible-envelope'?{envelope:newEnvelope()}:{})}:{kind,reference_feature_id:'',positive_normal:[null,null,null],min_orientation_cosine:null,height:null,numeric_tolerance:null}}
export function newBoundarySettings(kind:string):Form{
  const common={feature_id:'',evaluation:{frame_id:'',length_unit:null,origin:[null,null,null],rotation:identity()},quality_policy:{policy_id:'',policy_version:null,rules:(boundaryMetrics[kind]??[]).map(item_id=>normalizeLimitRule({item_id,unit:['support_count','direction_gap','jacobian_ratio'].includes(item_id)?'1':item_id==='angular_coverage'||kind==='fit-circle'&&item_id==='max_gap'?'rad':''}))}}
  if(kind==='extract-boundary')return {...common,region:newRegion(),surface:{alpha_radius:null,max_edge_length:null,max_normal_step:null,min_projected_area:null},method:{kind:null},targets:[]}
  return {...common,selection:{feature_id:'',segment_ids:[]},...(kind==='fit-line'?{positive_direction:[null,null,null],min_orientation_cosine:null}:{radius_range:[null,null],max_arc_step:null,solver:{ftol:null,xtol:null,gtol:null,max_nfev:null,x_scale:[null,null,null]}})}
}
const finite=(v:unknown):v is number=>typeof v==='number'&&Number.isFinite(v)
const positive=(v:unknown)=>finite(v)&&v>0
const id=(v:unknown)=>typeof v==='string'&&/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/.test(v)
const unit=(v:unknown)=>vector(v)&&Math.abs(v.reduce((a,b)=>a+b*b,0)-1)<=1e-8
export function regionErrors(value:unknown,e:Form):string[]{const r=object(value),rois=Array.isArray(r.rois)?r.rois.map(object):[];return !rois.length||!rois.some(i=>i.roi_id===r.roi_id)?['ROI']: [...roiIssues(rois),...(rois.some(i=>i.frame_id!==e.frame_id||i.length_unit!==e.length_unit)?['ROI / space']:[])]}
/** 表单只做现有规则的前置反馈，最终完整 Schema 与算法准入由后端校验。 */
export function boundaryIssues(kind:string,value:unknown):string[]{
  if(kind==='extract-boundary'&&isEdge(value))return edgeIssues(value)
  const p=object(value),e=object(p.evaluation),q=object(p.quality_policy),issues:string[]=[]
  if(!id(p.feature_id))issues.push('feature')
  issues.push(...evaluationIssues(e,kind==='extract-boundary'?['pose']:['feature']))
  const rules=Array.isArray(q.rules)?q.rules.map(normalizeLimitRule):[],byId=new Map(rules.filter(r=>r.enabled&&r.required).map(r=>[r.item_id,r]))
  if(!id(q.policy_id)||!Number.isSafeInteger(q.policy_version)||Number(q.policy_version)<1||rules.some(limitRuleError)||new Set(rules.map(r=>r.item_id)).size!==rules.length)issues.push('quality / policy')
  for(const key of boundaryMetrics[kind]??[]){const rule=byId.get(key),upper=['plane_max_residual','rms','max_residual','max_gap'].includes(key);if(!rule||(upper?rule.upper===null||rule.upper<0:rule.lower===null||rule.lower<=0||key==='support_count'&&rule.lower<(kind==='fit-circle'?3:2)))issues.push(`quality / ${key}`)}
  if(kind==='extract-boundary'){
    issues.push(...regionErrors(p.region,e));const s=object(p.surface),m=object(p.method),targets=Array.isArray(p.targets)?p.targets.map(object):[]
    const visible=m.kind==='visible-envelope'
    if(visible?p.surface!==null:['alpha_radius','max_edge_length','max_normal_step','min_projected_area'].some(k=>!positive(s[k])))issues.push('surface')
    if(!['projection','section','contour','pose-contour','visible-envelope'].includes(String(m.kind)))issues.push('method')
    if(['pose-contour','visible-envelope'].includes(String(m.kind))!==(e.kind==='pose'))issues.push('method / evaluation source')
    if(m.kind!=='projection'&&!positive(m.numeric_tolerance))issues.push('numeric_tolerance')
    if(m.kind==='section'&&(!vector(m.origin)||!unit(m.normal)))issues.push('section')
    if(m.kind==='contour'&&(!id(m.reference_feature_id)||!unit(m.positive_normal)||!finite(m.height)||!positive(m.min_orientation_cosine)||Number(m.min_orientation_cosine)>1))issues.push('contour')
    if(m.kind==='pose-contour'||visible){
      const h=object(m.height)
      if(!id(m.reference_feature_id))issues.push('contour / datum')
      if(h.kind==='fixed'?(!finite(h.value)||Object.keys(h).length!==2):h.kind==='measurement-ratio'?(!id(h.item_id)||!id(h.reference_feature_id)||!id(h.target_feature_id)||h.reference_feature_id===h.target_feature_id||!finite(h.ratio)||h.ratio<=0||h.ratio>=1||!['target-above','target-below'].includes(String(h.order))||Object.keys(h).length!==6):true)issues.push('contour / height source')
    }
    if(visible){
      issues.push(...envelopeIssues(m.envelope))
      if(targets.length||!Array.isArray(p.targets))issues.push('profiles / targets')
      const h=object(m.height),foreground=object(object(m.envelope).profiles).foreground
      if(h.kind==='measurement-ratio'&&((h.order==='target-above')!==(foreground==='above')))issues.push('foreground / order')
      for(const key of ['profile_coverage','estimated_fraction','profile_max_gap','max_cell_span']){const rule=byId.get(key);if(!rule||rule.unit!==(['profile_coverage','estimated_fraction'].includes(key)?'1':e.length_unit)||(key==='profile_coverage'?rule.lower===null||rule.lower<=0||rule.lower>1:rule.upper===null||rule.upper<0||key==='estimated_fraction'&&rule.upper>1))issues.push(`quality / ${key}`)}
    }else if(!targets.length||new Set(targets.map(t=>t.group_id??t.segment_id)).size!==targets.length)issues.push('targets')
    for(const t of targets){if('group_id' in t)issues.push(...fragmentIssues(t));else if(!id(t.segment_id)||typeof t.closed!=='boolean'||!['outer','inner','open','unknown'].includes(String(t.role))||(t.closed?t.role==='open':['outer','inner'].includes(String(t.role))))issues.push('target / identity');issues.push(...regionErrors(t.region,e))}
  }else{
    issues.push(...selectionIssues(p.selection))
    if(kind==='fit-circle')issues.push(...robustIssues(p.robust,q))
    if(kind==='fit-line'){if((!unit(p.positive_direction)&&!axisDirection(p.positive_direction))||!positive(p.min_orientation_cosine)||Number(p.min_orientation_cosine)>1)issues.push('direction')}
    else{const r=p.radius_range,solver=object(p.solver);if(!Array.isArray(r)||r.length!==2||!r.every(positive)||!(r[0]<r[1])||!positive(p.max_arc_step)||Number(p.max_arc_step)>=Math.PI)issues.push('circle / radius / arc');if(['ftol','xtol','gtol'].some(k=>!finite(solver[k])||Number(solver[k])<=Number.EPSILON||Number(solver[k])>=1)||!Number.isSafeInteger(solver.max_nfev)||Number(solver.max_nfev)<1||!vector(solver.x_scale)||!solver.x_scale.every(positive))issues.push('solver')}
  }
  return issues
}
