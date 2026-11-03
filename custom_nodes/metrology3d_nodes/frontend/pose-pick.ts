import {object,vector} from './form'

/** 将当前显示中的候选源坐标转换为已核对位姿的 U/V，不执行测量。 */
export function candidateUV(frame:unknown, xyz:unknown):number[]|null {
  if(!vector(xyz))return null
  const matrix=object(object(frame).transform).matrix
  if(!Array.isArray(matrix)||matrix.length!==4||!matrix.every(row=>Array.isArray(row)&&row.length===4&&row.every(v=>typeof v==='number'&&Number.isFinite(v))))return null
  const point=xyz as number[]
  return matrix.slice(0,2).map(row=>row[0]*point[0]!+row[1]*point[1]!+row[2]*point[2]!+row[3])
}
