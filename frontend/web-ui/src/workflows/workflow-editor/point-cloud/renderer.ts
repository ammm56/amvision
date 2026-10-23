import { AxesHelper, BufferAttribute, BufferGeometry, MOUSE, OrthographicCamera, PerspectiveCamera, Points, PointsMaterial, Raycaster, Scene, Vector2, WebGLRenderer } from 'three'
import { OrbitControls } from 'three/addons/controls/OrbitControls.js'
import type { CloudRendererPolicy } from '../services/measurement-resource.service'
import { reserveCpu, reserveGpu, type CloudDisplayData } from './preview-data'
import {fillPlaneColors,type PlaneColors} from './plane-colors'
import {createGeometryOverlay,type GeometryOverlayInput} from './geometry-overlay'

/** 一个激活的视口一个 renderer；没有常驻动画、后台重算或原始点云请求。 */
export function createCloudRenderer(host: HTMLElement, data: CloudDisplayData, policy: CloudRendererPolicy,
  picked: (index: number) => void, failed: (error: Error) => void) {
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
  let viewAxis: 'iso' | 'x' | 'y' | 'z' = 'iso'
  const scene = new Scene(), geometry = new BufferGeometry(), material = new PointsMaterial({ size: 2, sizeAttenuation: false, vertexColors: true })
  let axes: AxesHelper | null = null
  let camera: PerspectiveCamera | OrthographicCamera
  let radius = 1
  let pointDown: {x: number; y: number} | null = null
  function render() {
    if (!closed && renderer) renderer.render(scene, camera)
  }
  function schedule() { if (!closed && !frame) frame = requestAnimationFrame(() => { frame = 0; render() }) }
  function dispose() {
    if (closed) return
    closed = true
    cancelAnimationFrame(frame); observer?.disconnect(); overlay?.dispose(); controls?.dispose()
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
    ray.setFromCamera(new Vector2((event.clientX - r.left) / r.width * 2 - 1, -(event.clientY - r.top) / r.height * 2 + 1), camera)
    const hit = ray.intersectObject(points)[0]
    if (hit?.index !== undefined) picked(hit.index)
  }
  function bindControls() {
    controls?.dispose()
    controls = new OrbitControls(camera, renderer!.domElement)
    controls.enableDamping = false
    controls.mouseButtons.LEFT = panEnabled ? MOUSE.PAN : MOUSE.ROTATE
    controls.addEventListener('change', schedule)
  }
  function fit(axis: 'iso' | 'x' | 'y' | 'z' = 'iso') {
    viewAxis = axis
    const direction = axis === 'x' ? [1, 0, 0] : axis === 'y' ? [0, -1, 0] : axis === 'z' ? [0, 0, 1] : [1, -1, .8]
    camera.up.set(0, axis === 'z' ? 1 : 0, axis === 'z' ? 0 : 1)
    camera.position.set(...direction as [number, number, number]).normalize().multiplyScalar(radius * 3 / Math.min(1, width / height))
    camera.near = radius / 1000; camera.far = radius * 10000
    if (camera instanceof OrthographicCamera) {
      const y = radius * 1.15 / Math.min(1, width / height), x = y * width / height
      camera.left = -x; camera.right = x; camera.top = y; camera.bottom = -y; camera.zoom = 1
    } else camera.aspect = width / height
    camera.updateProjectionMatrix(); controls!.target.set(0, 0, 0); controls!.update(); schedule()
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
    bindControls(); fit()
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
        width = w; height = h; renderer.setSize(w, h); fit(viewAxis)
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
        camera = orthographic ? new OrthographicCamera() : new PerspectiveCamera(45, width / height)
        overlay?.camera(camera)
        bindControls(); fit(viewAxis)
      },
      pan(enabled: boolean) { panEnabled = enabled; controls!.mouseButtons.LEFT = enabled ? MOUSE.PAN : MOUSE.ROTATE },
      pointSize(size: number) { material.size = size; schedule() },
    }
  } catch (error) { dispose(); throw error }
}
