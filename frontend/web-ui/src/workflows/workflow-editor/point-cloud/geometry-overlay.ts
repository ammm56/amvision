import {AxesHelper,BoxGeometry,BufferGeometry,Camera,CylinderGeometry,DoubleSide,EdgesGeometry,Group,LineBasicMaterial,LineSegments,Matrix4,Mesh,MeshBasicMaterial,Object3D,Plane,Quaternion,Vector3,type Material} from 'three'
import {TransformControls} from 'three/addons/controls/TransformControls.js'
import {object,reserveCpu,reserveGpu} from './preview-data'
import type {CloudRendererPolicy} from '../services/measurement-resource.service'
import {measurementItems} from './measurement-display'
import {curveItems,curveStrokes} from './boundary-display'
import type {Raycaster} from 'three'

export type RoiValue=Record<string,unknown>
export interface GeometryOverlayInput { payload:Record<string,unknown>; rois?:RoiValue[]; selectedId?:string; mode?:'translate'|'rotate'; changed?:(roi:RoiValue)=>void;selectedMeasurement?:string;selectedPlane?:string;candidate?:number[];selectedCurve?:string;selectedSegment?:string;curveSelected?:(featureId:string,segmentId:string)=>void }
const vec=(v:unknown)=>{if(!Array.isArray(v)||v.length!==3||v.some(n=>typeof n!=='number'||!Number.isFinite(n)))throw new Error('cloud_preview_invalid');return new Vector3(v[0],v[1],v[2])}
function matrix(v:unknown,size:number){if(!Array.isArray(v)||v.length!==size||v.some(r=>!Array.isArray(r)||r.length!==size||r.some(n=>typeof n!=='number'||!Number.isFinite(n))))throw new Error('cloud_preview_invalid');return v as number[][]}
const positive=(n:unknown)=>{if(typeof n!=='number'||!Number.isFinite(n)||n<=0)throw new Error('cloud_preview_invalid');return n}
const orientation=(g:RoiValue,kind:unknown)=>kind==='box'?new Quaternion().setFromRotationMatrix(new Matrix4().set(...matrix(g.rotation,3).flatMap(r=>[...r,0]).concat([0,0,0,1]) as Parameters<Matrix4['set']>)):new Quaternion().setFromUnitVectors(new Vector3(0,1,0),vec(kind==='cylinder'?g.axis:g.normal))

