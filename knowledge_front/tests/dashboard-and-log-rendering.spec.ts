import { expect, test } from '@playwright/test'

const routePage = (path: string, name: string, component: string, extra = {}) => ({
  code: component, name, route_path: path, route_name: component, component_key: component,
  page_type: 'menu', sort_order: 1, is_visible: true, ...extra,
})
const dashboard = routePage('/dashboard', '工作台', 'Dashboard')
const profile = routePage('/profile', '个人信息', 'Profile')
const knowledgeBase = routePage('/knowledge-bases', '知识库管理', 'KnowledgeBaseManagement')
const qa = routePage('/qa', '知识问答', 'KnowledgeQA')
const logs = routePage('/qa-logs', '问答日志', 'QALogs')

for (const allowed of [[], [profile], [knowledgeBase, qa, profile]]) {
  test(`dashboard only offers authorized routes: ${allowed.map(item => item.route_path).join(', ')}`, async ({ page }) => {
    await page.route('**/api/v1/**', async route => {
      const path = new URL(route.request().url()).pathname
      let data: unknown
      if (path === '/api/v1/auth/refresh') {
        data = { access_token: 'test-token', user: { id: 'reader', display_name: 'Reader', role: 'user' },
          pages: [dashboard, ...allowed,
            routePage('/robots', '隐藏机器人', 'RobotManagement', { is_visible: false }),
            routePage('/unsupported', '未知页面', 'MissingComponent'),
            routePage('/button', '操作按钮', 'UserManagement', { page_type: 'button' }),
          ] }
      } else if (path === '/api/v1/dashboard') {
        data = { knowledge_base_count: 2, document_count: 8, robot_count: 3, user_count: 7 }
      } else {
        throw new Error(`Unexpected request: ${path}`)
      }
      await route.fulfill({ json: { code: 0, data } })
    })
    await page.goto('/dashboard')
    await expect(page.getByRole('heading', { name: '工作台' })).toBeVisible()
    await expect(page.locator('.quick-links button')).toHaveText(allowed.map(item => new RegExp(item.name)))
    await expect(page.locator('.metric-card')).toHaveCount(allowed.includes(knowledgeBase) ? 1 : 0)
    await expect(page.getByRole('button', { name: '前往知识问答' })).toHaveCount(allowed.includes(qa) ? 1 : 0)
    await expect(page.getByText('平台建设进度')).toHaveCount(0)
    await page.goto('/users')
    await expect(page).toHaveURL(/\/403$/)
  })
}

const answer = '# 操作步骤\n\n请先**检查电源**。[1]\n\n| 项目 | 结果 |\n| --- | --- |\n| 电源 | 正常 |\n\n```bash\necho ready\n```\n\n<img src=x onerror="window.renderingUnsafe = true">'
const source = {
  source_id: '1', chunk_id: 'chunk', document_id: 'document', version_id: 'version', version_no: 1,
  filename: 'guide.md', document_title: '操作手册', modality: 'text', score: 0.9,
  content: '## 使用说明\n\n- **检查电源**\n- 启动设备\n\n```bash\necho ready\n```',
}
const pdfSource = { ...source, source_id: '2', chunk_id: 'pdf-chunk', filename: 'guide.PDF',
  content: '接口说明\n\n1. 检查电源\n2. 启动设备\n\nx² < 10' }

