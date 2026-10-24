/** 尺寸配方、当前连线候选和静态量 ID；不在浏览器执行测量。 */
import {normalizeLimitRule,limitRuleError} from '@/workflows/workflow-editor/parameters/limit-rules'
import type {ParameterEditorSources} from '@/workflows/workflow-editor/parameters/editor-context'
import type {RecipeValidator} from '@/workflows/workflow-editor/parameters/recipe-validation'
import type {NumericItemProvider} from '@/workflows/workflow-editor/parameters/static-numeric-items'
import {identity,newRoi,object,roiIssues,vector,type Form} from './form'

const finite=(v:unknown):v is number=>typeof v==='number'&&Number.isFinite(v)
const id=(v:unknown)=>typeof v==='string'&&/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/.test(v)
const unit=(v:unknown)=>vector(v)&&Math.abs(v.reduce((s,x)=>s+x*x,0)-1)<=1e-8
export const dimensionComponents=['diameter','center_x','center_y','center_z']
/** 与公开参数指标一致，仅做配置提示；数值判定仍由后端执行。 */
function metricUnits(kind:string,p:Form):Record<string,string>{
  const length=String(object(p.evaluation).length_unit),units:Record<string,string>={geometry_usable:'1'}
  if(kind==='measure-extents'){
    Object.assign(units,{support_count:'1',span_u:length,span_v:length})
    if(object(p.mode).kind==='minimum-area-rectangle')for(const key of ['hull_point_count','candidate_count','tied_count','dimensions_consistent','orientation_unique'])units[key]='1'
  }else if(kind==='measure-edge-pair'){
    for(const role of ['reference','target'])for(const [key,u] of Object.entries({count:'1',plane_angle:'rad',plane_distance:length,crossing_sine:'1',intersection_residual:length,supported:'1'}))units[`${role}_${key}`]=u
  }else Object.assign(units,{support_count:'1',plane_max_residual:length,rms:length,max_residual:length,jacobian_ratio:'1',angular_coverage:'rad',max_gap:'rad',role_usable:'1'})
  return units
}
export function newExtentMode(kind:string):Form{
  return kind==='axis-spans'?{kind}:{kind,area_abs_tolerance:null,area_rel_tolerance:null,dimension_abs_tolerance:null,dimension_rel_tolerance:null,orientation_tolerance_radians:null}
}
export function newDimension(kind:string):Form{
  const common={evaluation:{frame_id:'',length_unit:null,origin:[null,null,null],rotation:identity()},quality_policy:{policy_id:'',policy_version:null,rules:[normalizeLimitRule({item_id:'geometry_usable',unit:'1',lower:1})]},outputs:[]}
  if(kind==='measure-extents')return {...common,source:{kind:'cloud'},mode:newExtentMode('axis-spans'),outputs:['u','v'].map(component=>({component,item_id:''}))}
  if(kind==='measure-edge-pair')return {...common,reference_feature_id:'',target_feature_id:'',query_position:[null,null,null],direction:[null,null,null],value_mode:'signed',max_plane_distance:null,max_plane_angle_radians:null,min_crossing_sine:null,outputs:[{component:'distance',item_id:''}]}
  return {...common,feature_id:'',target_kind:'closed-hole',display_direction:[null,null,null]}
}

