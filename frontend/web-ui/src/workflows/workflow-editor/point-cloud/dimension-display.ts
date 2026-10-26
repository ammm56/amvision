/** 只核对显示结构与版本分支；不在浏览器拟合、测量或重新判定质量。 */
import {object} from './preview-data'

function fail():never{throw new Error('cloud_preview_invalid')}
function finite(value:unknown):number {if(typeof value!=='number'||!Number.isFinite(value))fail();return value}
function count(value:unknown):number {const v=finite(value);if(!Number.isSafeInteger(v)||v<0)fail();return v}
function vector(value:unknown):number[] {if(!Array.isArray(value)||value.length!==3)fail();return value.map(finite)}
function points(value:unknown,length:number):number[][] {if(!Array.isArray(value)||value.length!==length)fail();return value.map(vector)}

export function validateDimensionGeometry(item:Record<string,unknown>,geometry:Record<string,unknown>|null,support:Record<string,unknown>[]):void{
  const evaluation=object(item.method).evaluation
  if(evaluation!==null){const e=object(evaluation);if(typeof e.frame_id!=='string'||!['m','mm','um'].includes(String(e.length_unit)))fail();vector(e.origin);points(e.rotation,3)}else if(item.valid)fail()
  const allowed=item.kind==='measure-extents'?['u','v','length','width']:item.kind==='measure-edge-pair'?['distance']:['diameter','center_x','center_y','center_z']
  if(!allowed.includes(String(item.component))||(item.valid?item.diagnostic!==null:!item.diagnostic))fail()
  for(const side of support){
    if(side.point_count!==null){
      const n=count(side.point_count),source=count(side.source_point_count)
      if(!['source','generated'].includes(String(side.vertex_kind))||(side.vertex_kind==='source'&&n>source)||typeof side.content_sha256!=='string'||!/^[0-9a-f]{64}$/.test(side.content_sha256))fail()
      if(n){const bounds=object(side.bounds);vector(bounds.min);vector(bounds.max)}else if(side.bounds!==null)fail()
    }else if([side.source_point_count,side.vertex_kind,side.content_sha256,side.bounds].some(v=>v!==null))fail()
    if(side.feature){const f=object(side.feature);if(item.kind==='measure-hole'&&f.kind!=='circle'||item.kind==='measure-edge-pair'&&f.kind!=='line')fail()}
  }
  if(!geometry)return
  if(item.kind==='measure-extents'){
    if(geometry.kind!=='projected-extents')fail()
    vector(geometry.origin);points(geometry.axes,2);points(geometry.corners,4)
    if(!Array.isArray(geometry.limits)||geometry.limits.length!==4||!Array.isArray(geometry.contacts)||geometry.contacts.length!==4)fail()
    const limits=geometry.limits.map(finite)
    if(limits[0]!>=limits[2]!||limits[1]!>=limits[3]!)fail()
    for(const raw of geometry.contacts){
      const c=object(raw)
      vector(c.point);vector(c.projected);count(c.vertex_index)
      if(count(c.tied_count)<1)fail()
      if(support[0]?.vertex_kind==='source'){
        count(c.source_index)
        if(c.lineage!==null)fail()
      }else{
        if(c.source_index!==null)fail()
        const lineage=object(c.lineage)
        if(!Array.isArray(lineage.source_edge)||lineage.source_edge.length!==2||!Array.isArray(lineage.weights)||lineage.weights.length!==2)fail()
        lineage.source_edge.forEach(count);lineage.weights.forEach(finite)
        if(count(lineage.source_face_count)<1||typeof lineage.source_faces_sha256!=='string'||!/^[0-9a-f]{64}$/.test(lineage.source_faces_sha256))fail()
      }
    }
    const rectangle=['length','width'].includes(String(item.component))
    if(rectangle!==Boolean(geometry.candidates))fail()
    if(rectangle){const c=object(geometry.candidates);if(c.dimensions_consistent!==true||typeof c.orientation_unique!=='boolean'||count(c.hull_point_count)<3||count(c.tied_count)<1||count(c.tied_count)>count(c.candidate_count)||finite(c.minimum_area)<=0||finite(c.orientation_spread_radians)<0||finite(c.orientation_spread_radians)>Math.PI/2)fail();for(const key of ['length_range','width_range']){const range=c[key];if(!Array.isArray(range)||range.length!==2||finite(range[0])<0||finite(range[0])>finite(range[1]))fail()}}
  }else if(item.kind==='measure-edge-pair'){
    if(geometry.kind!=='edge-pair-distance')fail()
    vector(geometry.query_position);vector(geometry.direction);points(geometry.endpoints,2);finite(geometry.signed_distance)
    for(const key of ['line_parameters','query_parameters']){const v=geometry[key];if(!Array.isArray(v)||v.length!==2)fail();v.forEach(finite)}
    if(!Array.isArray(geometry.segment_ids)||geometry.segment_ids.length!==2||geometry.segment_ids.some(s=>typeof s!=='string'||!s))fail()
  }else{
    if(geometry.kind!=='circle-dimensions')fail()
    const circle=object(geometry.circle);vector(circle.center);vector(circle.normal);if(finite(circle.radius)<=0)fail()
    vector(geometry.display_direction);points(geometry.diameter_endpoints,2)
  }
}
