import type { WorkflowGraphEdge, WorkflowGraphNode } from '../types'
import type { ParameterEditorSource, ParameterEditorSources } from './editor-context'
import { staticNumericItems, type NumericItemProviders } from './static-numeric-items'
import { limitRuleError, normalizeLimitRule } from './limit-rules'

export interface RecipeIssue { nodeId:string; message:string }
export type RecipeValidator = (node:WorkflowGraphNode, sources:ParameterEditorSources, zh:boolean) => string[]

export function recipeSources(nodes:WorkflowGraphNode[], edges:WorkflowGraphEdge[], nodeId:string):ParameterEditorSources {
  const index=new Map(nodes.map(n=>[n.node_id,n])),sources:ParameterEditorSources={}
  for(const edge of edges){
    if(edge.target_node_id!==nodeId)continue
    const source=index.get(edge.source_node_id)
    if(!source||source.enabled===false)continue
    ;(sources[edge.target_port]??=[]).push({nodeId:source.node_id,nodeTypeId:source.node_type_id,parameters:source.parameters,outputPort:edge.source_port} satisfies ParameterEditorSource)
  }
  return sources
}

/** 编辑/保存预检只处理可确定的配置错误；动态上游保留运行校验。 */
export function recipeIssues(nodes:WorkflowGraphNode[], edges:WorkflowGraphEdge[], providers:NumericItemProviders, validators:Readonly<Record<string,RecipeValidator>>, zh:boolean):RecipeIssue[] {
  const issues:RecipeIssue[]=[]
  const resolve=(id:string)=>recipeSources(nodes,edges,id)
  for(const node of nodes){
    if(node.enabled===false)continue
    const sources=resolve(node.node_id)
    for(const message of validators[node.node_type_id]?.(node,sources,zh)??[])issues.push({nodeId:node.node_id,message})
    if(node.node_type_id!=='core.rule.check-limits')continue
    const raw=node.parameters.rules
    if(!Array.isArray(raw)||!raw.length){issues.push({nodeId:node.node_id,message:zh?'rules：未配置公差规则':'rules: No limits configured'});continue}
    const items=staticNumericItems(sources,resolve,providers),byId=new Map(items?.map(i=>[i.item_id,i]))
    const rules=raw.map(normalizeLimitRule),seen=new Set<string>()
    for(const rule of rules){
      const error=limitRuleError(rule)
      const duplicate=seen.has(rule.item_id);seen.add(rule.item_id)
      const source=byId.get(rule.item_id)
      const reason=error||duplicate?(zh?'规则参数无效或 ID 重复':'Invalid rule or duplicate ID'):rule.enabled&&items!==null&&(!source||source.unit!==rule.unit)?(zh?'上游检查项缺失或单位不一致':'Missing upstream item or mismatched unit'):null
      if(reason)issues.push({nodeId:node.node_id,message:`rules / ${rule.item_id}: ${reason}`})
    }
    if(!rules.some(r=>r.enabled&&r.required))issues.push({nodeId:node.node_id,message:zh?'rules：至少启用一个必检项':'rules: Enable at least one required item'})
  }
  return issues
}
