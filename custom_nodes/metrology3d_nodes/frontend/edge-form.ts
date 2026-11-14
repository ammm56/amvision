import {object,newRoi,identity,type Form,type Field} from './form'
import {regionErrors} from './boundary-form'
import {evaluationIssues} from './evaluation-form'
import {fragmentIssues} from './circle-form'
import {normalizeLimitRule,limitRuleError} from '@/workflows/workflow-editor/parameters/limit-rules'

export const edgeKinds=['height-jump','normal-crease','sampling-boundary']
export const isEdge=(p:unknown)=>edgeKinds.includes(String(object(object(p).method).kind))
const region=()=>({roi_id:'',rois:[newRoi()]})
const positive=(v:unknown):v is number=>typeof v==='number'&&Number.isFinite(v)&&v>0
const nonnegative=(v:unknown):v is number=>typeof v==='number'&&Number.isFinite(v)&&v>=0
const id=(v:unknown)=>typeof v==='string'&&/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/.test(v)

/** 物理阈值均待填，切换方法不保留另一方法的隐藏参数。 */
export function newEdgeSettings(kind:string,previous:Form={}):Form{
  if(kind==='sampling-boundary')return {method:{kind,radius:null,min_neighbors:null,max_neighbors:null,angle_degrees:null}}
  const e=object(previous.evaluation),height=kind==='height-jump'
  const candidates={kind,support:{radius:null,min_points:null,min_tangent_ratio:null,min_normal_gap:null,max_rms:null,max_residual:null,min_joint_rms:null},support_a:region(),support_b:region(),max_unassigned_fraction:null,...(height?{adjacency:null,candidate_delta:null,min_height_axis_cosine:null}:{radius:null,max_neighbors:null,min_angle:null,max_pair_distance:null})}
  const chains={side:null,max_link_distance:null,max_turn_angle:null}
  return {feature_id:previous.feature_id??'',evaluation:height?{kind:'height-map',frame_id:e.frame_id??'',length_unit:e.length_unit??null}:{frame_id:e.frame_id??'',length_unit:e.length_unit??null,origin:[null,null,null],rotation:identity()},method:{kind,candidates,...(height?{pairing:{max_planar_gap:null,tie_tolerance:null},chains}:{pairing:{...chains,tie_tolerance:null}})},selection:{min_projected_area:null,targets:[],quality_policy:{policy_id:'',policy_version:null,rules:['support_count','length'].map(item_id=>normalizeLimitRule({item_id,unit:item_id==='support_count'?'1':e.length_unit??''}))}}}
}

/** 只做既有规则的表单反馈，最终完整契约仍由后端校验。 */
export function edgeIssues(value:unknown):string[]{
  const p=object(value),m=object(p.method),sampling=m.kind==='sampling-boundary',height=m.kind==='height-jump',issues:string[]=[]
  if(sampling){if(!positive(m.radius)||!Number.isSafeInteger(m.max_neighbors)||Number(m.max_neighbors)<3||!Number.isSafeInteger(m.min_neighbors)||Number(m.min_neighbors)<3||Number(m.min_neighbors)>=Number(m.max_neighbors)||!positive(m.angle_degrees)||m.angle_degrees>=360)issues.push('sampling / neighborhood');return issues}
  const e=object(p.evaluation),s=object(p.selection),c=object(m.candidates),f=object(c.support),pair=object(m.pairing),chain=height?object(m.chains):pair
  if(!id(p.feature_id))issues.push('feature')
  if(height){if(e.kind!=='height-map'||!id(e.frame_id)||!['mm','m','um'].includes(String(e.length_unit)))issues.push('height-map / space')}
  else issues.push(...evaluationIssues(e,[]))
  if(c.kind!==m.kind)issues.push('method / candidates')
  if(!Number.isSafeInteger(f.min_points)||Number(f.min_points)<3||['radius','max_rms','max_residual','min_joint_rms','min_tangent_ratio','min_normal_gap'].some(k=>!positive(f[k]))||Number(f.min_tangent_ratio)>1||Number(f.min_normal_gap)>1||Number(f.max_residual)<Number(f.max_rms)||Number(f.min_joint_rms)<=Number(f.max_rms))issues.push('support / plane')
  if(!nonnegative(c.max_unassigned_fraction)||c.max_unassigned_fraction>=1)issues.push('support / unassigned')
  issues.push(...regionErrors(c.support_a,e),...regionErrors(c.support_b,e))
  if(height){if(![4,8].includes(Number(c.adjacency))||!positive(c.candidate_delta)||!positive(c.min_height_axis_cosine)||c.min_height_axis_cosine>1||!positive(pair.max_planar_gap)||!nonnegative(pair.tie_tolerance)||pair.tie_tolerance>=Number(pair.max_planar_gap))issues.push('height / pairing')}
  else if(!positive(c.radius)||!Number.isSafeInteger(c.max_neighbors)||Number(c.max_neighbors)<3||!positive(c.min_angle)||c.min_angle>Math.PI/2||!positive(c.max_pair_distance)||c.max_pair_distance>Number(c.radius)||!nonnegative(pair.tie_tolerance))issues.push('normal / pairing')
  if(!(height?['high','low']:['a','b']).includes(String(chain.side))||!positive(chain.max_link_distance)||!positive(chain.max_turn_angle)||chain.max_turn_angle>Math.PI)issues.push('chain')
  const targets=Array.isArray(s.targets)?s.targets.map(object):[]
  if(!positive(s.min_projected_area)||!targets.length||new Set(targets.map(t=>t.group_id??t.segment_id)).size!==targets.length)issues.push('targets')
  for(const t of targets){if('group_id'in t)issues.push(...fragmentIssues(t));else if(!id(t.segment_id)||typeof t.closed!=='boolean'||!(t.closed?['outer','inner','unknown']:['open','unknown']).includes(String(t.role)))issues.push('target / identity');issues.push(...regionErrors(t.region,e))}
  const q=object(s.quality_policy),rules=Array.isArray(q.rules)?q.rules.map(normalizeLimitRule):[]
  if(!id(q.policy_id)||!Number.isSafeInteger(q.policy_version)||Number(q.policy_version)<1||rules.some(limitRuleError)||new Set(rules.map(r=>r.item_id)).size!==rules.length)issues.push('quality / policy')
  const units:Record<string,unknown>={support_count:'1',length:e.length_unit,max_pair_distance:e.length_unit,...(height?{max_planar_gap:e.length_unit}:{})}
  if(rules.some(r=>!(r.item_id in units)||r.unit!==units[r.item_id]))issues.push('quality / metrics')
  for(const name of ['support_count','length']){const r=rules.find(r=>r.item_id===name&&r.enabled&&r.required);if(!r||r.lower===null||(name==='support_count'?r.lower<2:r.lower<=0))issues.push(`quality / ${name}`)}
  return issues
}

