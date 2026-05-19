export interface NavigationItem {
  label: string
  path: string
  icon: 'FolderKanban' | 'ListChecks' | 'Database' | 'Cpu' | 'Rocket' | 'Workflow' | 'Cable' | 'Blocks' | 'Settings'
  requiredScopes: string[]
}

export const navigationItems: NavigationItem[] = [
  { label: '项目', path: '/projects', icon: 'FolderKanban', requiredScopes: ['workflows:read', 'models:read'] },
  { label: '任务', path: '/tasks', icon: 'ListChecks', requiredScopes: ['tasks:read'] },
  { label: '数据集', path: '/datasets', icon: 'Database', requiredScopes: ['datasets:read'] },
  { label: '模型', path: '/models', icon: 'Cpu', requiredScopes: ['models:read'] },
  { label: '部署', path: '/deployments', icon: 'Rocket', requiredScopes: ['models:read'] },
  { label: '流程', path: '/workflows/templates', icon: 'Workflow', requiredScopes: ['workflows:read'] },
  { label: '集成', path: '/integrations/trigger-sources', icon: 'Cable', requiredScopes: ['workflows:read'] },
  { label: '节点', path: '/custom-nodes', icon: 'Blocks', requiredScopes: ['workflows:read'] },
  { label: '设置', path: '/settings', icon: 'Settings', requiredScopes: ['auth:read'] },
]