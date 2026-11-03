import type {RecipeValidator} from '@/workflows/workflow-editor/parameters/recipe-validation'
import {geometryIssues,object} from './form'
/** 保存/发布沿既有配方检查；未知动态输入留给后端契约。 */
export const geometryRecipeValidator:RecipeValidator=(node,sources,zh)=>{
  const kind=node.node_type_id.split('.').at(-1)!,p=node.parameters[kind==='crop-roi'?'source':'settings']
  const issues=geometryIssues(kind,p)
  if(kind==='crop-roi'&&object(p).kind==='parameters'&&sources.roi?.length)issues.push(zh?'节点参数来源不能连接 ROI 输入':'Parameter ROI cannot also have an input connection')
  if(kind==='crop-roi'&&object(p).kind==='input'&&!sources.roi?.length)issues.push(zh?'输入端口来源必须连接 ROI 输入':'Input ROI requires an input connection')
  if(kind==='build-frame'){
    const connected=sources.features??[]
    if(connected.length&&connected.every(s=>s.nodeTypeId==='custom.metrology3d.fit-plane')){
      const ids=connected.map(s=>object(s.parameters.settings).feature_id),settings=object(p),required=[settings.primary_feature_id]
      if(object(settings.x_axis).kind==='plane-intersection')required.push(object(settings.x_axis).secondary_feature_id)
      if(object(settings.origin).kind==='three-planes')required.push(object(settings.origin).tertiary_feature_id)
      if(new Set(ids).size!==ids.length||required.some(id=>!ids.includes(id)))issues.push(zh?'已连接的基准 ID 重复或缺失':'Connected datum IDs are duplicated or missing')
    }
  }
  return issues
}
