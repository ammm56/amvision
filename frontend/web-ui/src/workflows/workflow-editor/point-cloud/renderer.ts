import { AxesHelper, Box3, Frustum, BufferAttribute, BufferGeometry, Color, Matrix4, MOUSE, OrthographicCamera, PerspectiveCamera, Points, PointsMaterial, Quaternion, Raycaster, Scene, Vector2, Vector3, WebGLRenderer } from 'three'
import { OrbitControls } from 'three/addons/controls/OrbitControls.js'
import { createDetailLayer } from './detail-layer'
import {createResampleLayer} from './resample-layer'
import {createNormalLayer} from './normal-layer'
import type { DetailBounds } from './asset-details'
import type { CloudRendererPolicy } from '../services/measurement-resource.service'
import { reserveCpu, reserveGpu, type CloudDisplayData } from './preview-data'
import {fillPlaneColors,type PlaneColors} from './plane-colors'
import {createGeometryOverlay,type GeometryOverlayInput,type GeometryFocus} from './geometry-overlay'
import {fillCoordinateColors,linearizeDisplayColors, type CloudColorMode, type CoordinateRange, scaleBar} from './view-presentation'
export type CloudViewAxis = 'iso' | 'x' | '-x' | 'y' | '-y' | 'z' | '-z'
export type CloudViewState = CloudViewAxis | 'free'

const directions:Record<CloudViewAxis,[number,number,number]>={iso:[1,-1,.8],x:[1,0,0],'-x':[-1,0,0],y:[0,-1,0],'-y':[0,1,0],z:[0,0,1],'-z':[0,0,-1]}
const presetRotations = (Object.keys(directions) as CloudViewAxis[]).map(axis => {
  const up = axis === 'z' || axis === '-z' ? new Vector3(0, 1, 0) : new Vector3(0, 0, 1)
  const rotation = new Quaternion().setFromRotationMatrix(new Matrix4().lookAt(new Vector3(...directions[axis]), new Vector3(), up))
  return {axis, rotation}
})

