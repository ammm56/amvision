import { AxesHelper, BufferAttribute, BufferGeometry, Matrix4, MOUSE, OrthographicCamera, PerspectiveCamera, Points, PointsMaterial, Quaternion, Raycaster, Scene, Vector2, Vector3, WebGLRenderer } from 'three'
import { OrbitControls } from 'three/addons/controls/OrbitControls.js'
import type { CloudRendererPolicy } from '../services/measurement-resource.service'
import { reserveCpu, reserveGpu, type CloudDisplayData } from './preview-data'
import {fillPlaneColors,type PlaneColors} from './plane-colors'
import {createGeometryOverlay,type GeometryOverlayInput} from './geometry-overlay'
export type CloudViewAxis = 'iso' | 'x' | '-x' | 'y' | '-y' | 'z' | '-z'
export type CloudViewState = CloudViewAxis | 'free'

const directions:Record<CloudViewAxis,[number,number,number]>={iso:[1,-1,.8],x:[1,0,0],'-x':[-1,0,0],y:[0,-1,0],'-y':[0,1,0],z:[0,0,1],'-z':[0,0,-1]}
const presetRotations = (Object.keys(directions) as CloudViewAxis[]).map(axis => {
  const up = axis === 'z' || axis === '-z' ? new Vector3(0, 1, 0) : new Vector3(0, 0, 1)
  const rotation = new Quaternion().setFromRotationMatrix(new Matrix4().lookAt(new Vector3(...directions[axis]), new Vector3(), up))
  return {axis, rotation}
})

/** 一个激活的视口一个 renderer；没有常驻动画、后台重算或原始点云请求。 */
export function createCloudRenderer(host: HTMLElement, data: CloudDisplayData, policy: CloudRendererPolicy,
  picked: (index: number) => void, failed: (error: Error) => void, viewChanged: (view: CloudViewState) => void) {
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
  let panEnabled = false
  const scene = new Scene(), geometry = new BufferGeometry(), material = new PointsMaterial({ size: 2, sizeAttenuation: false, vertexColors: true })
  let axes: AxesHelper | null = null
  let camera: PerspectiveCamera | OrthographicCamera
  let reportedView: CloudViewState | undefined
  let radius = 1
  let pointDown: {x: number; y: number} | null = null
  function render() {
    if (!closed && renderer) renderer.render(scene, camera)
  }
  function schedule() { if (!closed && !frame) frame = requestAnimationFrame(() => { frame = 0; render() }) }
  function publishView() {
    if (closed) return
    // 仅容纳 OrbitControls 在极轴处的浮点偏移，不是计量方向容差。
    const view = presetRotations.find(preset => 1 - Math.abs(camera.quaternion.dot(preset.rotation)) <= 1e-12)?.axis ?? 'free'
    if (view !== reportedView) { reportedView = view; viewChanged(view) }
  }
  function controlsChanged() { publishView(); schedule() }
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
    geometry.dispose(); material.dispose(); axes?.dispose(); scene.clear(); releaseGpu();releaseColor()
  }
  function lost(event: Event) { event.preventDefault(); dispose(); failed(new Error('cloud_context_lost')) }
  function down(event: PointerEvent) { pointDown = {x: event.clientX, y: event.clientY} }
  function pick(event: PointerEvent) {
    if (!renderer || overlay?.dragging() || !pointDown || Math.hypot(event.clientX - pointDown.x, event.clientY - pointDown.y) > 3) return
    const r = renderer.domElement.getBoundingClientRect(), ray = new Raycaster()
    ray.params.Points!.threshold = radius * .015
    ray.params.Line!.threshold = radius * .015
    ray.setFromCamera(new Vector2((event.clientX - r.left) / r.width * 2 - 1, -(event.clientY - r.top) / r.height * 2 + 1), camera)
    if(overlay?.pick(ray))return
    const hit = ray.intersectObject(points)[0]
    if (hit?.index !== undefined) picked(hit.index)
  }
  function bindControls() {
    releaseControls()
    controls = new OrbitControls(camera, renderer!.domElement)
    controls.enableDamping = false
    controls.zoomToCursor = true
    controls.mouseButtons.LEFT = panEnabled ? MOUSE.PAN : MOUSE.ROTATE
    controls.addEventListener('change', controlsChanged)
  }
  function fit(axis: CloudViewAxis = 'iso') {
    if (closed) return
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
  const points = new Points(geometry, material)
  try {
    releaseColor=reserveCpu(data.colors.byteLength,policy)
    geometry.setAttribute('position', new BufferAttribute(data.positions, 3)); geometry.setAttribute('color', new BufferAttribute(data.colors.slice(), 3))
    geometry.computeBoundingSphere(); radius = Math.max(geometry.boundingSphere?.radius ?? 0, 1e-6)
    renderer = new WebGLRenderer({ antialias: false, alpha: true, powerPreference: 'low-power' })
    renderer.localClippingEnabled = true
    renderer.setPixelRatio(1); renderer.setSize(width, height)
    renderer.domElement.setAttribute('aria-label', '3D point cloud')
    renderer.domElement.addEventListener('webglcontextlost', lost)
    renderer.domElement.addEventListener('pointerdown', down); renderer.domElement.addEventListener('pointerup', pick)
    host.append(renderer.domElement)
    axes = new AxesHelper(radius * .65); scene.add(points, axes)
    camera = new PerspectiveCamera(45, width / height)
    fit()
    overlay = createGeometryOverlay(scene,camera,renderer.domElement,data.origin,policy,schedule,active=>{if(controls)controls.enabled=!active},error=>{dispose();failed(error)})
    observer = new ResizeObserver(entries => {
      try {
        const box = entries[0]?.contentRect
        if (!box || closed || !renderer) return
        const [w, h] = dimensions(box.width, box.height)
        if (w === width && h === height) return
        // 先释放旧画布计量；新预算失败时整个 renderer 关闭，不能保持未计费画布。
        releaseGpu(); releaseGpu = () => {}
        releaseGpu = reserveGpu(data.positions.byteLength + data.colors.byteLength + w * h * 8 + 144, policy)
        width = w; height = h; renderer.setSize(w, h)
        if(camera instanceof OrthographicCamera){const half=(camera.top-camera.bottom)/2;camera.left=-half*w/h;camera.right=half*w/h}
        else camera.aspect=w/h
        camera.updateProjectionMatrix();schedule()
      } catch (error) { dispose(); failed(error as Error) }
    })
    observer.observe(host)
    return {
      dispose, fit,
      colors(samples:PlaneColors|null,mode:'original'|'support'|'residual'){
        if(closed)return
        const attribute=geometry.getAttribute('color') as BufferAttribute
        fillPlaneColors(attribute.array as Float32Array,data.colors,samples,mode);attribute.needsUpdate=true;schedule()
      },
      geometry(input:GeometryOverlayInput) { try { overlay?.update(input) } catch(error) { dispose(); failed(error as Error) } },
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