export interface DimensionFeatureChoice {id:string;kind:string;segments:string[];nodeId:string}
export function dimensionFeatureChoices(sources:ParameterEditorSources):DimensionFeatureChoice[]{
  return (sources.features??[]).flatMap(source=>{
    const p=object(source.parameters.settings)
    const kind=source.nodeTypeId==='custom.metrology3d.fit-circle'?'circle':source.nodeTypeId==='custom.metrology3d.fit-line'?'line':source.nodeTypeId==='custom.metrology3d.extract-boundary'?'boundary':null
    if(kind&&id(p.feature_id))return [{id:String(p.feature_id),kind,segments:kind==='boundary'&&Array.isArray(p.targets)?p.targets.map(t=>String(object(t).segment_id)).filter(id):[],nodeId:source.nodeId}]
    // 恢复资产的身份只取该连线端口本次输出，不能借用其他预览窗口的同名特征。
    const output=object(source.previewOutput)
    if(output.format_id!=='amvision.features3d.v2'||!Array.isArray(output.items))return []
    return output.items.flatMap(raw=>{const f=object(raw),g=object(f.geometry);return id(f.feature_id)&&['line','circle','boundary'].includes(String(f.kind))?[{id:String(f.feature_id),kind:String(f.kind),nodeId:source.nodeId,segments:Array.isArray(g.segments)?g.segments.map(s=>String(object(s).segment_id)).filter(id):[]}]:[]})
  })
}

export function dimensionIssues(kind:string,value:unknown):string[]{
  const p=object(value),e=object(p.evaluation),q=object(p.quality_policy),issues:string[]=[]
  if(!id(e.frame_id)||!['m','mm','um'].includes(String(e.length_unit))||!vector(e.origin))issues.push('evaluation')
  if(roiIssues([{...newRoi(),roi_id:'evaluation',frame_id:e.frame_id,length_unit:e.length_unit,geometry:{center:[0,0,0],size:[1,1,1],rotation:e.rotation}}]).length)issues.push('evaluation / rotation')
  const outputs=Array.isArray(p.outputs)?p.outputs.map(object):[]
  const allowed=kind==='measure-extents'?(object(p.mode).kind==='axis-spans'?['u','v']:['length','width']):kind==='measure-edge-pair'?['distance']:dimensionComponents
  if(!outputs.length||outputs.some(o=>!id(o.item_id)||!allowed.includes(String(o.component)))||new Set(outputs.map(o=>o.item_id)).size!==outputs.length||new Set(outputs.map(o=>o.component)).size!==outputs.length||kind!=='measure-hole'&&outputs.length!==allowed.length)issues.push('outputs')
  const rules=Array.isArray(q.rules)?q.rules.map(normalizeLimitRule):[],guard=rules.find(r=>r.item_id==='geometry_usable')
  if(!id(q.policy_id)||!Number.isSafeInteger(q.policy_version)||Number(q.policy_version)<1||rules.some(limitRuleError)||new Set(rules.map(r=>r.item_id)).size!==rules.length)issues.push('quality / policy')
  if(!guard||!guard.enabled||!guard.required||guard.unit!=='1'||guard.lower!==1||!guard.include_lower)issues.push('quality / geometry_usable')
  const units=metricUnits(kind,p)
  if(rules.some(r=>units[r.item_id]!==r.unit))issues.push('quality / metric unit')
  const rotation=e.rotation,normal=Array.isArray(rotation)&&rotation.length===3&&rotation.every(vector)?rotation.map(row=>row[2]!):null
  const direction=kind==='measure-edge-pair'?p.direction:p.display_direction
  if(kind!=='measure-extents'&&normal&&vector(direction)&&Math.abs(normal.reduce((s,n,i)=>s+n*direction[i]!,0))>1e-8)issues.push('direction / evaluation plane')
  if(kind==='measure-extents'){
    const s=object(p.source),selection=object(s.selection),m=object(p.mode)
    if(!['cloud','boundary'].includes(String(s.kind)))issues.push('source')
    if(s.kind==='boundary'&&(!id(selection.feature_id)||!Array.isArray(selection.segment_ids)||!selection.segment_ids.length||selection.segment_ids.some(v=>!id(v))||new Set(selection.segment_ids).size!==selection.segment_ids.length))issues.push('source / selection')
    if(!['axis-spans','minimum-area-rectangle'].includes(String(m.kind)))issues.push('mode')
    if(m.kind==='minimum-area-rectangle'&&['area_abs_tolerance','area_rel_tolerance','dimension_abs_tolerance','dimension_rel_tolerance','orientation_tolerance_radians'].some(k=>!finite(m[k])||Number(m[k])<0||k==='orientation_tolerance_radians'&&Number(m[k])>=Math.PI/4))issues.push('rectangle / tolerances')
  }else if(kind==='measure-edge-pair'){
    if(!id(p.reference_feature_id)||!id(p.target_feature_id)||p.reference_feature_id===p.target_feature_id)issues.push('line IDs')
    if(!vector(p.query_position)||!unit(p.direction)||!['signed','absolute'].includes(String(p.value_mode)))issues.push('query / direction / value_mode')
    if(!finite(p.max_plane_distance)||p.max_plane_distance<0||!finite(p.max_plane_angle_radians)||p.max_plane_angle_radians<0||p.max_plane_angle_radians>=Math.PI/2||!finite(p.min_crossing_sine)||p.min_crossing_sine<=0||p.min_crossing_sine>1)issues.push('intersection conditions')
    const query=p.query_position,origin=e.origin
    if(normal&&vector(query)&&vector(origin)&&finite(p.max_plane_distance)&&Math.abs(normal.reduce((s,n,i)=>s+n*(query[i]!-origin[i]!),0))>p.max_plane_distance)issues.push('query / evaluation plane')
  }else if(!id(p.feature_id)||!['closed-hole','open-arc'].includes(String(p.target_kind))||!unit(p.display_direction))issues.push('circle / role / direction')
  return issues
}

