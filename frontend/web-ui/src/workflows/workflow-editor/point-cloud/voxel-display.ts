import {object,vector} from './preview-data'

export interface VoxelGrid {origin:number[];axes:number[][]}
// 与 geometry3d.ORTHOGONAL_TOLERANCE 一致，仅校验坐标基，不是测量公差。
const orthogonalTolerance=1e-8
export function voxelGrid(value:unknown):VoxelGrid {
  const raw=object(value),origin=vector(raw.origin)
  if(!Array.isArray(raw.axes)||raw.axes.length!==3)throw new Error('cloud_preview_invalid')
  const axes=raw.axes.map(vector),sizes=axes.map(a=>Math.hypot(...a))
  if(sizes.some(s=>!Number.isFinite(s)||s<=0||Math.abs(s/sizes[0]!-1)>orthogonalTolerance))throw new Error('cloud_preview_invalid')
  const u=axes.map((a,i)=>a.map(v=>v/sizes[i]!))
  if([[0,1],[0,2],[1,2]].some(([i,j])=>Math.abs(u[i!]!.reduce((s,v,c)=>s+v*u[j!]![c]!,0))>orthogonalTolerance))throw new Error('cloud_preview_invalid')
  const determinant=u[0]!.reduce((s,v,i)=>s+v*(u[1]![(i+1)%3]!*u[2]![(i+2)%3]!-u[1]![(i+2)%3]!*u[2]![(i+1)%3]!),0)
  if(determinant<=0)throw new Error('cloud_preview_invalid')
  return {origin,axes}
}
/** 只为选中格生成八个角，不生成全云体素几何。 */
export function voxelCorners(grid:VoxelGrid,key:string[]):number[][] {
  const k=key.map(Number)
  if(k.length!==3||k.some(v=>!Number.isSafeInteger(v)||!Number.isSafeInteger(v+1)))throw new Error('cloud_position_precision')
  const corners=Array.from({length:8},(_,i)=>grid.origin.map((v,c)=>v+grid.axes.reduce((s,a,j)=>s+a[c]!*(k[j]!+((i>>j)&1)),0)))
  if(corners.flat().some(v=>!Number.isFinite(v)))throw new Error('cloud_position_precision')
  return corners
}
export function comparableClouds(first:Record<string,unknown>,second:Record<string,unknown>):boolean {
  const a=first.spatial as Record<string,unknown>|undefined,b=second.spatial as Record<string,unknown>|undefined
  return first.state==='ready'&&second.state==='ready'&&typeof first.observation_id==='string'
    &&first.observation_id===second.observation_id&&Boolean(a?.frame_id)&&a?.frame_id===b?.frame_id&&a?.length_unit===b?.length_unit
}
