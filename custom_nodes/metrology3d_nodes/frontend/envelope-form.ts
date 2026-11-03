/** 格剖面配方只做结构准入；计算和质量判定在现有节点执行。 */
import {object,type Form} from './form'

export const profileSides=['u-min','u-max','v-min','v-max']
const finite=(v:unknown):v is number=>typeof v==='number'&&Number.isFinite(v)
const pair=(v:unknown):v is number[]=>Array.isArray(v)&&v.length===2&&v.every(finite)
export function newEnvelope():Form{return {grid:{origin:[null,null],step:null,shape:[null,null],min_cell_count:null},selection:{kind:'grid-connected',seed_min:[null,null],seed_max:[null,null],connectivity:null,closing_radius_cells:null},profiles:{foreground:null,edge_policy:null,min_observed_length:null}}}
/** 切换方法时保留种子，清除不适用字段；连接距离由配方明确填写。 */
export function selectEnvelopePartition(value:Form,kind:string):Form{
  const s=object(value.selection)
  return {...value,selection:{kind,seed_min:s.seed_min,seed_max:s.seed_max,...(kind==='distance-connected'?{connection_distance:null}:{connectivity:null,closing_radius_cells:null})}}
}
export function envelopeIssues(value:unknown):string[]{
  const p=object(value),g=object(p.grid),s=object(p.selection),profiles=object(p.profiles),issues:string[]=[]
  const grid=pair(g.origin)&&finite(g.step)&&g.step>0&&pair(g.shape)&&g.shape.every(n=>Number.isSafeInteger(n)&&n>0)&&Number.isSafeInteger(g.min_cell_count)&&Number(g.min_cell_count)>0
  if(!grid)issues.push('grid')
  if(!pair(s.seed_min)||!pair(s.seed_max)||s.seed_min.some((n,i)=>n>=(s.seed_max as number[])[i]!))issues.push('seed window')
  else if(grid){const low=s.seed_min,high=s.seed_max,origin=g.origin as number[],shape=g.shape as number[],step=g.step as number;if(low.some((n,i)=>n<origin[i]!||high[i]!>origin[i]!+shape[i]!*step))issues.push('seed / grid')}
  if(s.kind==='distance-connected'){
    if(!finite(s.connection_distance)||s.connection_distance<=0||'connectivity' in s||'closing_radius_cells' in s)issues.push('selection')
  }else if(s.kind==='grid-connected'){
    if(![4,8].includes(Number(s.connectivity))||!Number.isSafeInteger(s.closing_radius_cells)||Number(s.closing_radius_cells)<0||'connection_distance' in s)issues.push('selection')
  }else issues.push('selection')
  if(!['above','below'].includes(String(profiles.foreground))||!['cell-edge','interpolate-or-cell-edge'].includes(String(profiles.edge_policy))||!finite(profiles.min_observed_length)||profiles.min_observed_length<=0)issues.push('profiles')
  return issues
}
