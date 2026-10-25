/** M3.1 编辑校验只核对配方；完整点云计算仍由节点执行器负责。 */
import { normalizeLimitRule, limitRuleError } from '@/workflows/workflow-editor/parameters/limit-rules'
import type { RecipeValidator } from '@/workflows/workflow-editor/parameters/recipe-validation'
import type { NumericItemProvider } from '@/workflows/workflow-editor/parameters/static-numeric-items'
import { geometryIssues, newSettings, object, vector, type Form } from './form'

export const quantileMethods = ['inverted_cdf','averaged_inverted_cdf','closest_observation','interpolated_inverted_cdf','hazen','weibull','linear','median_unbiased','normal_unbiased','lower','higher','midpoint','nearest']
const finite = (v:unknown):v is number => typeof v==='number'&&Number.isFinite(v)
const id = (v:unknown) => typeof v==='string'&&/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/.test(v)
const unit = (v:unknown) => vector(v)&&Math.abs(v.reduce((a,b)=>a+b*b,0)-1)<=1e-8
export function measurementMetrics(statistic:boolean, lengthUnit:string) {
  return ['reference','target'].flatMap(side=>(statistic?['count','std']:['count','covered','direction_cosine','nearest_distance','triangle_edge','max_residual']).map(key=>({item_id:`${side}_${key}`,unit:['count','covered','direction_cosine'].includes(key)?'1':lengthUnit})))
}
export function newMeasurementMode(statistic=false):Form {
  const quality_policy = {policy_id:'',policy_version:null,rules:measurementMetrics(statistic,'').map(normalizeLimitRule)}
  return statistic?{kind:'roi-statistic',origin:[null,null,null],direction:[null,null,null],statistic:{kind:'mean'},quality_policy}:{kind:'directional-planes',reference_feature_id:'',target_feature_id:'',query_position:[null,null,null],direction:[null,null,null],support_radius:null,reference_policy:{kind:'measured-support'},quality_policy}
}
export function newMeasurement(height:boolean):Form {
  const {kind:_,target_feature_id:__,...directional}=newMeasurementMode()
  return {item_id:'',frame_id:'',length_unit:null,...(height?{...directional,search_radius:null,search_interval:[null,null],plane_fit:newSettings(true)}:{mode:newMeasurementMode()})}
}
export function measurementIssues(height:boolean, value:unknown):string[] {
  const p=object(value),s=height?p:object(p.mode),stat=s.kind==='roi-statistic',issues:string[]=[]
  if(!id(p.item_id)||!id(p.frame_id)||!['m','mm','um'].includes(String(p.length_unit)))issues.push('item_id / frame_id / length_unit')
  if(!height&&!['directional-planes','roi-statistic'].includes(String(s.kind)))issues.push('mode')
  if(!unit(s.direction))issues.push('direction')
  if(stat){
    if('reference_policy' in s)issues.push('reference_policy')
    const method=object(s.statistic)
    if(!vector(s.origin))issues.push('origin')
    if(method.kind==='quantile'){
      if(!finite(method.probability)||method.probability<0||method.probability>1||!quantileMethods.includes(String(method.method)))issues.push('quantile')
    }else if(!['mean','median'].includes(String(method.kind)))issues.push('statistic')
  }else{
    const policy=object(s.reference_policy)
    if(policy.kind==='plane-extension'){
      if(!finite(policy.max_extension_distance)||policy.max_extension_distance<=0)issues.push('reference_policy / max_extension_distance')
    }else if(policy.kind!=='measured-support'||Object.keys(policy).length!==1)issues.push('reference_policy')
    if(!vector(s.query_position)||!finite(s.support_radius)||s.support_radius<=0)issues.push('query_position / support_radius')
    if(!id(s.reference_feature_id)||!height&&(!id(s.target_feature_id)||s.reference_feature_id===s.target_feature_id))issues.push('feature IDs')
  }
  if(height){
    if(!finite(p.search_radius)||p.search_radius<=0||!Array.isArray(p.search_interval)||p.search_interval.length!==2||!p.search_interval.every(finite)||p.search_interval[0]>=p.search_interval[1])issues.push('search_radius / search_interval')
    issues.push(...geometryIssues('fit-plane',p.plane_fit).map(i=>`plane_fit / ${i}`))
    if(object(p.plane_fit).feature_id===p.reference_feature_id)issues.push('plane_fit / feature_id')
    const rules=object(object(p.plane_fit).quality_policy).rules
    if(Array.isArray(rules)&&rules.map(normalizeLimitRule).some(r=>['rms','max_residual'].includes(r.item_id)&&r.unit!==p.length_unit))issues.push('plane_fit / unit')
  }
  const q=object(s.quality_policy),rules=Array.isArray(q.rules)?q.rules.map(normalizeLimitRule):[],metrics=measurementMetrics(stat,String(p.length_unit)),byId=new Map(rules.map(r=>[r.item_id,r]))
  if(!id(q.policy_id)||!Number.isSafeInteger(q.policy_version)||Number(q.policy_version)<1)issues.push('quality_policy / identity')
  if(rules.length!==metrics.length||byId.size!==rules.length||rules.some(r=>limitRuleError(r)))issues.push('quality_policy / rules')
  for(const m of metrics){const r=byId.get(m.item_id)
    if(!r||!r.enabled||!r.required||r.unit!==m.unit){issues.push(`quality / ${m.item_id}`);continue}
    if(m.item_id.endsWith('_count')?(r.lower===null||r.lower<(stat?1:3)):m.item_id.endsWith('_covered')?(r.lower!==1||!r.include_lower):m.item_id.endsWith('_cosine')?(r.lower===null||r.lower<=0||r.lower>1):(r.upper===null||r.upper<0))issues.push(`quality / ${m.item_id} / bound`)
  }
  return issues
}
export const measurementNumericItems:NumericItemProvider=source=>{
  const p=object(source.parameters.settings)
  return id(p.item_id)&&['m','mm','um'].includes(String(p.length_unit))?[{item_id:String(p.item_id),unit:String(p.length_unit)}]:null
}
export const measurementRecipeValidator:RecipeValidator=(node,sources,zh)=>{
  const height=node.node_type_id.endsWith('height-query'),p=object(node.parameters.settings),s=height?p:object(p.mode),stat=s.kind==='roi-statistic'
  const issues=measurementIssues(height,p)
  if(stat&&(sources.features?.length||!sources.reference?.length||!sources.target?.length)||!stat&&(sources.reference?.length||sources.target?.length||!sources.features?.length))issues.push(zh?'测量模式与输入连接不一致':'Measurement mode and input connections do not match')
  const features=sources.features??[]
  if(!stat&&features.length&&features.every(f=>['custom.metrology3d.fit-plane','custom.metrology3d.height-query'].includes(f.nodeTypeId))){
    const ids=features.map(f=>object(f.nodeTypeId.endsWith('height-query')?object(f.parameters.settings).plane_fit:f.parameters.settings).feature_id)
    const selected=height?[s.reference_feature_id]:[s.reference_feature_id,s.target_feature_id]
    if(new Set(ids).size!==ids.length||selected.some(i=>!ids.includes(i)))issues.push(zh?'平面特征 ID 重复或缺失':'Plane feature IDs are duplicated or missing')
  }
  return issues
}
