/** 仅由已保存配方声明检查项，不使用一次预览成功项推断配方。 */
import type {ParameterEditorSource} from '@/workflows/workflow-editor/parameters/editor-context'
import type {PinLayout} from './pin-layout'
import type {MeasurementItem} from './measurement-items'
export function connectorNumericItems(source:ParameterEditorSource):Array<{item_id:string;unit:string}>|null {
  if(source.nodeTypeId==='custom.connector.measure'&&source.outputPort==='measurements'){
    const items=source.parameters.items as MeasurementItem[]|undefined
    if(!Array.isArray(items)||items.length>8192||items.some(i=>!i||typeof i.item_id!=='string'||typeof i.kind!=='string'))return null
    return items.filter(i=>i.enabled!==false).map(i=>({item_id:i.item_id,unit:i.kind==='angle'?'degrees':String(source.parameters.unit??'pixel')}))
  }
  if(source.nodeTypeId==='custom.connector.pin-array-locate'&&source.outputPort==='checks'){
    const layout=source.parameters.layout as PinLayout|undefined
    if(!Array.isArray(layout?.pins)||layout.pins.some(p=>!p||typeof p.pin_id!=='string')||
      layout.candidate_bands!==undefined&&(!Array.isArray(layout.candidate_bands)||layout.candidate_bands.some(b=>!b||typeof b.band_id!=='string')))return null
    return [...layout.pins.map(p=>({item_id:`presence:${p.pin_id}`,unit:'unitless'})),...(layout.candidate_bands??[]).map(b=>({item_id:`extra:${b.band_id}`,unit:'unitless'}))]
  }
  return null
}
