import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'

const baseId = '00000000-0000-4000-8000-000000000001'
const authoringPage = { code: 'document_create', name: '创建文档', route_path: '/create-document', route_name: 'DocumentCreate', component_key: 'DocumentCreate', page_type: 'menu', sort_order: 45, is_visible: true }
interface Submission { request_id: string; title: string; format: string; content: unknown; knowledge_base_id: string }
async function setup(page: Page, options: { failOnce?: boolean; allowed?: boolean; noBases?: boolean } = {}) {
  const submissions: Submission[] = []
  let saved: unknown
  await page.route('**/api/v1/**', async route => {
    const path = new URL(route.request().url()).pathname
    let data: unknown
    if (path.endsWith('/auth/refresh')) {
      data = { access_token: 'test-token', user: { id: 'writer', display_name: 'Writer', role: 'writer', role_name: '编辑者' }, pages: options.allowed === false ? [] : [authoringPage] }
    } else if (path.endsWith('/knowledge-bases')) {
      data = { items: options.noBases ? [] : [{ id: baseId, name: '设备知识库', status: 'active' }] }
    } else if (path.endsWith('/documents/create')) {
      const body: Submission = route.request().postDataJSON()
      submissions.push(body)
      if (options.failOnce && submissions.length === 1) {
        await route.fulfill({ status: 503, json: { code: 50301, message: '存储暂不可用', data: null } })
        return
      }
      saved = { document: { id: body.request_id, title: body.title, knowledge_base_id: baseId },
        version: { filename: `${body.title}.${body.format}`, status: 'INDEXED', error_message: null, task: { status: 'SUCCESS', error_message: null } } }
      data = saved
    } else if (path.includes('/documents/created/')) {
      data = saved
    } else {
      throw new Error(`Unexpected API: ${path}`)
    }
    await route.fulfill({ json: { code: 0, data } })
  })
  return submissions
}
async function metadata(page: Page, title: string) {
  await page.getByRole('textbox', { name: '文档标题', exact: true }).fill(title)
  await page.getByRole('combobox', { name: '保存到知识库' }).click()
  await page.getByRole('option', { name: '设备知识库', exact: true }).click()
}

test('assigned role can create a Markdown document with preview and save it once', async ({ page }) => {
  const submissions = await setup(page)
  await page.goto('/create-document')
  await metadata(page, '设备手册')
  const content = '# 设备指南\n\n- **检查电源**\n- 启动设备'
  await page.getByRole('textbox', { name: 'Markdown 文档正文' }).fill(content)
  await expect(page.locator('.authoring-preview h1')).toHaveText('设备指南')
  await expect(page.locator('.authoring-preview li')).toHaveCount(2)
  await page.getByRole('button', { name: '保存到知识库', exact: true }).click()
  await expect(page.getByText('设备手册.md 已保存，可用于知识问答')).toBeVisible()
  expect(submissions).toHaveLength(1)
  expect(submissions[0]).toMatchObject({ title: '设备手册', format: 'md', knowledge_base_id: baseId, content })
  await expect(page.getByRole('button', { name: '保存到知识库', exact: true })).toBeDisabled()
  await expect(page.getByRole('button', { name: '查看知识库文档', exact: true })).toHaveCount(0)
  await page.getByRole('button', { name: '继续创建下一篇' }).click()
  await expect(page.getByRole('textbox', { name: '文档标题', exact: true })).toHaveValue('')
})

test('Word editor saves alignment, font, highlight and a table as a docx draft', async ({ page }) => {
  const submissions = await setup(page)
  await page.goto('/create-document')
  await metadata(page, 'Word 设备指南')
  await page.getByText('Word', { exact: true }).click()
  const editor = page.getByRole('textbox', { name: 'Word 文档正文' })
  await editor.fill('检查电源')
  await editor.press('ControlOrMeta+a')
  await page.locator('.umo-toolbar button:has(use[*|href="#umo-icon-bold"])').click()
  await expect(editor.locator('b')).toHaveText('检查电源')
  await page.locator('.umo-toolbar button:has(use[*|href="#umo-icon-align-center"])').click()
  await expect(editor.locator('p').first()).toHaveCSS('text-align', 'center')
  await page.getByRole('textbox', { name: '选择字体', exact: true }).click()
  await page.locator('.umo-select-option').getByText('宋体', { exact: true }).click()
  await page.locator('.umo-toolbar button:has(use[*|href="#umo-icon-highlight"]) .umo-button-content').click()
  await editor.press('ArrowRight')
  await editor.press('ControlOrMeta+End')
  await editor.press('Enter')
  await expect(editor).toContainText('检查电源')
  await page.locator('.umo-ribbon-tabs-item').getByText('表格', { exact: true }).click()
  await page.locator('.umo-toolbar button:has(use[*|href="#umo-icon-table"])').click()
  await page.locator('.umo-table-grid .row').nth(2).locator('.cell').nth(1).click()
  await expect(editor.locator('table')).toBeVisible()
  await expect(editor).toContainText('检查电源')
  await page.getByRole('button', { name: '保存到知识库', exact: true }).click()
  await expect(page.getByText('Word 设备指南.docx 已保存，可用于知识问答')).toBeVisible()
  expect(submissions[0]?.format).toBe('docx')
  const json = JSON.stringify(submissions[0]?.content)
  expect(json).toContain('"type":"bold"')
  expect(json).toContain('"type":"table"')
  expect(json).toContain('检查电源')
  expect(json).toContain('"textAlign":"center"')
  expect(json).toContain('"fontFamily":"SimSun"')
  expect(json).toContain('"backgroundColor":"#ffff8a"')
  expect(json).toContain('"page":')
})

