import type {ParameterEditorSource,ParameterEditorSources} from './editor-context'
export interface StaticNumericItem {item_id:string;unit:string;label?:string}
export type NumericItemProvider = (source: ParameterEditorSource) => StaticNumericItem[] | null
export type NumericItemProviders = Readonly<Record<string, NumericItemProvider>>
/** 只遍历明确连线；行业条目由发行组合入口提供，不读取执行结果。 */
export function staticNumericItems(sources:ParameterEditorSources|undefined,resolve:((id:string)=>ParameterEditorSources)|undefined,providers:NumericItemProviders={}):StaticNumericItem[]|null {
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
      return providers[source.nodeTypeId]?.(source) ?? null
    }finally{active.delete(source.nodeId)}
  }
  const inputs=sources?.table
  if(!inputs?.length)return null
  const results=inputs.map(visit)
  if(results.some(v=>v===null))return null
  const items=results.flat() as StaticNumericItem[]
  return new Set(items.map(i=>i.item_id)).size===items.length?items:null
}
