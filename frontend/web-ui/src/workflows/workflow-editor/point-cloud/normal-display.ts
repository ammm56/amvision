import {object,vector} from './preview-data'

export const normalNames=['normals','normal_valid','normal_oriented','normal_reason'] as const
export interface NormalPoint {vector:number[];valid:boolean;oriented:boolean;reason:number}
/** 显示读取方只声明随数据携带的计算状态，不凭 normals 字段猜有效性。 */
export function normalOrientation(value:unknown,spatial:unknown):string {
  const info=object(value),space=object(spatial),orientation=object(info.orientation),method=object(info.method)
  if(info.frame_id!==space.frame_id||info.length_unit!==space.length_unit||method.method_id!=='estimate-normals'||method.method_version!==1||!['unoriented','direction','viewpoint'].includes(String(orientation.kind)))throw new Error('cloud_preview_invalid')
  return String(orientation.kind)
}
export function normalPoint(read:(name:string,component?:number)=>number,dtype:string,orientation:string):NormalPoint {
  const normal=vector([0,1,2].map(c=>read('normals',c))),valid=read('normal_valid'),oriented=read('normal_oriented'),reason=read('normal_reason')
  const good=valid===1,signed=oriented===1,tolerance=dtype==='float32'?64*2**-23:2e-8
  if(![0,1].includes(valid)||![0,1].includes(oriented)||!Number.isInteger(reason)||reason<0||reason>5||signed&&!good||good!==(reason===0||reason===5)||reason===5&&signed||!good&&normal.some(n=>n!==0)||good&&Math.abs(Math.hypot(...normal)-1)>tolerance||orientation==='unoriented'&&(signed||reason===5)||orientation!=='unoriented'&&good&&(reason===0)!==signed)throw new Error('cloud_preview_invalid')
  return {vector:normal,valid:good,oriented:signed,reason}
}
export function normalLabel(value:NormalPoint,zh:boolean):string {
  if(value.valid)return value.oriented?(zh?'已定向法向':'Oriented normal'):(zh?'有效无符号法向':'Valid unoriented normal')
  return (zh?['','邻域不足','支持退化','数值失败','质量不满足','定向歧义']:['','Insufficient support','Degenerate support','Numeric failure','Quality failed','Ambiguous orientation'])[value.reason]??''
}
