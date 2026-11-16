/** 复用现有测量指标集合，仅补充工程名称，不产生限值。 */
import {measurementMetrics} from './measurement-form'
import {frameMetrics,planeMetrics} from './form'
import {object,type Form} from './form'
import {metricUnits} from './dimension-form'
import {relationMetrics} from './relation-form'
const labels:Record<string,[string,string]>={
  count:['支持点数','Support point count'],std:['高度标准差','Height standard deviation'],
  covered:['实测支持覆盖','Measured support coverage'],direction_cosine:['测量方向余弦','Measurement direction cosine'],
  nearest_distance:['最近支持距离','Nearest support distance'],triangle_edge:['支持三角形最大边长','Maximum support triangle edge'],
  max_residual:['最大拟面残差','Maximum plane residual'],
}
const geometryLabels:Record<string,[string,string]>={
  input_count:['输入点数','Input point count'],inlier_count:['内点数','Inlier count'],inlier_ratio:['内点比例','Inlier ratio'],
  tangent_ratio:['切向分布比','Tangent spread ratio'],normal_gap:['法向分离度','Normal separation'],
  rms:['残差均方根','Residual RMS'],max_residual:['最大残差','Maximum residual'],
  axis_sine:['基准轴分离正弦','Datum axis separation sine'],x_alignment:['X 方向一致性','X alignment'],z_alignment:['Z 方向一致性','Z alignment'],
  origin_condition:['三面求交条件数','Three-plane intersection condition'],
}
/** 单位来自实际输入；输入尚未准备时由工程师显式选择，不猜 mm。 */
export function geometryQualityItems(plane:boolean,threePlanes:boolean,zh:boolean){
  const ids=plane?['input_count','inlier_ratio',...planeMetrics]:[...frameMetrics,...(threePlanes?['origin_condition']:[])]
  return ids.map(item_id=>({item_id,unit:['rms','max_residual'].includes(item_id)?undefined:'1',unitOptions:['rms','max_residual'].includes(item_id)?['m','mm','um']:undefined,label:geometryLabels[item_id]![zh?0:1]}))
}
export function measurementQualityItems(statistic:boolean,unit:string,zh:boolean){
  return measurementMetrics(statistic,unit).map(item=>{
    const reference=item.item_id.startsWith('reference_'),key=item.item_id.slice(reference?10:7)
    return {...item,label:`${zh?(reference?'基准':'目标'):(reference?'Datum':'Target')} · ${labels[key]![zh?0:1]}`}
  })
}

