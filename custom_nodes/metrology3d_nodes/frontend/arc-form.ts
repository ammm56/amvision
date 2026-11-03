/** 角域只关联当前输入观测和已解析评价面，不把背景云当成来源。 */
import type {ParameterEditorSources} from '@/workflows/workflow-editor/parameters/editor-context'
import {curveItems} from '@/workflows/workflow-editor/point-cloud/boundary-display'
import {arcUV,validArc,type ArcEdit,type ArcHandle,type ArcValues} from '@/workflows/workflow-editor/point-cloud/arc-edit'
import {evaluationIssues} from './evaluation-form'
import {object,type Form} from './form'

function equal(a:unknown,b:unknown):boolean {
  if(a===b)return true
  if(Array.isArray(a)&&Array.isArray(b))return a.length===b.length&&a.every((v,i)=>equal(v,b[i]))
  if(!a||!b||typeof a!=='object'||typeof b!=='object'||Array.isArray(a)||Array.isArray(b))return false
  const x=object(a),y=object(b),keys=Object.keys(x)
  return keys.length===Object.keys(y).length&&keys.every(k=>Object.hasOwn(y,k)&&equal(x[k],y[k]))
}

export function boundaryArcEdit(kind:string,draft:Form,target:Form|undefined,payload:Form|undefined,sources:ParameterEditorSources,runId:string,handle:ArcHandle):ArcEdit|null {
  if(!payload||!runId||payload.state!=='ready')return null
  const spatial=object(payload.spatial),evaluation=object(draft.evaluation),extract=kind==='extract-boundary'
  if(!extract&&(handle==='inner'||handle==='outer'))return null
  if(evaluation.frame_id!==spatial.frame_id||evaluation.length_unit!==spatial.length_unit)return null
  const raw=object(extract?target?.arc:draft.robust)
  const value:ArcValues={center:raw.center as number[],start_angle:raw.start_angle as number,sweep:raw.sweep as number,...(extract?{radius_range:raw.radius_range as number[]}:{})}
  if(!Array.isArray(value.center)||extract&&!Array.isArray(value.radius_range)||!validArc(value))return null
  const inputs=sources[extract?'cloud':'features']??[]
  if(inputs.length!==1)return null
  const input=object(inputs[0]!.previewOutput)
  if(input.run_id!==runId||input.observation_id!==payload.observation_id||extract&&input.state!=='ready')return null
  const inputSpace=extract?object(input.spatial):input
  if(inputSpace.frame_id!==spatial.frame_id||inputSpace.length_unit!==spatial.length_unit)return null
  let plane:Form|null=null,points:number[][]=[]
  const identity:unknown[]=[runId,payload.observation_id,inputs[0]!.nodeId,inputs[0]!.outputPort,kind,draft.feature_id,extract?target?.group_id:draft.selection,draft.evaluation]
  try{
    if(extract){
      const method=object(draft.method)
      identity.push(method)
      if(method.kind==='projection'&&!evaluation.kind)plane=evaluation
      else {
        const feature=curveItems(payload).find(f=>f.kind==='boundary'&&f.feature_id===draft.feature_id)
        const parameters=object(feature?.method.parameters),resolution=object(feature?.method.resolution)
        if(feature&&equal(parameters.evaluation,draft.evaluation)&&equal(parameters.method,draft.method))plane=object(resolution.evaluation)
      }
    }else if(kind==='fit-circle'){
      const items=Array.isArray(input.items)?input.items.map(object):[]
      const features=items.filter(f=>f.kind==='boundary'&&f.feature_id===object(draft.selection).feature_id&&f.valid===true)
      if(features.length!==1)return null
      const feature=features[0]!,inherited=object(object(feature.method).resolution).evaluation
      if(evaluation.kind==='feature')plane=object(inherited)
      else if(!evaluation.kind)plane=evaluation
      const display=curveItems(payload).find(f=>f.kind==='boundary'&&f.feature_id===feature.feature_id||f.kind==='circle'&&f.feature_id===draft.feature_id&&equal(object(f.method.parameters).selection,draft.selection))
      if(display?.valid)points=display.points
      identity.push(feature.method)
    }
    if(!plane||evaluationIssues(plane,[]).length||plane.frame_id!==spatial.frame_id||plane.length_unit!==spatial.length_unit)return null
    const radius=value.radius_range?.[1]??0
    const minSweep=extract?raw.max_overlap_angle:0
    if(typeof minSweep!=='number'||!Number.isFinite(minSweep)||minSweep<0||minSweep>=Math.PI)return null
    const edit:ArcEdit={key:'',values:value,evaluation:{origin:plane.origin as number[],rotation:plane.rotation as number[][]},displayRadius:radius,minSweep,handle}
    if(!validArc(value,edit.minSweep))return null
    if(!extract){
      for(const point of points){const uv=arcUV(edit,point);edit.displayRadius=Math.max(edit.displayRadius,Math.hypot(uv[0]!-value.center[0]!,uv[1]!-value.center[1]!))}
      if(!(edit.displayRadius>0)||!Number.isFinite(edit.displayRadius))return null
    }
    edit.key=JSON.stringify([...identity,plane,handle])
    return edit
  }catch{return null}
}
