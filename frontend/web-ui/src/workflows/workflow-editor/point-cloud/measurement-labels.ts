/** 只解释后端声明的方法和原因，不推断精度或产品判定。 */
import {object} from './preview-data'
import type {MeasurementDisplay} from './measurement-display'
export function measurementMethod(item:MeasurementDisplay,zh:boolean):string {
  if(item.kind==='height-query')return zh?'局部实测面高度':'Local measured-surface height'
  if(item.kind==='measure-edge-pair')return zh?'有限边段方向间距':'Directional distance of finite edges'
  const p=object(item.method.parameters)
  if(item.kind==='measure-arc')return object(p.mode).kind==='continuous-arc'
    ?(zh?'连续实测开弧 · 圆模型量值':'Continuous measured open arc · circle-model quantities')
    :(zh?'实测支持角区并集 · 缺口不连接':'Measured angular union · gaps remain open')
  if(item.kind==='measure-hole')return p.target_kind==='open-arc'
    ?(zh?'部分实测圆弧估计':'Measured partial-arc estimate')
    :(zh?'实测闭合孔拟合':'Measured closed-hole fit')
  if(item.kind==='measure-extents')return object(p.mode).kind==='robust-profile-spans'
    ?(zh?'可见包络 · 稳健剖面跨度':'Visible envelope · robust profile spans')
    :object(p.mode).kind==='minimum-area-rectangle'?(zh?'最小面积矩形':'Minimum-area rectangle'):(zh?'投影包络跨度':'Projected envelope spans')
  return object(p.mode).kind==='roi-statistic'?(zh?'区域统计差':'ROI statistic difference'):(zh?'两平面同线测距':'Collinear plane distance')
}
export function measurementReason(reason:string|null,zh:boolean):string {
  if(!reason)return ''
  const labels:Record<string,string>={outside_support:'查询位置不在实测支持内',query_pose_unavailable:'本次基准坐标不可用',reference_extension_limit_exceeded:'基准延伸超过上限',quality_failed:'几何质量条件未通过',requires_single_open_segment:'连续开弧必须选择一条开放实测段',requires_open_sweep:'连续开弧不能覆盖整周',angular_support_gap:'实测相邻点角步超限',nonmonotonic_arc:'实测段存在角度回折或无有效转角',overlapping_arc:'实测段重复绕圈',incomplete_closed_arc:'闭合拓扑未形成完整单周',degenerate_arc_edge:'实测边存在重复端点'}
  return zh&&labels[reason]?`${labels[reason]} (${reason})`:reason
}
