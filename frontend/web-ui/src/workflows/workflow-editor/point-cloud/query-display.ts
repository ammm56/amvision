/** 读取查询来源和本次解析证据；不使用显示点替代测量。 */
import {object} from './preview-data'
export interface QueryDisplay {kind:'configured'|'pose-uv';poseId:string|null;frameId:string|null;uv:number[]|null;position:number[]|null;direction:number[]|null;reason:string|null}
const vector=(v:unknown,n=3):v is number[]=>Array.isArray(v)&&v.length===n&&v.every(x=>typeof x==='number'&&Number.isFinite(x))
export function queryDisplay(item:Record<string,unknown>,payload:Record<string,unknown>):QueryDisplay|null{
  const method=object(item.method),p=object(method.parameters),s=item.kind==='height-query'?p:object(p.mode),q=object(s.query)
  if(s.kind==='roi-statistic'){
    if(method.query_resolution!==null)throw new Error('cloud_preview_invalid')
    return null
  }
  const r=object(method.query_resolution),line=r.line===null?null:object(r.line)
  if(line&&(!vector(line.query_position)||!vector(line.direction)||Math.abs(line.direction.reduce((sum,x)=>sum+x*x,0)-1)>1e-8))throw new Error('cloud_preview_invalid')
  if(q.kind==='configured'){
    if(!line||r.pose!==null||!vector(q.query_position)||!vector(q.direction)||JSON.stringify(q.query_position)!==JSON.stringify(line.query_position)||JSON.stringify(q.direction)!==JSON.stringify(line.direction))throw new Error('cloud_preview_invalid')
    return {kind:'configured',poseId:null,frameId:null,uv:null,position:line.query_position as number[],direction:line.direction as number[],reason:null}
  }
  const pose=object(r.pose),spatial=object(payload.spatial),found=pose.state==='found'
  if(q.kind!=='pose-uv'||typeof q.pose_id!=='string'||!q.pose_id||typeof q.target_frame_id!=='string'||!q.target_frame_id||!vector(q.uv,2)||pose.pose_id!==q.pose_id||pose.target_frame_id!==q.target_frame_id||pose.source_frame_id!==spatial.frame_id||pose.length_unit!==spatial.length_unit||pose.observation_id!==payload.observation_id||found!==!!line||found!==(pose.transform!==null)||found!==(pose.reason===null)||!['found','not_found','ambiguous','underconstrained','insufficient_quality'].includes(String(pose.state)))throw new Error('cloud_preview_invalid')
  if(!found&&(item.valid||item.reason!=='query_pose_unavailable'))throw new Error('cloud_preview_invalid')
  if(found){
    const matrix=object(pose.transform).matrix
    if(!Array.isArray(matrix)||matrix.length!==4||!matrix.every(row=>vector(row,4)))throw new Error('cloud_preview_invalid')
    const local=[q.uv[0]!,q.uv[1]!,0],m=matrix as number[][]
    for(let i=0;i<3;i++){
      const expected=m.slice(0,3).reduce((sum,row,j)=>sum+row[i]!*(local[j]!-row[3]!),0)
      if(Math.abs((line!.query_position as number[])[i]!-expected)>Math.max(1e-8,32*Number.EPSILON*Math.max(1,Math.abs(expected)))||Math.abs((line!.direction as number[])[i]!-m[2]![i]!)>1e-8)throw new Error('cloud_preview_invalid')
    }
  }else if(typeof pose.reason!=='string'||!pose.reason)throw new Error('cloud_preview_invalid')
  return {kind:'pose-uv',poseId:q.pose_id,frameId:q.target_frame_id,uv:q.uv,position:line?line.query_position as number[]:null,direction:line?line.direction as number[]:null,reason:pose.reason as string|null}
}
