/** 关系证据只负责读取与显示，不在浏览器重新求最近点、拟合或判公差。 */
import {object} from './preview-data'
import {Vector3} from 'three'

function fail():never{throw new Error('cloud_preview_invalid')}
function point(value:unknown){if(!Array.isArray(value)||value.length!==3||value.some(v=>typeof v!=='number'||!Number.isFinite(v)))fail()}

/** 只将已核验落点投影到显式评价面；虚线为构造，不补实测支持。 */
export function relationDistanceStrokes(method:Record<string,unknown>,geometry:Record<string,unknown>){
  if(geometry.endpoints===null)return {dimension:[] as Vector3[],construction:[] as Vector3[]}
  if(!Array.isArray(geometry.endpoints)||geometry.endpoints.length!==2)fail()
  const original=geometry.endpoints.map(value=>{point(value);return new Vector3(...value as [number,number,number])})
  const space=object(object(method.parameters).space)
  if(space.kind==='spatial')return {dimension:original,construction:[] as Vector3[]}
  if(space.kind!=='projection')fail()
  const plane=object(space.plane);point(plane.origin)
  if(!Array.isArray(plane.rotation)||plane.rotation.length!==3)fail()
  plane.rotation.forEach(point)
  const rotation=plane.rotation as number[][],normal=new Vector3(rotation[0]![2],rotation[1]![2],rotation[2]![2])
  if(Math.abs(normal.lengthSq()-1)>1e-8)fail()
  const origin=new Vector3(...plane.origin as [number,number,number])
  const dimension=original.map(value=>value.clone().addScaledVector(normal,-value.clone().sub(origin).dot(normal)))
  const construction=original.flatMap((value,index)=>value.equals(dimension[index]!)?[]:[value,dimension[index]!])
  return {dimension,construction}
}
export function validateRelationGeometry(item:Record<string,unknown>,geometry:Record<string,unknown>|null,support:Record<string,unknown>[],spatial:Record<string,unknown>):void{
  const p=object(object(item.method).parameters),r=object(p.relation),space=object(p.space),projection=space.kind==='projection'
  if(!['point-point','point-line','point-plane','line-line','line-angle','plane-angle'].includes(String(r.kind))||!['spatial','projection'].includes(String(space.kind)))fail()
  const frame=projection?object(space.plane):space,angle=String(r.kind).endsWith('angle')
  if(frame.frame_id!==spatial.frame_id||frame.length_unit!==spatial.length_unit||p.item_id!==item.item_id||item.component!==(angle?'angle':'distance'))fail()
  if(item.valid?item.diagnostic!==null:!['source','geometry','quality'].includes(String(object(item.diagnostic).stage)))fail()
  if(!item.valid&&![null,'reference','target'].includes(object(item.diagnostic).role as null|string))fail()
  for(let i=0;i<2;i++){
    const s=support[i]!,selector=object(i===0?r.reference:r.target),source=s.point===null?{}:object(s.point),f=s.feature===null?{}:object(s.feature),plane=s.plane===null?{}:object(s.plane)
    if(s.role!==(i===0?'reference':'target'))fail()
    if(['source-point','coordinate','circle-center'].includes(String(selector.kind))){
      if(source.point!==null)point(source.point)
      if((source.point===null)!==(typeof source.reason==='string'))fail()
      const origin={'source-point':'measured','coordinate':'specified','circle-center':'estimated'}[String(selector.kind)]
      if(source.origin!==origin)fail()
      if(selector.kind==='source-point'&&(!Number.isSafeInteger(source.source_index)||Number(source.source_index)<0||source.source_index!==selector.source_index))fail()
      if(selector.kind==='coordinate'&&JSON.stringify(selector.position)!==JSON.stringify(source.point))fail()
      if(selector.kind==='circle-center'&&(f.kind!=='circle'||f.feature_id!==selector.feature_id||source.feature_id!==selector.feature_id))fail()
    }else if(selector.kind==='line'){
      if(s.point!==null||f.kind!=='line'||f.feature_id!==selector.feature_id)fail()
    }else if(selector.kind==='plane'){
      if(s.point!==null||object(object(plane.method).parameters).feature_id!==selector.feature_id)fail()
    }else fail()
  }
  if(!geometry)return
  if(geometry.kind!=='geometric-relation'||!Array.isArray(geometry.support_pairs)||geometry.support_pairs.length>8192)fail()
  for(const pair of geometry.support_pairs)if(!Array.isArray(pair)||pair.length!==2||pair.some(v=>typeof v!=='string'||!v))fail()
  if(angle){if(geometry.endpoints!==null||geometry.contacts_unique!==null||geometry.support_pairs.length)fail()}
  else if(geometry.contacts_unique===true){if(!Array.isArray(geometry.endpoints)||geometry.endpoints.length!==2)fail();geometry.endpoints.forEach(point)}
  else if(geometry.contacts_unique!==false||geometry.endpoints!==null||r.kind!=='line-line')fail()
}

export function relationMethod(parameters:Record<string,unknown>,zh:boolean):string{
  const r=object(parameters.relation),space=object(parameters.space)
  const labels:Record<string,string>=zh?{'point-point':'点点距离','point-line':'点线垂距','point-plane':'点面垂距','line-line':'线线最短距离','line-angle':'线方向夹角','plane-angle':'平面法向夹角'}:{'point-point':'Point distance','point-line':'Point to line','point-plane':'Point to plane','line-line':'Closest line distance','line-angle':'Line direction angle','plane-angle':'Plane normal angle'}
  const parts=[labels[String(r.kind)]??String(r.kind),space.kind==='projection'?(zh?'评价面投影':'Evaluation-plane projection'):(zh?'三维空间':'Spatial')]
  if(r.support_mode)parts.push(r.support_mode==='finite'?(zh?'有限实测支持':'Finite measured support'):(zh?'无限模型':'Infinite model'))
  if(r.angle_mode)parts.push((zh?{unoriented:'无向 0–90°',oriented:'向量 0–180°',signed:'绕 +N 有符号'}:{unoriented:'Unoriented 0–90°',oriented:'Vector 0–180°',signed:'Signed about +N'})[String(r.angle_mode)]??String(r.angle_mode))
  return parts.join(' · ')
}
