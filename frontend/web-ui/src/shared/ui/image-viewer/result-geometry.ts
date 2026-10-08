import type {ResultColumn} from './result-format'
/** 显示位置只来自同次后端结果；expected-point 始终表示名义位置。 */
export interface ResultGeometryShape { item_id:string;kind:'line'|'point'|'expected-point';points:Array<[number,number]> }
export interface ResultTable { observation_id:string;columns:ResultColumn[];rows:Record<string,unknown>[];result_geometry:{observation_id:string;image:{width:number;height:number};items:ResultGeometryShape[]} }

export function readResultTable(value:unknown):ResultTable|null {
  // 运行结果可能来自旧快照或自定义节点，损坏的可选显示数据不能使整张图片无法打开。
  const record=(item:unknown):item is Record<string,unknown>=>Boolean(item)&&typeof item==='object'&&!Array.isArray(item)
  if(!record(value)||typeof value.observation_id!=='string'||!value.observation_id)return null
  const {rows,columns,result_geometry:geometry}=value
  if(!Array.isArray(rows)||rows.length>8192||!Array.isArray(columns)||columns.length>32||!record(geometry))return null
  if(geometry.observation_id!==value.observation_id||!record(geometry.image)||!Array.isArray(geometry.items)||geometry.items.length>9216)return null
  if(![geometry.image.width,geometry.image.height].every(size=>typeof size==='number'&&Number.isInteger(size)&&size>0))return null
  if(rows.some(row=>!record(row)||typeof row.item_id!=='string'||!row.item_id)||new Set(rows.map(row=>row.item_id)).size!==rows.length)return null
  if(columns.some(column=>!record(column)||typeof column.key!=='string'||!column.key||typeof column.label!=='string'||!column.label)||new Set(columns.map(column=>column.key)).size!==columns.length)return null
  if(columns.some(column=>column.format!==undefined&&!['value','unit','result','validity','reason'].includes(String(column.format))))return null
  if(geometry.items.some(shape=>!record(shape)||typeof shape.item_id!=='string'||!shape.item_id||!['line','point','expected-point'].includes(String(shape.kind))||!Array.isArray(shape.points)||shape.points.length!==(shape.kind==='line'?2:1)||shape.points.some(point=>!Array.isArray(point)||point.length!==2||point.some(coordinate=>typeof coordinate!=='number'||!Number.isFinite(coordinate))))||new Set(geometry.items.map(shape=>shape.item_id)).size!==geometry.items.length)return null
  return value as unknown as ResultTable
}

export function selectedResultShape(table:ResultTable|null|undefined,id:string|null|undefined):ResultGeometryShape|null {
  if(!table||!id||!table.rows.some(row=>row.item_id===id))return null
  return table.result_geometry.items.find(shape=>shape.item_id===id)??null
}

export function formatResultValue(value:unknown):string {
  if(value===null||value===undefined)return '—'
  if(typeof value==='number')return Number.isFinite(value)?Number(value.toPrecision(7)).toString():'—'
  if(typeof value==='object')return JSON.stringify(value)
  return String(value)
}
