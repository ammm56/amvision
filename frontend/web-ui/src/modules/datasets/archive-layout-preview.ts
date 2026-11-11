import { SaxesParser } from 'saxes'
import { parse as parseYaml } from 'yaml'
import type { ArchivePreview } from './archive-preview.worker'

const imageExtension = /\.(?:jpe?g|png|bmp)$/i
const splitNames = ['train', 'val', 'test'] as const
type Split = typeof splitNames[number]
type ReadText = (path: string) => Promise<string>

function splitName(name: string): Split | undefined {
  if (name === 'valid') return 'val'
  return splitNames.find(key => key === name)
}

function countSample(result: ArchivePreview, split: Split, count: number) {
  result.samples = (result.samples ?? 0) + 1
  result.objects = (result.objects ?? 0) + count
  result.splits[split] = (result.splits[split] ?? 0) + 1
  result.splitObjects[split] = (result.splitObjects[split] ?? 0) + count
}

function classes() {
  const items = new Map<string, ArchivePreview['classes'][number]>()
  return {
    add(name: string, id = '—', count = 1) {
      const key = id === '—' ? name : id
      const item = items.get(key) || { id, name, count: 0 }
      item.count += count
      items.set(key, item)
    },
    rows: () => Array.from(items.values()),
  }
}

function vocObjectNames(xml: string) {
  const parser = new SaxesParser()
  const stack: string[] = [], names: string[] = []
  let value = ''
  parser.on('opentag', tag => { stack.push(tag.name); value = '' })
  parser.on('text', text => { value += text })
  parser.on('cdata', text => { value += text })
  parser.on('closetag', () => {
    if (stack.at(-2) === 'object' && stack.at(-1) === 'name') names.push(value.trim())
    stack.pop()
  })
  parser.write(xml).close()
  return names
}

async function inspectVoc(result: ArchivePreview, paths: Set<string>, read: ReadText, task: string) {
  const labels = classes()
  const section = task === 'segmentation' ? 'Segmentation' : 'Main'
  const suffix = '/ImageSets/' + section + '/'
  const sets = new Map<string, Map<string, string>>()
  for (const path of paths) {
    const parts = ('/' + path).split(suffix)
    if (parts.length !== 2 || !/^(train|val|test|trainval)\.txt$/.test(parts[1])) continue
    const root = parts[0].slice(1)
    if (!sets.has(root)) sets.set(root, new Map())
    sets.get(root)!.set(parts[1].slice(0, -4), path)
  }
  for (const [root, files] of sets) {
    if (!files.has('train') && !files.has('val') && files.has('trainval')) files.set('train', files.get('trainval')!)
    for (const key of splitNames) {
      const list = files.get(key)
      if (!list) continue
      const members = new Set((await read(list)).split(/\r?\n/).map(line => line.trim()).filter(Boolean))
      result.splits[key] = result.splits[key] || 0
      result.splitObjects[key] = result.splitObjects[key] || 0
      for (const member of members) {
        const annotation = [root, 'Annotations', member + '.xml'].filter(Boolean).join('/')
        if (!paths.has(annotation)) {
          if (result.issues.length < 50) result.issues.push({ path: annotation, kind: 'missing', manifest: list })
          continue
        }
        const names = vocObjectNames(await read(annotation))
        for (const name of names) labels.add(name)
        countSample(result, key, names.length)
      }
    }
  }
  result.classes = labels.rows()
}

function joinPath(base: string, relative: string) {
  const parts: string[] = []
  for (const part of (base + '/' + relative.replaceAll('\\', '/')).split('/')) {
    if (part === '..') parts.pop()
    else if (part && part !== '.') parts.push(part)
  }
  return parts.join('/')
}

