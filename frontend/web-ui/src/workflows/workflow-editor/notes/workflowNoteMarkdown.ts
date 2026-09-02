import DOMPurify from 'dompurify'
import { marked, Renderer } from 'marked'

const allowedTags = [
  'a', 'blockquote', 'br', 'code', 'del', 'em', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'hr',
  'li', 'ol', 'p', 'pre', 'strong', 'table', 'tbody', 'td', 'th', 'thead', 'tr', 'ul',
]

function escapeHtml(value: string): string {
  return value
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;')
}

function readSafeLinkHref(value: string): string | null {
  const normalized = value.trim()
  if (!normalized) return null
  try {
    const url = new URL(normalized)
    return url.protocol === 'http:' || url.protocol === 'https:' ? normalized : null
  } catch {
    return null
  }
}

function createNoteRenderer(): Renderer {
  const renderer = new Renderer()
  renderer.html = () => ''
  renderer.image = ({ text }) => `<span>${escapeHtml(text)}</span>`
  renderer.link = function ({ href, title, tokens }) {
    const label = this.parser.parseInline(tokens)
    const safeHref = readSafeLinkHref(href)
    if (!safeHref) return label
    const titleAttribute = title ? ` title="${escapeHtml(title)}"` : ''
    return `<a href="${escapeHtml(safeHref)}" target="_blank" rel="noopener noreferrer"${titleAttribute}>${label}</a>`
  }
  return renderer
}

/**
 * 将说明节点的 Markdown 子集渲染为经过白名单清理的 HTML。
 * 原始 HTML、远程图片和危险链接协议不会进入输出。
 */
export function renderWorkflowNoteMarkdown(content: string): string {
  const rendered = marked.parse(content, {
    async: false,
    breaks: true,
    gfm: true,
    renderer: createNoteRenderer(),
  }) as string
  return DOMPurify.sanitize(rendered, {
    ALLOWED_TAGS: allowedTags,
    ALLOWED_ATTR: ['href', 'rel', 'target', 'title'],
    ALLOW_DATA_ATTR: false,
  })
}