/** 只显示有限几何；所有坐标先减 render_origin，显示缓冲统一计费。 */
export function createGeometryOverlay(scene:Object3D,camera:Camera,canvas:HTMLElement,origin:number[],policy:CloudRendererPolicy,schedule:()=>void,drag:(active:boolean)=>void,failed:(error:Error)=>void) {
  let root=new Group(),gizmo:TransformControls|null=null, releases:(()=>void)[]=[],input:GeometryOverlayInput|undefined,closed=false
  const physicalOrigin=new Vector3(...origin),targets=new Map<string,Object3D>(),updates=new Map<string,(roi:RoiValue)=>void>()
  function resources(object:Object3D){const geometries=new Set<BufferGeometry>(),materials=new Set<Material>();object.traverse(o=>{const item=o as Mesh;if(item.geometry)geometries.add(item.geometry);if(item.material)for(const m of Array.isArray(item.material)?item.material:[item.material])materials.add(m)});return {geometries,materials}}
  function account(object:Object3D){const buffers=new Set<ArrayBufferLike>();for(const g of resources(object).geometries){for(const a of Object.values(g.attributes))buffers.add(a.array.buffer);if(g.index)buffers.add(g.index.array.buffer)}const bytes=[...buffers].reduce((s,b)=>s+b.byteLength,0);releases.push(reserveCpu(bytes,policy));releases.push(reserveGpu(bytes,policy))}
  function clear(){drag(false);gizmo?.detach();gizmo?.dispose();gizmo=null;for(const g of resources(root).geometries)g.dispose();for(const m of resources(root).materials)m.dispose();root.removeFromParent();root.clear();targets.clear();updates.clear();for(const release of releases)release();releases=[];root=new Group()}
  function pose(roi:RoiValue,target:Object3D){const g=object(roi.geometry);target.position.copy(vec(roi.kind==='section-band'?g.origin:g.center)).sub(physicalOrigin);target.quaternion.copy(orientation(g,roi.kind))}
  function finiteMesh(roi:RoiValue,color:number,clips:Plane[]=[]){
    const target=new Group();pose(roi,target);root.add(target)
    const g=object(roi.geometry),geometry=roi.kind==='box'?new BoxGeometry(...vec(g.size).toArray().map(positive) as [number,number,number]):new CylinderGeometry(positive(g.radius),positive(g.radius),positive(g.length),48)
    const material=new MeshBasicMaterial({color,transparent:true,opacity:.13,depthWrite:false,side:DoubleSide,clippingPlanes:clips})
    const mesh=new Mesh(geometry,material);target.add(mesh)
    const edge=new LineSegments(new EdgesGeometry(geometry),new LineBasicMaterial({color,clippingPlanes:clips}));target.add(edge)
    account(target);return {target,material,edge}
  }
  function sectionPlanes(roi:RoiValue){const g=object(roi.geometry),n=vec(g.normal),p=vec(g.origin).sub(physicalOrigin),half=positive(g.thickness)/2;return [new Plane(n,n.dot(p.clone().negate())+half),new Plane(n.clone().negate(),n.dot(p)+half)]}
  function buildRoi(roi:RoiValue,rois:RoiValue[]){
    if(roi.kind!=='section-band'){targets.set(String(roi.roi_id),finiteMesh(roi,0xd18c00).target);return}
    let bounded=roi;const sections:RoiValue[]=[],seen=new Set<unknown>()
    while(bounded.kind==='section-band'){if(seen.has(bounded.roi_id))throw new Error('cloud_preview_invalid');seen.add(bounded.roi_id);sections.push(bounded);const next=rois.find(r=>r.roi_id===object(bounded.geometry).bounds_roi_id);if(!next)throw new Error('cloud_preview_invalid');bounded=next}
    const shape=finiteMesh(bounded,0xc8558a,sections.flatMap(sectionPlanes)),anchor=new Group();pose(roi,anchor);root.add(anchor);targets.set(String(roi.roi_id),anchor)
    updates.set(String(roi.roi_id),next=>{const clips=[next,...sections.slice(1)].flatMap(sectionPlanes);shape.material.clippingPlanes=clips;(shape.edge.material as LineBasicMaterial).clippingPlanes=clips})
  }
  function buildEvidence(payload:Record<string,unknown>){
    if(!payload.geometry)return
    const g=object(payload.geometry),spatial=object(payload.spatial)
    if(g.format_id!=='amvision.geometry-preview.v2'||g.observation_id!==payload.observation_id||g.frame_id!==spatial.frame_id||g.length_unit!==spatial.length_unit||!Array.isArray(g.planes)||g.planes.length>8192)throw new Error('cloud_preview_invalid')
    for(const raw of g.planes){const p=object(raw);if(!p.valid)continue;const plane=object(p.geometry),bounds=object(p.support_bounds),low=vec(bounds.min),high=vec(bounds.max),n=vec(plane.normal),offset=plane.offset;if(typeof offset!=='number'||!Number.isFinite(offset))throw new Error('cloud_preview_invalid')
      const center=low.clone().add(high).multiplyScalar(.5);center.addScaledVector(n,-n.dot(center)-offset)
      const q=new Quaternion().setFromUnitVectors(new Vector3(0,0,1),n),inv=q.clone().invert();let x=0,y=0
      for(let i=0;i<8;i++){const d=new Vector3(i&1?high.x:low.x,i&2?high.y:low.y,i&4?high.z:low.z).sub(center).applyQuaternion(inv);x=Math.max(x,Math.abs(d.x));y=Math.max(y,Math.abs(d.y))}
      const geometry=new BufferGeometry().setFromPoints([new Vector3(-x,-y,0),new Vector3(x,-y,0),new Vector3(x,-y,0),new Vector3(x,y,0),new Vector3(x,y,0),new Vector3(-x,y,0),new Vector3(-x,y,0),new Vector3(-x,-y,0)])
      const outline=new LineSegments(geometry,new LineBasicMaterial({color:p.feature_id===input?.selectedPlane?0xd18c00:0x287bb8}));outline.position.copy(center.sub(physicalOrigin));outline.quaternion.copy(q);root.add(outline);account(outline)
    }
    if(g.frame){const f=object(g.frame);if(f.state==='found'){const t=object(f.transform),m=new Matrix4().set(...matrix(t.matrix,4).flat() as Parameters<Matrix4['set']>);if(t.source_frame_id===spatial.frame_id)m.invert();else if(t.target_frame_id===spatial.frame_id)m.identity();else throw new Error('cloud_preview_invalid');const bounds=object(payload.bounds),length=vec(bounds.max).sub(vec(bounds.min)).length()*.25;const axes=new AxesHelper(length);axes.applyMatrix4(m);axes.position.sub(physicalOrigin);root.add(axes);account(axes)}}
  }
  function lines(points:Vector3[],color:number){
    const local=points.map(p=>p.clone().sub(physicalOrigin)),geometry=new BufferGeometry().setFromPoints(local)
    const position=geometry.getAttribute('position')
    for(let i=0;i<local.length;i++)for(let axis=0;axis<3;axis++)if(!Number.isFinite(position.getComponent(i,axis))||Math.abs(position.getComponent(i,axis)-local[i]!.getComponent(axis))>policy.max_position_error){geometry.dispose();throw new Error('cloud_position_precision')}
    const line=new LineSegments(geometry,new LineBasicMaterial({color,depthTest:false}));root.add(line);account(line);return line
  }
  function buildCurves(next:GeometryOverlayInput){
    for(const stroke of curveStrokes(curveItems(next.payload),policy)){
      const selected=stroke.featureId===next.selectedCurve&&(!next.selectedSegment||stroke.segmentId===next.selectedSegment)
      const line=lines(stroke.points.map(vec),selected?0xd18c00:stroke.fitted?0xc8558a:0x208c77)
      line.userData.curve={featureId:stroke.featureId,segmentId:stroke.segmentId}
    }
  }
  function buildMeasurements(next:GeometryOverlayInput){
    for(const item of measurementItems(next.payload)){
      const selected=item.item_id===next.selectedMeasurement,color=selected?0xd18c00:0x508691
      if(item.valid&&item.geometry?.kind==='directional-distance'){
        const endpoints=item.geometry.endpoints
        if(!Array.isArray(endpoints)||endpoints.length!==2)throw new Error('cloud_preview_invalid')
        lines(endpoints.map(vec),color)
      }
      if(!selected)continue
      for(const side of item.support){
        const coverage=side.coverage?object(side.coverage):null
        if(coverage?.triangle){const raw=coverage.triangle;if(!Array.isArray(raw)||raw.length!==3)throw new Error('cloud_preview_invalid');const p=raw.map(vec);lines([p[0]!,p[1]!,p[1]!,p[2]!,p[2]!,p[0]!],side.role==='reference'?0x287bb8:0x339653)}
        if(side.statistic&&side.bounds){const b=object(side.bounds),low=vec(b.min),high=vec(b.max),corners=Array.from({length:8},(_,i)=>new Vector3(i&1?high.x:low.x,i&2?high.y:low.y,i&4?high.z:low.z)),points:Vector3[]=[];for(let i=0;i<8;i++)for(const bit of [1,2,4])if(!(i&bit))points.push(corners[i]!,corners[i|bit]!);lines(points,side.role==='reference'?0x287bb8:0x339653)}
      }
    }
    if(next.candidate){const p=vec(next.candidate),bounds=object(next.payload.bounds),size=vec(bounds.max).sub(vec(bounds.min)).length()*.01,points:Vector3[]=[];for(let i=0;i<3;i++){const delta=new Vector3().setComponent(i,size);points.push(p.clone().sub(delta),p.clone().add(delta))}lines(points,0xe1a100)}
  }
  function update(next:GeometryOverlayInput){
    if(closed)return;input=next
    if(gizmo?.dragging)return
    clear()
    try {
      scene.add(root);buildEvidence(next.payload);buildMeasurements(next);buildCurves(next)
      const spatial=object(next.payload.spatial),attached=next.payload.geometry?object(next.payload.geometry).rois:[],rois=next.rois??(Array.isArray(attached)?attached.map(object):[])
      if(rois.length>8192)throw new Error('cloud_preview_invalid')
      for(const roi of rois){if(roi.frame_id!==spatial.frame_id||roi.length_unit!==spatial.length_unit)throw new Error('cloud_geometry_space');buildRoi(roi,rois)}
      const target=targets.get(next.selectedId??'')
      if(target&&next.changed){gizmo=new TransformControls(camera,canvas);gizmo.setMode(next.mode??'translate');gizmo.attach(target);const helper=gizmo.getHelper();root.add(helper);account(helper)
        gizmo.addEventListener('change',schedule)
        gizmo.addEventListener('dragging-changed',e=>{
          drag(e.value===true)
          // 等本次控件事件完成，再用最新草稿重建依赖边界；卸载后不得重新分配。
          if(e.value===false)queueMicrotask(()=>{
            if(closed||!input)return
            try{update(input)}catch(error){failed(error as Error)}
          })
        })
        gizmo.addEventListener('objectChange',()=>{const roi=input?.rois?.find(r=>r.roi_id===input?.selectedId);if(!roi)return;const g={...object(roi.geometry)},position=target.position.clone().add(physicalOrigin).toArray(),q=target.quaternion
          if(roi.kind==='section-band'){g.origin=position;g.normal=new Vector3(0,1,0).applyQuaternion(q).toArray()}else {g.center=position;if(roi.kind==='cylinder')g.axis=new Vector3(0,1,0).applyQuaternion(q).toArray();else {const m=new Matrix4().makeRotationFromQuaternion(q).elements;g.rotation=[[m[0],m[4],m[8]],[m[1],m[5],m[9]],[m[2],m[6],m[10]]]}}
          const changed={...roi,geometry:g};updates.get(String(roi.roi_id))?.(changed);input?.changed?.(changed);schedule()
        })
      }
      schedule()
    }catch(error){clear();throw error}
  }
  return {update,pick(ray:Raycaster){if(closed||!input?.curveSelected)return false;const hit=ray.intersectObject(root,true).find(h=>h.object.userData.curve);if(!hit)return false;const c=hit.object.userData.curve;input.curveSelected(c.featureId,c.segmentId);return true},camera(value:Camera){camera=value;if(gizmo)gizmo.camera=value},dragging:()=>!!gizmo?.dragging,dispose(){if(!closed){closed=true;clear()}}}
}
