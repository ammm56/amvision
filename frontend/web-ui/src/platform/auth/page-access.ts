import type { CurrentUser } from '@/shared/contracts'
import { hasScopes, hasScope } from './permissions'

// 页面 ID 和业务读取能力独立于导航文案；所有入口使用同一策略。
export const pageDefinitions = [
  { id: 'projects', label: '项目', scopes: ['workflows:read', 'models:read'], path: '/projects' },
  { id: 'tasks', label: '任务', scopes: ['tasks:read'], path: '/tasks' },
  { id: 'datasets', label: '数据集', scopes: ['datasets:read'], path: '/datasets' },
  { id: 'models', label: '模型', scopes: ['models:read'], path: '/models' },
  { id: 'deployments', label: '部署', scopes: ['models:read'], path: '/deployments' },
  { id: 'inference', label: '推理', scopes: ['models:read'], path: '/inference' },
  { id: 'workflow-graph', label: '图编辑', scopes: ['workflows:read'], path: '/workflows/graph' },
  { id: 'workflow-apps', label: '应用管理', scopes: ['workflows:read'], path: '/workflows/apps' },
  { id: 'workflow-monitor', label: '运行时监视', scopes: ['workflows:read'], path: null },
  { id: 'workflow-app-mode', label: '应用模式', scopes: ['workflows:read'], path: null },
  { id: 'integrations', label: '集成', scopes: ['workflows:read'], path: '/integrations/trigger-sources' },
  { id: 'custom-nodes', label: '节点', scopes: ['workflows:read'], path: '/custom-nodes' },
  { id: 'settings-preferences', label: '偏好', scopes: [], path: '/settings?category=preferences' },
  { id: 'settings-startup', label: '启动页面', scopes: [], path: '/settings?category=startup' },
  { id: 'settings-session', label: '当前会话', scopes: [], path: '/settings?category=security&section=session' },
  { id: 'settings-services', label: '运行状态', scopes: ['auth:read'], path: '/settings?category=services' },
  { id: 'settings-system', label: '系统环境', scopes: ['auth:read'], path: '/settings?category=system' },
  { id: 'settings-accounts', label: '用户管理', scopes: ['auth:read'], path: '/settings?category=security&section=accounts' },
] as const
export type PageId = typeof pageDefinitions[number]['id']
export function canAccessPage(user: CurrentUser | null, id: string): boolean {
  const page = pageDefinitions.find((item) => item.id === id)
  return Boolean(user && page && (user.allowed_pages == null || user.allowed_pages.includes(id)) && hasScopes(user, [...page.scopes]))
}
export function canInvokeWorkflow(user: CurrentUser | null): boolean {
  return hasScope(user, 'workflows:write') || hasScopes(user, ['workflows:read', 'workflows:invoke'])
}
export function canReadProjectFiles(user: CurrentUser | null): boolean {
  return hasScope(user, 'projects:files:read') || hasScopes(user, ['workflows:read', 'models:read'])
}
export function settingsPath(user: CurrentUser | null): string | null {
  if (user?.allowed_pages == null && canAccessPage(user, 'settings-system')) return '/settings'
  return pageDefinitions.find((page) => page.id.startsWith('settings-') && canAccessPage(user, page.id))?.path ?? null
}
export function pageForPath(path: string): string | null {
  const url = new URL(path, 'http://local')
  const p = url.pathname
  if (p === '/settings') {
    const category = url.searchParams.get('category') || 'system'
    if (category === 'security') return url.searchParams.get('section') === 'accounts' ? 'settings-accounts' : 'settings-session'
    return `settings-${category}`
  }
  if (/^\/workflows\/runtime\/[^/]+\/app-mode\/?$/.test(p)) return 'workflow-app-mode'
  if (/^\/workflows\/runtime\/[^/]+\/monitor\/?$/.test(p)) return 'workflow-monitor'
  if (p.startsWith('/workflows/graph') || p.endsWith('/edit') && p.startsWith('/workflows/apps/')) return 'workflow-graph'
  if (p === '/workflows/apps/new' || p.startsWith('/workflows/templates')) return 'workflow-graph'
  if (p === '/workflows' || p.startsWith('/workflows/apps') || p.startsWith('/workflows/applications')) return 'workflow-apps'
  return pageDefinitions.find((page) => page.path && !page.path.includes('?') && (p === page.path || p.startsWith(page.path + '/')))?.id ?? null
}
export function canAccessPath(user: CurrentUser | null, path: string): boolean {
  if (!path.startsWith('/') || path.startsWith('//') || path.includes('\\')) return false
  try {
    const pathname = new URL(path, 'http://local').pathname
    if (['/workflows/graph', '/workflows/graph/new', '/workflows/apps/new', '/workflows/templates/new'].includes(pathname) && !hasScope(user, 'workflows:write')) return false
    const page = pageForPath(path)
    return Boolean(page && canAccessPage(user, page))
  } catch { return false }
}
export function firstAccessiblePath(user: CurrentUser | null): string {
  // 旧账号保留项目首页习惯；显式账号首次进入个人启动设置自行选择。
  if (user?.allowed_pages == null && canAccessPage(user, 'projects')) return '/projects'
  if (canAccessPage(user, 'settings-startup')) return '/settings?category=startup'
  return pageDefinitions.find((page) => page.path && canAccessPath(user, page.path))?.path ?? '/forbidden'
}
