/** 关系编辑只组织显式参数；测量、支持检查和拟合仍在后端。 */
import {normalizeLimitRule,limitRuleError} from '@/workflows/workflow-editor/parameters/limit-rules'
import type {ParameterEditorSources} from '@/workflows/workflow-editor/parameters/editor-context'
import type {RecipeValidator} from '@/workflows/workflow-editor/parameters/recipe-validation'
import type {NumericItemProvider} from '@/workflows/workflow-editor/parameters/static-numeric-items'
import {object,vector,type Form} from './form'
import {evaluationIssues,newEvaluation} from './evaluation-form'
import {dimensionFeatureChoices} from './dimension-form'

export const relationKinds=['point-point','point-line','point-plane','line-line','line-angle','plane-angle']
const id=(v:unknown)=>typeof v==='string'&&/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/.test(v)
const finite=(v:unknown):v is number=>typeof v==='number'&&Number.isFinite(v)
export function newOperand(kind:string):Form {
  return kind==='coordinate'?{kind,position:[null,null,null]}:kind==='source-point'?{kind,source_index:null}:{kind,feature_id:''}
}
export function newRelation(kind='point-point'):Form {
  const point=newOperand('coordinate'),line=newOperand('line'),plane=newOperand('plane')
  const relation:Form={kind,reference:point,target:newOperand('coordinate')}
  if(kind==='point-line')Object.assign(relation,{target:line,support_mode:'finite'})
  if(kind==='point-plane')Object.assign(relation,{target:plane,support_mode:'finite',value_mode:'absolute',coverage:newCoverage()})
  if(kind==='line-line')Object.assign(relation,{reference:line,target:newOperand('line'),support_mode:'finite',min_crossing_sine:null})
  if(kind.endsWith('angle'))Object.assign(relation,{reference:kind==='line-angle'?line:plane,target:newOperand(kind==='line-angle'?'line':'plane'),angle_mode:'unoriented'})
  return {space:{kind:'spatial',frame_id:'',length_unit:null},relation,item_id:'',quality_policy:{policy_id:'',policy_version:1,rules:[normalizeLimitRule({item_id:'geometry_usable',unit:'1',lower:1})]}}
}
export const newCoverage=()=>({support_radius:null,min_support_count:null,max_triangle_edge:null,max_plane_residual:null})
export function relationSpace(value:unknown,kind:string):Form {
  const s=object(value),current=s.kind==='projection'?object(s.plane):s
  return kind==='projection'?{kind,plane:newEvaluation('configured',current),min_direction_norm:null}:{kind,frame_id:current.frame_id??'',length_unit:current.length_unit??null}
}
export function relationIssues(value:unknown):string[] {
  const p=object(value),r=object(p.relation),s=object(p.space),q=object(p.quality_policy),issues:string[]=[]
  if(!id(p.item_id))issues.push('item_id')
  if(!relationKinds.includes(String(r.kind)))issues.push('relation')
  if(s.kind==='spatial') {if(!id(s.frame_id)||!['m','mm','um'].includes(String(s.length_unit)))issues.push('space')}
  else if(s.kind==='projection') {issues.push(...evaluationIssues(s.plane,[]));if(!finite(s.min_direction_norm)||s.min_direction_norm<=0||s.min_direction_norm>1)issues.push('min_direction_norm')}
  else issues.push('space')
  for(const role of ['reference','target']){
    const o=object(r[role]),expected=r.kind==='plane-angle'||r.kind==='point-plane'&&role==='target'?'plane':String(r.kind).startsWith('line')||r.kind==='point-line'&&role==='target'?'line':'point'
    if(expected==='point'){
      if(o.kind==='coordinate'){if(!vector(o.position))issues.push(`${role}.position`)}
      else if(o.kind==='source-point'){if(!Number.isSafeInteger(o.source_index)||Number(o.source_index)<0)issues.push(`${role}.source_index`)}
      else if(o.kind!=='circle-center'||!id(o.feature_id))issues.push(`${role}.point`)
    }else if(o.kind!==expected||!id(o.feature_id))issues.push(`${role}.feature_id`)
  }
  if(['point-line','point-plane','line-line'].includes(String(r.kind))&&!['finite','model'].includes(String(r.support_mode)))issues.push('support_mode')
  if(r.kind==='line-line'&&(!finite(r.min_crossing_sine)||r.min_crossing_sine<=0||r.min_crossing_sine>1))issues.push('min_crossing_sine')
  if(r.kind==='point-plane'){
    if(s.kind!=='spatial'||!['absolute','signed'].includes(String(r.value_mode)))issues.push('point-plane')
    const c=object(r.coverage)
    if(r.support_mode==='finite'){
      if(!finite(c.support_radius)||c.support_radius<=0||!Number.isSafeInteger(c.min_support_count)||Number(c.min_support_count)<3||!finite(c.max_triangle_edge)||c.max_triangle_edge<=0||!finite(c.max_plane_residual)||c.max_plane_residual<0)issues.push('coverage')
    }else if(r.coverage!==null)issues.push('coverage')
  }
  if(String(r.kind).endsWith('angle')&&(!['unoriented','oriented','signed'].includes(String(r.angle_mode))||r.angle_mode==='signed'&&s.kind!=='projection'))issues.push('angle_mode')
  const rules=Array.isArray(q.rules)?q.rules.map(normalizeLimitRule):[],guard=rules.find(r=>r.item_id==='geometry_usable')
  if(!id(q.policy_id)||!Number.isSafeInteger(q.policy_version)||Number(q.policy_version)<1)issues.push('quality_policy')
  const allowed=String(r.kind).endsWith('angle')?['geometry_usable','reference_usable','target_usable']:['geometry_usable','reference_usable','target_usable','contacts_unique']
  if(!guard?.enabled||!guard.required||guard.lower!==1||!guard.include_lower||new Set(rules.map(r=>r.item_id)).size!==rules.length||rules.some(r=>limitRuleError(r)||!allowed.includes(r.item_id)||r.unit!=='1'))issues.push('quality.rules')
  return issues
}
export function relationChoices(sources:ParameterEditorSources){
  return [...dimensionFeatureChoices(sources),...(sources.features??[]).flatMap(s=>{
    const p=object(s.parameters.settings),out=object(s.previewOutput)
    if(s.nodeTypeId==='custom.metrology3d.fit-plane'&&id(p.feature_id))return [{id:String(p.feature_id),kind:'plane',nodeId:s.nodeId,segments:[],groups:[]}]
    return Array.isArray(out.items)?out.items.map(object).filter(f=>f.kind==='plane'&&id(f.feature_id)).map(f=>({id:String(f.feature_id),kind:'plane',nodeId:s.nodeId,segments:[],groups:[]})):[]
  })]
}
export const relationNumericItems:NumericItemProvider=source=>{
  const p=object(source.parameters.settings),s=object(p.space),space=s.kind==='projection'?object(s.plane):s
  return id(p.item_id)&&['m','mm','um'].includes(String(space.length_unit))?[{item_id:String(p.item_id),unit:String(object(p.relation).kind).endsWith('angle')?'rad':String(space.length_unit)}]:null
}
export const relationRecipeValidator:RecipeValidator=(node,sources,zh)=>{
  const p=object(node.parameters.settings),r=object(p.relation),issues=relationIssues(p),choices=relationChoices(sources)
  if(sources.cloud?.length!==1)issues.push(zh?'必须连接一个当前点云':'Connect one current cloud')
  if(new Set(choices.map(c=>c.id)).size!==choices.length)issues.push(zh?'输入特征 ID 重复':'Duplicate feature IDs')
  const complete=(sources.features??[]).every(s=>['fit-plane','fit-line','fit-circle'].some(k=>s.nodeTypeId===`custom.metrology3d.${k}`)||object(s.previewOutput).format_id==='amvision.features3d.v1')
  for(const role of ['reference','target']){const o=object(r[role]);if(o.feature_id&&complete&&!choices.some(c=>c.id===o.feature_id&&c.kind===(o.kind==='circle-center'?'circle':o.kind)))issues.push(zh?`${role} 特征不在当前输入中`:`${role} feature is not in current inputs`)}
  return issues
}