test('save failure preserves the draft and retry keeps its request ID', async ({ page }) => {
  const submissions = await setup(page, { failOnce: true })
  await page.goto('/create-document')
  await metadata(page, '重试文档')
  await page.getByRole('textbox', { name: 'Markdown 文档正文' }).fill('需要保留的正文')
  const save = page.getByRole('button', { name: '保存到知识库', exact: true })
  await save.click()
  await expect(page.getByText('存储暂不可用')).toBeVisible()
  await expect(page.getByRole('textbox', { name: 'Markdown 文档正文' })).toHaveValue('需要保留的正文')
  await save.click()
  await expect(page.getByText('重试文档.md 已保存，可用于知识问答')).toBeVisible()
  expect(submissions).toHaveLength(2)
  expect(submissions[0]?.request_id).toBe(submissions[1]?.request_id)
})

test('draft survives refresh and format switch can be cancelled', async ({ page }) => {
  await setup(page)
  page.on('dialog', dialog => dialog.accept())
  await page.goto('/create-document')
  await metadata(page, '本地草稿')
  await page.getByRole('textbox', { name: 'Markdown 文档正文' }).fill('# 保留正文')
  await page.reload()
  await expect(page.getByRole('textbox', { name: '文档标题', exact: true })).toHaveValue('本地草稿')
  await expect(page.getByRole('textbox', { name: 'Markdown 文档正文' })).toHaveValue('# 保留正文')
  await page.getByText('Word', { exact: true }).click()
  await page.getByRole('button', { name: '继续编辑', exact: true }).click()
  await expect(page.getByRole('textbox', { name: 'Markdown 文档正文' })).toHaveValue('# 保留正文')
})

test('empty knowledge base list keeps save disabled', async ({ page }) => {
  await setup(page, { noBases: true })
  await page.goto('/create-document')
  await expect(page.getByText('暂无可用知识库，请联系管理员创建并启用知识库。')).toBeVisible()
  await page.getByRole('textbox', { name: '文档标题', exact: true }).fill('草稿')
  await page.getByRole('textbox', { name: 'Markdown 文档正文' }).fill('正文')
  await expect(page.getByRole('button', { name: '保存到知识库', exact: true })).toBeDisabled()
})

test('unassigned role cannot enter document creation', async ({ page }) => {
  const submissions = await setup(page, { allowed: false })
  await page.goto('/create-document')
  await expect(page).toHaveURL(/\/403$/)
  expect(submissions).toHaveLength(0)
})

test('Word paper starts inside its margins, expands fullscreen, and toolbar save uploads', async ({ page }) => {
  const submissions = await setup(page)
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  await page.setViewportSize({ width: 1600, height: 1000 })
  await page.goto('/create-document')
  await metadata(page, '版式检查')
  await page.getByText('Word', { exact: true }).click()
  const editor = page.getByRole('textbox', { name: 'Word 文档正文' })
  await editor.fill('从正文页边距开始输入')
  const margins = await editor.evaluate(element => {
    const paragraph = element.querySelector('p')!.getBoundingClientRect()
    const paper = element.closest('.umo-page-content')!.getBoundingClientRect()
    return { leftRatio: (paragraph.left - paper.left) / paper.width, topRatio: (paragraph.top - paper.top) / paper.width }
  })
  // A4: 3.18 cm left margin, 2.54 cm top margin. Scaling must preserve both.
  expect(margins.leftRatio).toBeCloseTo(3.18 / 21, 2)
  expect(margins.topRatio).toBeGreaterThan(0.10)
  await page.getByRole('button', { name: '全屏编辑', exact: true }).click()
  const full = page.locator('.umo-editor-is-fullscreen')
  await expect(full).toBeVisible()
  expect((await full.boundingBox())!.height).toBe(1000)
  await page.getByRole('button', { name: '未保存到知识库', exact: true }).click()
  await page.locator('.umo-document-status-container').getByRole('button', { name: '保存到知识库', exact: true }).click()
  await expect(page.getByText('版式检查.docx 已保存，可用于知识问答')).toBeVisible()
  expect(submissions).toHaveLength(1)
  await expect(editor).toHaveAttribute('contenteditable', 'false')
  expect(errors).toEqual([])
})

