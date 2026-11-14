/** 圆弧显示只解释有限证据，不重新拟圆或从显示采样计算量值。 */
import {object} from './preview-data'
import type {MeasurementDisplay} from './measurement-display'

export const openArcComponents=['radius','signed_sweep','sweep','arc_length','chord_length','start_x','start_y','start_z','end_x','end_y','end_z']
export const unionArcComponents=['radius','coverage_angle','supported_length']
export function measurementUnit(item:Pick<MeasurementDisplay,'kind'|'component'>,lengthUnit:string):string{
  return item.kind==='measure-relation'&&item.component==='angle'||item.kind==='measure-arc'&&['signed_sweep','sweep','coverage_angle'].includes(item.component??'')?'rad':lengthUnit
}
function fail():never{throw new Error('cloud_preview_invalid')}
function finite(v:unknown):number{if(typeof v!=='number'||!Number.isFinite(v))fail();return v}
function xyz(v:unknown):void{if(!Array.isArray(v)||v.length!==3)fail();v.forEach(finite)}
function spans(v:unknown):void{
  if(!Array.isArray(v)||!v.length||v.length>8192)fail()
  let end=-1
  for(const raw of v){const p=object(raw),a=finite(p.start_angle),s=finite(p.sweep);if(a<0||s<=0||a<=end||a+s>2*Math.PI+1e-10)fail();end=a+s}
}
export function validateArcGeometry(item:Record<string,unknown>,geometry:Record<string,unknown>|null):void{
  const mode=object(object(object(item.method).parameters).mode),continuous=mode.kind==='continuous-arc'
  if(!continuous&&mode.kind!=='supported-union'||!(continuous?openArcComponents:unionArcComponents).includes(String(item.component)))fail()
  if(!geometry)return
  const g=geometry,c=object(g.circle)
  if(g.kind!=='circle-arcs'||finite(c.radius)<=0)fail()
  xyz(c.center);xyz(c.normal);spans(g.pieces)
  if(!Array.isArray(g.parts)||!g.parts.length||g.parts.length>8192)fail()
  const ids=new Set<string>()
  for(const raw of g.parts){const p=object(raw);if(typeof p.segment_id!=='string'||!p.segment_id||ids.has(p.segment_id)||typeof p.closed!=='boolean'||!Number.isSafeInteger(p.point_count)||Number(p.point_count)<2||finite(p.polyline_length)<=0)fail();ids.add(p.segment_id);spans(p.pieces);if(p.signed_sweep!==null)finite(p.signed_sweep);if((p.signed_sweep===null)!==(typeof p.angular_reason==='string'))fail()}
  if(finite(g.coverage_angle)<=0||Number(g.coverage_angle)>2*Math.PI+1e-10||finite(g.overlap_angle)<0||finite(g.polyline_length)<=0)fail()
  if(continuous){
    const sweep=finite(g.signed_sweep)
    if(g.parts.length!==1||object(g.parts[0]).closed||!sweep||Math.abs(sweep)>=2*Math.PI||g.direction!==(sweep>0?'ccw':'cw'))fail()
    for(const raw of [g.start,g.end]){const e=object(raw);xyz(e.point);xyz(e.projected);if(!Number.isSafeInteger(e.vertex_index)||Number(e.vertex_index)<0)fail();if(e.source_index!==null&&(!Number.isSafeInteger(e.source_index)||Number(e.source_index)<0))fail();if((e.source_index===null)===(e.lineage===null))fail()}
  }else if([g.start,g.end,g.signed_sweep,g.direction].some(v=>v!==null))fail()
}