test('QA log details render Markdown answers and sources safely', async ({ page }) => {
  await page.route('**/api/v1/**', async route => {
    const path = new URL(route.request().url()).pathname
    const detail = { id: 'log', question: '如何启动？', answer, sources: [source, pdfSource], status: 'SUCCESS',
      source_type: 'WEB', created_at: '2026-10-27T00:00:00Z', request_id: 'test-request' }
    const data = path.endsWith('/auth/refresh')
      ? { access_token: 'test-token', user: { id: 'admin', display_name: 'Admin', role: 'super_admin' }, pages: [logs] }
      : path.endsWith('/qa-logs') ? { items: [detail], total: 1 } : detail
    await route.fulfill({ json: { code: 0, data } })
  })
  await page.goto('/qa-logs')
  await page.getByRole('button', { name: '查看详情' }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog.getByRole('heading', { name: '操作步骤' })).toBeVisible()
  await expect(dialog.locator('.qa-answer table')).toContainText('电源')
  await expect(dialog.locator('.qa-answer pre code')).toHaveText('echo ready\n')
  await expect(dialog.locator('.qa-source-content h2')).toHaveText('使用说明')
  await expect(dialog.locator('.qa-source-content li')).toHaveCount(2)
  await expect(dialog.locator('[onerror]')).toHaveCount(0)
  await expect(dialog.locator('.source-plain-text')).toHaveText(pdfSource.content)
  await expect(dialog.locator('.source-plain-text')).toHaveCSS('white-space', 'pre-wrap')
})

test('knowledge QA renders Markdown and preserves PDF citation text and line breaks', async ({ page }) => {
  await page.route('**/api/v1/**', async route => {
    const path = new URL(route.request().url()).pathname
    let data: unknown
    if (path.endsWith('/auth/refresh')) {
      data = { access_token: 'test-token', user: { id: 'reader', display_name: 'Reader', role: 'user' }, pages: [qa] }
    } else if (path.endsWith('/knowledge-bases')) {
      data = { items: [{ id: 'base', name: '设备资料', status: 'active' }] }
    } else if (path.endsWith('/web/suggested-questions')) {
      data = { questions: [], status: 'empty' }
    } else if (path.endsWith('/web/query')) {
      data = { answer, sources: [source, pdfSource], answer_status: 'answered' }
    } else {
      throw new Error(`Unexpected request: ${path}`)
    }
    await route.fulfill({ json: { code: 0, data } })
  })
  await page.goto('/qa')
  await page.getByRole('textbox', { name: '你的问题' }).fill('如何启动？')
  await page.getByRole('button', { name: '发送问题' }).click()
  await expect(page.locator('.answer-body h1')).toHaveText('操作步骤')
  await expect(page.locator('.answer-body table')).toContainText('电源')
  await expect(page.locator('.source-markdown h2')).toHaveText('使用说明')
  await expect(page.locator('.source-plain-text')).toHaveText(pdfSource.content)
  await expect(page.locator('.source-plain-text')).toHaveCSS('white-space', 'pre-wrap')
  await expect(page.locator('[onerror]')).toHaveCount(0)
})

test('audit log shows the operator name instead of their ID', async ({ page }) => {
  await page.route('**/api/v1/**', async route => {
    const path = new URL(route.request().url()).pathname
    const data = path.endsWith('/auth/refresh')
      ? { access_token: 'test-token', user: { id: 'admin', display_name: 'Admin', role: 'super_admin' },
          pages: [routePage('/audit-logs', '审计日志', 'AuditLogs')] }
      : { items: [{ id: 'audit', action: 'user.update', resource_type: 'user', user_id: 'internal-user-uuid',
          user_name: '张三', ip_address: '127.0.0.1', created_at: '2026-10-27T00:00:00Z' }], total: 1 }
    await route.fulfill({ json: { code: 0, data } })
  })
  await page.goto('/audit-logs')
  await expect(page.getByRole('columnheader', { name: '操作人', exact: true })).toBeVisible()
  await expect(page.locator('.el-table__body-wrapper')).toContainText('张三')
  await expect(page.locator('.el-table__body-wrapper')).not.toContainText('internal-user-uuid')
})

