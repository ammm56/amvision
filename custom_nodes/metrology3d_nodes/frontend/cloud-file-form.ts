/** 文件选项的编辑模型；完整文件检查仍由既有受控读取器负责。 */
import {copy} from './form'

export const profiles = ['ply-ascii','ply-binary-le','ply-binary-be','pcd-ascii','pcd-binary','pcd-binary-compressed','xyz-whitespace','xyzn-whitespace','xyzi-whitespace','xyzrgb-whitespace'] as const
export const dtypes = ['int8','uint8','int16','uint16','int32','uint32','int64','uint64','float32','float64'] as const
export type FieldKind = 'position'|'normal'|'color-rgb'|'validity'|'scalar'
export interface FileMapping {
  source_names:string[]; target_name:string; semantic:FieldKind; dtype:string; components:number; unit:string|null
}
export interface FileOptions {
  profile_id:string; profile_version:number
  spatial:{length_unit:string|null;unit_source:string;frame_id:string;axes:{handedness:string;axis_labels:string[];definition_source:string}}
  field_mapping:FileMapping[]
}
export interface FileIssue {path:string; code:'required'|'invalid'|'duplicate'|'layout'}
const identifier=(v:unknown):v is string=>typeof v==='string'&&/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/.test(v)
const text=(v:unknown)=>typeof v==='string'&&v.length>0&&v.length<=128
const record=(v:unknown):v is Record<string,unknown>=>!!v&&typeof v==='object'&&!Array.isArray(v)
const exact=(v:object,keys:string[])=>Object.keys(v).every(k=>keys.includes(k))
const reserved:Record<string,{kind:FieldKind; columns:string[]; dtype:string; unit:string|null}>={
  positions:{kind:'position',columns:['x','y','z'],dtype:'',unit:null},
  normals:{kind:'normal',columns:['nx','ny','nz'],dtype:'',unit:'1'},
  colors:{kind:'color-rgb',columns:['r','g','b'],dtype:'uint8',unit:'1'},
  validity:{kind:'validity',columns:['validity'],dtype:'uint8',unit:'1'},
}
export const textLayouts:Record<string,string[]>={
  'xyz-whitespace':['positions'],'xyzn-whitespace':['positions','normals'],
  'xyzi-whitespace':['positions','intensity'],'xyzrgb-whitespace':['positions','colors'],
}
/** 为用户明确选择的字段用途创建一行，浮点精度不作隐式猜测。 */
export function newFileMapping(kind:FieldKind):FileMapping {
  const entry=Object.entries(reserved).find(([,v])=>v.kind===kind)
  if(!entry)return {source_names:[''],target_name:'',semantic:'scalar',dtype:'',components:1,unit:null}
  const [name,spec]=entry
  return {source_names:[...spec.columns],target_name:name,semantic:kind,dtype:spec.dtype,components:spec.columns.length,unit:spec.unit}
}
export function newFileOptions():FileOptions {
  return {profile_id:'',profile_version:1,spatial:{length_unit:null,unit_source:'unknown',frame_id:'',axes:{handedness:'unknown',axis_labels:['X','Y','Z'],definition_source:'unknown'}},field_mapping:[newFileMapping('position')]}
}
/** 只判断可编辑结构，不修复或丢弃原有非法字段。 */
export function isFileOptionsShape(v:unknown):v is FileOptions {
  if(!record(v)||!record(v.spatial)||!record(v.spatial.axes)||!Array.isArray(v.spatial.axes.axis_labels)||!Array.isArray(v.field_mapping))return false
  return v.field_mapping.every(f=>record(f)&&Array.isArray(f.source_names))
}
/** 切换编码不改字段；无头文本布局需显式重置，避免静默丢列。 */
export function textLayoutMappings(profile:string,current:FileMapping[]):FileMapping[] {
  return (textLayouts[profile]??[]).map(name=>{
    const spec=reserved[name]
    const old=current.find(f=>f.target_name===name)
    const next=spec?newFileMapping(spec.kind):{...newFileMapping('scalar'),target_name:name,source_names:[name]}
    if(old&&['float32','float64'].includes(old.dtype))next.dtype=old.dtype
    if(old&&name==='intensity')next.unit=old.unit
    return next
  })
}
/** 前端防错与 CloudFileOptions 对齐；后端严格校验保持权威。 */
export function fileOptionsIssues(value:unknown):FileIssue[] {
  if(!isFileOptionsShape(value))return [{path:'configuration',code:'invalid'}]
  const v=value, issues:FileIssue[]=[]
  const check=(ok:boolean,path:string,code:FileIssue['code']='invalid')=>{if(!ok)issues.push({path,code})}
  check(exact(v,['profile_id','profile_version','spatial','field_mapping']),'configuration')
  check((profiles as readonly string[]).includes(v.profile_id),'profile_id','required')
  check(v.profile_version===1,'profile_version')
  const s=v.spatial,a=s.axes
  check(exact(s,['length_unit','unit_source','frame_id','axes']),'spatial')
  check(identifier(s.frame_id),'frame_id','required')
  check(s.length_unit===null||['m','mm','um'].includes(s.length_unit),'length_unit')
  check(['unknown','configuration','metadata'].includes(s.unit_source)&&(s.length_unit===null)===(s.unit_source==='unknown'),'unit_source')
  check(exact(a,['handedness','axis_labels','definition_source']),'axes')
  check(['right','left','unknown'].includes(a.handedness),'handedness')
  check(['unknown','configuration','metadata'].includes(a.definition_source)&&(a.handedness==='unknown')===(a.definition_source==='unknown'),'definition_source')
  check(a.axis_labels.length===3&&a.axis_labels.every(text),'axis_labels','required')
  const targets=new Set<string>(),sources=new Set<string>()
  v.field_mapping.forEach((f,i)=>{
    const path=`field_mapping.${i+1}`
    check(exact(f,['source_names','target_name','semantic','dtype','components','unit']),path)
    check(identifier(f.target_name),`${path}.target_name`,'required')
    check(!targets.has(f.target_name),`${path}.target_name`,'duplicate'); targets.add(f.target_name)
    check((dtypes as readonly string[]).includes(f.dtype),`${path}.dtype`,'required')
    check(f.unit===null||identifier(f.unit),`${path}.unit`)
    check(Number.isInteger(f.components)&&f.components>=1&&f.components<=3&&f.source_names.length===f.components,`${path}.components`)
    for(const name of f.source_names){check(text(name),`${path}.source_names`,'required');check(!sources.has(name),`${path}.source_names`,'duplicate');sources.add(name)}
    const spec=reserved[f.target_name]
    if(spec)check(f.semantic===spec.kind&&f.components===spec.columns.length&&f.unit===spec.unit&&(spec.dtype?f.dtype===spec.dtype:['float32','float64'].includes(f.dtype)),`${path}.semantic`)
    else check(f.target_name!=='sample_origin'&&f.semantic==='scalar'&&f.components===1,`${path}.semantic`)
  })
  check(targets.has('positions'),'positions','required')
  const layout=textLayouts[v.profile_id]
  if(layout){
    check(JSON.stringify(v.field_mapping.map(f=>[f.target_name,f.source_names]))===JSON.stringify(layout.map(name=>[name,reserved[name]?.columns??[name]])),'field_mapping','layout')
    check(v.field_mapping.every(f=>f.target_name==='colors'||['float32','float64'].includes(f.dtype)),'field_mapping.dtype')
  }
  return issues
}
export function copyFileOptions(value:FileOptions):FileOptions{return copy(value)}