/** 一个激活视口一个 renderer；无常驻动画，资产细节请求由外部控制器管理。 */
export function createCloudRenderer(host: HTMLElement, data: CloudDisplayData, policy: CloudRendererPolicy,
  picked: (index: number) => void, failed: (error: Error) => void, viewChanged: (view: CloudViewState) => void, initialActive = true,
  presentation?: {range:CoordinateRange|null; coordinateColor:boolean; scaleChanged:(scale:ReturnType<typeof scaleBar>)=>void}) {
  const rect = host.getBoundingClientRect()
  function dimensions(width: number, height: number) {
    const w = Math.max(1, Math.floor(width)), h = Math.max(1, Math.floor(height))
    if (w * h > policy.max_canvas_pixels) throw new Error('cloud_canvas_capacity')
    return [w, h] as const
  }
  let [width, height] = dimensions(rect.width, rect.height)
  let releaseGpu = reserveGpu(data.positions.byteLength + data.colors.byteLength + width * height * 8 + 144, policy)
  let renderer: WebGLRenderer | null = null
  let releaseColor = () => {}
  let observer: ResizeObserver | null = null
  let controls: OrbitControls | null = null
  let overlay: ReturnType<typeof createGeometryOverlay> | null = null
  let frame = 0, closed = false
  let active = initialActive, measurable = rect.width > 0 && rect.height > 0
  let panEnabled = false
  const scene = new Scene(), geometry = new BufferGeometry(), material = new PointsMaterial({ size: 2, sizeAttenuation: false, vertexColors: true })
  const detailLayer = createDetailLayer(scene, material, policy)
  const resampleLayer = createResampleLayer(scene,data.origin,policy,schedule)
  const heightLayer = createResampleLayer(scene,data.origin,policy,schedule)
  const normalLayer = createNormalLayer(scene,data,policy,schedule)
  let detailChanged: (() => void) | null = null
  let detailPicked: ((point: ReturnType<CloudDisplayData['point']>) => void) | null = null
  let axes: AxesHelper | null = null
  let camera: PerspectiveCamera | OrthographicCamera
  let reportedView: CloudViewState | undefined
  let radius = 1,viewRadius=1,baseRadius=1,comparisonRadius=0,comparisonCount=0,detailCount=0
  let pointDown: {x: number; y: number} | null = null
  function render() {
    if (!closed && active && measurable && renderer) {
      renderer.render(scene, camera)
      presentation?.scaleChanged(camera instanceof OrthographicCamera ? scaleBar((camera.right-camera.left)/camera.zoom,width) : null)
    }
  }
  function schedule() { if (!closed && active && measurable && !frame) frame = requestAnimationFrame(() => { frame = 0; render() }) }
  function publishView() {
    if (closed) return
    // 仅容纳 OrbitControls 在极轴处的浮点偏移，不是计量方向容差。
    const view = presetRotations.find(preset => 1 - Math.abs(camera.quaternion.dot(preset.rotation)) <= 1e-12)?.axis ?? 'free'
    if (view !== reportedView) { reportedView = view; viewChanged(view) }
  }
  function controlsChanged() { publishView(); detailChanged?.(); schedule() }
  function releaseControls() {
    controls?.removeEventListener('change', controlsChanged)
    controls?.dispose(); controls = null
  }
  function dispose() {
    if (closed) return
    closed = true
    cancelAnimationFrame(frame); observer?.disconnect(); overlay?.dispose(); releaseControls()
    if (renderer) {
      renderer.domElement.removeEventListener('webglcontextlost', lost)
      renderer.domElement.removeEventListener('pointerdown', down)
      renderer.domElement.removeEventListener('pointerup', pick)
      renderer.dispose(); renderer.forceContextLoss(); renderer.domElement.remove(); renderer = null
    }
    detailLayer.clear();resampleLayer.dispose();heightLayer.dispose();normalLayer.dispose(); geometry.dispose(); material.dispose(); axes?.dispose(); scene.clear(); releaseGpu();releaseColor()
  }
  function lost(event: Event) { event.preventDefault(); dispose(); failed(new Error('cloud_context_lost')) }
  function down(event: PointerEvent) { if(active&&measurable)pointDown = {x: event.clientX, y: event.clientY} }
  function pick(event: PointerEvent) {
    if (!active || !measurable || !renderer || overlay?.dragging() || !pointDown || Math.hypot(event.clientX - pointDown.x, event.clientY - pointDown.y) > 3) return
    const r = renderer.domElement.getBoundingClientRect(), ray = new Raycaster()
    ray.params.Points!.threshold = viewRadius * .015
    ray.params.Line!.threshold = viewRadius * .015
    ray.setFromCamera(new Vector2((event.clientX - r.left) / r.width * 2 - 1, -(event.clientY - r.top) / r.height * 2 + 1), camera)
    if(overlay?.pick(ray))return
    if (!points.visible) {
      const hit = ray.intersectObjects(detailLayer.objects())[0]
      if (hit?.index !== undefined) { const point = detailLayer.point(hit.object, hit.index); if (point) detailPicked?.(point) }
      return
    }
    const hit = ray.intersectObject(points)[0]
    if (hit?.index !== undefined) picked(hit.index)
  }
  function bindControls() {
    releaseControls()
    controls = new OrbitControls(camera, renderer!.domElement)
    controls.enableDamping = false
    controls.enabled = active && measurable
    controls.zoomToCursor = true
    controls.mouseButtons.LEFT = panEnabled ? MOUSE.PAN : MOUSE.ROTATE
    controls.addEventListener('change', controlsChanged)
  }
  function fit(axis: CloudViewAxis = 'z') {
    if (closed) return
    viewRadius=radius
    const direction = directions[axis],top=axis==='z'||axis==='-z'
    camera.up.set(0, top ? 1 : 0, top ? 0 : 1)
    camera.position.set(...direction as [number, number, number]).normalize().multiplyScalar(radius * 3 / Math.min(1, width / height))
    camera.near = radius / 1000; camera.far = radius * 10000
    if (camera instanceof OrthographicCamera) {
      const y = radius * 1.15 / Math.min(1, width / height), x = y * width / height
      camera.left = -x; camera.right = x; camera.top = y; camera.bottom = -y; camera.zoom = 1
    } else camera.aspect = width / height
    camera.updateProjectionMatrix()
    // OrbitControls 在构造时冻结 up 的变换，换轴必须同步重建控制器。
    bindControls(); controls!.target.set(0, 0, 0); controls!.update(); publishView(); schedule()
  }
  function focusBounds(bounds:{center:Vector3;radius:number}|null|undefined){
    if(closed||!bounds)return
    viewRadius=bounds.radius
    const direction=camera.position.clone().sub(controls!.target).normalize()
    const distance=viewRadius*3/Math.min(1,width/height)
    camera.position.copy(bounds.center).addScaledVector(direction,distance)
    camera.near=Math.min(radius,viewRadius)/1000;camera.far=Math.max(radius,viewRadius)*10000
    camera.zoom=1
    if(camera instanceof OrthographicCamera){const y=viewRadius*1.15/Math.min(1,width/height);camera.left=-y*width/height;camera.right=y*width/height;camera.top=y;camera.bottom=-y}
    controls!.target.copy(bounds.center);camera.updateProjectionMatrix();controls!.update();schedule()
  }
  const points = new Points(geometry, material)
  function syncInteraction(){overlay?.activity(active&&measurable);if(controls)controls.enabled=active&&measurable&&!overlay?.dragging()}
  function resize(wide:number,tall:number){
    if(closed||!renderer)return
    measurable=wide>0&&tall>0
    syncInteraction()
    if(!active||!measurable){cancelAnimationFrame(frame);frame=0;pointDown=null;return}
    const [w,h]=dimensions(wide,tall)
    const changed=w!==width||h!==height
    if(changed){
      // 新画布沿原预算计量；失败时由调用方完整关闭。
      releaseGpu();releaseGpu=()=>{}
      releaseGpu=reserveGpu(data.positions.byteLength+data.colors.byteLength+w*h*8+144,policy)
      width=w;height=h;renderer.setSize(w,h)
      if(camera instanceof OrthographicCamera){const half=(camera.top-camera.bottom)/2;camera.left=-half*w/h;camera.right=half*w/h}
      else camera.aspect=w/h
      camera.updateProjectionMatrix()
    }
    if(changed)detailChanged?.(); schedule()
  }
  try {
    releaseColor=reserveCpu(data.colors.byteLength,policy)
    geometry.setAttribute('position', new BufferAttribute(data.positions, 3)); geometry.setAttribute('color', new BufferAttribute(data.colors.slice(), 3))
    if(presentation?.coordinateColor&&presentation.range){fillCoordinateColors(geometry.getAttribute('color').array as Float32Array,data.positions,data.origin[2]!,presentation.range);detailLayer.colors(presentation.range)}
    linearizeDisplayColors(geometry.getAttribute('color').array as Float32Array)
    geometry.computeBoundingSphere(); radius = Math.max(geometry.boundingSphere?.radius ?? 0, 1e-6);baseRadius=radius
    renderer = new WebGLRenderer({ antialias: false, alpha: true, powerPreference: 'low-power' })
    scene.background = new Color(0x202326)
    renderer.localClippingEnabled = true
    renderer.setPixelRatio(1); renderer.setSize(width, height)
    renderer.domElement.setAttribute('aria-label', '3D point cloud')
    renderer.domElement.addEventListener('webglcontextlost', lost)
    renderer.domElement.addEventListener('pointerdown', down); renderer.domElement.addEventListener('pointerup', pick)
    host.append(renderer.domElement)
    axes = new AxesHelper(radius * .12); axes.visible=false; scene.add(points, axes)
    camera = new OrthographicCamera(-1,1,1,-1)
    fit()
    overlay = createGeometryOverlay(scene,camera,renderer.domElement,data.origin,policy,schedule,dragging=>{if(controls)controls.enabled=active&&measurable&&!dragging},error=>{dispose();failed(error)})
    syncInteraction()
    observer = new ResizeObserver(entries => {
      try {
        const box = entries[0]?.contentRect
        if (!box || closed || !renderer) return
        resize(box.width,box.height)
      } catch (error) { dispose(); failed(error as Error) }
    })
    observer.observe(host)
    return {
      dispose, fit,
      comparison(value:CloudDisplayData|null){
        if(closed)return
        if(value&&value.count+data.count+detailCount>policy.max_points)throw new Error('cloud_preview_capacity')
        resampleLayer.comparison(value);comparisonCount=value?.count??0;comparisonRadius=0
        if(value)for(let i=0;i<value.count;i++)comparisonRadius=Math.max(comparisonRadius,Math.hypot(...[0,1,2].map(c=>value.positions[i*3+c]!+value.origin[c]!-data.origin[c]!)))
        radius=Math.max(baseRadius,comparisonRadius)
      },
      voxelCell:resampleLayer.cell,
      heightCell:heightLayer.cell,
      normals:normalLayer.update,
      detailEvents(changed: (() => void) | null, picked: ((point: ReturnType<CloudDisplayData['point']>) => void) | null) { detailChanged = changed; detailPicked = picked },
      detailVisible(bounds: DetailBounds) {
        camera.updateMatrixWorld()
        const frustum = new Frustum().setFromProjectionMatrix(new Matrix4().multiplyMatrices(camera.projectionMatrix, camera.matrixWorldInverse))
        const local = (value: number[]) => new Vector3(value[0]! - data.origin[0]!, value[1]! - data.origin[1]!, value[2]! - data.origin[2]!)
        return frustum.intersectsBox(new Box3(local(bounds.min), local(bounds.max)))
      },
      detailAdd(value:CloudDisplayData){if(value.count+detailCount+data.count+comparisonCount>policy.max_points)throw new Error('cloud_preview_capacity');detailLayer.add(value);detailCount+=value.count},
      detailClear() { detailLayer.clear();detailCount=0; points.visible = true; schedule() },
      detailComplete() { detailLayer.visible(true); points.visible = false; schedule() },
      detailBounds(bounds: DetailBounds) {
        baseRadius = Math.max(...[bounds.min, bounds.max].map(v => Math.hypot(...v.map((x, i) => x - data.origin[i]!))), 1e-6);radius=Math.max(baseRadius,comparisonRadius)
      },
      activity(value:boolean){
        if(closed)return
        try{active=value;pointDown=null;detailChanged?.();const box=host.getBoundingClientRect();resize(box.width,box.height)}catch(error){dispose();failed(error as Error)}
      },
      focus(kind:GeometryFocus){focusBounds(overlay?.focus(kind))},
      focusVoxel(corners:number[][]){
        if(corners.length!==8||corners.some(v=>v.length!==3||v.some(n=>!Number.isFinite(n))))throw new Error('cloud_preview_invalid')
        const box=new Box3().setFromPoints(corners.map(v=>new Vector3(...v as [number,number,number]).sub(new Vector3(...data.origin as [number,number,number]))))
        focusBounds({center:box.getCenter(new Vector3()),radius:Math.max(box.getSize(new Vector3()).length()/2,1e-6)})
      },
      colors(samples:PlaneColors|null,mode:CloudColorMode,range?:CoordinateRange|null){
        if(closed)return
        const attribute=geometry.getAttribute('color') as BufferAttribute
        if(mode==='coordinate-z'){
          if(!range)throw new Error('cloud_preview_invalid')
          fillCoordinateColors(attribute.array as Float32Array,data.positions,data.origin[2]!,range)
        }else fillPlaneColors(attribute.array as Float32Array,data.colors,samples,mode)
        linearizeDisplayColors(attribute.array as Float32Array)
        detailLayer.colors(mode === 'coordinate-z' ? range ?? null : null)
        attribute.needsUpdate=true;schedule()
      },
      evidenceVisibility(visible:boolean){overlay?.evidenceVisibility(visible)},
      axesVisible(visible:boolean){if(axes){axes.visible=visible;schedule()}},
      geometry(input:GeometryOverlayInput) { try { overlay?.update(input) } catch(error) { dispose(); failed(error as Error) } },
      roiVisibility(hidden:ReadonlySet<string>) { try { overlay?.visibility(hidden) } catch(error) { dispose(); failed(error as Error) } },
      projection(orthographic: boolean) {
        if(closed||(camera instanceof OrthographicCamera)===orthographic)return
        const old=camera,target=controls!.target.clone(),distance=old.position.distanceTo(target)
        const half=old instanceof OrthographicCamera?(old.top-old.bottom)/(2*old.zoom):distance*Math.tan(old.fov*Math.PI/360)/old.zoom
        camera = orthographic ? new OrthographicCamera(-half*width/height,half*width/height,half,-half,old.near,old.far) : new PerspectiveCamera(45, width / height,old.near,old.far)
        camera.up.copy(old.up);camera.position.copy(old.position);camera.quaternion.copy(old.quaternion)
        if(camera instanceof PerspectiveCamera)camera.position.copy(old.position).sub(target).normalize().multiplyScalar(half/Math.tan(camera.fov*Math.PI/360)).add(target)
        overlay?.camera(camera)
        bindControls();controls!.target.copy(target);controls!.update();camera.updateProjectionMatrix();publishView();schedule()
      },
      zoom(inward:boolean){if(closed)return;if(inward)controls!.dollyIn(.8);else controls!.dollyOut(.8);controls!.update();schedule()},
      pan(enabled: boolean) { panEnabled = enabled; controls!.mouseButtons.LEFT = enabled ? MOUSE.PAN : MOUSE.ROTATE },
      pointSize(size: number) { material.size = size; schedule() },
    }
  } catch (error) { dispose(); throw error }
}