for (const path of ['/qa', '/qa-logs']) {
  test(`${path} preserves Word citation styles, lists and tables safely`, async ({ page }) => {
    const word = { ...source, filename: 'guide.docx', content: '红色斜体\n列表\n单元格', content_html:
      '<p style="text-align:center"><span style="font-weight:700;font-style:italic;color:#ff0000">红色斜体</span></p><ol start="3"><li>列表</li></ol><table><tr><td colspan="2">单元格</td></tr></table><script>window.wordUnsafe=true</script><img src=x onerror="window.wordUnsafe=true"><a href="javascript:alert(1)">危险链接</a>' }
    await page.route('**/api/v1/**', async route => {
      const url = new URL(route.request().url()).pathname
      const detail = { id: 'log', question: '格式测试', answer: '依据资料回答。[1]', sources: [word, pdfSource], status: 'SUCCESS', answer_status: 'answered', source_type: 'WEB', created_at: '2026-10-28T00:00:00Z', request_id: 'word-test' }
      let data: unknown = detail
      if (url.endsWith('/auth/refresh')) data = { access_token: 'test-token', user: { id: 'reader', display_name: 'Reader', role: 'user' }, pages: [qa, logs] }
      else if (url.endsWith('/knowledge-bases')) data = { items: [{ id: 'base', name: '设备资料', status: 'active' }] }
      else if (url.endsWith('/web/suggested-questions')) data = { questions: [], status: 'empty' }
      else if (url.endsWith('/qa-logs')) data = { items: [detail], total: 1 }
      await route.fulfill({ json: { code: 0, data } })
    })
    await page.goto(path)
    if (path === '/qa') {
      await page.getByRole('textbox', { name: '你的问题' }).fill('格式测试')
      await page.getByRole('button', { name: '发送问题' }).click()
    } else {
      await page.getByRole('button', { name: '查看详情' }).click()
    }
    const rich = page.locator('.word-content')
    await expect(rich.locator('p')).toHaveCSS('text-align', 'center')
    await expect(rich.locator('span')).toHaveCSS('font-weight', '700')
    await expect(rich.locator('span')).toHaveCSS('font-style', 'italic')
    await expect(rich.locator('span')).toHaveCSS('color', 'rgb(255, 0, 0)')
    await expect(rich.locator('ol')).toHaveAttribute('start', '3')
    await expect(rich.locator('td')).toHaveAttribute('colspan', '2')
    await expect(rich.locator('script, img, [onerror], [href^="javascript:"]')).toHaveCount(0)
    expect(await page.evaluate(() => (window as unknown as { wordUnsafe?: boolean }).wordUnsafe)).toBeUndefined()
    await expect(page.locator('.source-plain-text')).toHaveText(pdfSource.content)
  })
}

