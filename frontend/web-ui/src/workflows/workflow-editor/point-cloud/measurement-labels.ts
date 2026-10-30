/** 只解释后端声明的方法和原因，不推断精度或产品判定。 */
import {object} from './preview-data'
import type {MeasurementDisplay} from './measurement-display'
export function measurementMethod(item:MeasurementDisplay,zh:boolean):string {
  if(item.kind==='height-query')return zh?'局部实测面高度':'Local measured-surface height'
  if(item.kind==='measure-edge-pair')return zh?'有限边段方向间距':'Directional distance of finite edges'
  const p=object(item.method.parameters)
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
  const labels:Record<string,string>={outside_support:'查询位置不在实测支持内',query_pose_unavailable:'本次基准坐标不可用',reference_extension_limit_exceeded:'基准延伸超过上限',quality_failed:'几何质量条件未通过'}
  return zh&&labels[reason]?`${labels[reason]} (${reason})`:reason
}
