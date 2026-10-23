/** 有界显示点的支持分类/残差着色；不从 LOD 反推测量质量。 */
import {object} from './preview-data'
export interface PlaneColors {classes:number[];residuals:(number|null)[]}
/** 仅描述有界显示点，不把显示采样数量当作算法完整支持数量。 */
export function planeColorSummary(samples:PlaneColors|null){
  if(!samples)return null
  let support=0,rejected=0,unrelated=0,extent=0,hasResidual=false
  for(let i=0;i<samples.classes.length;i++){
    const kind=samples.classes[i],value=samples.residuals[i]
    if(kind===1)support++;else if(kind===2)rejected++;else unrelated++
    if(value!==null&&value!==undefined){hasResidual=true;extent=Math.max(extent,Math.abs(value))}
  }
  return {support,rejected,unrelated,extent:hasResidual?extent:null}
}
export function planeColorData(payload:Record<string,unknown>,featureId:string):PlaneColors|null {
  const geometry=payload.geometry?object(payload.geometry):null
  if(!geometry||!Array.isArray(geometry.planes))return null
  const plane=geometry.planes.map(object).find(p=>p.feature_id===featureId)
  if(!plane?.samples)return null
  const samples=object(plane.samples),n=payload.display_point_count
  if(samples.data_sha256!==object(payload.data).checksum||!Array.isArray(samples.classes)||samples.classes.length!==n||!Array.isArray(samples.residuals)||samples.residuals.length!==n)throw new Error('cloud_preview_invalid')
  const classes=samples.classes,residuals=samples.residuals
  if(classes.some((v,i)=>![0,1,2].includes(v)||residuals[i]!==null&&(typeof residuals[i]!=='number'||!Number.isFinite(residuals[i])||v===0)))throw new Error('cloud_preview_invalid')
  return {classes,residuals} as PlaneColors
}
export function fillPlaneColors(target:Float32Array,original:Float32Array,samples:PlaneColors|null,mode:'original'|'support'|'residual'){
  if(mode==='original'||!samples){target.set(original);return}
  let extent=0
  for(const value of samples.residuals)if(value!==null)extent=Math.max(extent,Math.abs(value))
  for(let i=0;i<samples.classes.length;i++){
    const residual=samples.residuals[i],kind=samples.classes[i]
    const t=residual===null||residual===undefined?null:extent?residual/extent:0
    const color=mode==='support'?(kind===1?[.12,.68,.40]:kind===2?[.88,.24,.18]:[.48,.48,.48]):t===null?[.48,.48,.48]:t<0?[1+t,1+t,1]:[1,1-t,1-t]
    target.set(color,i*3)
  }
}
