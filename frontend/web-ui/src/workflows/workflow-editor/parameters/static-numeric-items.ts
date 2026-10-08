import {connectorNumericItems} from '../../../../../../custom_nodes/connector_nodes/frontend/numeric-items'
import type {ParameterEditorSource,ParameterEditorSources} from './editor-context'
export interface StaticNumericItem {item_id:string;unit:string}
/** 显式注册包的静态描述；Core 表格只消费 ID/单位，不知道任何产品概念。 */
export function staticNumericItems(sources:ParameterEditorSources|undefined,resolve:((id:string)=>ParameterEditorSources)|undefined):StaticNumericItem[]|null {
  const active=new Set<string>()
  function visit(source:ParameterEditorSource):StaticNumericItem[]|null {
    if(active.has(source.nodeId)||active.size>=32)return null
    active.add(source.nodeId)
    try{
      if(source.nodeTypeId==='core.value.numeric-tables-merge'&&resolve){
        const inputs=resolve(source.nodeId).tables
        if(!inputs?.length)return null
        const items=inputs.map(visit)
        return items.some(v=>v===null)?null:items.flat() as StaticNumericItem[]
      }
      return connectorNumericItems(source)
    }finally{active.delete(source.nodeId)}
  }
  const inputs=sources?.table
  if(!inputs?.length)return null
  const results=inputs.map(visit)
  if(results.some(v=>v===null))return null
  const items=results.flat() as StaticNumericItem[]
  return new Set(items.map(i=>i.item_id)).size===items.length?items:null
}