const metricLabels:Record<string,[string,string]>={
  ...geometryLabels,
  support_count:['支持点数','Support points'],length:['实测段长度','Measured segment length'],
  surface_point_count:['表面点数','Surface points'],face_count:['三角面数','Triangle count'],candidate_count:['候选数','Candidate count'],
  profile_coverage:['剖面覆盖比例','Profile coverage'],estimated_fraction:['构造端点比例','Estimated endpoint fraction'],
  missing_neighbor_fraction:['缺少邻点比例','Missing neighbor fraction'],profile_max_gap:['剖面最大缺口','Maximum profile gap'],
  profile_max_jump:['剖面最大跳变','Maximum profile jump'],max_cell_span:['格内最大跨度','Maximum cell span'],added_cell_count:['形态处理新增格数','Added cells'],
  span:['支持跨度','Support span'],direction_gap:['方向可辨识比','Direction separation'],plane_max_residual:['评价面最大残差','Maximum evaluation-plane residual'],
  max_gap:['最大支持缺口','Maximum support gap'],angular_coverage:['实测角度覆盖','Angular coverage'],jacobian_ratio:['拟圆可辨识比','Circle identifiability'],
  weighted_rms:['加权残差 RMS','Weighted residual RMS'],inlier_fraction:['内点比例','Inlier fraction'],occupied_sector_count:['有实测支持的角区数','Occupied sectors'],
  sector_coverage:['角区覆盖比例','Sector coverage'],target_max_gap:['目标角域最大缺口','Maximum target angular gap'],
  inlier_angular_coverage:['内点角度覆盖','Inlier angular coverage'],inlier_max_gap:['内点最大角度缺口','Maximum inlier angular gap'],inlier_jacobian_ratio:['内点可辨识比','Inlier identifiability'],
  max_pair_distance:['最大配对距离','Maximum paired distance'],max_planar_gap:['最大面内缺口','Maximum planar gap'],
  geometry_usable:['几何有效','Geometry usable'],span_u:['U 方向跨度','U span'],span_v:['V 方向跨度','V span'],
  hull_point_count:['凸包点数','Hull points'],tied_count:['并列候选数','Tied candidates'],dimensions_consistent:['候选尺寸一致','Consistent dimensions'],orientation_unique:['方向唯一','Unique orientation'],
  role_usable:['特征角色有效','Feature role usable'],selected_point_count:['选中点数','Selected points'],selected_segment_count:['选中片段数','Selected segments'],
  coverage_angle:['支持总角度','Supported angle'],overlap_angle:['重叠角度','Overlap angle'],polyline_length:['实测折线长度','Measured polyline length'],
  source_count:['移动云点数','Source points'],reference_count:['参考云点数','Reference points'],correspondence_count:['对应点数','Correspondences'],
  source_coverage:['移动云覆盖比例','Source coverage'],reference_coverage:['参考云覆盖比例','Reference coverage'],observability:['局部可辨识性','Local observability'],
  rank:['约束秩','Constraint rank'],iterations:['迭代次数','Iterations'],converged:['收敛状态','Convergence'],candidate_consistency:['候选一致性','Candidate consistency'],datum_valid:['基准有效','Datum valid'],
  reference_usable:['基准几何有效','Reference usable'],target_usable:['目标几何有效','Target usable'],contacts_unique:['接触点唯一','Unique contacts'],
}
const contactLabels:Record<string,[string,string]>={count:['支持点数','Support count'],plane_angle:['评价面夹角','Evaluation-plane angle'],plane_distance:['评价面距离','Evaluation-plane distance'],crossing_sine:['交线正弦','Crossing sine'],intersection_residual:['求交残差','Intersection residual'],supported:['实测支持有效','Measured support valid']}
function metricLabel(id:string,zh:boolean):string{
  if(metricLabels[id])return metricLabels[id]![zh?0:1]
  const role=id.startsWith('reference_')?'reference':id.startsWith('target_')?'target':null,key=role?id.slice(role.length+1):''
  return role&&contactLabels[key]?`${zh?(role==='reference'?'基准':'目标'):role==='reference'?'Reference':'Target'} · ${contactLabels[key]![zh?0:1]}`:id
}
function items(units:Record<string,string>,zh:boolean){return Object.entries(units).map(([item_id,unit])=>({item_id,label:metricLabel(item_id,zh),unit:['','null','undefined'].includes(unit)?undefined:unit,unitOptions:['','null','undefined'].includes(unit)?['m','mm','um']:undefined}))}
/** 指标与 boundary3d_quality 的公开集合对应，包括可选诊断项，不生成限值。 */
export function boundaryQualityItems(kind:string,p:Form,zh:boolean,fragment=false){
  const unit=String(object(p.evaluation).length_unit??''),method=String(object(p.method).kind),units:Record<string,string>={support_count:'1'}
  if(fragment)return items({...units,length:unit},zh)
  if(kind==='extract-boundary'){
    if(method==='sampling-boundary')return []
    Object.assign(units,{length:unit})
    if(['height-jump','normal-crease'].includes(method))Object.assign(units,{max_pair_distance:unit,...(method==='height-jump'?{max_planar_gap:unit}:{})})
    else{
      Object.assign(units,{input_count:'1',surface_point_count:'1',face_count:'1',candidate_count:'1'})
      if(method==='visible-envelope')Object.assign(units,{profile_coverage:'1',estimated_fraction:'1',missing_neighbor_fraction:'1',profile_max_gap:unit,profile_max_jump:unit,max_cell_span:unit,added_cell_count:'1'})
    }
  }else{
    Object.assign(units,{plane_max_residual:unit,rms:unit,max_residual:unit})
    if(kind==='fit-line')Object.assign(units,{span:unit,direction_gap:'1',max_gap:unit})
    else Object.assign(units,{jacobian_ratio:'1',angular_coverage:'rad',max_gap:'rad',weighted_rms:unit,inlier_fraction:'1',occupied_sector_count:'1',sector_coverage:'1',target_max_gap:'rad',inlier_angular_coverage:'rad',inlier_max_gap:'rad',inlier_jacobian_ratio:'1'})
  }
  return items(units,zh)
}
export const dimensionQualityItems=(kind:string,p:Form,zh:boolean)=>items(metricUnits(kind,p),zh).map(item=>{
  const role=item.item_id.startsWith('reference_')?'reference':item.item_id.startsWith('target_')?'target':null,key=role?item.item_id.slice(role.length+1):''
  return kind==='measure-edge-pair'&&role&&contactLabels[key]?{...item,label:`${zh?(role==='reference'?'基准':'目标'):role==='reference'?'Reference':'Target'} · ${contactLabels[key]![zh?0:1]}`}:item
})
export const relationQualityItems=(p:Form,zh:boolean)=>items(Object.fromEntries(relationMetrics(String(object(p.relation).kind)).map(id=>[id,'1'])),zh)
export const deviationQualityItems=(p:Form,zh:boolean)=>measurementQualityItems(false,String(p.length_unit??''),zh).filter(item=>item.item_id.startsWith('reference_'))
export function registrationQualityItems(p:Form,zh:boolean){
  const units=Object.fromEntries(['source_count','reference_count','correspondence_count','source_coverage','reference_coverage','rank','observability','iterations','converged',...(p.initialization==='fpfh'?['candidate_consistency']:p.initialization==='datum'?['datum_valid']:[])].map(id=>[id,'1']))
  return items({...units,rms:String(p.length_unit??''),max_residual:String(p.length_unit??'')},zh)
}
