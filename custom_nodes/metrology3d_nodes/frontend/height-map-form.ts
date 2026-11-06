/** 高度格参数不从当前显示范围猜测；坐标来源切换删除冲突字段。 */
import {object,vector,type Form} from './form'
import {newProjection} from './raster-form'

export function newHeightMap():Form {
  return {frame:{kind:'current-frame',frame_id:''},length_unit:'',grid:newProjection('orthographic-height'),width:null,height:null,aggregation:''}
}
export function heightMapIssues(value:Form):string[] {
  const issues:string[]=[],f=object(value.frame),g=object(value.grid)
  const id=(v:unknown)=>typeof v==='string'&&/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/.test(v)
  const positive=(v:unknown):v is number=>typeof v==='number'&&Number.isFinite(v)&&v>0
  if(f.kind==='current-frame'){if(!id(f.frame_id)||Object.keys(f).length!==2)issues.push('frame')}
  else if(f.kind==='pose-frame'){if(!id(f.pose_id)||!id(f.target_frame_id)||Object.keys(f).length!==3)issues.push('pose')}
  else issues.push('frame')
  if(!['m','mm','um'].includes(String(value.length_unit)))issues.push('unit')
  if(!['minimum','maximum','mean','median'].includes(String(value.aggregation)))issues.push('aggregation')
  if(!positive(value.width)||!positive(value.height)||!Number.isSafeInteger(value.width)||!Number.isSafeInteger(value.height)||!Number.isSafeInteger(Number(value.width)*Number(value.height)))issues.push('size')
  if(g.kind!=='orthographic-height'||!vector(g.origin)||!positive(g.column_step)||!positive(g.row_step))issues.push('grid')
  const axes=[g.column_direction,g.row_direction,g.height_direction]
  if(!axes.every(vector))issues.push('axes')
  else {
    const [a,b,c]=axes as [number[],number[],number[]],dot=(u:number[],v:number[])=>u.reduce((s,n,i)=>s+n*v[i]!,0)
    const cross=[a[1]!*b[2]!-a[2]!*b[1]!,a[2]!*b[0]!-a[0]!*b[2]!,a[0]!*b[1]!-a[1]!*b[0]!]
    if(axes.some(v=>Math.abs(dot(v as number[],v as number[])-1)>1e-8)||Math.abs(dot(a,b))>1e-8||Math.abs(dot(a,c))>1e-8||Math.abs(dot(b,c))>1e-8||Math.abs(dot(cross,c)-1)>1e-8)issues.push('axes')
  }
  for(const [n,s] of [[value.width,g.column_step],[value.height,g.row_step]])if(positive(n)&&positive(s)&&(!Number.isFinite((n-.5)*s)||(n-.5)*s<=(n-1.5)*s))issues.push('precision')
  return issues
}