async function inspectLabels(result: ArchivePreview, paths: Set<string>, images: string[], read: ReadText, yaml?: string) {
  const labels = classes()
  const membership = new Map<string, Split>()
  let names: Record<string,string> = {}
  if (yaml) {
    const config = parseYaml(await read(yaml)) || {}
    names = config.names || {}
    for (const [id, name] of Object.entries(names)) labels.add(String(name), id, 0)
    const parent = yaml.split('/').slice(0,-1).join('/')
    let base = joinPath(parent, String(config.path || '.'))
    if (!images.some(path => !base || path.startsWith(base + '/'))) base = parent
    for (const split of splitNames) {
      const spec = config[split] ?? (split === 'val' ? config.valid : undefined)
      for (const item of Array.isArray(spec) ? spec : [spec]) {
        if (typeof item !== 'string') continue
        const path = joinPath(base, item)
        if (path.endsWith('.txt') && paths.has(path)) {
          const dir = path.split('/').slice(0,-1).join('/')
          for (const line of (await read(path)).split(/\r?\n/).map(s => s.trim()).filter(Boolean)) {
            if (line.startsWith('#')) continue
            const fromBase = joinPath(base, line)
            const image = paths.has(fromBase) ? fromBase : joinPath(dir, line)
            if (paths.has(image)) membership.set(image, split)
          }
        } else {
          for (const image of images) if (image === path || image.startsWith(path + '/')) membership.set(image,split)
        }
      }
    }
  }
  if (!membership.size) {
    for (const image of images) {
      const split = image.split('/').map(splitName).find(Boolean)
      if (split) membership.set(image, split)
    }
  }
  for (const [image, split] of membership) {
    const stem = image.replace(imageExtension,'.txt')
    const sibling = ('/' + stem).replace('/images/', '/labels/').slice(1)
    const candidates = [sibling, stem]
    if (result.format === 'dota') candidates.unshift(sibling.replace('/' + split + '/', '/' + split + '_original/'))
    const path = candidates.find(p => paths.has(p))
    let count = 0
    if (path) {
      for (const line of (await read(path)).split(/\r?\n/)) {
        const parts = line.trim().split(/\s+/)
        if (parts.length < 2 || !Number.isFinite(Number(parts[0]))) continue
        const key = result.format === 'dota' ? parts[8] : parts[0]
        if (!key) continue
        if (result.format === 'dota') labels.add(key)
        else labels.add(String(names[key] ?? ('class-' + key)), key)
        count++
      }
    }
    countSample(result,split,count)
  }
  result.classes = labels.rows()
}

/** 只读标注和目录。图片与掩膜像素由正式导入 worker 校验。 */
export async function inspectArchiveLayout(result: ArchivePreview, paths: Set<string>, read: ReadText, task: string) {
  const files = Array.from(paths)
  const images = files.filter(path => imageExtension.test(path))
  if (!images.length) return
  if (files.some(path => /(?:^|\/)Annotations\/[^/]+\.xml$/.test(path))) {
    result.format = 'voc'
    await inspectVoc(result,paths,read,task)
    return
  }
  const yaml = files.find(path => /(?:^|\/)(?:data|dataset)\.ya?ml$/i.test(path))
  const isDota = files.some(path => /(?:^|\/)labels\/(train|val|test)_original\//.test(path))
  if (yaml || isDota || files.some(p => /(?:^|\/)labels\/(train|val|test)\//.test(p))) {
    result.format = isDota && !yaml ? 'dota' : 'yolo'
    if (result.format === 'dota') result.task = 'obb'
    await inspectLabels(result,paths,images,read,yaml)
    return
  }
  const labels = classes()
  const parents = new Set<string>()
  const explicit = images.some(p => splitName(p.split('/').at(-3) || ''))
  for (const path of images) {
    const parts = path.split('/')
    const split = splitName(parts.at(-3) || '')
    const name = parts.at(-2)
    if (!name || /^(images|labels|masks|JPEGImages|SegmentationClass|SegmentationObject)$/i.test(name) || (explicit && !split)) return
    parents.add(parts.slice(0,explicit ? -3 : -2).join('/'))
  }
  if (parents.size !== 1) return
  result.format = 'imagenet'
  result.task = 'classification'
  for (const path of images) {
    const parts = path.split('/')
    labels.add(parts.at(-2)!)
    countSample(result,splitName(parts.at(-3) || '') || 'train',1)
  }
  result.classes = labels.rows()
}
