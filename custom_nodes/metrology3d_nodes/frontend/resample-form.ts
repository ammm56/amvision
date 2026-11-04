/** 三种采样方法互斥，格相位与精度限值必须由配方显式指定。 */
import {type Form, vector} from './form'
export function newResample(kind: string): Form {
  if(kind==='stride')return {kind,every_k_points:null,offset:null}
  return {kind,voxel_size:null,grid_origin:[null,null,null],frame_id:'',length_unit:'',
    ...(kind==='voxel-centroid'?{max_position_error:null,attributes:'positions-only'}:{})}
}
export function resampleValid(value: Form): boolean {
  const positive=(n:unknown):n is number=>typeof n==='number'&&Number.isFinite(n)&&n>0
  if(value.kind==='stride')return positive(value.every_k_points)&&Number.isSafeInteger(value.every_k_points)
    && typeof value.offset==='number'&&Number.isSafeInteger(value.offset)&&value.offset>=0&&value.offset<value.every_k_points
  if(!['voxel-representative','voxel-centroid'].includes(String(value.kind)))return false
  return positive(value.voxel_size)&&vector(value.grid_origin)&&typeof value.frame_id==='string'
    &&/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/.test(value.frame_id)&&['m','mm','um'].includes(String(value.length_unit))
    &&(value.kind!=='voxel-centroid'||positive(value.max_position_error)&&value.attributes==='positions-only')
}
