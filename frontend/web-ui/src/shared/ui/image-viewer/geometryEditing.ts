export type ImagePointTuple = [number, number]
export type ImageBboxTuple = [number, number, number, number]
export type GeometryResizeHandle =
  | 'nw'
  | 'n'
  | 'ne'
  | 'e'
  | 'se'
  | 's'
  | 'sw'
  | 'w'

export interface ImageGeometryBounds {
  x1: number
  y1: number
  x2: number
  y2: number
}

export function movePoint(
  point: ImagePointTuple,
  deltaX: number,
  deltaY: number,
  canvasWidth: number,
  canvasHeight: number,
): ImagePointTuple {
  return [
    roundCoordinate(clamp(point[0] + deltaX, 0, canvasWidth)),
    roundCoordinate(clamp(point[1] + deltaY, 0, canvasHeight)),
  ]
}

export function normalizeBbox(
  bbox: ImageBboxTuple,
  canvasWidth: number,
  canvasHeight: number,
  minimumSize = 1,
): ImageBboxTuple {
  const x1 = clamp(Math.min(bbox[0], bbox[2]), 0, Math.max(0, canvasWidth - minimumSize))
  const y1 = clamp(Math.min(bbox[1], bbox[3]), 0, Math.max(0, canvasHeight - minimumSize))
  const x2 = clamp(Math.max(bbox[0], bbox[2]), x1 + minimumSize, canvasWidth)
  const y2 = clamp(Math.max(bbox[1], bbox[3]), y1 + minimumSize, canvasHeight)
  return [roundCoordinate(x1), roundCoordinate(y1), roundCoordinate(x2), roundCoordinate(y2)]
}

export function moveBbox(
  bbox: ImageBboxTuple,
  deltaX: number,
  deltaY: number,
  canvasWidth: number,
  canvasHeight: number,
): ImageBboxTuple {
  const width = bbox[2] - bbox[0]
  const height = bbox[3] - bbox[1]
  const x1 = clamp(bbox[0] + deltaX, 0, Math.max(0, canvasWidth - width))
  const y1 = clamp(bbox[1] + deltaY, 0, Math.max(0, canvasHeight - height))
  return [
    roundCoordinate(x1),
    roundCoordinate(y1),
    roundCoordinate(x1 + width),
    roundCoordinate(y1 + height),
  ]
}

export function resizeBbox(
  bbox: ImageBboxTuple,
  handle: GeometryResizeHandle,
  point: ImagePointTuple,
  canvasWidth: number,
  canvasHeight: number,
  minimumSize = 2,
): ImageBboxTuple {
  let [x1, y1, x2, y2] = bbox
  if (handle.includes('w')) x1 = clamp(point[0], 0, x2 - minimumSize)
  if (handle.includes('e')) x2 = clamp(point[0], x1 + minimumSize, canvasWidth)
  if (handle.includes('n')) y1 = clamp(point[1], 0, y2 - minimumSize)
  if (handle.includes('s')) y2 = clamp(point[1], y1 + minimumSize, canvasHeight)
  return [roundCoordinate(x1), roundCoordinate(y1), roundCoordinate(x2), roundCoordinate(y2)]
}

export function readPolygonBounds(points: ImagePointTuple[]): ImageGeometryBounds {
  const xValues = points.map(([x]) => x)
  const yValues = points.map(([, y]) => y)
  return {
    x1: Math.min(...xValues),
    y1: Math.min(...yValues),
    x2: Math.max(...xValues),
    y2: Math.max(...yValues),
  }
}

export function movePolygon(
  points: ImagePointTuple[],
  deltaX: number,
  deltaY: number,
  canvasWidth: number,
  canvasHeight: number,
): ImagePointTuple[] {
  const bounds = readPolygonBounds(points)
  const resolvedDeltaX = clamp(deltaX, -bounds.x1, canvasWidth - bounds.x2)
  const resolvedDeltaY = clamp(deltaY, -bounds.y1, canvasHeight - bounds.y2)
  return points.map(([x, y]) => [
    roundCoordinate(x + resolvedDeltaX),
    roundCoordinate(y + resolvedDeltaY),
  ])
}

export function resizePolygon(
  points: ImagePointTuple[],
  handle: GeometryResizeHandle,
  pointer: ImagePointTuple,
  canvasWidth: number,
  canvasHeight: number,
  minimumSize = 2,
): ImagePointTuple[] {
  const bounds = readPolygonBounds(points)
  const resizedBounds = resizeBbox(
    [bounds.x1, bounds.y1, bounds.x2, bounds.y2],
    handle,
    pointer,
    canvasWidth,
    canvasHeight,
    minimumSize,
  )
  const oldWidth = Math.max(minimumSize, bounds.x2 - bounds.x1)
  const oldHeight = Math.max(minimumSize, bounds.y2 - bounds.y1)
  const newWidth = resizedBounds[2] - resizedBounds[0]
  const newHeight = resizedBounds[3] - resizedBounds[1]
  return points.map(([x, y]) => [
    roundCoordinate(resizedBounds[0] + ((x - bounds.x1) / oldWidth) * newWidth),
    roundCoordinate(resizedBounds[1] + ((y - bounds.y1) / oldHeight) * newHeight),
  ])
}

export function movePolygonVertex(
  points: ImagePointTuple[],
  vertexIndex: number,
  pointer: ImagePointTuple,
  canvasWidth: number,
  canvasHeight: number,
): ImagePointTuple[] {
  return points.map((point, index) => index === vertexIndex
    ? [
        roundCoordinate(clamp(pointer[0], 0, canvasWidth)),
        roundCoordinate(clamp(pointer[1], 0, canvasHeight)),
      ]
    : [...point],
  )
}

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.min(maximum, Math.max(minimum, value))
}

function roundCoordinate(value: number): number {
  return Math.round(value * 1000) / 1000
}
