/** 参数角域的坐标和拖动规则；不提取边界或重算拟圆结果。 */
export type ArcHandle = 'center' | 'inner' | 'outer' | 'start' | 'end'
export interface ArcValues { center:number[]; start_angle:number; sweep:number; radius_range?:number[] }
export interface ArcEdit {
  key:string
  values:ArcValues
  evaluation:{origin:number[];rotation:number[][]}
  displayRadius:number
  minSweep:number
  handle:ArcHandle
}
export const fullTurn=2*Math.PI
export const wrapAngle=(value:number)=>((value%fullTurn)+fullTurn)%fullTurn
const finite=(value:unknown):value is number=>typeof value==='number'&&Number.isFinite(value)
export function validArc(value:ArcValues,minSweep=0):boolean {
  return value.center.length===2&&value.center.every(finite)&&finite(value.start_angle)&&value.start_angle>=0&&value.start_angle<fullTurn&&finite(value.sweep)&&value.sweep>minSweep&&value.sweep<=fullTurn&&(!value.radius_range||(value.radius_range.length===2&&value.radius_range.every(finite)&&value.radius_range[0]!>0&&value.radius_range[1]!>value.radius_range[0]!))
}
export function arcWorld(edit:ArcEdit,uv:number[]):number[] {
  return edit.evaluation.origin.map((value,i)=>value+edit.evaluation.rotation[i]![0]!*uv[0]!+edit.evaluation.rotation[i]![1]!*uv[1]!)
}
export function arcUV(edit:ArcEdit,xyz:number[]):number[] {
  return [0,1].map(axis=>xyz.reduce((sum,value,i)=>sum+(value-edit.evaluation.origin[i]!)*edit.evaluation.rotation[i]![axis]!,0))
}
export function arcHandleUV(edit:ArcEdit):number[] {
  const v=edit.values
  if(edit.handle==='center')return [...v.center]
  const angle=v.start_angle+(edit.handle==='end'?v.sweep:edit.handle==='inner'||edit.handle==='outer'?v.sweep/2:0)
  const radius=edit.handle==='inner'?v.radius_range![0]!:edit.handle==='outer'?v.radius_range![1]!:edit.displayRadius
  return v.center.map((value,i)=>value+radius*(i?Math.sin(angle):Math.cos(angle)))
}
/** 每次手势独立累计角度，跨零不交换端点，整周不退化为零。 */
export function arcGesture(edit:ArcEdit) {
  const original:ArcValues={...edit.values,center:[...edit.values.center],...(edit.values.radius_range?{radius_range:[...edit.values.radius_range]}:{})}
  let previous=wrapAngle(original.start_angle+original.sweep),unwrapped=original.sweep
  return (uv:number[]):ArcValues|null=>{
    if(uv.length!==2||!uv.every(finite))return null
    const value={...original,center:[...original.center],...(original.radius_range?{radius_range:[...original.radius_range]}:{})}
    if(edit.handle==='center')value.center=[...uv]
    else {
      const x=uv[0]!-original.center[0]!,y=uv[1]!-original.center[1]!,radius=Math.hypot(x,y)
      if(!radius||!Number.isFinite(radius))return null
      if(edit.handle==='inner'||edit.handle==='outer'){
        if(!value.radius_range)return null
        value.radius_range[edit.handle==='inner'?0:1]=radius
      }else{
        const angle=wrapAngle(Math.atan2(y,x))
        if(edit.handle==='start')value.start_angle=angle
        else {let delta=angle-previous;if(delta>Math.PI)delta-=fullTurn;if(delta< -Math.PI)delta+=fullTurn;unwrapped+=delta;previous=angle;value.sweep=unwrapped}
      }
    }
    return validArc(value,edit.minSweep)?value:null
  }
}
