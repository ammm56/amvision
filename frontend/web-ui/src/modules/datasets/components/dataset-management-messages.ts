const zh = {
  manage: '管理数据集', search: '搜索数据集 ID 或版本 ID', dataset: '数据集 ID', version: '版本 ID',
  task: '任务类型', samples: '样本数', categories: '类别数', actions: '操作', close: '关闭', cancel: '取消',
  remove: '删除版本', removeTitle: '删除数据集版本',
  removeDetails: '删除该版本及其图片、标注、关联导入／导出记录和所属文件。存在外部引用时阻止删除。此操作不可撤销。',
  empty: '暂无数据集', emptyDescription: '完成数据集导入后，可在这里管理数据集版本。',
  noResults: '没有匹配的数据集', noResultsDescription: '请尝试其他数据集 ID 或版本 ID。',
  accepted: '删除已受理，文件清理进度可在页面中查看。',
}
const en: Record<keyof typeof zh, string> = {
  manage: 'Manage datasets', search: 'Search dataset ID or version ID', dataset: 'Dataset ID', version: 'Version ID',
  task: 'Task type', samples: 'Samples', categories: 'Classes', actions: 'Actions', close: 'Close', cancel: 'Cancel',
  remove: 'Delete version', removeTitle: 'Delete dataset version',
  removeDetails: 'Delete this version, its images, annotations, related import/export records and owned files. External references prevent deletion. This cannot be undone.',
  empty: 'No datasets', emptyDescription: 'Import a dataset to manage its versions here.',
  noResults: 'No matching datasets', noResultsDescription: 'Try another dataset ID or version ID.',
  accepted: 'Deletion accepted. File cleanup progress is available on the page.',
}
export const datasetManagementMessages = { 'zh-CN': zh, 'en-US': en, 'ja-JP': en, 'ko-KR': en }
