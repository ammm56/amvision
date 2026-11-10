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
  issues: string[]
}

async function inspect(file: File): Promise<ArchivePreview> {
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
    issues: [],
  }
  const paths = new Set<string>(),
    basenames = new Set<string>()
  const manifests: FileEntry[] = []
  const issue = (message: string) => {
    if (result.issues.length < 50) result.issues.push(message)
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
        issue(path)
      if (paths.has(path)) issue(path)
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
        /(^|\/)annotations\/[^/]+\.json$/i.test(path)
      )
        manifests.push(entry)
    }
    if (!paths.size) issue('ZIP 中没有文件')
    const labels = new Map<
      string,
      { id: string; name: string; count: number }
    >()
    let budget = 16 * 1024 * 1024
    // 超出本地预览预算的清单交由服务端处理，避免展示不完整的合计。
    if (manifests.reduce((n, e) => n + e.uncompressedSize, 0) <= budget) {
      for (const entry of manifests) {
        const chunks: Uint8Array<ArrayBuffer>[] = []
        await entry.getData(
          new WritableStream<Uint8Array>({
            write(chunk) {
              budget -= chunk.byteLength
              if (budget < 0) throw Error('ZIP 清单超过预览预算')
              chunks.push(new Uint8Array(chunk))
            },
          }),
          { checkSignature: true },
        )
        const data = JSON.parse(await new Blob(chunks).text())
        if (
          data?.format_id === 'amvision.sample-media.v1' &&
          Array.isArray(data.samples)
        ) {
          result.format = 'amvision-media'
          result.task = data.task_type
          result.samples = data.samples.length
          const prefix = entry.filename.slice(0, -'samples.json'.length)
          for (const row of data.samples) {
            result.splits[row.split] = (result.splits[row.split] || 0) + 1
            for (const k of ['image', 'depth', 'cloud', 'mask', 'calibration'])
              if (row[k] && !paths.has(prefix + row[k])) issue(String(row[k]))
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
          result.format = 'coco'
          result.samples = (result.samples ?? 0) + data.images.length
          const anns = Array.isArray(data.annotations) ? data.annotations : []
          result.objects = (result.objects ?? 0) + anns.length
          const split = entry.filename
            .toLowerCase()
            .match(/(?:^|[\/_.-])(train|val|test)(?:[\/_.-]|$)/)?.[1]
          if (split)
            result.splits[split] =
              (result.splits[split] || 0) + data.images.length
          const names = new Map<number, string>()
          for (const cat of data.categories) {
            names.set(cat.id, cat.name)
            if (!labels.has(cat.name))
              labels.set(cat.name, {
                id: String(cat.id),
                name: cat.name,
                count: 0,
              })
          }
          for (const annotation of anns) {
            const item = labels.get(names.get(annotation.category_id) || '')
            if (item) item.count++
          }
          for (const image of data.images)
            if (
              typeof image.file_name === 'string' &&
              !basenames.has(
                image.file_name.replaceAll('\\', '/').split('/').at(-1)!,
              )
            )
              issue(image.file_name)
        }
      }
    }
    if (!result.format && !manifests.length) {
      const has = (re: RegExp) => [...paths].some((path) => re.test(path))
      if (has(/(^|\/)data\.ya?ml$/i) && has(/(^|\/)labels\//i))
        result.format = 'yolo'
      else if (has(/(^|\/)Annotations\/[^/]+\.xml$/i)) result.format = 'voc'
      else if (has(/(^|\/)labelTxt\/[^/]+\.txt$/i)) result.format = 'dota'
      const images = [...paths].filter((p) =>
        /\.(jpg|jpeg|bmp|png|tiff?|webp)$/i.test(p),
      )
      if (
        !result.format &&
        images.length &&
        images.every((p) => /(^|\/)(train|val|test)\/[^/]+\/[^/]+$/i.test(p))
      ) {
        result.format = 'imagenet'
        result.task = 'classification'
        for (const path of images) {
          const name = path.split('/').at(-2)!
          if (!labels.has(name)) labels.set(name, { id: '—', name, count: 0 })
          labels.get(name)!.count++
        }
      }
      if (result.format && images.length) {
        result.samples = images.length
        for (const path of images) {
          const split = path.match(/(?:^|\/)(train|val|test)(?:\/)/i)?.[1]
          if (split) result.splits[split] = (result.splits[split] || 0) + 1
        }
      }
    }
    result.classes = [...labels.values()]
    return result
  } finally {
    await reader.close()
  }
}
self.onmessage = async ({ data }: MessageEvent<File>) => {
  try {
    self.postMessage({ result: await inspect(data) })
  } catch (error) {
    self.postMessage({
      error: error instanceof Error ? error.message : String(error),
    })
  }
}
