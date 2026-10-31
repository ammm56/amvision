import {AxesHelper,Box3,BoxGeometry,BufferGeometry,Camera,CylinderGeometry,DoubleSide,EdgesGeometry,Group,LineBasicMaterial,LineDashedMaterial,LineSegments,Matrix4,Mesh,MeshBasicMaterial,Object3D,Plane,Quaternion,Vector3,type Material} from 'three'
import {Points,PointsMaterial,BufferAttribute} from 'three'
import {curveColorValues,curveColorScale,curveColor,type CurveColorMode} from './curve-colors'
import {TransformControls} from 'three/addons/controls/TransformControls.js'
import {object,reserveCpu,reserveGpu} from './preview-data'
import type {CloudRendererPolicy} from '../services/measurement-resource.service'
import {measurementItems,referenceExtension} from './measurement-display'
import {curveItems,curveStrokes} from './boundary-display'
import type {Raycaster} from 'three'
import {roiDependencies,roiGraphIssues} from './roi-graph'
import {roiLeaves,roiVisibility} from './roi-visibility'
import {expandRoiDisplayBounds} from './roi-display-bounds'
import {arcWorld,arcUV,arcHandleUV,arcGesture,type ArcEdit,type ArcValues} from './arc-edit'
import {buildDebugOverlay} from './debug-overlay'
import type {DebugEvidence,DebugLayers,DebugSelection} from './boundary-debug'

export type RoiValue=Record<string,unknown>
export type GeometryFocus='roi'|'measurement'|'feature'|'plane'|'arc'|'debug'
export interface GeometryOverlayInput { payload:Record<string,unknown>; rois?:RoiValue[]; selectedId?:string; mode?:'translate'|'rotate'|'scale'; changed?:(roi:RoiValue)=>void;selectedMeasurement?:string;selectedPlane?:string;candidate?:number[];selectedCurve?:string;selectedSegment?:string;curveColorMode?:CurveColorMode;curveSelected?:(featureId:string,segmentId:string)=>void;measurementSelected?:(id:string)=>void;arc?:ArcEdit;arcChanged?:(key:string,value:ArcValues)=>void }
export interface GeometryOverlayInput {debug?:DebugEvidence;debugLayers?:DebugLayers;debugSelection?:DebugSelection|null;debugSelected?:(selection:DebugSelection)=>void;debugFailed?:(error:Error)=>void}
export interface GeometryOverlayInput {selectedCurvePoint?:number|null;curvePointSelected?:(featureId:string,segmentId:string,index:number)=>void}
export interface GeometryOverlayInput {hiddenRoiIds?:ReadonlySet<string>;roiScope?:string}
const vec=(v:unknown)=>{if(!Array.isArray(v)||v.length!==3||v.some(n=>typeof n!=='number'||!Number.isFinite(n)))throw new Error('cloud_preview_invalid');return new Vector3(v[0],v[1],v[2])}
function matrix(v:unknown,size:number){if(!Array.isArray(v)||v.length!==size||v.some(r=>!Array.isArray(r)||r.length!==size||r.some(n=>typeof n!=='number'||!Number.isFinite(n))))throw new Error('cloud_preview_invalid');return v as number[][]}
const positive=(n:unknown)=>{if(typeof n!=='number'||!Number.isFinite(n)||n<=0)throw new Error('cloud_preview_invalid');return n}
const orientation=(g:RoiValue,kind:unknown)=>kind==='box'?new Quaternion().setFromRotationMatrix(new Matrix4().set(...matrix(g.rotation,3).flatMap(r=>[...r,0]).concat([0,0,0,1]) as Parameters<Matrix4['set']>)):new Quaternion().setFromUnitVectors(new Vector3(0,1,0),vec(kind==='cylinder'?g.axis:g.normal))

