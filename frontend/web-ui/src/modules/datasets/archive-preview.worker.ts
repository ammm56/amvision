import { inspectArchiveLayout } from './archive-layout-preview'
import { BlobReader, ZipReader, type FileEntry } from '@zip.js/zip.js'

/** 只读取 ZIP 目录与有界清单。原始图片和点云由正式导入 worker 校验。 */
export interface ArchivePreview {
  files: string[]
  limited: boolean
  fileCount: number
  format: string
  task: string
  samples: number | null
  objects: number | null
  classes: { id: string; name: string; count: number }[]
  splits: Record<string, number>
  splitObjects: Record<string, number>
  annotationFiles: string[]
  issues: { path: string; kind: 'missing' | 'duplicate' | 'unsafe' | 'empty'; manifest?: string }[]
}

export async function inspect(file: File, task = 'detection'): Promise<ArchivePreview> {
  const reader = new ZipReader(new BlobReader(file), { useWebWorkers: false })
  const result: ArchivePreview = {
    files: [],
    limited: false,
    fileCount: 0,
    format: '',
    task: '',
    samples: null,
    objects: null,
    classes: [],
    splits: {},
    splitObjects: {},
    annotationFiles: [],
    issues: [],
  }
  const paths = new Set<string>(),
    basenames = new Set<string>()
  const manifests: FileEntry[] = []
  const entries = new Map<string, FileEntry>()
  const issue = (path: string, kind: ArchivePreview['issues'][number]['kind'], manifest?: string) => {
    if (result.issues.length < 50) result.issues.push({ path, kind, manifest })
  }
  try {
    for await (const entry of reader.getEntriesGenerator()) {
      if (entry.directory) continue
      const path = entry.filename.replaceAll('\\', '/')
      if (
        path.startsWith('/') ||
        /^[a-z]:/i.test(path) ||
        path.split('/').includes('..') ||
        entry.encrypted
      )
        issue(path, 'unsafe')
      if (paths.has(path)) issue(path, 'duplicate')
      entries.set(path, entry)
      paths.add(path)
      basenames.add(path.split('/').at(-1)!)
      if (result.files.length < 2000) result.files.push(path)
      result.fileCount++
      if (result.fileCount > 100000) {
        result.limited = true
        return result
      }
      if (
        /(^|\/)(samples|instances[^/]*|train|val|test|_annotations\.coco)\.json$/i.test(
          path,
        ) ||
        /(^|\/)(annotations|train|val|valid|test)\/[^/]+\.json$/i.test(path)
      )
        manifests.push(entry)
    }
    if (!paths.size) issue(file.name, 'empty')
    const labels = new Map<
      string,
      { id: string; name: string; count: number }
    >()
    let budget = 16 * 1024 * 1024
    const readText = async (path: string) => {
      const entry = entries.get(path)!
      if (entry.uncompressedSize > budget) throw new RangeError('preview-budget')
      const chunks: Uint8Array<ArrayBuffer>[] = []
      await entry.getData(new WritableStream<Uint8Array>({
        write(chunk) {
          budget -= chunk.byteLength
          if (budget < 0) throw new RangeError('preview-budget')
          chunks.push(new Uint8Array(chunk))
        },
      }), { checkSignature: true })
      return new Blob(chunks).text()
    }
    try {
      for (const entry of manifests) {
        const data = JSON.parse(await readText(entry.filename.replaceAll('\\', '/')))
        if (
          data?.format_id === 'amvision.sample-media.v1' &&
          Array.isArray(data.samples)
        ) {
          result.format = 'amvision-media'
          result.task = data.task_type
          result.samples = data.samples.length
          result.objects = data.task_type === 'anomaly' ? result.samples : 0
          const prefix = entry.filename.slice(0, -'samples.json'.length)
          for (const row of data.samples) {
            result.splits[row.split] = (result.splits[row.split] || 0) + 1
            result.splitObjects[row.split] = (result.splitObjects[row.split] || 0) + (data.task_type === 'anomaly' ? 1 : 0)
            for (const k of ['image', 'depth', 'cloud', 'mask', 'calibration'])
              if (row[k] && !paths.has(prefix + row[k])) issue(String(row[k]), 'missing', entry.filename)
            if (row.category || row.label) {
              const name = row.category || row.label
              if (!labels.has(name))
                labels.set(name, { id: String(labels.size), name, count: 0 })
              labels.get(name)!.count++
            }
          }
        } else if (
          Array.isArray(data?.images) &&
          Array.isArray(data.categories)
        ) {
          result.annotationFiles.push(entry.filename)
          result.format = 'coco'
          result.samples = (result.samples ?? 0) + data.images.length
          const anns = Array.isArray(data.annotations) ? data.annotations : []
          result.objects = (result.objects ?? 0) + anns.length
          const parts = entry.filename.toLowerCase().split('/')
          const split = [parts.at(-2), parts.at(-1)].map(part =>
            part?.includes('train') ? 'train' : part?.includes('val') ? 'val' : part?.includes('test') ? 'test' : null,
          ).find(Boolean) || 'train'
          result.splits[split] = (result.splits[split] || 0) + data.images.length
          result.splitObjects[split] = (result.splitObjects[split] || 0) + anns.length
          for (const cat of data.categories) {
            if (!labels.has(String(cat.id)))
              labels.set(String(cat.id), {
                id: String(cat.id),
                name: cat.name,
                count: 0,
              })
          }
          for (const annotation of anns) {
            const item = labels.get(String(annotation.category_id))
            if (item) item.count++
          }
          for (const image of data.images)
            if (
              typeof image.file_name === 'string' &&
              !basenames.has(
                image.file_name.replaceAll('\\', '/').split('/').at(-1)!,
              )
            )
              issue(image.file_name, 'missing', entry.filename)
        }
      }
      if (result.format) result.classes = [...labels.values()]
      else await inspectArchiveLayout(result, paths, readText, task)
    } catch (error) {
      if (!(error instanceof RangeError) || error.message !== 'preview-budget') throw error
      result.limited = true
      result.samples = null
      result.objects = null
      result.splits = {}
      result.splitObjects = {}
      result.classes = []
    }
    return result
  } finally {
    await reader.close()
  }
}
self.onmessage = async ({ data }: MessageEvent<{file: File; task: string}>) => {
  try {
    self.postMessage({ result: await inspect(data.file, data.task) })
  } catch (error) {
    self.postMessage({
      error: error instanceof Error ? error.message : String(error),
    })
  }
}