test('Word draft restores alignment and font without making external requests', async ({ page }) => {
  await setup(page)
  const externalRequests: string[] = []
  page.on('request', request => {
    if (new URL(request.url()).hostname !== '127.0.0.1') externalRequests.push(request.url())
  })
  page.on('dialog', dialog => dialog.accept())
  await page.goto('/create-document')
  await metadata(page, 'Word 草稿')
  await page.getByText('Word', { exact: true }).click()
  const editor = page.getByRole('textbox', { name: 'Word 文档正文' })
  await editor.fill('需要恢复的正文')
  await page.locator('.umo-toolbar button:has(use[*|href="#umo-icon-align-center"])').click()
  await page.reload()
  await expect(editor).toContainText('需要恢复的正文')
  await expect(editor.locator('p').first()).toHaveCSS('text-align', 'center')
  expect(externalRequests).toEqual([])
})

async function openWord(page: Page) {
  await setup(page)
  await page.goto('/create-document')
  await page.getByText('Word', { exact: true }).click()
  const editor = page.getByRole('textbox', { name: 'Word 文档正文' })
  await expect(editor).toBeVisible()
  return editor
}

test('repeated Tab keeps the first character inside the text area', async ({ page }) => {
  const editor = await openWord(page)
  await editor.click()
  for (let index = 0; index < 20; index++) await editor.press('Tab')
  await expect(editor).toBeFocused()
  await page.keyboard.insertText('2')
  await expect(editor).toContainText('2')
  const geometry = await editor.evaluate(element => {
    const paragraph = element.querySelector('p')!
    const range = document.createRange()
    range.selectNodeContents(paragraph)
    const text = range.getBoundingClientRect()
    const block = paragraph.getBoundingClientRect()
    return { textRight: text.right, blockRight: block.right, indent: getComputedStyle(paragraph).textIndent }
  })
  expect(geometry.textRight, JSON.stringify(geometry)).toBeLessThanOrEqual(geometry.blockRight)
})

test('Backspace at the start of an inherited indented paragraph clears formatting', async ({ page }) => {
  const editor = await openWord(page)
  await editor.fill('第一段')
  await editor.press('Tab')
  await editor.press('Enter')
  await editor.press('Backspace')
  await expect(editor.locator('p')).toHaveCount(2)
  await expect(editor.locator('p').last()).toHaveCSS('text-indent', '0px')
})

test('long text flows onto additional sheets automatically', async ({ page }) => {
  const editor = await openWord(page)
  await editor.fill('自动分页验证。'.repeat(1000))
  await expect.poll(async () => editor.evaluate(element => {
    const paper = element.closest('.umo-page-content')!
    return Number(paper.getAttribute('data-page-count') || 1)
  })).toBeGreaterThan(1)
  await expect.poll(async () => editor.evaluate(element => {
    const paragraph = element.querySelector('p')!
    const range = document.createRange()
    range.selectNodeContents(paragraph)
    const paper = element.closest('.umo-page-content')!
    const box = paper.getBoundingClientRect()
    const zoom = box.width / (21 * 96 / 2.54)
    const pageHeight = 29.7 * 96 / 2.54
    const margin = 2.54 * 96 / 2.54
    return Array.from(range.getClientRects()).map(rect => {
      const top = (rect.top - box.top) / zoom
      const local = top % (pageHeight + 24)
      return { top: local, bottom: local + rect.height / zoom }
    }).filter(rect => rect.top < margin - 3 || rect.bottom > pageHeight - margin + 3)
  })).toEqual([])
  await editor.evaluate(el => { const viewport = el.closest<HTMLElement>('.umo-zoomable-container')!; viewport.style.scrollBehavior = 'auto'; viewport.scrollTop = 1000 })
  await page.screenshot({ path: '/tmp/kbs-auto-pagination.png', fullPage: true })
})

