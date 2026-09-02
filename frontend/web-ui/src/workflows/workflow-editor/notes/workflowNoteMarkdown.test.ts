import { describe, expect, it } from 'vitest'

import { renderWorkflowNoteMarkdown } from './workflowNoteMarkdown'

describe('workflow note markdown', () => {
  it('渲染常用 Markdown 并统一安全链接属性', () => {
    const html = renderWorkflowNoteMarkdown('## 操作说明\n\n- 输入图片\n- [打开文档](https://example.com/help)')

    expect(html).toContain('<h2>操作说明</h2>')
    expect(html).toContain('<li>输入图片</li>')
    expect(html).toContain('href="https://example.com/help"')
    expect(html).toContain('target="_blank"')
    expect(html).toContain('rel="noopener noreferrer"')
  })

  it('阻断原始 HTML、事件属性、危险链接和远程图片', () => {
    const html = renderWorkflowNoteMarkdown([
      '<script>alert(1)</script>',
      '<img src=x onerror=alert(2)>',
      '[危险链接](javascript:alert(3))',
      '[相对路径](./local-help)',
      '[邮件](mailto:ops@example.com)',
      '![远程图片](https://example.com/a.png)',
    ].join('\n\n'))

    expect(html).not.toContain('<script')
    expect(html).not.toContain('<img')
    expect(html).not.toContain('onerror')
    expect(html).not.toContain('javascript:')
    expect(html).not.toContain('./local-help')
    expect(html).not.toContain('mailto:')
    expect(html).not.toContain('https://example.com/a.png')
    expect(html).toContain('远程图片')
  })
})
