import { expect, it } from 'vitest'
import { inspectArchiveLayout } from '@/modules/datasets/archive-layout-preview'
import type { ArchivePreview } from '@/modules/datasets/archive-preview.worker'

async function inspect(files: Record<string, string>) {
  const result: ArchivePreview = {
    files: Object.keys(files), fileCount: Object.keys(files).length, limited: false,
    format: '', task: '', classes: [], samples: null, objects: null,
    splits: {}, splitObjects: {}, annotationFiles: [], issues: [],
  }
  await inspectArchiveLayout(result, new Set(result.files), async path => files[path], 'detection')
  return result
}

it('ImageNet 的 valid 目录属于验证集，目录名作为来源类别', async () => {
  const result = await inspect({'pcb/train/pin/a.png':'', 'pcb/valid/pin/b.png':'', 'pcb/test/body/c.png':''})
  expect(result.task).toBe('classification')
  expect(result.splits).toEqual({train:1, val:1, test:1})
  expect(result.classes).toContainEqual({id:'—', name:'pin', count:2})
})

it('仅有类别目录时，ImageNet 沿用后台默认的 train', async () => {
  const result = await inspect({'parts/pin/a.png':'', 'parts/body/b.png':''})
  expect(result.splits).toEqual({train:2})
})

it('VOC 按 ImageSets 的互斥清单计数，不重复计算 trainval', async () => {
  const annotation = '<annotation><object><name>pin&amp;tip</name></object></annotation>'
  const result = await inspect({
    'VOC/JPEGImages/a.jpg':'', 'VOC/JPEGImages/b.jpg':'',
    'VOC/Annotations/a.xml':annotation, 'VOC/Annotations/b.xml':annotation,
    'VOC/ImageSets/Main/train.txt':'a', 'VOC/ImageSets/Main/val.txt':'b',
    'VOC/ImageSets/Main/trainval.txt':'a\nb',
  })
  expect(result.splitObjects).toEqual({train:1, val:1})
  expect(result.classes).toEqual([{id:'—',name:'pin&tip',count:2}])
})

it('YOLO 从 YAML 列表路径读取划分，并保留非连续数字类别 ID', async () => {
  const result = await inspect({
    'x/dataset.yaml':'train: lists/train.txt\nnames: {7: bolt}\n',
    'x/lists/train.txt':'# train\nimages/a.jpg',
    'x/images/a.jpg':'', 'x/images/unused.jpg':'',
    'x/labels/a.txt':'7 .5 .5 .1 .1',
  })
  expect(result.splits).toEqual({train:1})
  expect(result.classes).toEqual([{id:'7',name:'bolt',count:1}])
})

it('DOTA 从原始多边形标注第九列取类别', async () => {
  const result = await inspect({
    'obb/images/train/a.png':'',
    'obb/labels/train_original/a.txt':'imagesource:demo\n0 0 1 0 1 1 0 1 pin 0',
  })
  expect(result.task).toBe('obb')
  expect(result.splitObjects).toEqual({train:1})
  expect(result.classes[0].name).toBe('pin')
})
