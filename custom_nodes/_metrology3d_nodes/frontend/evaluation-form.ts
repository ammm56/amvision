/** 配置面与运行继承面共用编辑边界，浏览器不计算测量结果。 */
import {identity,newRoi,object,roiIssues,vector,type Form} from './form'

export const evaluationAxes=['u','-u','v','-v']
export function newEvaluation(kind:string,current:unknown):Form {
  const p=object(current),space={frame_id:p.frame_id??'',length_unit:p.length_unit??null}
  return kind==='feature'?{kind,...space}:kind==='pose'?{kind,...space,pose_id:'',target_frame_id:''}:{...space,origin:[null,null,null],rotation:identity()}
}
export function evaluationIssues(value:unknown,allowed:string[]):string[] {
  const e=object(value),id=(v:unknown)=>typeof v==='string'&&/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/.test(v)
  if(!id(e.frame_id)||!['m','mm','um'].includes(String(e.length_unit)))return ['evaluation / space']
  if(e.kind==='feature'||e.kind==='pose'){
    if(!allowed.includes(e.kind)||'origin' in e||'rotation' in e)return ['evaluation / source']
    return e.kind==='pose'&&(!id(e.pose_id)||!id(e.target_frame_id)||e.target_frame_id===e.frame_id)?['evaluation / pose']:[]
  }
  if(e.kind!==undefined||!vector(e.origin))return ['evaluation / origin']
  return roiIssues([{...newRoi(),roi_id:'evaluation',frame_id:e.frame_id,length_unit:e.length_unit,geometry:{center:[0,0,0],size:[1,1,1],rotation:e.rotation}}]).length?['evaluation / rotation']:[]
}
export function axisDirection(value:unknown):boolean {const p=object(value);return p.kind==='axis'&&evaluationAxes.includes(String(p.axis))&&Object.keys(p).length===2}
export function planePosition(value:unknown):boolean {const p=object(value);return p.kind==='plane-uv'&&Object.keys(p).length===2&&Array.isArray(p.uv)&&p.uv.length===2&&p.uv.every(v=>typeof v==='number'&&Number.isFinite(v))}
