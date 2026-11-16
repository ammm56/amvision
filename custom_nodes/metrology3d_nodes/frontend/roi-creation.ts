/** 显式评价平面内两次拾取创建候选 ROI；垂直范围由操作人员确认。 */
import {copy,object,vector,type Form} from './form'
export function createPickedRoi(roi:Form,spatial:Form,plane:string,a:number[],b:number[],low:number,high:number):Form {
  const axes=plane==='xy'?[0,1,2]:plane==='xz'?[0,2,1]:plane==='yz'?[1,2,0]:null
  if(!axes||!vector(a)||!vector(b)||!Number.isFinite(low)||!Number.isFinite(high)||high<=low)throw new Error('ROI range')
  const [u,v,n]=axes as [number,number,number],center=[0,0,0],size=[0,0,0]
  center[n]=(low+high)/2;size[n]=high-low
  let geometry:Form
  if(roi.kind==='box'){
    for(const i of [u,v]){center[i]=(a[i]!+b[i]!)/2;size[i]=Math.abs(a[i]!-b[i]!)}
    if(size.some(value=>value<=0))throw new Error('ROI corners')
    geometry={center,size,rotation:[[1,0,0],[0,1,0],[0,0,1]]}
  }else if(roi.kind==='cylinder'){
    center[u]=a[u]!;center[v]=a[v]!;const axis=[0,0,0];axis[n]=1
    const radius=Math.hypot(a[u]!-b[u]!,a[v]!-b[v]!)
    if(radius<=0)throw new Error('ROI radius')
    geometry={center,axis,radius,length:high-low}
  }else throw new Error('ROI kind')
  return {...copy(roi),frame_id:spatial.frame_id,length_unit:spatial.length_unit,geometry}
}
export function previewAxisRange(payload:Form,plane:string):number[]|null{
  const bounds=object(payload.bounds),axis=plane==='xy'?2:plane==='xz'?1:0
  return vector(bounds.min)&&vector(bounds.max)&&bounds.max[axis]!>bounds.min[axis]!?[bounds.min[axis]!,bounds.max[axis]!]:null
}
/** 截面原点取实测显示点；厚度与有限边界必须已显式配置。 */
export function createPickedSection(roi:Form,spatial:Form,plane:string,point:number[]):Form{
  const g=object(roi.geometry),axis=plane==='xy'?2:plane==='xz'?1:plane==='yz'?0:null
  if(roi.kind!=='section-band'||axis===null||!vector(point)||typeof g.thickness!=='number'||!Number.isFinite(g.thickness)||g.thickness<=0||typeof g.bounds_roi_id!=='string'||!g.bounds_roi_id||g.bounds_roi_id===roi.roi_id)throw new Error('Section parameters')
  const normal=[0,0,0];normal[axis]=1
  return {...copy(roi),frame_id:spatial.frame_id,length_unit:spatial.length_unit,geometry:{...copy(g),origin:[...point],normal}}
}
