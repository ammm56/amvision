import type { RecipeValidator } from '@/workflows/workflow-editor/parameters/recipe-validation'
import { hydratePinLayout, isPinLayoutValid, type PinLayout } from './pin-layout'
import { invalidMeasurementReferences, type MeasurementItem } from './measurement-items'

/** 连接器静态校验只使用显式直连；动态几何仍由运行时契约验证。 */
export const connectorRecipeValidator:RecipeValidator=(node,sources,zh)=>{
  const invalid=zh?'配置无效':'Invalid configuration'
  if(node.node_type_id==='custom.connector.pin-array-locate'){
    try{
      const layout=hydratePinLayout(node.parameters.layout as PinLayout)
      if(!isPinLayoutValid(layout))return [`layout: ${invalid}`]
      const poses=sources.pose
      if(node.parameters.pose_mode!=='identity'&&poses?.length===1&&poses[0]!.nodeTypeId==='custom.opencv.rigid-locate'){
        const reference=poses[0]!.parameters.template_resource as {sha256?:string}|undefined
        if(reference?.sha256&&layout.reference_sha256&&reference.sha256!==layout.reference_sha256)return [zh?'layout：参考模板与 Pose 上游模板版本不同':'layout: Reference template differs from the Pose template version']
      }
    }catch{return [`layout: ${invalid}`]}
  }
  if(node.node_type_id==='custom.connector.measure'){
    const items=node.parameters.items as MeasurementItem[]|undefined
    if(!Array.isArray(items)||!items.length||items.some(i=>!i||typeof i.item_id!=='string'))return [`items: ${invalid}`]
    const pins=sources.pins,features=sources.features
    if(pins?.length===1&&features?.length===1&&pins[0]!.nodeTypeId==='custom.connector.pin-array-locate'&&features[0]!.nodeTypeId==='custom.connector.pin-array-locate'){
      if(pins[0]!.nodeId!==features[0]!.nodeId)return [zh?'items：Pins 和 Features 必须来自同一次观测的同一节点':'items: Pins and Features must come from the same observation node']
      try{
        const layout=hydratePinLayout(pins[0]!.parameters.layout as PinLayout)
        if(isPinLayoutValid(layout))return invalidMeasurementReferences(items,layout).map(id=>`${id}: ${zh?'PIN / 端点引用无效':'Invalid PIN / endpoint reference'}`)
      }catch{/* 上游自身校验负责指出布局错误，不把不可解析当成空布局。 */}
    }
  }
  return []
}
