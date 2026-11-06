/** 标定没有物理默认值；输入和投影切换删除不适用字段。 */
import {type Form, object, vector} from './form'

export const rasterDtypes = ['uint8','uint16','int16','uint32','int32','float32','float64']
const bytes: Record<string,number> = {uint8:1,uint16:2,int16:2,uint32:4,int32:4,float32:4,float64:8}
export function newProjection(kind: string): Form {
  return kind === 'orthographic-height'
    ? {kind,origin:[null,null,null],column_direction:[null,null,null],row_direction:[null,null,null],height_direction:[null,null,null],column_step:null,row_step:null}
    : {kind:'rectified-pinhole',depth_kind:'axial-z',fx:null,fy:null,cx:null,cy:null}
}
export function newRasterInput(kind = 'file'): Form {
  return kind === 'local-array' ? {kind} : {kind:'file',file_format:'npy',raster:{
    format_id:'amvision.calibrated-raster.v1',width:null,height:null,dtype:'',calibration_id:'',calibration_revision:'',
    spatial:{length_unit:null,unit_source:'configuration',frame_id:'',axes:{handedness:'right',axis_labels:['X','Y','Z'],definition_source:'configuration'}},
    projection:newProjection('rectified-pinhole'),value_scale:null,value_offset:null,
    validity:{invalid_raw_values:[],minimum:null,maximum:null},position_dtype:'',
  }}
}
const finite=(n: unknown): n is number=>typeof n==='number'&&Number.isFinite(n)
const positive=(n: unknown): n is number=>finite(n)&&n>0
const id=(v: unknown)=>typeof v==='string'&&/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/.test(v)
const keys=(o: Form, names: string[])=>Object.keys(o).length===names.length&&Object.keys(o).every(k=>names.includes(k))
export function rasterValid(value: Form): boolean {
  if(value.kind==='local-array')return keys(value,['kind'])
  const r=object(value.raster),s=object(r.spatial),axes=object(s.axes),p=object(r.projection),v=object(r.validity)
  if(value.kind!=='file'||!keys(value,['kind','file_format','raster'])||!['npy','png','tiff'].includes(String(value.file_format)))return false
  if(!keys(r,['format_id','width','height','dtype','calibration_id','calibration_revision','spatial','projection','value_scale','value_offset','validity','position_dtype']))return false
  if(r.format_id!=='amvision.calibrated-raster.v1'||!positive(r.width)||!Number.isSafeInteger(r.width)||!positive(r.height)||!Number.isSafeInteger(r.height)||!rasterDtypes.includes(String(r.dtype)))return false
  if(r.width*r.height*bytes[String(r.dtype)]!>1e9||!id(r.calibration_id)||!id(r.calibration_revision)||!id(s.frame_id))return false
  if(!keys(s,['length_unit','unit_source','frame_id','axes'])||!['m','mm','um'].includes(String(s.length_unit))||!['metadata','configuration'].includes(String(s.unit_source)))return false
  if(!keys(axes,['handedness','axis_labels','definition_source'])||axes.handedness!=='right'||!['metadata','configuration'].includes(String(axes.definition_source))||!Array.isArray(axes.axis_labels)||axes.axis_labels.length!==3||!axes.axis_labels.every(x=>typeof x==='string'&&x.length>0&&x.length<=128))return false
  if(!positive(r.value_scale)||!finite(r.value_offset)||!['float32','float64'].includes(String(r.position_dtype)))return false
  if(!keys(v,['invalid_raw_values','minimum','maximum'])||!Array.isArray(v.invalid_raw_values)||!v.invalid_raw_values.every(finite)||new Set(v.invalid_raw_values).size!==v.invalid_raw_values.length)return false
  for(const n of v.invalid_raw_values as number[]){
    if(r.dtype==='float32'&&Math.fround(n)!==n)return false
    if(!String(r.dtype).startsWith('float')){
      const signed=String(r.dtype).startsWith('int'),bits=bytes[String(r.dtype)]!*8
      if(!Number.isInteger(n)||n<(signed?-(2**(bits-1)):0)||n>(signed?2**(bits-1)-1:2**bits-1))return false
    }
  }
  if((v.minimum!==null&&!finite(v.minimum))||(v.maximum!==null&&!finite(v.maximum))||(finite(v.minimum)&&finite(v.maximum)&&v.minimum>v.maximum))return false
  if(value.file_format==='png'&&!['uint8','uint16'].includes(String(r.dtype)))return false
  if(value.file_format==='tiff'&&['uint32','float64'].includes(String(r.dtype)))return false
  if(p.kind==='rectified-pinhole')return keys(p,['kind','depth_kind','fx','fy','cx','cy'])&&['axial-z','ray-range'].includes(String(p.depth_kind))&&positive(p.fx)&&positive(p.fy)&&finite(p.cx)&&finite(p.cy)&&JSON.stringify(axes.axis_labels)==='["X","Y","Z"]'
  if(p.kind!=='orthographic-height'||!keys(p,['kind','origin','column_direction','row_direction','height_direction','column_step','row_step'])||!vector(p.origin)||!positive(p.column_step)||!positive(p.row_step))return false
  const directions=[p.column_direction,p.row_direction,p.height_direction]
  if(!directions.every(vector))return false
  const dot=(a:number[],b:number[])=>a.reduce((sum,x,i)=>sum+x*b[i]!,0)
  return directions.every((a,i)=>Math.abs(dot(a,a)-1)<=1e-8&&directions.slice(i+1).every(b=>Math.abs(dot(a,b))<=1e-8))
}