export const dimensionNumericItems:NumericItemProvider=source=>{
  const p=object(source.parameters.settings),e=object(p.evaluation)
  return Array.isArray(p.outputs)&&['m','mm','um'].includes(String(e.length_unit))?p.outputs.map(object).filter(o=>id(o.item_id)).map(o=>({item_id:String(o.item_id),unit:String(e.length_unit)})):null
}
export const dimensionRecipeValidator:RecipeValidator=(node,sources,zh)=>{
  const kind=node.node_type_id.split('.').at(-1)!,p=object(node.parameters.settings),issues=dimensionIssues(kind,p)
  if(kind==='measure-extents'&&object(p.source).kind==='cloud'?(sources.cloud?.length!==1||!!sources.features?.length):(!sources.features?.length||!!sources.cloud?.length))issues.push(zh?'测量定义与输入连接不一致':'Measurement and input connections do not match')
  const choices=dimensionFeatureChoices(sources)
  if(new Set(choices.map(c=>c.id)).size!==choices.length)issues.push(zh?'输入特征 ID 重复':'Duplicate input feature IDs')
  const expected=kind==='measure-extents'?'boundary':kind==='measure-edge-pair'?'line':'circle'
  const selection=object(object(p.source).selection)
  const ids=kind==='measure-extents'?(object(p.source).kind==='boundary'?[selection.feature_id]:[]):kind==='measure-edge-pair'?[p.reference_feature_id,p.target_feature_id]:[p.feature_id]
  // read-cloud 的恢复特征只能由本次预览提供；尚无输出时不伪造候选。
  const complete=(sources.features??[]).every(s=>['custom.metrology3d.fit-line','custom.metrology3d.fit-circle','custom.metrology3d.extract-boundary'].includes(s.nodeTypeId)||object(s.previewOutput).format_id==='amvision.features3d.v2')
  if(complete&&ids.some(id=>!choices.some(c=>c.id===id&&c.kind===expected)))issues.push(zh?'所选特征不在当前输入中':'Selected feature is not in current inputs')
  const boundary=choices.find(c=>c.id===selection.feature_id&&c.kind==='boundary')
  if(boundary&&Array.isArray(selection.segment_ids)&&selection.segment_ids.some(id=>!boundary.segments.includes(String(id))))issues.push(zh?'所选边界段不在当前输入中':'Selected segment is not in current boundary')
  return issues
}