test('body after a heading returns to the text margin on subsequent Enter', async ({ page }) => {
  const editor = await openWord(page)
  await editor.fill('标题示例')
  await page.locator('.umo-toolbar').getByText('标题 1', { exact: true }).click()
  await editor.press('ControlOrMeta+End')
  await editor.press('Enter')
  await page.keyboard.insertText('正文示例')
  await editor.press('Enter')
  await page.keyboard.insertText('第二段正文')
  await expect(editor.locator('h1')).toHaveCount(1)
  const offsets = await editor.locator('p').evaluateAll(paragraphs => paragraphs.filter(p => p.textContent).map(p => {
    const range = document.createRange()
    range.selectNodeContents(p)
    return { left: range.getBoundingClientRect().left - p.getBoundingClientRect().left, indent: getComputedStyle(p).textIndent, margin: getComputedStyle(p).marginLeft }
  }))
  expect(offsets).toEqual([{ left: 0, indent: '0px', margin: '0px' }, { left: 0, indent: '0px', margin: '0px' }])
})

test('paragraph settings and context menu apply first-line indent and can clear it', async ({ page }) => {
  const editor = await openWord(page)
  await editor.fill('第一段正文')
  await page.getByRole('button', { name: '段落设置', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: '段落设置', exact: true })
  await dialog.getByRole('spinbutton', { name: '首行缩进（字符）' }).fill('2')
  await dialog.getByRole('spinbutton', { name: '左侧缩进（厘米）' }).fill('1')
  await dialog.getByRole('button', { name: '应用段落设置' }).click()
  await expect(editor.locator('p').first()).toHaveCSS('text-indent', '28px')
  await editor.press('End')
  await editor.press('Enter')
  await page.keyboard.insertText('第二段正文')
  await expect(editor.locator('p').last()).toHaveCSS('text-indent', '28px')
  await editor.press('ControlOrMeta+a')
  await editor.locator('p').last().click({ button: 'right' })
  await page.getByRole('menuitem', { name: '清除缩进 / 退出列表' }).click()
  for (const paragraph of await editor.locator('p').all()) {
    await expect(paragraph).toHaveCSS('text-indent', '0px')
    await expect(paragraph).toHaveCSS('margin-left', '0px')
  }
})

test('numbered heading, body, repeated heading and body do not drift right', async ({ page }) => {
  const editor = await openWord(page)
  await editor.click()
  for (const [heading, body] of [['1. 测试缩进', '正文一'], ['2. 测试', '正文二'], ['缩进问题', '正文三']]) {
    await page.locator('.umo-toolbar').getByText('标题 1', { exact: true }).click()
    await page.keyboard.type(heading!)
    await page.keyboard.press('Enter')
    await page.locator('.umo-toolbar').getByText('正文', { exact: true }).click()
    await page.keyboard.type(body!)
    await page.keyboard.press('Enter')
    await page.keyboard.type('连续正文')
    await page.keyboard.press('Enter')
  }
  const offsets = await editor.locator('p').evaluateAll(nodes => nodes.filter(node => node.textContent).map(node => {
    const range = document.createRange()
    range.selectNodeContents(node)
    const root = node.closest('.umo-editor')!
    const zoom = root.getBoundingClientRect().width / root.clientWidth
    return Math.round((range.getBoundingClientRect().left - root.getBoundingClientRect().left) / zoom - parseFloat(getComputedStyle(root).paddingLeft))
  }))
  expect(offsets.every(offset => Math.abs(offset) <= 1), JSON.stringify(offsets)).toBe(true)
})

test('fullscreen can be exited by button and Escape, paragraph buttons fit the toolbar', async ({ page }) => {
  await openWord(page)
  await page.getByRole('button', { name: '全屏编辑', exact: true }).click()
  await page.getByRole('button', { name: '退出全屏 · Esc', exact: true }).click()
  await expect(page.locator('.umo-editor-is-fullscreen')).toHaveCount(0)
  await page.getByRole('button', { name: '全屏编辑', exact: true }).click()
  await page.getByRole('textbox', { name: 'Word 文档正文' }).click()
  await page.keyboard.press('Escape')
  await expect(page.locator('.umo-editor-is-fullscreen')).toHaveCount(0)
  const fits = await page.locator('.paragraph-actions').evaluate(element => {
    const box = element.getBoundingClientRect()
    return Array.from(element.querySelectorAll('button')).every(button => {
      const bounds = button.getBoundingClientRect()
      return bounds.top >= box.top && bounds.bottom <= box.bottom
    })
  })
  expect(fits).toBe(true)
})

test('explicit page break moves following content onto a new sheet', async ({ page }) => {
  const editor = await openWord(page)
  await editor.fill('第一页')
  await editor.press('Control+Enter')
  await page.keyboard.insertText('第二页')
  await expect(page.locator('.umo-page-break')).toHaveCount(1)
  await expect.poll(async () => editor.locator('p').filter({ hasText: '第二页' }).evaluate(element => {
    const paper = element.closest('.umo-page-content')!
    const box = paper.getBoundingClientRect()
    return (element.getBoundingClientRect().top - box.top) / (box.width / (21 * 96 / 2.54))
  })).toBeGreaterThan(29.7 * 96 / 2.54)
})
