/** 偏差配置沿用既有方向支持质量校验，缺省工艺数值保持未填写。 */
import {normalizeLimitRule} from '@/workflows/workflow-editor/parameters/limit-rules'
import type {RecipeValidator} from '@/workflows/workflow-editor/parameters/recipe-validation'
import type {NumericItemProvider} from '@/workflows/workflow-editor/parameters/static-numeric-items'
import {measurementMetrics,measurementPolicyIssues} from './measurement-form'
import {relationChoices} from './relation-form'
import {object,type Form} from './form'
export const deviationComponents=['min','max','peak-to-valley','mean','rms']
export const deviationLabel=(key:string,zh:boolean)=>({min:zh?'最小偏差':'Minimum',max:zh?'最大偏差':'Maximum','peak-to-valley':zh?'偏差峰谷':'Peak-to-valley',mean:zh?'平均偏差':'Mean',rms:'RMS'} as Record<string,string>)[key]??key
const id=(v:unknown)=>typeof v==='string'&&/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/.test(v)
const positive=(v:unknown)=>typeof v==='number'&&Number.isFinite(v)&&v>0
const metrics=(unit:string)=>measurementMetrics(false,unit).filter(m=>m.item_id.startsWith('reference_'))
export function newDeviation():Form{return {reference_feature_id:'',frame_id:'',length_unit:null,support_radius:null,reference_policy:{kind:'measured-support'},quality_policy:{policy_id:'',policy_version:1,rules:metrics('').map(normalizeLimitRule)},outputs:deviationComponents.map(component=>({component,item_id:''}))}}
export function deviationIssues(value:unknown):string[]{
  const p=object(value),issues:string[]=[],r=object(p.reference_policy),outputs=Array.isArray(p.outputs)?p.outputs.map(object):[]
  if(!id(p.reference_feature_id))issues.push('reference_feature_id')
  if(!id(p.frame_id))issues.push('frame_id')
  if(!['m','mm','um'].includes(String(p.length_unit)))issues.push('length_unit')
  if(!positive(p.support_radius))issues.push('support_radius')
  if(r.kind==='plane-extension'){if(!positive(r.max_extension_distance)||Object.keys(r).length!==2)issues.push('max_extension_distance')}
  else if(r.kind!=='measured-support'||Object.keys(r).length!==1)issues.push('reference_policy')
  if(outputs.length!==5||new Set(outputs.map(o=>o.component)).size!==5||outputs.some(o=>!deviationComponents.includes(String(o.component))||!id(o.item_id))||new Set(outputs.map(o=>o.item_id)).size!==5)issues.push('outputs')
  return [...issues,...measurementPolicyIssues(p.quality_policy,metrics(String(p.length_unit)))]
}
export const deviationNumericItems:NumericItemProvider=source=>{
  const p=object(source.parameters.settings)
  return Array.isArray(p.outputs)&&['m','mm','um'].includes(String(p.length_unit))?p.outputs.map(object).filter(o=>id(o.item_id)).map(o=>({item_id:String(o.item_id),unit:String(p.length_unit)})):null
}
export const deviationRecipeValidator:RecipeValidator=(node,sources,zh)=>{
  const p=object(node.parameters.settings),issues=deviationIssues(p),choices=relationChoices(sources).filter(c=>c.kind==='plane')
  if(sources.cloud?.length!==1)issues.push(zh?'必须连接完整目标点云':'Connect one target cloud')
  if(!sources.features?.length)issues.push(zh?'必须连接基准平面':'Connect datum plane features')
  if(new Set(choices.map(c=>c.id)).size!==choices.length)issues.push(zh?'基准 ID 重复':'Duplicate datum IDs')
  const complete=(sources.features??[]).every(s=>s.nodeTypeId==='custom.metrology3d.fit-plane'||object(s.previewOutput).format_id==='amvision.features3d.v1')
  if(complete&&!choices.some(c=>c.id===p.reference_feature_id))issues.push(zh?'指定基准不在输入中':'Datum is not in current inputs')
  return issues
}