export function edgeFields(kind:string,label:(cn:string,en:string)=>string):Field[]{
  const num=(path:string,cn:string,en:string):Field=>({path,label:label(cn,en),type:'number'})
  if(kind==='sampling-boundary')return [num('method.radius','邻域半径','Neighborhood radius'),num('method.max_neighbors','邻点上限（含自身）','Neighbor limit (including self)'),num('method.min_neighbors','最少邻点（不含自身）','Minimum neighbors (excluding self)'),num('method.angle_degrees','缺口角度 °','Gap angle °')]
  const height=kind==='height-jump',prefix=height?'method.chains':'method.pairing'
  const fields:Field[]=[...(height?[num('method.candidates.adjacency','格邻接 4 / 8','Cell adjacency 4 / 8'),num('method.candidates.candidate_delta','候选高度差','Candidate height difference'),num('method.candidates.min_height_axis_cosine','最小高度轴余弦','Minimum height-axis cosine'),num('method.pairing.max_planar_gap','最大面内间隙','Maximum planar gap')]:[num('method.candidates.radius','法向搜索半径','Normal search radius'),num('method.candidates.max_neighbors','邻点上限','Neighbor limit'),num('method.candidates.min_angle','最小折角 rad','Minimum crease angle rad'),num('method.candidates.max_pair_distance','最大实测配对距离','Maximum measured pair distance')]),num('method.pairing.tie_tolerance','等距数值容差','Equal-distance tolerance'),{path:`${prefix}.side`,label:label('输出实测侧','Measured output side'),type:'select',options:height?['high','low']:['a','b']},num(`${prefix}.max_link_distance`,'最大段连接距离','Maximum segment link distance'),num(`${prefix}.max_turn_angle`,'最大转角 rad','Maximum turn angle rad'),num('selection.min_projected_area','最小投影面积','Minimum projected area'),num('method.candidates.max_unassigned_fraction','未归属比例上限','Unassigned fraction limit')]
  for(const [key,cn,en] of [['radius','双侧支持半径','Side support radius'],['min_points','每侧最少点数','Minimum points per side'],['min_tangent_ratio','最小切向可辨识比','Minimum tangent ratio'],['min_normal_gap','最小法向特征间隔','Minimum normal gap'],['max_rms','每侧 RMS 上限','Per-side RMS limit'],['max_residual','每侧最大残差','Per-side maximum residual'],['min_joint_rms','联合单面 RMS 下限','Joint-plane minimum RMS']])fields.push(num(`method.candidates.support.${key}`,cn!,en!))
  return fields
}
