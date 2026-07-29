const categoryOrders: Record<string, string[]> = {
  core: [
    'core.io.image',
    'core.io.file',
    'core.io.input',
    'core.io.response',
    'core.io.video',
    'core.ui.preview',
    'core.logic.condition',
    'core.logic.collection',
    'core.logic.branch',
    'core.logic.iteration',
    'core.logic.parallel',
    'core.logic.object',
    'core.logic.transform',
    'core.logic.variable',
    'core.logic.rule',
    'core.model.inference',
    'core.model.lifecycle',
    'core.dataset.import',
    'core.dataset.export',
    'core.deployment.runtime',
    'core.task.observation',
    'core.inspection.record',
    'core.vision.roi',
    'core.vision.region',
    'core.vision.geometry',
    'core.vision.position',
    'core.vision.assembly',
    'core.vision.continuity',
    'core.vision.defect',
    'core.vision.video',
  ],
  'custom:opencv.nodes': [
    'opencv.image.color',
    'opencv.image.enhancement',
    'opencv.image.filter',
    'opencv.image.edge',
    'opencv.image.threshold',
    'opencv.image.transform',
    'opencv.mask.operation',
    'opencv.mask.morphology',
    'opencv.segmentation.image',
    'opencv.segmentation.region',
    'opencv.feature.detection',
    'opencv.matching.feature',
    'opencv.matching.template',
    'opencv.matching.registration',
    'opencv.geometry.detection',
    'opencv.geometry.contour',
    'opencv.geometry.shape',
    'opencv.calibration.camera',
    'opencv.calibration.pose',
    'opencv.measurement.edge',
    'opencv.measurement.circle',
    'opencv.measurement.geometry',
    'opencv.inspection.statistics',
    'opencv.inspection.batch',
    'opencv.inspection.difference',
    'opencv.output.render',
    'opencv.output.workflow',
  ],
}

const categoryNamespaces = new Set(['core', 'opencv'])

export interface NodeCategoryParts {
  rootId: string
  rootLabel: string
  childLabel: string
}

export function readNodeCategoryParts(category: string): NodeCategoryParts {
  const rawTokens = category
    .split(/[./]+/)
    .map((token) => token.trim())
    .filter(Boolean)
  const tokens = rawTokens.length >= 3 && categoryNamespaces.has(rawTokens[0].toLowerCase())
    ? rawTokens.slice(1)
    : rawTokens
  const rootId = tokens[0] ?? category
  const childTokens = tokens.slice(1)
  return {
    rootId,
    rootLabel: humanizeNodeCategoryToken(rootId),
    childLabel: childTokens.length > 0
      ? childTokens.map(humanizeNodeCategoryToken).join(' ')
      : humanizeNodeCategoryToken(rootId),
  }
}

export function readNodeCategoryLabel(category: string): string {
  const parts = readNodeCategoryParts(category)
  return parts.rootLabel === parts.childLabel
    ? parts.rootLabel
    : `${parts.rootLabel} / ${parts.childLabel}`
}

export function compareNodeCategories(sourceId: string, left: string, right: string): number {
  const order = categoryOrders[sourceId] ?? []
  const leftIndex = order.indexOf(left)
  const rightIndex = order.indexOf(right)
  if (leftIndex >= 0 || rightIndex >= 0) {
    if (leftIndex < 0) return 1
    if (rightIndex < 0) return -1
    return leftIndex - rightIndex
  }
  return readNodeCategoryLabel(left).localeCompare(readNodeCategoryLabel(right))
}

export function humanizeNodeCategoryToken(token: string): string {
  const normalizedToken = token.toLowerCase()
  const fixedLabels: Record<string, string> = {
    api: 'API',
    cv: 'CV',
    http: 'HTTP',
    io: 'IO',
    opencv: 'OpenCV',
    plc: 'PLC',
    roi: 'ROI',
    sql: 'SQL',
    ui: 'UI',
    uvc: 'UVC',
  }
  if (fixedLabels[normalizedToken]) return fixedLabels[normalizedToken]
  return token
    .split(/[-_]+/)
    .filter(Boolean)
    .map((part) => fixedLabels[part.toLowerCase()] ?? part.replace(/^\w/, (character) => character.toUpperCase()))
    .join(' ')
}
