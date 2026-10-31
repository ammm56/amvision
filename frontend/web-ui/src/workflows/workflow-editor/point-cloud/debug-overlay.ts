import {
  BufferAttribute,
  BufferGeometry,
  Group,
  LineBasicMaterial,
  LineSegments,
  Mesh,
  MeshBasicMaterial,
  DoubleSide,
  Points,
  PointsMaterial,
  Vector3,
} from 'three'
import type { CloudRendererPolicy } from '../services/measurement-resource.service'
import { reserveCpu, reserveGpu } from './preview-data'
import {
  debugPoint,
  type DebugEvidence,
  type DebugLayers,
  type DebugSelection,
} from './boundary-debug'

/** 使用一个格网 Mesh 和少量线/点缓冲，不逐格创建对象；原 overlay 负责销毁几何。 */
export function buildDebugOverlay(
  root: Group,
  d: DebugEvidence,
  layers: DebugLayers,
  selected: DebugSelection | null,
  origin: number[],
  policy: CloudRendererPolicy,
  account: (release: () => void) => void,
) {
  if (d.state !== 'ready') return
  const a = d.arrays,
    offset = new Vector3(...origin)
  function geometry(
    count: number,
    positions: (index: number) => number[],
    colors?: (index: number) => number[],
  ) {
    const bytes = count * 3 * 4 * (colors ? 2 : 1)
    account(reserveCpu(bytes, policy))
    account(reserveGpu(bytes, policy))
    const xyz = new Float32Array(count * 3),
      rgb = colors ? new Float32Array(count * 3) : null
    for (let i = 0; i < count; i++) {
      const p = positions(i)
      for (let c = 0; c < 3; c++) {
        const value = p[c]! - offset.getComponent(c)
        xyz[i * 3 + c] = value
        if (
          !Number.isFinite(xyz[i * 3 + c]) ||
          Math.abs(xyz[i * 3 + c]! - value) > policy.max_position_error
        )
          throw new Error('cloud_position_precision')
      }
      if (rgb) rgb.set(colors!(i), i * 3)
    }
    const g = new BufferGeometry()
    g.setAttribute('position', new BufferAttribute(xyz, 3))
    if (rgb) g.setAttribute('color', new BufferAttribute(rgb, 3))
    return g
  }
  const point = (name: string, index: number) =>
    [0, 1, 2].map((c) => a[name]!.get(index, c))
  const mark = (
    object: Mesh | Points | LineSegments,
    kind: DebugSelection['kind'],
  ) => {
    object.userData.debug = { id: d.id, kind }
    root.add(object)
    return object
  }
  if (d.grid && layers.grid) {
    const grid = d.grid,
      n = grid.shape[0]! * grid.shape[1]!,
      corners = [
        [0, 0],
        [1, 0],
        [1, 1],
        [0, 0],
        [1, 1],
        [0, 1],
      ]
    const g = geometry(
      n * 6,
      (i) => {
        const cell = Math.floor(i / 6),
          corner = corners[i % 6]!
        return debugPoint(
          d,
          grid.origin[0]! +
            (Math.floor(cell / grid.shape[1]!) + corner[0]!) * grid.step,
          grid.origin[1]! + ((cell % grid.shape[1]!) + corner[1]!) * grid.step,
        )
      },
      (i) => {
        const cell = Math.floor(i / 6)
        if (selected?.kind === 'cell' && selected.index === cell)
          return [1, 0.72, 0.05]
        if (a.selected!.get(cell)) return [0.08, 0.62, 0.45]
        if (a.grouped?.get(cell) && !a.foreground!.get(cell))
          return [0.72, 0.28, 0.62]
        if (a.foreground!.get(cell)) return [0.18, 0.44, 0.8]
        if (a.usable!.get(cell)) return [0.45, 0.5, 0.55]
        return a.counts!.get(cell) ? [0.85, 0.5, 0.12] : [0.24, 0.26, 0.29]
      },
    )
    mark(
      new Mesh(
        g,
        new MeshBasicMaterial({
          vertexColors: true,
          side: DoubleSide,
          transparent: true,
          opacity: 0.48,
          depthTest: false,
          depthWrite: false,
        }),
      ),
      'cell',
    )
    const [u, v] = grid.seedMin,
      [x, y] = grid.seedMax
    const cornersUv = [
        [u!, v!],
        [x!, v!],
        [x!, y!],
        [u!, y!],
      ],
      indices = [0, 1, 1, 2, 2, 3, 3, 0]
    const line = new LineSegments(
      geometry(8, (i) =>
        debugPoint(d, ...(cornersUv[indices[i]!]! as [number, number])),
      ),
      new LineBasicMaterial({ color: 0xe7b62e, depthTest: false }),
    )
    root.add(line)
  }
  if (layers.partition && a.metric_uv) {
    const uv = a.metric_uv,
      labels = a.metric_labels!,
      target = d.grid?.component
    mark(
      new Points(
        geometry(
          uv.count,
          (i) => debugPoint(d, uv.get(i, 0), uv.get(i, 1)),
          (i) =>
            selected?.kind === 'metric' && selected.index === i
              ? [1, 0.72, 0.05]
              : labels.get(i) === target
                ? [0.08, 0.8, 0.52]
                : [0.38, 0.4, 0.48],
        ),
        new PointsMaterial({
          size: 4,
          sizeAttenuation: false,
          vertexColors: true,
          depthTest: false,
        }),
      ),
      'metric',
    )
  }
  if (layers.profiles && a.profile_positions) {
    const offsets = a.profile_offsets!,
      breaks = a.profile_breaks!,
      points = a.profile_positions!,
      pairs: number[] = []
    const scratch = reserveCpu(points.count * 16, policy)
    try {
      for (let i = 1; i < points.count; i++)
        if (!breaks.get(i)) pairs.push(i - 1, i)
      root.add(
        new LineSegments(
          geometry(pairs.length, (i) => point('profile_positions', pairs[i]!)),
          new LineBasicMaterial({ color: 0x287bb8, depthTest: false }),
        ),
      )
      mark(
        new Points(
          geometry(
            points.count,
            (i) => point('profile_positions', i),
            (i) =>
              selected?.kind === 'profile' && selected.index === i
                ? [1, 0.72, 0.05]
                : a.profile_kinds!.get(i) === 0
                  ? [0.15, 0.48, 0.9]
                  : [0.8, 0.25, 0.6],
          ),
          new PointsMaterial({
            size: 5,
            sizeAttenuation: false,
            vertexColors: true,
            depthTest: false,
          }),
        ),
        'profile',
      )
      if (offsets.count !== 5) throw new Error('cloud_debug_invalid')
    } finally {
      scratch()
    }
  }
  if (layers.candidates && a.candidate_positions) {
    const offsets = a.candidate_offsets!,
      indices = a.candidate_indices!,
      closed = a.candidate_closed!
    for (let c = 0; c < closed.count; c++) {
      const start = offsets.get(c),
        end = offsets.get(c + 1),
        count = end - start,
        edges = Math.max(0, count - 1) + (closed.get(c) && count > 1 ? 1 : 0)
      const chosen = selected?.kind === 'candidate' && selected.index === c
      const line = new LineSegments(
        geometry(edges * 2, (i) =>
          point(
            'candidate_positions',
            indices.get(start + ((Math.floor(i / 2) + (i % 2)) % count)),
          ),
        ),
        new LineBasicMaterial({
          color: chosen ? 0xd18c00 : 0x82949b,
          depthTest: false,
        }),
      )
      mark(line, 'candidate').userData.debug.index = c
    }
  }
}
