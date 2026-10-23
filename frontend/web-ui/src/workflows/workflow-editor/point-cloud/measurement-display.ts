/** 显示结构与空间校验，不在浏览器重做测量或公差判定。 */
import {object} from './preview-data'
export interface MeasurementDisplay { item_id:string;valid:boolean;value:number|null;reason:string|null;geometry:Record<string,unknown>|null;support:Record<string,unknown>[];quality:Record<string,unknown> }
export function measurementItems(payload:Record<string,unknown>):MeasurementDisplay[]{
  if(payload.measurements===undefined)return []
  const body=object(payload.measurements),spatial=object(payload.spatial)
  if(body.format_id!=='amvision.measurement-evidence3d.v1'||body.observation_id!==payload.observation_id||body.frame_id!==spatial.frame_id||body.length_unit!==spatial.length_unit||!Array.isArray(body.items)||body.items.length>8192)throw new Error('cloud_preview_invalid')
  const ids=new Set<string>()
  return body.items.map(raw=>{
    const item=object(raw),valid=item.valid
    if(typeof item.item_id!=='string'||!item.item_id||ids.has(item.item_id)||typeof valid!=='boolean'||!Array.isArray(item.support)||item.support.length!==2)throw new Error('cloud_preview_invalid')
    ids.add(item.item_id)
    if(valid?(typeof item.value!=='number'||!Number.isFinite(item.value)||item.reason!==null||!item.geometry):(item.value!==null||item.geometry!==null||typeof item.reason!=='string'||!item.reason))throw new Error('cloud_preview_invalid')
    const quality=object(item.quality)
    if(quality.usable!==valid||object(quality.metrics).observation_id!==payload.observation_id)throw new Error('cloud_preview_invalid')
    const support=item.support.map(object)
    if(support[0]?.role!=='reference'||support[1]?.role!=='target')throw new Error('cloud_preview_invalid')
    const geometry=valid?object(item.geometry):null
    if(geometry&&(!['directional-distance','statistic-difference'].includes(String(geometry.kind))||geometry.kind==='statistic-difference'&&geometry.endpoints!==null))throw new Error('cloud_preview_invalid')
    return {item_id:item.item_id,valid,value:item.value as number|null,reason:item.reason as string|null,geometry,support,quality}
  })
}
