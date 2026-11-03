import { BufferAttribute, BufferGeometry, Points, type PointsMaterial, type Scene } from 'three'
import type { CloudRendererPolicy } from '../services/measurement-resource.service'
import { reserveCpu, reserveGpu, type CloudDisplayData } from './preview-data'
import { fillCoordinateColors, linearizeDisplayColors, type CoordinateRange } from './view-presentation'

/** 与现有 renderer 共用场景及预算；成功 add 后接管该块解码数据。 */
export function createDetailLayer(scene: Scene, material: PointsMaterial, policy: CloudRendererPolicy) {
  const entries: { points: Points; data: CloudDisplayData; release: () => void }[] = []
  let coordinate: CoordinateRange | null = null
  function color(points: Points, data: CloudDisplayData) {
    const attribute = points.geometry.getAttribute('color') as BufferAttribute
    const values = attribute.array as Float32Array
    values.set(data.colors)
    if (coordinate) fillCoordinateColors(values, data.positions, data.origin[2]!, coordinate)
    linearizeDisplayColors(values); attribute.needsUpdate = true
  }
  function clear() {
    for (const entry of entries) { scene.remove(entry.points); entry.points.geometry.dispose(); entry.data.dispose(); entry.release() }
    entries.length = 0
  }
  return {
    clear,
    objects: () => entries.map(e => e.points),
    point(object: unknown, index: number) { return entries.find(e => e.points === object)?.data.point(index) },
    add(data: CloudDisplayData) {
      let cpu = () => {}, gpu = () => {}
      const geometry = new BufferGeometry()
      try {
        cpu = reserveCpu(data.colors.byteLength, policy)
        gpu = reserveGpu(data.positions.byteLength + data.colors.byteLength, policy)
        geometry.setAttribute('position', new BufferAttribute(data.positions, 3))
        geometry.setAttribute('color', new BufferAttribute(data.colors.slice(), 3))
        const points = new Points(geometry, material)
        points.visible = false
        color(points, data); scene.add(points)
        entries.push({ points, data, release: () => { cpu(); gpu() } })
      } catch (error) { geometry.dispose(); cpu(); gpu(); throw error }
    },
    visible(value: boolean) { for (const entry of entries) entry.points.visible = value },
    colors(range: CoordinateRange | null) { coordinate = range; for (const entry of entries) color(entry.points, entry.data) },
  }
}