for (const path of ['/qa', '/qa-logs']) {
  test(`${path} renders Excel citation cells as tables with sheets, coordinates and literal content`, async ({ page }) => {
    const excel = { ...source, filename: '部门全年收支表.XLSX', document_title: '部门全年收支表', content: [
      '工作表：收支',
      'A1：部门\\月份', 'B1：1', 'C1：2', 'H1：合计',
      'A2：开发部门', 'B2：23452', 'C2：123124', 'H2：=SUM(B2:G2)',
      'A3：测试部门', 'B3：23551', 'C3：12321', 'H3：265448',
      'G5：总额', 'H5：809127',
      '工作表：说明', 'A1：**原样内容** | A2: 单元格内说明',
      '第二行说明', 'C1：<img src=x onerror="window.excelUnsafe=true">',
    ].join('\n') }
    const partial = { ...source, source_id: '2', chunk_id: 'partial-excel', filename: '旧版.xls',
      content: '上个单元格的截断片段\nB12：00123\nAA12：0\nB13：-2.5\nAA13：尾部片段' }
    const fallback = { ...source, source_id: '3', chunk_id: 'unknown-excel', filename: '旧记录.xlsx',
      content: '历史表格文本\n无法还原的引用片段\n<iframe src="https://example.com"></iframe>' }
    const sparse = { ...source, source_id: '4', chunk_id: 'sparse-excel', filename: '稀疏.xlsx',
      content: '工作表：稀疏引用\nA1：起点\nXFD1048576：末端' }
    const overlapping = { ...source, source_id: '5', chunk_id: 'overlapping-excel', filename: '重叠.xlsx',
      content: 'A1：第一段\nA1：第二段' }
    const detail = { id: 'log', question: '收支是多少？', answer: '总额 809127。[1]', sources: [excel, partial, fallback, sparse, overlapping, pdfSource],
      status: 'SUCCESS', answer_status: 'answered', source_type: 'WEB', created_at: '2026-10-29T00:00:00Z', request_id: 'excel-citation' }
    await page.route('**/api/v1/**', async route => {
      const url = new URL(route.request().url()).pathname
      let data: unknown = detail
      if (url.endsWith('/auth/refresh')) data = { access_token: 'test-token', user: { id: 'reader', display_name: 'Reader', role: 'user' }, pages: [qa, logs] }
      else if (url.endsWith('/knowledge-bases')) data = { items: [{ id: 'base', name: '设备资料', status: 'active' }] }
      else if (url.endsWith('/web/suggested-questions')) data = { questions: [], status: 'empty' }
      else if (url.endsWith('/qa-logs')) data = { items: [detail], total: 1 }
      await route.fulfill({ json: { code: 0, data } })
    })
    await page.goto(path)
    if (path === '/qa') {
      await page.getByRole('textbox', { name: '你的问题' }).fill('收支是多少？')
      await page.getByRole('button', { name: '发送问题' }).click()
    } else {
      await page.getByRole('button', { name: '查看详情' }).click()
    }
    const table = page.getByRole('table', { name: '工作表：收支', exact: true })
    await expect(table).toBeVisible()
    await expect(table.getByRole('columnheader')).toHaveText(['行', 'A', 'B', 'C', 'D', 'E', 'F', 'G', 'H'])
    await expect(table.locator('[data-cell="A2"]')).toHaveText('开发部门')
    await expect(table.locator('[data-cell="B2"]')).toHaveText('23452')
    await expect(table.locator('[data-cell="D2"]')).toHaveText('')
    await expect(table.locator('[data-cell="H2"]')).toHaveText('=SUM(B2:G2)')
    await expect(table.locator('[data-cell="H5"]')).toHaveText('809127')
    const notes = page.getByRole('table', { name: '工作表：说明', exact: true })
    await expect(notes.locator('[data-cell="A1"]')).toHaveText('**原样内容** | A2: 单元格内说明\n第二行说明')
    await expect(notes.locator('[data-cell="C1"]')).toContainText('<img src=x')
    await expect(page.locator('.excel-source [data-cell="B12"]')).toHaveText('00123')
    await expect(page.locator('.excel-source [data-cell="AA12"]')).toHaveText('0')
    await expect(page.locator('.excel-source')).toContainText(['', '上个单元格的截断片段', '历史表格文本', '稀疏引用', '第一段'])
    const sparseTable = page.getByRole('table', { name: '工作表：稀疏引用', exact: true })
    await expect(sparseTable.locator('td')).toHaveCount(4)
    await expect(sparseTable.locator('[data-cell="XFD1048576"]')).toHaveText('末端')
    await expect(page.locator('.excel-source').last()).toHaveText(overlapping.content)
    await expect(page.locator('.excel-source img, .excel-source iframe, .excel-source strong')).toHaveCount(0)
    expect(await page.evaluate(() => (window as any).excelUnsafe)).toBeUndefined()
    await expect(page.locator('.source-plain-text').filter({ hasText: '接口说明' })).toHaveText(pdfSource.content)
    const scroll = table.locator('..')
    await expect(scroll).toHaveCSS('overflow-x', 'auto')
    const fits = await scroll.evaluate(element => element.getBoundingClientRect().right <= window.innerWidth)
    expect(fits).toBe(true)
    await scroll.scrollIntoViewIfNeeded()
    await scroll.evaluate(element => { element.scrollLeft = element.scrollWidth })
    await expect(table.locator('[data-cell="H2"]')).toBeInViewport()
    await scroll.evaluate(element => { element.scrollLeft = 0 })
    await page.screenshot({ path: test.info().outputPath('excel-citation.png') })
  })
}
