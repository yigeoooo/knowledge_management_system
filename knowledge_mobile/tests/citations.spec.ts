import { expect, test } from '@playwright/test'

const excerpt = [
  '# 工作表：Sheet1', '列1: 兴文石海景区套票产品基础内容',
  '表头/首个数据行（第2行）：列1: 产品名称 | 列2: 产品内容 | 列3: 产品价格 | 列4: 产品线路',
  '第4行：产品名称: 地质户外游 | 产品价格: 168元/人 | 产品线路: 南入口 | 游船\n出口 | 列5: 预约',
].join('\n\n')
const partial = '# 工作表：片段\n\n表头/首个数据行（第5行）：列1: 名称 | 列2: 名称\n\n第7行：名称: 保留原文'
const plain = '校验 <tag>\n输入 x | y\n然后提交'
const docx = '## 票务须知\n\n产品 | 备注 | 价格\n\n户外游 |  | 168元\n\n线路 <b>原文</b>\n请提前预约'
const markdown = '| 套票 | 价格 |\n| --- | --- |\n| 户外游 | 168元 |'

const sources = [
  { filename: '套票产品内容.xlsx', content: excerpt },
  { filename: '历史套票.xls', content: '工作表：旧版\nA1：名称\nB1：价格\nA3：地质奇幻游\nB3：138元/人' },
  { filename: '票务须知.docx', content: docx },
  { filename: '票务原件.docx', content: '价格说明', content_html: '<h2>原件</h2><table><tr><td colspan="2"><b>价格说明</b></td><td>项目</td><td>线路</td><td>价格</td><td>预约</td><td>联系人</td></tr></table>' },
  { filename: '票务说明.md', content: markdown },
  { filename: '票价表.docx', content: markdown },
  { filename: '备注.docx', content: plain },
  { filename: '待核对.xlsx', content: partial },
].map((source, i) => ({ ...source, chunk_id: String(i), document_title: source.filename }))

const pages = [
  ['KnowledgeQA', '/qa', '知识问答'], ['QALogs', '/qa-logs', '问答日志'], ['RobotQA', '/robot-qa', '机器人问答'],
].map(([key, path, name]) => ({ component_key: key, route_path: path, name, code: key, page_type: 'menu', is_visible: true }))
const identity = { access_token: 'fixture', user: { id: 'u' }, pages }
const conversation = { id: 'c', title: '套票价格', knowledge_base_id: 'kb', knowledge_base_name: '票务', knowledge_base_status: 'active', turn_count: 1 }
const turn = { id: 't', question: '套票多少钱？', answer: markdown, status: 'SUCCESS', sources }

for (const path of ['/qa', '/qa-logs', '/robot-qa']) {
  test(path + ' 在窄屏还原 Excel 行列、Word 引用及表格', async ({ page }) => {
    // Exercise the installed app's request path for a live question. Playwright
    // intercepts the simulated Android transport before any network access.
    if (path === '/qa') {
      await page.addInitScript(() => Object.assign(window, { CapacitorCustomPlatform: { name: 'android' } }))
    }
    await page.route('**/api/v1/**', route => {
      const url = new URL(route.request().url()).pathname
      let data: unknown
      if (url.endsWith('/auth/refresh')) data = identity
      else if (url.endsWith('/qa-users')) data = { items: [{ id: 'u', name: '访客', conversation_count: 1 }], total: 1 }
      else if (url.endsWith('/knowledge-bases')) data = { items: [{ id: 'kb', name: '票务' }], total: 1 }
      else if (url.endsWith('/robots')) data = { items: [{ id: 'r', status: 'active', serial_no: 'R', knowledge_base_id: 'kb', knowledge_base_status: 'active' }], total: 1 }
      else if (url.endsWith('/web/suggested-questions')) data = { questions: [] }
      else if (url.endsWith('/turns')) data = { items: [turn], conversation, next_before: null }
      else if (url.endsWith('/web/conversations') && route.request().method() === 'POST') data = { ...turn, conversation }
      else if (url.endsWith('conversations')) data = { items: [conversation], next_cursor: null }
      else throw new Error('Unexpected fixture request ' + url)
      return route.fulfill({ json: { code: 0, data } })
    })
    await page.setViewportSize({ width: 360, height: 780 })
    await page.goto('/#' + path + (path === '/robot-qa' ? '?robot_id=r&conversation_id=c' : ''))
    if (path === '/qa-logs') {
      await page.locator('.owner-item').click()
      await page.locator('.audit-conversation').click()
    } else if (path === '/qa') {
      await page.getByRole('textbox', { name: '你的问题' }).fill(turn.question)
      await page.getByRole('button', { name: '发送问题' }).click()
    }
    await page.locator('.turn-sources > summary').click()
    const citation = (filename: string) => page.locator('.turn-source').filter({ has: page.getByText(filename, { exact: true }) })
    const word = citation('票务须知.docx')
    await expect(word.getByRole('heading', { name: '票务须知' })).toBeVisible()
    await expect(word.locator('tr')).toHaveCount(2)
    await expect(word.locator('tr').last().getByRole('cell')).toHaveText(['户外游', '', '168元'])
    await expect(word).toContainText('线路 <b>原文</b>')
    await expect(citation('票务原件.docx').locator('td[colspan="2"] b')).toHaveText('价格说明')
    await expect(citation('票价表.docx').getByRole('columnheader')).toHaveText(['套票', '价格'])
    await expect(citation('备注.docx').locator('.source-plain-text')).toHaveText(plain)
    await expect(citation('票务说明.md').getByRole('table')).toContainText('168元')
    if (path !== '/robot-qa') await expect(page.locator('.conversation-answer table')).toContainText('168元')
    await expect(page.getByRole('table', { name: '工作表：旧版' }).locator('[data-cell="B3"]')).toHaveText('138元/人')
    const table = page.getByRole('table', { name: '工作表：Sheet1' })
    await expect(table.locator('[data-cell="A2"]')).toHaveText('产品名称')
    await expect(table.locator('[data-cell="B4"]')).toBeEmpty()
    await expect(table.locator('[data-cell="C4"]')).toHaveText('168元/人')
    expect(await table.locator('[data-cell="D4"]').textContent()).toBe('南入口 | 游船\n出口')
    await expect(table.locator('[data-cell="E4"]')).toHaveText('预约')
    await expect(citation('套票产品内容.xlsx')).toContainText('兴文石海景区套票产品基础内容')
    await expect(citation('待核对.xlsx').locator('.excel-source-text')).toHaveText(partial)
    for (const scrollable of [citation('套票产品内容.xlsx').locator('.excel-source-scroll'), citation('票务原件.docx').getByRole('table')]) {
      expect(await scrollable.evaluate(el => {
        el.scrollLeft = 64
        return el.scrollLeft
      })).toBeGreaterThan(0)
    }
    for (const selector of ['.phone-content', path === '/qa-logs' ? '.detail-panel' : '.chat-messages']) {
      expect(await page.locator(selector).evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true)
    }
  })
}
