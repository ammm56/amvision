import {Matrix4,Vector3} from 'three'
import {object,count,vector,decodePreviewBytes,reserveCpu,validatePolicy} from './preview-data'
import type {CloudRendererPolicy} from '../services/measurement-resource.service'
import {heightMapIssues} from '../../../../../../custom_nodes/metrology3d_nodes/frontend/height-map-form'

export interface HeightCell { row:number;column:number;count:number;height:number|null;min:number|null;max:number|null;corners:number[][]|null }
export async function decodeHeightMap(payload:Record<string,unknown>,policy:CloudRendererPolicy,signal:AbortSignal){
  validatePolicy(policy)
  const body=object(payload.height_map),e=object(body.evidence),p=object(e.parameters),g=object(p.grid),data=object(body.data)
  if(body.format_id!=='amvision.height-map-preview.v1'||body.state!=='ready'||body.observation_id!==payload.observation_id||body.cloud_id!==payload.cloud_id||e.format_id!=='amvision.height-map.v1'||heightMapIssues(p).length)throw new Error('cloud_preview_invalid')
  const width=count(p.width),height=count(p.height),n=width*height,bytes=e.dtype==='float32'?4:e.dtype==='float64'?8:0,size=n*(bytes*3+8)
  if(!bytes||!Number.isSafeInteger(n)||n>policy.max_points||n>policy.max_canvas_pixels||size!==data.content_length||size>policy.max_data_bytes)throw new Error('cloud_preview_capacity')
  const frame=object(p.frame),spatial=object(payload.spatial)
  let sourceFromGrid:Matrix4|null=null
  if(frame.kind==='pose-frame'){
    const pose=object(e.pose),transform=object(pose.transform),rows=transform.matrix
    if(pose.state!=='found'||pose.pose_id!==frame.pose_id||pose.target_frame_id!==frame.target_frame_id||pose.source_frame_id!==spatial.frame_id||pose.length_unit!==p.length_unit||!Array.isArray(rows)||rows.length!==4||!rows.every(r=>Array.isArray(r)&&r.length===4&&r.every(v=>typeof v==='number'&&Number.isFinite(v))))throw new Error('cloud_preview_invalid')
    const matrix=new Matrix4().fromArray(rows.flat() as number[]).transpose()
    if(Math.abs(matrix.determinant()-1)>1e-8||rows[3].some((v:number,i:number)=>Math.abs(v-(i===3?1:0))>1e-8))throw new Error('cloud_preview_invalid')
    for(let i=0;i<3;i++)for(let j=0;j<3;j++)if(Math.abs(rows[i].slice(0,3).reduce((s:number,v:number,k:number)=>s+v*rows[j][k],0)-(i===j?1:0))>1e-8)throw new Error('cloud_preview_invalid')
    sourceFromGrid=matrix.invert()
  }else if(e.pose!==null||frame.frame_id!==spatial.frame_id)throw new Error('cloud_preview_invalid')
  if(p.length_unit!==spatial.length_unit||e.input_count!==payload.point_count||e.vertex_kind!==payload.vertex_kind)throw new Error('cloud_preview_invalid')
  const release=reserveCpu(size*6+n*8,policy)
  try{
    const raw=await decodePreviewBytes(data,signal),view=new DataView(raw.buffer)
    const value=(field:number,i:number)=>bytes===4?view.getFloat32(field*n*bytes+i*bytes,true):view.getFloat64(field*n*bytes+i*bytes,true)
    const sizeAt=(i:number)=>{const v=view.getBigUint64(n*bytes*3+i*8,true);if(v>BigInt(Number.MAX_SAFE_INTEGER))throw new Error('cloud_preview_invalid');return Number(v)}
    let minimum=Infinity,maximum=-Infinity,occupied=0,members=0
    for(let i=0;i<n;i++){
      const c=sizeAt(i),h=value(0,i),low=value(1,i),high=value(2,i)
      members+=c
      if(c){if(![h,low,high].every(Number.isFinite)||low>h||h>high)throw new Error('cloud_preview_invalid');occupied++;minimum=Math.min(minimum,h);maximum=Math.max(maximum,h)}
      else if(![h,low,high].every(Number.isNaN))throw new Error('cloud_preview_invalid')
    }
    if(occupied!==count(e.occupied_count)||members+count(e.outside_count)!==count(e.input_count))throw new Error('cloud_preview_invalid')
    const origin=vector(g.origin),u=vector(g.column_direction),v=vector(g.row_direction),z=vector(g.height_direction)
    let closed=false
    function cell(row:number,column:number):HeightCell{
      if(closed||!Number.isInteger(row)||!Number.isInteger(column)||row<0||row>=height||column<0||column>=width)throw new Error('cloud_preview_invalid')
      const i=row*width+column,c=sizeAt(i),lo=c?value(1,i):null,hi=c?value(2,i):null
      const corners=c?Array.from({length:8},(_,j)=>{
        const a=(column+((j&1)?.5:-.5))*Number(g.column_step),b=(row+((j&2)?.5:-.5))*Number(g.row_step),h=(j&4)?hi!:lo!
        const point=new Vector3(...origin.map((o,k)=>o+u[k]!*a+v[k]!*b+z[k]!*h) as [number,number,number])
        if(sourceFromGrid)point.applyMatrix4(sourceFromGrid)
        return point.toArray()
      }):null
      return {row,column,count:c,height:c?value(0,i):null,min:lo,max:hi,corners}
    }
    return {width,height,unit:String(p.length_unit),aggregation:String(p.aggregation),occupied,outside:count(e.outside_count),
      columnStep:Number(g.column_step),rowStep:Number(g.row_step),minimum:occupied?minimum:null,maximum:occupied?maximum:null,
      value:(index:number)=>{if(closed||!Number.isInteger(index)||index<0||index>=n)throw new Error('cloud_preview_invalid');return value(0,index)},cell,
      dispose(){if(!closed){closed=true;release()}}}
  }catch(e){release();throw e}
}
