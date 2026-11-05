/** 质量与物理尺度由配方填写，不从预览或既有法向推导默认值。 */
import {type Form, vector} from './form'
export const newNeighborhood=(kind:string):Form=>kind==='knn'?{kind,neighbors:null,support:{kind:'unrestricted'}}:kind==='hybrid'?{kind,radius:null,max_neighbors:null}:{kind,radius:null}
export const newOrientation=(kind:string):Form=>kind==='direction'?{kind,direction:[null,null,null],min_abs_cosine:null}:kind==='viewpoint'?{kind,position:[null,null,null],facing:'toward',min_abs_cosine:null}:{kind}
export function newNormals():Form{return {neighborhood:newNeighborhood('knn'),quality:{min_support_points:null,min_normal_gap:null,max_rms:null,max_surface_variation:null},orientation:newOrientation('unoriented'),frame_id:'',length_unit:'',existing_normals:'reject',diagnostics:false}}
export const normalsRecord=(v:unknown):Form=>v&&typeof v==='object'&&!Array.isArray(v)?v as Form:{}
const finite=(v:unknown):v is number=>typeof v==='number'&&Number.isFinite(v)
const positive=(v:unknown):v is number=>finite(v)&&v>0
const count=(v:unknown,max:number)=>positive(v)&&Number.isSafeInteger(v)&&v<=max
const fields=(value:Form,names:string[])=>Object.keys(value).every(key=>names.includes(key))
export function normalsValid(value:Form):boolean{
  const n=normalsRecord(value.neighborhood),q=normalsRecord(value.quality),o=normalsRecord(value.orientation),s=normalsRecord(n.support)
  if(!fields(value,['neighborhood','quality','orientation','frame_id','length_unit','existing_normals','diagnostics'])||!fields(q,['min_support_points','min_normal_gap','max_rms','max_surface_variation']))return false
  if(!fields(n,n.kind==='knn'?['kind','neighbors','support']:n.kind==='hybrid'?['kind','radius','max_neighbors']:['kind','radius'])||!fields(s,s.kind==='bounded'?['kind','max_distance']:['kind']))return false
  if(!fields(o,o.kind==='direction'?['kind','direction','min_abs_cosine']:o.kind==='viewpoint'?['kind','position','facing','min_abs_cosine']:['kind']))return false
  const capacity=n.kind==='knn'?n.neighbors:n.max_neighbors
  if(n.kind==='knn'){if(!count(n.neighbors,2147483646)||!['unrestricted','bounded'].includes(String(s.kind))||(s.kind==='bounded'&&!positive(s.max_distance)))return false}
  else if(n.kind==='radius'||n.kind==='hybrid'){if(!positive(n.radius)||(n.kind==='hybrid'&&!count(n.max_neighbors,2147483646)))return false}else return false
  if(!count(q.min_support_points,2147483647)||(q.min_support_points as number)<3||(n.kind!=='radius'&&(q.min_support_points as number)>(capacity as number)+1))return false
  if(!finite(q.min_normal_gap)||q.min_normal_gap<0||q.min_normal_gap>1||!finite(q.max_rms)||q.max_rms<0||!finite(q.max_surface_variation)||q.max_surface_variation<0||q.max_surface_variation>1/3)return false
  if(o.kind!=='unoriented'){
    if(!positive(o.min_abs_cosine)||o.min_abs_cosine>1)return false
    if(o.kind==='direction'){if(!vector(o.direction)||!(o.direction as number[]).some(v=>v!==0))return false}
    else if(o.kind==='viewpoint'){if(!vector(o.position)||!['toward','away'].includes(String(o.facing)))return false}else return false
  }
  return typeof value.frame_id==='string'&&/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/.test(value.frame_id)&&['m','mm','um'].includes(String(value.length_unit))&&['reject','replace'].includes(String(value.existing_normals))&&typeof value.diagnostics==='boolean'
}