/** 只显示有限几何；所有坐标先减 render_origin，显示缓冲统一计费。 */
export function createGeometryOverlay(scene:Object3D,camera:Camera,canvas:HTMLElement,origin:number[],policy:CloudRendererPolicy,schedule:()=>void,drag:(active:boolean)=>void,failed:(error:Error)=>void) {
  let root=new Group(),gizmo:TransformControls|null=null, releases:(()=>void)[]=[],input:GeometryOverlayInput|undefined,closed=false,arcRelease=()=>{},cancelArc:(()=>void)|undefined
  const physicalOrigin=new Vector3(...origin),targets=new Map<string,Object3D>(),updates=new Map<string,((roi:RoiValue)=>void)[]>()
  let hidden:ReadonlySet<string>=new Set(),roiGraph:RoiValue[]=[],cancelRoi:(()=>void)|undefined,roiControl:{control:TransformControls;target:Object3D;id:string}|undefined
  let restoredInput:GeometryOverlayInput|undefined
  let interactive=true
  const roiInstances:{id:string;target:Object3D;sections:RoiValue[]}[]=[]
  function resources(object:Object3D){const geometries=new Set<BufferGeometry>(),materials=new Set<Material>();object.traverse(o=>{const item=o as Mesh;if(item.geometry)geometries.add(item.geometry);if(item.material)for(const m of Array.isArray(item.material)?item.material:[item.material])materials.add(m)});return {geometries,materials}}
  function account(object:Object3D){const buffers=new Set<ArrayBufferLike>();for(const g of resources(object).geometries){for(const a of Object.values(g.attributes))buffers.add(a.array.buffer);if(g.index)buffers.add(g.index.array.buffer)}const bytes=[...buffers].reduce((s,b)=>s+b.byteLength,0);releases.push(reserveCpu(bytes,policy));releases.push(reserveGpu(bytes,policy))}
  function clear(){cancelArc=undefined;cancelRoi=undefined;roiControl=undefined;roiInstances.length=0;roiGraph=[];arcRelease();arcRelease=()=>{};drag(false);gizmo?.detach();gizmo?.dispose();gizmo=null;for(const g of resources(root).geometries)g.dispose();for(const m of resources(root).materials)m.dispose();root.removeFromParent();root.clear();targets.clear();updates.clear();for(const release of releases)release();releases=[];root=new Group()}
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
  function buildRois(rois:RoiValue[],selectedId?:string){
    if(roiGraphIssues(rois).length)throw new Error('cloud_preview_invalid')
    roiGraph=rois
    const byId=new Map(rois.map(r=>[String(r.roi_id),r])),referenced=new Set(rois.flatMap(roiDependencies)),seen=new Set<string>()
    const pending:{roi:RoiValue;sections:RoiValue[];release:()=>void}[]=[]
    function enqueue(roi:RoiValue,sections:RoiValue[]){
      const release=reserveCpu(256+sections.length*16,policy)
      pending.push({roi,sections,release})
    }
    try{
      for(const roi of rois)if(!referenced.has(String(roi.roi_id))||roi.roi_id===selectedId)enqueue(roi,[])
      while(pending.length){
        const item=pending.pop()!,{roi,sections}=item,id=String(roi.roi_id)
        try{
          const key=JSON.stringify([id,...sections.map(s=>String(s.roi_id)).sort()])
          if(seen.has(key))continue
          releases.push(reserveCpu(256+key.length*2,policy));seen.add(key)
          if(roi.kind==='union'){
            for(const child of roiDependencies(roi))enqueue(byId.get(child)!,sections)
          }else if(roi.kind==='section-band'){
            if(!targets.has(id)){const anchor=new Group();pose(roi,anchor);root.add(anchor);targets.set(id,anchor)}
            enqueue(byId.get(roiDependencies(roi)[0]!)!,[...sections,roi])
          }else{
            const shape=finiteMesh(roi,sections.length?0xc8558a:0xd18c00,sections.flatMap(sectionPlanes))
            roiInstances.push({id,target:shape.target,sections});shape.target.userData.roiId=id
            if(!sections.length)targets.set(id,shape.target)
            for(const section of sections){
              const sectionId=String(section.roi_id),list=updates.get(sectionId)??[]
              list.push(next=>{const clips=sections.map(s=>s.roi_id===next.roi_id?next:s).flatMap(sectionPlanes);shape.material.clippingPlanes=clips;(shape.edge.material as LineBasicMaterial).clippingPlanes=clips})
              updates.set(sectionId,list)
            }
          }
        }finally{item.release()}
      }
    }finally{for(const item of pending)item.release()}
  }
  /** 独立显示通道：不清空 root，不触碰测量或调试几何。 */
  function visibility(value:ReadonlySet<string>){
    if(closed)return
    hidden=new Set(value)
    if(input)input.hiddenRoiIds=hidden
    if(roiControl){
      const {control,target,id}=roiControl,visible=['visible','partial'].includes(roiVisibility(roiGraph,id,hidden))
      if(!visible){cancelRoi?.();control.detach();control.getHelper().visible=false}
      else {control.attach(target);control.getHelper().visible=interactive}
    }
    for(const instance of roiInstances)instance.target.visible=!hidden.has(instance.id)
    schedule()
  }
  /** 暂停保留几何；只有当前未结束的手势回到起点。 */
  function activity(value:boolean){
    if(closed||interactive===value)return
    if(!value){cancelArc?.();cancelRoi?.()}
    interactive=value
    if(gizmo){gizmo.enabled=value;gizmo.getHelper().visible=value&&(!roiControl||['visible','partial'].includes(roiVisibility(roiGraph,roiControl.id,hidden)))}
    drag(false)
  }
  function buildEvidence(payload:Record<string,unknown>){
    if(!payload.geometry)return
    const g=object(payload.geometry),spatial=object(payload.spatial)
    if(g.format_id!=='amvision.geometry-preview.v1'||g.observation_id!==payload.observation_id||g.frame_id!==spatial.frame_id||g.length_unit!==spatial.length_unit||!Array.isArray(g.planes)||g.planes.length>8192)throw new Error('cloud_preview_invalid')
    for(const raw of g.planes){const p=object(raw);if(!p.valid)continue;const plane=object(p.geometry),bounds=object(p.support_bounds),low=vec(bounds.min),high=vec(bounds.max),n=vec(plane.normal),offset=plane.offset;if(typeof offset!=='number'||!Number.isFinite(offset))throw new Error('cloud_preview_invalid')
      const center=low.clone().add(high).multiplyScalar(.5);center.addScaledVector(n,-n.dot(center)-offset)
      const q=new Quaternion().setFromUnitVectors(new Vector3(0,0,1),n),inv=q.clone().invert();let x=0,y=0
      for(let i=0;i<8;i++){const d=new Vector3(i&1?high.x:low.x,i&2?high.y:low.y,i&4?high.z:low.z).sub(center).applyQuaternion(inv);x=Math.max(x,Math.abs(d.x));y=Math.max(y,Math.abs(d.y))}
      const geometry=new BufferGeometry().setFromPoints([new Vector3(-x,-y,0),new Vector3(x,-y,0),new Vector3(x,-y,0),new Vector3(x,y,0),new Vector3(x,y,0),new Vector3(-x,y,0),new Vector3(-x,y,0),new Vector3(-x,-y,0)])
      const outline=new LineSegments(geometry,new LineBasicMaterial({color:p.feature_id===input?.selectedPlane?0xd18c00:0x287bb8}));outline.userData.plane=p.feature_id;outline.position.copy(center.sub(physicalOrigin));outline.quaternion.copy(q);root.add(outline);account(outline)
    }
    if(g.frame){const f=object(g.frame);if(f.state==='found'){const t=object(f.transform),m=new Matrix4().set(...matrix(t.matrix,4).flat() as Parameters<Matrix4['set']>);if(t.source_frame_id===spatial.frame_id)m.invert();else if(t.target_frame_id===spatial.frame_id)m.identity();else throw new Error('cloud_preview_invalid');const bounds=object(payload.bounds),length=vec(bounds.max).sub(vec(bounds.min)).length()*.25;const axes=new AxesHelper(length);axes.applyMatrix4(m);axes.position.sub(physicalOrigin);root.add(axes);account(axes)}}
  }
  function pointGeometry(points:Vector3[]){
    const local=points.map(p=>p.clone().sub(physicalOrigin)),geometry=new BufferGeometry().setFromPoints(local)
    const position=geometry.getAttribute('position')
    for(let i=0;i<local.length;i++)for(let axis=0;axis<3;axis++)if(!Number.isFinite(position.getComponent(i,axis))||Math.abs(position.getComponent(i,axis)-local[i]!.getComponent(axis))>policy.max_position_error){geometry.dispose();throw new Error('cloud_position_precision')}
    return geometry
  }
  function lines(points:Vector3[],color:number,dashed=false){
    const geometry=pointGeometry(points)
    const size=dashed?Math.max(points[0]!.distanceTo(points[1]!)/20,Number.EPSILON):0
    const line=new LineSegments(geometry,dashed?new LineDashedMaterial({color,depthTest:false,dashSize:size,gapSize:size}):new LineBasicMaterial({color,depthTest:false}));root.add(line);if(dashed)line.computeLineDistances();account(line);return line
  }
  function buildCurves(next:GeometryOverlayInput){
    const curves=curveItems(next.payload)
    for(const stroke of curveStrokes(curves,policy)){
      const selected=stroke.featureId===next.selectedCurve&&(!next.selectedSegment||stroke.segmentId===next.selectedSegment||stroke.groupId===next.selectedSegment)
      const color=stroke.outlier?0xc33b3b:selected?0xd18c00:stroke.estimate==='edge'?0xc8558a:stroke.estimate==='center'?0x287bb8:stroke.fitted?0xc8558a:0x208c77
      const line=stroke.markers?new Points(pointGeometry(stroke.points.map(vec)),new PointsMaterial({color,size:4,sizeAttenuation:false,depthTest:false})):lines(stroke.points.map(vec),color,stroke.estimate==='edge'||stroke.fitted)
      if(stroke.markers){root.add(line);account(line)}
      line.userData.curve={featureId:stroke.featureId,segmentId:stroke.segmentId,groupId:stroke.groupId}
    }
    const selected=curves.find(c=>c.feature_id===next.selectedCurve),mode=next.curveColorMode??'support'
    if(selected){const scale=curveColorScale(selected,mode),values=curveColorValues(selected,mode);if(scale&&values){
      for(const segment of selected.topology?.segments??[]){
        const points=selected.points.slice(segment.start,segment.start+segment.count),geometry=pointGeometry(points.map(vec)),colors=new Float32Array(points.length*3)
        const markers=new Points(geometry,new PointsMaterial({size:6,sizeAttenuation:false,vertexColors:true,depthTest:false}));root.add(markers)
        for(let i=0;i<points.length;i++)colors.set(curveColor(values[segment.start+i]!,scale.min,scale.max),i*3)
        geometry.setAttribute('color',new BufferAttribute(colors,3));markers.userData.curve={featureId:selected.feature_id,segmentId:segment.segment_id,groupId:segment.group_id,start:segment.start};account(markers)
      }
    }}
    if(selected&&next.selectedCurvePoint!=null){const p=selected.points[next.selectedCurvePoint];if(p){const marker=new Points(pointGeometry([vec(p)]),new PointsMaterial({size:11,color:0xffb800,sizeAttenuation:false,depthTest:false}));root.add(marker);account(marker)}}
  }
  function buildMeasurements(next:GeometryOverlayInput){
    for(const item of measurementItems(next.payload)){
      const selected=item.item_id===next.selectedMeasurement,color=selected?0xd18c00:0x508691
      const dimension=(points:Vector3[],dashed=false)=>{const line=lines(points,color,dashed);line.userData.measurement=item.item_id;return line}
      if(item.valid&&item.geometry&&['directional-distance','edge-pair-distance'].includes(String(item.geometry.kind))){
        const endpoints=item.geometry.endpoints
        if(!Array.isArray(endpoints)||endpoints.length!==2)throw new Error('cloud_preview_invalid')
        dimension(endpoints.map(vec))
      }
      if(item.valid&&item.geometry?.kind==='projected-extents'){
        const p=(item.geometry.corners as unknown[]).map(vec)
        if(selected)lines([p[0]!,p[1]!,p[1]!,p[2]!,p[2]!,p[3]!,p[3]!,p[0]!],0x508691,item.support.some(s=>s.sample_origin==='estimated'))
        dimension(['u','length'].includes(item.component??'')?[p[0]!,p[1]!]:[p[0]!,p[3]!])
      }
      if(item.valid&&item.geometry?.kind==='circle-dimensions'){
        if(item.component==='diameter')dimension((item.geometry.diameter_endpoints as unknown[]).map(vec))
        else if(selected){const circle=object(item.geometry.circle),center=vec(circle.center),size=positive(circle.radius)*.05,points:Vector3[]=[];for(let i=0;i<3;i++){const delta=new Vector3().setComponent(i,size);points.push(center.clone().sub(delta),center.clone().add(delta))}lines(points,color)}
      }
      if(!selected)continue
      const extension=referenceExtension(item.support)
      if(extension?.datum_point&&extension.projected_support_point){
        lines([vec(extension.projected_support_point),vec(extension.datum_point)],extension.state==='used'?0xc8558a:0xc33b3b,true)
      }
      for(const side of item.support){
        const coverage=side.coverage?object(side.coverage):null
        if(coverage?.triangle){const raw=coverage.triangle;if(!Array.isArray(raw)||raw.length!==3)throw new Error('cloud_preview_invalid');const p=raw.map(vec);lines([p[0]!,p[1]!,p[1]!,p[2]!,p[2]!,p[0]!],side.role==='reference'?0x287bb8:0x339653)}
        if(side.statistic&&side.bounds){const b=object(side.bounds),low=vec(b.min),high=vec(b.max),corners=Array.from({length:8},(_,i)=>new Vector3(i&1?high.x:low.x,i&2?high.y:low.y,i&4?high.z:low.z)),points:Vector3[]=[];for(let i=0;i<8;i++)for(const bit of [1,2,4])if(!(i&bit))points.push(corners[i]!,corners[i|bit]!);lines(points,side.role==='reference'?0x287bb8:0x339653)}
      }
    }
    if(next.candidate){const p=vec(next.candidate),bounds=object(next.payload.bounds),size=vec(bounds.max).sub(vec(bounds.min)).length()*.01,points:Vector3[]=[];for(let i=0;i<3;i++){const delta=new Vector3().setComponent(i,size);points.push(p.clone().sub(delta),p.clone().add(delta))}lines(points,0xe1a100)}
  }
  function buildArc(edit:ArcEdit){
    const target=new Group(),arcRoot=new Group();root.add(arcRoot,target);arcRoot.userData.arc=true
    target.quaternion.setFromRotationMatrix(new Matrix4().set(...edit.evaluation.rotation.flatMap(r=>[...r,0]).concat([0,0,0,1]) as Parameters<Matrix4['set']>))
    let current=edit,gesture=arcGesture(edit),active=false,cancelling=false
    const draw=(value:ArcValues)=>{
      arcRelease();arcRelease=()=>{}
      for(const g of resources(arcRoot).geometries)g.dispose();for(const m of resources(arcRoot).materials)m.dispose();arcRoot.clear()
      current={...edit,values:value,displayRadius:value.radius_range?.[1]??edit.displayRadius}
      const radius=current.displayRadius,step=2*Math.acos(Math.max(-1,1-policy.max_position_error/(2*radius))),count=Math.max(1,Math.ceil(value.sweep/Math.min(Math.PI,step))),radii=value.radius_range??[radius]
      if(!Number.isFinite(count)||(count*radii.length+2)*2>policy.max_points*8)throw new Error('cloud_preview_capacity')
      const point=(r:number,a:number)=>vec(arcWorld(current,[value.center[0]!+r*Math.cos(a),value.center[1]!+r*Math.sin(a)]))
      const points:Vector3[]=[]
      for(const r of radii)for(let i=0;i<count;i++)points.push(point(r,value.start_angle+value.sweep*i/count),point(r,value.start_angle+value.sweep*(i+1)/count))
      for(const a of [value.start_angle,value.start_angle+value.sweep])points.push(point(value.radius_range?.[0]??0,a),point(radius,a))
      const geometry=pointGeometry(points),line=new LineSegments(geometry,new LineBasicMaterial({color:0xd18c00,depthTest:false}));arcRoot.add(line)
      const bytes=geometry.getAttribute('position').array.byteLength,releaseCpu=reserveCpu(bytes,policy)
      try{const releaseGpu=reserveGpu(bytes,policy);arcRelease=()=>{releaseGpu();releaseCpu()}}catch(error){releaseCpu();throw error}
      target.position.copy(vec(arcWorld(current,arcHandleUV(current)))).sub(physicalOrigin)
    }
    draw(edit.values)
    const control=new TransformControls(camera,canvas);gizmo=control;control.setMode('translate');control.setSpace('local');control.showZ=false;control.attach(target);root.add(control.getHelper());account(control.getHelper())
    const live=()=>!closed&&interactive&&gizmo===control&&input?.arc?.key===edit.key
    const restore=()=>{
      if(!live()||!active)return
      active=false;cancelling=true;draw(edit.values)
      restoredInput={...input!,arc:{...input!.arc!,values:edit.values}}
      input?.arcChanged?.(edit.key,edit.values);control.dragging=false;drag(false);cancelling=false;schedule()
    }
    cancelArc=restore
    control.addEventListener('change',schedule)
    control.addEventListener('mouseDown',()=>{if(live()){active=true;gesture=arcGesture(current)}})
    control.addEventListener('dragging-changed',event=>{
      if(!live()||cancelling)return
      drag(event.value===true)
      if(event.value===false){active=false;queueMicrotask(()=>{if(live()&&input)try{update(input)}catch(error){failed(error as Error)}})}
    })
    control.addEventListener('objectChange',()=>{
      if(!live())return
      try{const value=gesture(arcUV(edit,target.position.clone().add(physicalOrigin).toArray()));if(value){draw(value);input?.arcChanged?.(edit.key,value)}else target.position.copy(vec(arcWorld(current,arcHandleUV(current)))).sub(physicalOrigin);schedule()}catch(error){failed(error as Error)}
    })
  }
  function update(next:GeometryOverlayInput){
    if(closed)return
    const same=input?.payload===next.payload&&input?.arc?.key===next.arc?.key&&input?.selectedId===next.selectedId&&input?.mode===next.mode&&input?.roiScope===next.roiScope
    // 取消手势已经恢复对象；父表单回传同一恢复值时不重建其他证据。
    if(restoredInput&&same){
      const restored=restoredInput;restoredInput=undefined
      const keys=['payload','selectedId','mode','roiScope','selectedMeasurement','selectedPlane','candidate','selectedCurve','selectedSegment','curveColorMode','selectedCurvePoint','debug','debugLayers','debugSelection'] as const
      if(keys.every(key=>restored[key]===next[key])&&JSON.stringify(restored.arc)===JSON.stringify(next.arc)&&JSON.stringify(restored.rois)===JSON.stringify(next.rois)){input=next;roiGraph=next.rois??[];visibility(next.hiddenRoiIds??hidden);return}
    }
    restoredInput=undefined
    input=next
    if(gizmo?.dragging&&same)return
    clear()
    try {
      scene.add(root);buildEvidence(next.payload);buildMeasurements(next);buildCurves(next)
      if(next.debug&&next.debugLayers){
        const layer=new Group(),owned:(()=>void)[]=[]
        try{buildDebugOverlay(layer,next.debug,next.debugLayers,next.debugSelection??null,origin,policy,r=>owned.push(r));root.add(layer);releases.push(...owned)}
        catch(error){for(const g of resources(layer).geometries)g.dispose();for(const m of resources(layer).materials)m.dispose();layer.clear();for(const release of owned)release();next.debugFailed?.(error as Error)}
      }
      const spatial=object(next.payload.spatial),attached=next.payload.geometry?object(next.payload.geometry).rois:[],rois=next.rois??(Array.isArray(attached)?attached.map(object):[])
      if(rois.length>8192)throw new Error('cloud_preview_invalid')
      for(const roi of rois)if(roi.frame_id!==spatial.frame_id||roi.length_unit!==spatial.length_unit)throw new Error('cloud_geometry_space')
      buildRois(rois,next.selectedId)
      const target=targets.get(next.selectedId??'')
      const original=rois.find(r=>r.roi_id===next.selectedId)
      if(next.arc&&next.arcChanged)buildArc(next.arc)
      else if(target&&next.changed&&!(next.mode==='scale'&&original?.kind==='section-band')){gizmo=new TransformControls(camera,canvas);gizmo.setMode(next.mode??'translate');if(next.mode==='scale'){gizmo.setSpace('local');if(original?.kind==='cylinder')gizmo.showZ=false}gizmo.attach(target);const helper=gizmo.getHelper();root.add(helper);account(helper)
        const control=gizmo,id=next.selectedId!,scope=next.roiScope,payload=next.payload
        let start:RoiValue|undefined,cancelling=false
        const live=()=>!closed&&interactive&&gizmo===control&&input?.payload===payload&&input?.roiScope===scope&&input?.selectedId===id
        roiControl={control,target,id}
        cancelRoi=()=>{
          if(!live()||!start)return
          const restored=start;start=undefined;cancelling=true
          pose(restored,target);target.scale.set(1,1,1)
          for(const update of updates.get(id)??[])update(restored)
          restoredInput={...input!,rois:input!.rois?.map(roi=>roi.roi_id===id?restored:roi)}
          input?.changed?.(restored);control.dragging=false;drag(false);cancelling=false;schedule()
        }
        control.addEventListener('mouseDown',()=>{if(live()){const roi=input?.rois?.find(r=>r.roi_id===id);if(roi)start=JSON.parse(JSON.stringify(roi)) as RoiValue}})
        control.addEventListener('change',()=>{if(live())schedule()})
        control.addEventListener('dragging-changed',e=>{
          if(!live()||cancelling)return
          drag(e.value===true)
          // 等本次控件事件完成，再用最新草稿重建依赖边界；卸载后不得重新分配。
          if(e.value===false){start=undefined;queueMicrotask(()=>{
            if(!live()||!input)return
            try{update(input)}catch(error){failed(error as Error)}
          })}
        })
        control.addEventListener('objectChange',()=>{if(!live()||!control.object)return;const roi=input?.rois?.find(r=>r.roi_id===id);if(!roi)return;const g={...object(roi.geometry)},position=target.position.clone().add(physicalOrigin).toArray(),q=target.quaternion
          if(next.mode==='scale'&&original){
            const s=target.scale,base=object(original.geometry)
            if(![s.x,s.y,s.z].every(v=>Number.isFinite(v)&&v>0)){s.set(1,1,1);schedule();return}
            if(roi.kind==='box')g.size=vec(base.size).multiply(s).toArray()
            else if(roi.kind==='cylinder'){s.z=s.x;g.radius=positive(base.radius)*s.x;g.length=positive(base.length)*s.y}
            if((Array.isArray(g.size)&&g.size.some(v=>!Number.isFinite(v)||v<=0))||roi.kind==='cylinder'&&(!Number.isFinite(g.radius)||!Number.isFinite(g.length))){s.set(1,1,1);schedule();return}
          }
          if(roi.kind==='section-band'){g.origin=position;g.normal=new Vector3(0,1,0).applyQuaternion(q).toArray()}else {g.center=position;if(roi.kind==='cylinder')g.axis=new Vector3(0,1,0).applyQuaternion(q).toArray();else {const m=new Matrix4().makeRotationFromQuaternion(q).elements;g.rotation=[[m[0],m[4],m[8]],[m[1],m[5],m[9]],[m[2],m[6],m[10]]]}}
          const changed={...roi,geometry:g};for(const update of updates.get(String(roi.roi_id))??[])update(changed);input?.changed?.(changed);schedule()
        })
      }
      visibility(next.hiddenRoiIds??new Set())
      if(gizmo){gizmo.enabled=interactive;if(!interactive)gizmo.getHelper().visible=false}
    }catch(error){clear();throw error}
  }
  function keydown(event:KeyboardEvent){if(event.key==='Escape'&&gizmo?.dragging&&(cancelArc||cancelRoi)){event.preventDefault();event.stopPropagation();(cancelArc??cancelRoi)?.()}}
  canvas.ownerDocument.addEventListener('keydown',keydown,true)
  return {update,visibility,activity,focus(kind:GeometryFocus){
    if(closed||!input)return null
    const bounds=new Box3()
    if(kind==='roi'){
      const id=input.selectedId??'',leaves=new Set(roiLeaves(roiGraph,id)),section=roiGraph.find(r=>r.roi_id===id)?.kind==='section-band'
      for(const instance of roiInstances)if(leaves.has(instance.id)&&instance.target.visible&&(!section||instance.sections.some(s=>s.roi_id===id)))expandRoiDisplayBounds(bounds,instance.target)
    }
    else root.traverse(o=>{const c=o.userData.curve;if(kind==='debug'&&o.userData.debug?.id===input?.debug?.id||kind==='arc'&&o.userData.arc||kind==='plane'&&!!input?.selectedPlane&&o.userData.plane===input.selectedPlane||kind==='measurement'&&!!input?.selectedMeasurement&&o.userData.measurement===input.selectedMeasurement||kind==='feature'&&!!input?.selectedCurve&&c?.featureId===input.selectedCurve&&(!input.selectedSegment||c.segmentId===input.selectedSegment||c.groupId===input.selectedSegment))bounds.expandByObject(o)})
    return bounds.isEmpty()?null:{center:bounds.getCenter(new Vector3()),radius:Math.max(bounds.getSize(new Vector3()).length()/2,1e-6)}
  },pick(ray:Raycaster){if(closed||!input)return false;const hit=ray.intersectObject(root,true).find(h=>h.object.userData.debug&&input?.debugSelected||h.object.userData.curve&&input?.curveSelected||h.object.userData.measurement&&input?.measurementSelected);if(!hit)return false;const d=hit.object.userData.debug,c=hit.object.userData.curve;if(d){const index=d.kind==='cell'?Math.floor((hit.faceIndex??-2)/2):d.index??hit.index;if(Number.isSafeInteger(index)&&index>=0)input.debugSelected?.({kind:d.kind,index})}else if(c){if(Number.isSafeInteger(c.start)&&hit.index!==undefined&&input.curvePointSelected)input.curvePointSelected(c.featureId,c.segmentId,c.start+hit.index);else input.curveSelected?.(c.featureId,c.segmentId)}else input.measurementSelected?.(hit.object.userData.measurement);return true},camera(value:Camera){camera=value;if(gizmo)gizmo.camera=value},dragging:()=>!!gizmo?.dragging,dispose(){if(!closed){closed=true;canvas.ownerDocument.removeEventListener('keydown',keydown,true);clear()}}}
}
