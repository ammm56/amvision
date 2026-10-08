import type { PreviewNodeDisplay } from '../preview/useWorkflowPreviewDisplays'

const keys=['image_width','image_height','model','unit','plane_id','control_points','validation_points','max_validation_error']
function canonical(value:unknown):unknown {
  if(Array.isArray(value))return value.map(canonical)
  return value && typeof value==='object' ? Object.fromEntries(Object.entries(value).sort(([a],[b])=>a.localeCompare(b)).map(([k,v])=>[k,canonical(v)])) : value
}
/** 比较当前有效参数而非屏幕格式；结果必须来自同一个成功运行。 */
export function currentCalibration(display:PreviewNodeDisplay|null|undefined, parameters:Record<string,unknown>, state:{runId:string;succeeded:boolean}|undefined):Record<string,unknown>|null {
  if(!state?.succeeded || !state.runId)return null
  const candidate=[display,...display?.variants ?? []].find(d=>d?.payload.calibration_resource)
  if(!candidate || candidate.stale || candidate.previewRunId!==state.runId)return null
  const settings=Object.fromEntries(keys.map(key=>[key,parameters[key] ?? (key==='model'?'affine':key==='unit'?'millimeter':undefined)]))
  if(JSON.stringify(canonical(settings))!==JSON.stringify(canonical(candidate.payload.parameter_snapshot)))return null
  const result=candidate.payload.calibration_resource
  return result && typeof result==='object' && !Array.isArray(result) ? result as Record<string,unknown> : null
}
