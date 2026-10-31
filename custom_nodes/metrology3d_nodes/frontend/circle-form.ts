import {object,type Form} from './form'
import {normalizeLimitRule,limitRuleError} from '@/workflows/workflow-editor/parameters/limit-rules'

export const robustMetrics=['inlier_fraction','sector_coverage','inlier_angular_coverage','inlier_jacobian_ratio','target_max_gap','inlier_max_gap','weighted_rms']
const finite=(v:unknown):v is number=>typeof v==='number'&&Number.isFinite(v)
const id=(v:unknown)=>typeof v==='string'&&/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/.test(v)
/** 角域全部显式填写，缺省不产生可执行生产数值。 */
export function newAngularFit(kind='angular-soft-l1'):Form{return {kind,center:[null,null],start_angle:null,sweep:null,sector_count:null,loss_scale:null,inlier_residual:null}}
export function newFragmentTarget(previous:Form):Form{return {group_id:previous.group_id??previous.segment_id??'',region:previous.region,role:'open',arc:{center:[null,null],radius_range:[null,null],start_angle:null,sweep:null,max_overlap_angle:null},fragment_quality_policy:{policy_id:'',policy_version:null,rules:['support_count','length'].map(item_id=>normalizeLimitRule({item_id,unit:item_id==='support_count'?'1':''}))}}}
export function angularIssues(value:unknown):string[]{const p=object(value);return !Array.isArray(p.center)||p.center.length!==2||!p.center.every(finite)||!finite(p.start_angle)||p.start_angle<0||p.start_angle>=2*Math.PI||!finite(p.sweep)||p.sweep<=0||p.sweep>2*Math.PI?['angular domain']:[]}
export function fragmentIssues(value:unknown):string[]{
  const t=object(value),a=object(t.arc),q=object(t.fragment_quality_policy),rules=Array.isArray(q.rules)?q.rules.map(normalizeLimitRule):[],ids=new Map(rules.filter(r=>r.enabled&&r.required).map(r=>[r.item_id,r]))
  const issues=angularIssues(a)
  if(!id(t.group_id)||t.role!=='open'||'segment_id' in t||'closed' in t)issues.push('fragment group')
  if(!Array.isArray(a.radius_range)||a.radius_range.length!==2||!a.radius_range.every(v=>finite(v)&&v>0)||a.radius_range[0]>=a.radius_range[1]||!finite(a.max_overlap_angle)||a.max_overlap_angle<0||a.max_overlap_angle>=Number(a.sweep)||a.max_overlap_angle>=Math.PI)issues.push('arc band')
  if(!id(q.policy_id)||!Number.isSafeInteger(q.policy_version)||Number(q.policy_version)<1||rules.some(limitRuleError)||new Set(rules.map(r=>r.item_id)).size!==rules.length||Number(ids.get('support_count')?.lower??0)<2||Number(ids.get('length')?.lower??0)<=0)issues.push('fragment quality')
  return issues
}
export function selectionIssues(value:unknown):string[]{const p=object(value),segments=Array.isArray(p.segment_ids)?p.segment_ids:[],groups=Array.isArray(p.group_ids)?p.group_ids:[],ids=segments.length?segments:groups;return !id(p.feature_id)||!!segments.length===!!groups.length||ids.some(v=>!id(v))||new Set(ids).size!==ids.length?['selection']:[]}
export function robustIssues(value:unknown,quality:unknown):string[]{
  if(value===null||value===undefined)return []
  const p=object(value),q=object(quality),rules=Array.isArray(q.rules)?q.rules.map(normalizeLimitRule):[],byId=new Map(rules.filter(r=>r.enabled&&r.required).map(r=>[r.item_id,r])),issues=angularIssues(p)
  if(!['angular-soft-l1','arc-length-soft-l1'].includes(String(p.kind))||!Number.isSafeInteger(p.sector_count)||Number(p.sector_count)<1||Number(p.sector_count)>8192||!finite(p.loss_scale)||p.loss_scale<=0||!finite(p.inlier_residual)||p.inlier_residual<=0)issues.push('robust fit')
  for(const key of robustMetrics){const r=byId.get(key),upper=['target_max_gap','inlier_max_gap','weighted_rms'].includes(key);if(!r||(upper?r.upper===null||r.upper<0:r.lower===null||r.lower<=0||['inlier_fraction','sector_coverage','inlier_jacobian_ratio'].includes(key)&&r.lower>1))issues.push(`quality / ${key}`)}
  return issues
}
export function changeCircleFit(draft:Form,method:string):Form{
  const robust=method!=='linear'
  if(robust&&draft.robust)return {...draft,robust:{...object(draft.robust),kind:method}}
  const q=object(draft.quality_policy),unit=object(draft.evaluation).length_unit
  let rules=(Array.isArray(q.rules)?q.rules:[]).map(normalizeLimitRule).filter(r=>!robustMetrics.includes(r.item_id))
  if(robust)rules=rules.concat(robustMetrics.map(item_id=>normalizeLimitRule({item_id,unit:item_id==='weighted_rms'?String(unit??''):['inlier_fraction','sector_coverage','inlier_jacobian_ratio'].includes(item_id)?'1':'rad'})))
  return {...draft,robust:robust?newAngularFit(method):null,quality_policy:{...q,rules}}
}
