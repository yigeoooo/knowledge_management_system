import { expect, test } from '@playwright/test'

const prompt = { key: 'answer_robot', name: '机器人简洁回答', active_version: 1, generation: 1 }
const original = { id: 'v1', version: 1, content: '请根据资料用简洁的自然语言回答问题，不得编造事实。', note: '初始版本', created_at: '2026-11-12T00:00:00Z', sha256: 'original' }
const dataset = { id: 'd1', name: '江源杯测试集', knowledge_base_id: 'kb1', knowledge_base_name: '宜宾江源杯知识库', description: '待审核标注草稿' }
const example = { prompt_keys: ['answer_robot', 'review_answer'], id: 'e1', name: '套票价格', inputs: { question: '地质科普游多少钱一人？', robot: true, context: {} }, reference: { expected_document_ids: ['doc1'], expected_documents: ['套票产品内容'], answer_points: ['99元'], expected_status: 'SUCCESS', reference_answer: '99元/人。', source_notes: 'Sheet1 第5行', forbidden_points: [] }, status: 'draft', revision: 1, reviewed_by: null }
const arm = { outputs: { answer: '99元/人。', status: 'SUCCESS', latency_ms: 1200, retrieved_documents: ['套票产品内容'], cited_documents: ['套票产品内容'], token_usage: { input_tokens: 200, output_tokens: 10 } }, scores: { status_accuracy: 1 }, error: null }
const run = { id: 'r1', name: '首轮草稿对比', dataset_id: 'd1', status: 'COMPLETED', created_at: '2026-11-12T00:00:00Z', completed: 1, total: 1, reviewed_only: false, summary: { baseline: { metrics: { status_accuracy: { value: 1, count: 1 } } }, candidate: { metrics: { status_accuracy: { value: 1, count: 1 } } }, delta: { status_accuracy: 0 }, paired_count: 1, human_reviewed_count: 0, human_passed_count: 0, human_failed_count: 0, human: { baseline: null, candidate: null } }, snapshot: { dataset_name: '江源杯测试集', dataset_hash: 'dataset-hash', environment_hash: 'environment-hash', environment: {}, examples: [example], baseline: { answer_robot: original }, candidate: { answer_robot: original } }, results: [{ id: 'e1', name: example.name, baseline: arm, candidate: arm, review: null }] }

for (const width of [1440, 390]) {
  test(`record categories expose manual completion independently of generation at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1100 })
    const records: import('../src/lib/evaluations').Run[] = [
      { ...run, name: '旧实验待处理', total: 2, completed: 2 },
      { ...run, id: 'partial', name: '已处理部分题目', total: 2, completed: 2,
        summary: { ...run.summary, human_reviewed_count: 1, human_passed_count: 1, human_failed_count: 0, human: { baseline: null, candidate: 1 } } },
      { ...run, id: 'partial-rejected', name: '部分确认含错误', total: 2, completed: 2,
        summary: { ...run.summary, human_reviewed_count: 1, human_passed_count: 0, human_failed_count: 1, human: { baseline: null, candidate: 0 } } },
      { ...run, id: 'approved', name: '全部人工确认合格', total: 2, completed: 2,
        summary: { ...run.summary, human_reviewed_count: 2, human_passed_count: 2, human_failed_count: 0, human: { baseline: null, candidate: 1 } } },
      { ...run, id: 'rejected', name: '全部确认含错误', total: 2, completed: 2,
        summary: { ...run.summary, human_reviewed_count: 2, human_passed_count: 1, human_failed_count: 1, human: { baseline: null, candidate: 0.5 } } },
      { ...run, id: 'failed', name: '异常空实验', status: 'FAILED', total: 0, completed: 0 },
      { ...run, id: 'running', name: '正在生成实验', status: 'RUNNING', total: 2, completed: 1 },
      { ...run, id: 'single', scope: 'single', name: '单题待确认' },
      { ...run, id: 'single-rejected', scope: 'single', name: '单题已确认不合格',
        summary: { ...run.summary, human_reviewed_count: 1, human_passed_count: 0, human_failed_count: 1, human: { baseline: null, candidate: 0 } } },
      { ...run, id: 'other', dataset_id: 'd2', name: '另一个评测集实验' },
    ]
    const queries: URLSearchParams[] = []
    await page.route('**/evaluations/runs*', route => {
      const query = new URL(route.request().url()).searchParams
      queries.push(query)
      return route.fulfill({ json: { code: 0, data: { items: records.filter(item =>
        item.dataset_id === query.get('dataset_id') && (item.scope || 'dataset') === query.get('scope')) } } })
    })
    await page.goto('/evaluations')
    await page.getByRole('tab', { name: '实验记录', exact: true }).click()
    const table = page.locator('.run-records-table')
    const record = (name: string) => table.getByRole('row').filter({ hasText: name })
    await expect(page.getByRole('radio', { name: '评测集记录', exact: true })).toBeChecked()
    await expect(record('旧实验待处理')).toContainText('答案已生成')
    await expect(record('旧实验待处理').locator('.review-status')).toContainText('待处理')
    await expect(record('旧实验待处理')).toContainText('已确认 0 / 2 题')
    await expect(record('旧实验待处理').locator('.review-totals')).toHaveCount(0)
    await expect(record('已处理部分题目')).toContainText('部分已处理')
    await expect(record('已处理部分题目')).toContainText('已确认 1 / 2 题')
    await expect(record('已处理部分题目').locator('.review-totals')).toHaveCount(0)
    await expect(record('部分确认含错误')).toContainText('部分已处理')
    await expect(record('部分确认含错误').locator('.failed-count')).toHaveText('不合格 1 题')
    await expect(record('全部人工确认合格')).toContainText('全部已处理')
    await expect(record('全部人工确认合格').locator('.review-totals')).toHaveCount(0)
    await expect(record('全部确认含错误')).toContainText('全部已处理')
    await expect(record('全部确认含错误').locator('.passed-count')).toHaveText('合格 1 题')
    await expect(record('全部确认含错误').locator('.failed-count')).toHaveText('不合格 1 题')
    await expect(record('异常空实验')).toContainText('执行异常 · 未全部处理')
    await expect(record('异常空实验')).not.toContainText('全部已处理')
    await expect(record('异常空实验').locator('.review-totals')).toHaveCount(0)
    await expect(record('正在生成实验')).toContainText('等待答案生成')
    await expect(record('正在生成实验').locator('.review-totals')).toHaveCount(0)
    await expect(record('单题待确认')).toHaveCount(0)
    await expect(record('另一个评测集实验')).toHaveCount(0)
    if (width === 1440) await page.screenshot({ path: '/tmp/kbs-evaluation-records-dataset.png', fullPage: true, animations: 'disabled' })
    await page.getByRole('radiogroup', { name: '实验记录类型' }).getByText('单题测试记录', { exact: true }).click()
    await expect(record('单题待确认')).toContainText('已确认 0 / 1 题')
    await expect(record('单题已确认不合格')).toContainText('全部已处理')
    await expect(record('单题已确认不合格').locator('.passed-count')).toHaveText('合格 0 题')
    await expect(record('单题已确认不合格').locator('.failed-count')).toHaveText('不合格 1 题')
    await expect(record('单题待确认').locator('.review-totals')).toHaveCount(0)
    await expect(record('旧实验待处理')).toHaveCount(0)
    expect(queries.some(query => query.get('scope') === 'single' && query.get('dataset_id') === 'd1')).toBe(true)
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true)
    await expect(table.locator('.el-loading-mask:visible')).toHaveCount(0)
    if (width === 390) await record('单题已确认不合格').locator('.review-status').scrollIntoViewIfNeeded()
    await page.screenshot({ path: `/tmp/kbs-evaluation-records-single-${width}.png`, fullPage: true, animations: 'disabled' })
    await page.getByRole('radiogroup', { name: '实验记录类型' }).getByText('评测集记录', { exact: true }).click()
    await expect(record('旧实验待处理')).toBeVisible()
    await expect(record('单题待确认')).toHaveCount(0)
  })
}

test.beforeEach(async ({ page }) => {
  const versions = [original]
  await page.route('**/api/v1/**', async route => {
    const path = new URL(route.request().url()).pathname
    let data: unknown
    if (path.endsWith('/auth/refresh')) data = { access_token: 'test', user: { display_name: '管理员' }, pages: [
      { code: 'prompts', name: '提示词管理', route_path: '/prompts', route_name: 'PromptManagement', component_key: 'PromptManagement', page_type: 'menu', is_visible: true },
      { code: 'evaluations', name: '质量评测', route_path: '/evaluations', route_name: 'EvaluationManagement', component_key: 'EvaluationManagement', page_type: 'menu', is_visible: true },
      { code: 'qa_logs', name: '问答日志', route_path: '/qa-logs', route_name: 'ConversationHistory', component_key: 'ConversationHistory', page_type: 'menu', is_visible: true },
    ] }
    else if (path.endsWith('/prompts')) data = { items: [prompt] }
    else if (path.endsWith('/prompts/answer_robot')) data = { ...prompt, versions }
    else if (path.endsWith('/prompts/answer_robot/versions')) { const body = route.request().postDataJSON(); const version = { ...original, id: 'v2', version: 2, content: body.content, note: body.note }; versions.unshift(version); data = version }
    else if (path.endsWith('/release-check')) data = { eligible: false, evaluation_run_id: null, dataset_id: 'd1', datasets: [dataset], reasons: ['此版本尚未通过质量评测，请先试测并完成人工复核'], runs: [] }
    else if (path.endsWith('/evaluations/datasets/d1/documents')) data = { items: [{ id: 'doc1', title: '套票产品内容', filename: '套票产品内容.xlsx', indexed: true }, { id: 'doc2', title: '套票产品内容', filename: '副本.xlsx', indexed: true }] }
    else if (path.endsWith('/documents/doc1/preview') || path.endsWith('/documents/doc2/preview')) data = { kind: 'word', document: { id: path.includes('doc2') ? 'doc2' : 'doc1', title: '套票产品内容', indexed: true }, version: { id: 'ver1', number: 1, filename: '产品说明.docx' }, html: '<h2>地质科普游</h2><p>地质科普游票价 99 元/人。</p>' + '<p>对照知识库文档里的适用条件和活动项目。</p>'.repeat(35) }
    else if (path.endsWith('/evaluations/datasets')) data = { items: [dataset] }
    else if (path.endsWith('/evaluations/options')) data = { knowledge_bases: [{ id: 'kb1', name: '宜宾江源杯知识库' }] }
    else if (path.endsWith('/examples')) data = { items: [example] }
    else if (path.endsWith('/evaluations/runs')) data = { items: [run] }
    else if (path.endsWith('/evaluations/runs/r1')) data = run
    else throw new Error(`Unexpected request: ${path}`)
    await route.fulfill({ json: { code: 0, data } })
  })
})

test('comparison identifies the historical candidate and frozen baseline versions', async ({ page }) => {
  const published = { ...original, id: 'v2', version: 2, note: '当前发布版本' }
  const historical = { ...run, prompt_details: { v1: { name: prompt.name, note: original.note }, v2: { name: prompt.name, note: published.note } }, snapshot: { ...run.snapshot,
    baseline: { answer_robot: published }, candidate: { answer_robot: original } } }
  await page.route('**/evaluations/runs/r1', route => route.fulfill({ json: { code: 0, data: historical } }))
  await page.goto('/evaluations?run=r1')
  const answers = page.getByRole('dialog', { name: '评测对比详情' }).locator('.answer-columns article')
  await expect(answers.nth(0)).toContainText('机器人简洁回答 · v2')
  await expect(answers.nth(1)).toContainText('机器人简洁回答 · v1')
  await expect(answers.nth(1)).toContainText('初始版本')
  await answers.nth(1).scrollIntoViewIfNeeded()
  await page.screenshot({ path: '/tmp/kbs-evaluation-historical-versions.png', animations: 'disabled' })
  await answers.nth(1).getByText('查看本题提示词正文', { exact: true }).click()
  await expect(answers.nth(1).locator('pre')).toContainText(original.content)
})

for (const scope of ['single', 'dataset'] as const) {
  for (const retryOne of [false, true]) {
    test(`failed ${scope} comparison retries ${retryOne ? 'one question' : 'all errors'} in the same record`, async ({ page }) => {
      const failed = { ...run, scope, status: 'FAILED', error_message: '部分样本调用失败',
        results: [{ ...run.results[0]!, baseline: { outputs: {}, scores: {}, error: 'ChatError', error_message: '问答模型连接超时，请稍后重试' } }] }
      const queued = { ...failed, status: 'PENDING', completed: 0, error_message: null,
        results: [{ ...failed.results[0]!, retry_pending: ['baseline'] }] }
      let current: typeof failed | typeof queued = failed
      let sent: unknown = null
      await page.route('**/evaluations/runs/r1', route => route.fulfill({ json: { code: 0, data: current } }))
      await page.route('**/evaluations/runs/r1/retry', route => {
        expect(route.request().method()).toBe('POST')
        sent = route.request().postDataJSON()
        current = queued
        return route.fulfill({ json: { code: 0, data: queued } })
      })
      await page.route('**/evaluations/runs?*', route => route.fulfill({ json: { code: 0, data: { items: [current] } } }))
      await page.goto('/evaluations?run=r1')
      const dialog = page.getByRole('dialog', { name: '评测对比详情' })
      await expect(dialog.locator('.answer-columns')).toContainText('问答模型连接超时，请稍后重试')
      await expect(dialog.getByRole('region', { name: '异常重测' })).toContainText('1 道题异常或未生成')
      if (!retryOne && scope === 'dataset') await page.screenshot({ path: '/tmp/kbs-evaluation-retry.png', animations: 'disabled' })
      if (retryOne) await dialog.getByRole('button', { name: '重新测试这道题', exact: true }).click()
      else await dialog.getByRole('button', { name: '一键重测所有异常题', exact: true }).click()
      await expect(dialog.locator('h2')).toHaveText(run.name)
      await expect(dialog).toContainText('正在重测异常题')
      await expect(dialog).toContainText('等待重测')
      await expect(dialog.getByRole('button', { name: '一键重测所有异常题', exact: true })).toBeDisabled()
      await expect(page).toHaveURL(/run=r1/)
      expect(sent).toEqual(retryOne ? { example_id: 'e1' } : {})
      await page.keyboard.press('Escape')
      await expect(page.getByRole('radio', { name: scope === 'single' ? '单题测试记录' : '评测集记录', exact: true })).toBeChecked()
      await expect(page.locator('.run-records-table')).toContainText(run.name)
    })
  }
}

test('retry errors keep the original comparison available', async ({ page }) => {
  const failed = { ...run, status: 'FAILED', results: [{ ...run.results[0]!, baseline: { ...arm, error: 'ChatError' } }] }
  await page.route('**/evaluations/runs/r1', route => route.fulfill({ json: { code: 0, data: failed } }))
  await page.route('**/evaluations/runs/r1/retry', route => route.fulfill({ status: 409, json: { code: 40900, message: '知识库索引或运行配置已变化', data: null } }))
  await page.goto('/evaluations?run=r1')
  const dialog = page.getByRole('dialog', { name: '评测对比详情' })
  await dialog.getByRole('button', { name: '一键重测所有异常题', exact: true }).click()
  await expect(dialog.getByRole('region', { name: '异常重测' })).toContainText('知识库索引或运行配置已变化')
  await expect(dialog.getByRole('button', { name: '一键重测所有异常题', exact: true })).toBeEnabled()
  await expect(dialog.locator('h2')).toHaveText(run.name)
  await expect(page).toHaveURL(/run=r1/)
})

test('historical version selection is submitted as the candidate', async ({ page }) => {
  const published = { ...original, id: 'v2', version: 2, note: '已发布的改进版本' }
  const requests: unknown[] = []
  await page.route('**/prompts/answer_robot', route => route.fulfill({ json: { code: 0, data: { ...prompt, active_version: 2, versions: [published, original] } } }))
  await page.route('**/evaluations/datasets/d1/examples', route => route.fulfill({ json: { code: 0, data: { items: [{ ...example, status: 'enabled' }] } } }))
  await page.route('**/evaluations/runs', route => {
    requests.push(route.request().postDataJSON())
    return route.fulfill({ json: { code: 0, data: run } })
  })
  await page.goto('/evaluations')
  await page.getByRole('tab', { name: '发起版本对比', exact: true }).click()
  await page.locator('.experiment-form .el-select').click()
  await page.getByRole('option', { name: 'v1 · 初始版本', exact: true }).click()
  await page.getByRole('button', { name: '开始对比评测', exact: true }).click()
  await expect(page.getByRole('dialog', { name: '评测对比详情' })).toBeVisible()
  expect(requests).toHaveLength(1)
  expect(requests[0]).toMatchObject({ overrides: { answer_robot: 'v1' } })
})

test('saving a draft preserves publication and sends its version to evaluation', async ({ page }) => {
  await page.goto('/prompts')
  await expect(page.locator('.editor-heading')).toContainText('当前发布 v1')
  await page.locator('.prompt-editor textarea').fill(original.content + ' 只回答当前问题的核心内容。')
  await page.getByPlaceholder('例如：缩短机器人回答，同时保留价格和适用条件').fill('收紧回答范围')
  await page.getByRole('button', { name: '保存新版本', exact: true }).click()
  await expect(page.locator('.editor-heading')).toContainText('当前发布 v1')
  await expect(page.getByRole('button', { name: '发布所选版本' })).toBeDisabled()
  await expect(page.getByText('此版本尚未通过质量评测，请先试测并完成人工复核')).toBeVisible()
  await page.screenshot({ path: '/tmp/kbs-prompt-studio.png', fullPage: true, animations: 'disabled' })
  await page.getByRole('button', { name: '试测此版本' }).click()
  await expect(page).toHaveURL(/evaluations\?prompt=answer_robot&version=v2/)
  await expect(page.getByRole('tab', { name: '发起版本对比' })).toHaveAttribute('aria-selected', 'true')
  await expect(page.locator('.experiment-form')).toContainText('v2 · 收紧回答范围')
  await expect(page.getByRole('button', { name: '开始对比评测' })).toBeDisabled()
})

for (const width of [1440, 390]) {
  test(`draft labels and paired comparison stay legible at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 })
    await page.goto('/evaluations')
    await expect(page.getByText('草稿', { exact: true })).toBeVisible()
    await page.getByRole('tab', { name: '实验记录' }).click()
    await page.getByRole('button', { name: '查看逐题对比' }).click()
    const dialog = page.getByRole('dialog', { name: '评测对比详情' })
    await expect(dialog).toBeVisible()
    await expect(dialog.getByText('草稿试测 · 非验收结论', { exact: true })).toBeVisible()
    await expect(dialog.locator('.answer-columns article')).toHaveCount(2)
    await expect(dialog.locator('.comparison-content h3')).toHaveText(example.inputs.question)
    await expect(dialog.getByRole('button', { name: '保存人工复核' })).toBeDisabled()
    const panel = page.locator('.el-dialog.evaluation-dialog')
    const bounds = await panel.boundingBox()
    expect(bounds!.width).toBeLessThan(width)
    expect(await panel.evaluate(el => el.scrollWidth <= el.clientWidth + 1)).toBe(true)
    if (width === 1440) await page.screenshot({ path: '/tmp/kbs-evaluation-comparison.png', fullPage: true, animations: 'disabled' })
    await page.keyboard.press('Escape')
    await expect(dialog).toBeHidden()
    await expect(page.getByRole('tab', { name: '实验记录' })).toHaveAttribute('aria-selected', 'true')
  })
}

test('expected documents are selected from the dataset and saved as IDs', async ({ page }) => {
  let saved: { reference: { expected_document_ids: string[]; expected_documents?: string[] } } | undefined
  await page.route('**/api/v1/evaluations/examples/e1', async route => {
    saved = route.request().postDataJSON()
    await route.fulfill({ json: { code: 0, data: example } })
  })
  await page.goto('/evaluations')
  await page.getByRole('button', { name: '查看 / 编辑', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: '查看 / 编辑测试题' })
  const picker = dialog.getByRole('combobox', { name: '预期命中的文档', exact: true })
  await picker.focus()
  await picker.fill('套票')
  await expect(page.getByRole('option').filter({ hasText: '副本.xlsx' })).toBeVisible()
  await page.getByRole('option').filter({ hasText: '副本.xlsx' }).click()
  await picker.press('Escape')
  await page.screenshot({ path: '/tmp/kbs-document-picker.png', fullPage: true, animations: 'disabled' })
  await dialog.getByRole('button', { name: '保存草稿' }).click()
  await expect(dialog).toBeHidden()
  expect(saved?.reference.expected_document_ids).toEqual(['doc1', 'doc2'])
  expect(saved?.reference.expected_documents).toBeUndefined()
})

test('publication is unlocked by a qualifying evaluation and submits its evidence', async ({ page }) => {
  let allowed = false
  let published: { evaluation_run_id: string; version: number } | undefined
  await page.route('**/release-check*', route => route.fulfill({ json: { code: 0, data: {
    eligible: allowed, evaluation_run_id: allowed ? 'approved-run' : null, dataset_id: 'd1', datasets: [dataset],
    reasons: allowed ? [] : ['请逐题完成人工复核'],
    runs: [{ id: 'approved-run', name: '已审核验收集', eligible: allowed, reasons: [] }],
  } } }))
  await page.route('**/prompts/answer_robot/publish', async route => {
    published = route.request().postDataJSON()
    await route.fulfill({ json: { code: 0, data: { ...prompt, active_version: 2, generation: 2 } } })
  })
  await page.goto('/prompts')
  await page.locator('.prompt-editor textarea').fill(original.content + ' 请优先回答票价。')
  await page.getByRole('button', { name: '保存新版本', exact: true }).click()
  await expect(page.getByText('请逐题完成人工复核')).toBeVisible()
  await expect(page.getByRole('button', { name: '发布所选版本' })).toBeDisabled()
  allowed = true
  await page.getByRole('button', { name: '刷新发布条件' }).click()
  await expect(page.getByRole('button', { name: '发布所选版本' })).toBeEnabled()
  await page.getByRole('button', { name: '发布所选版本' }).click()
  await page.getByRole('button', { name: '确认发布', exact: true }).click()
  await expect.poll(() => published?.evaluation_run_id).toBe('approved-run')
  expect(published?.version).toBe(2)
})

for (const width of [1500, 390]) {
  test(`authoring keeps the question while previewing documents and enables in one save at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1000 })
    let saved: { status: string; inputs: { question: string; context: object }; reference: { expected_document_ids: string[] } } | undefined
    await page.route('**/api/v1/evaluations/examples/e1', async route => {
      saved = route.request().postDataJSON()
      await route.fulfill({ json: { code: 0, data: { ...example, status: saved?.status } } })
    })
    await page.goto('/evaluations')
    await expect(page.getByRole('button', { name: '审核', exact: true })).toHaveCount(0)
    await page.getByRole('button', { name: '查看 / 编辑', exact: true }).click()
    const dialog = page.getByRole('dialog', { name: '查看 / 编辑测试题' })
    const question = dialog.getByRole('textbox', { name: '测试问题', exact: true })
    await question.fill('新问题：票价包含哪些项目？')
    await expect(dialog.getByRole('region', { name: '历史问答' })).toHaveCount(0)
    if (width < 1024) await dialog.getByText('资料预览', { exact: true }).click()
    const sources = dialog.getByRole('region', { name: '知识库资料预览' })
    await expect(sources.getByText('地质科普游票价 99 元/人。')).toBeVisible()
    await expect.poll(() => dialog.locator('.example-workspace').evaluate(el => {
      const content = el.querySelector('.source-content')!
      return content.getBoundingClientRect().bottom - el.getBoundingClientRect().bottom
    })).toBeLessThanOrEqual(1)
    await sources.getByRole('combobox', { name: '预览文档' }).click()
    await page.getByRole('option').filter({ hasText: '副本.xlsx' }).click()
    await sources.getByRole('button', { name: '加入预期文档', exact: true }).click()
    await expect(sources.getByRole('button', { name: '已加入预期文档' })).toBeDisabled()
    if (width >= 1024) {
      await sources.getByRole('button', { name: '放大预览' }).click()
      await expect(question).toBeHidden()
      await sources.getByRole('button', { name: '返回对照' }).click()
    } else await dialog.getByText('题目编辑', { exact: true }).click()
    await expect(question).toHaveValue('新问题：票价包含哪些项目？')
    const panel = page.locator('.el-dialog.example-dialog')
    expect(await panel.evaluate(el => el.scrollWidth <= el.clientWidth + 1)).toBe(true)
    await page.screenshot({ path: `/tmp/kbs-authoring-${width}.png`, animations: 'disabled' })
    await dialog.getByRole('button', { name: '保存并启用', exact: true }).click()
    await expect(dialog).toBeHidden()
    expect(saved?.status).toBe('enabled')
    expect(saved?.reference.expected_document_ids).toEqual(['doc1', 'doc2'])
    expect(saved?.inputs.context).toEqual({})
  })
}

test('history only appears for follow-up or summary and uses ordinary question fields', async ({ page }) => {
  let saved: { inputs: { task: string; context: { turns: { question: string; answer: string }[] } } } | undefined
  await page.route('**/api/v1/evaluations/examples/e1', async route => {
    saved = route.request().postDataJSON()
    await route.fulfill({ json: { code: 0, data: example } })
  })
  await page.goto('/evaluations')
  await page.getByRole('button', { name: '查看 / 编辑', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: '查看 / 编辑测试题' })
  await expect(dialog.getByRole('region', { name: '历史问答' })).toHaveCount(0)
  await dialog.locator('.el-select').filter({ has: page.locator('input[aria-label="测试任务"]') }).click()
  await page.getByRole('option', { name: '连续追问（带历史问答）', exact: true }).click()
  await dialog.getByRole('textbox', { name: '第 1 轮问题', exact: true }).fill('地质科普游包括什么？')
  await dialog.getByRole('textbox', { name: '第 1 轮回答', exact: true }).fill('包含景区门票、体验馆和护照。')
  await dialog.getByRole('button', { name: '保存并启用', exact: true }).click()
  await expect(dialog).toBeHidden()
  expect(saved?.inputs.task).toBe('answer')
  expect(saved?.inputs.context.turns).toEqual([{ question: '地质科普游包括什么？', answer: '包含景区门票、体验馆和护照。' }])
})

for (const [task, width] of [['连续追问（带历史问答）', 2048], ['会话摘要', 390]] as const) {
  test(`import previews real question-answer pairs before replacing history for ${task} at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1080 })
    const conversation = { id: 'c1', title: '票价咨询会话', last_turn_no: 4, last_message_at: '2026-11-12T00:00:00Z' }
    const turns = [
      { id: 't1', turn_no: 1, question: '地质科普游多少钱？', answer: '票价为 99 元/人。', status: 'SUCCESS', importable: true },
      { id: 't2', turn_no: 2, question: '包含什么项目？', answer: '包括景区门票和体验馆。', status: 'SUCCESS', importable: true },
      { id: 't3', turn_no: 3, question: '失败的问题', answer: '', status: 'FAILED', importable: false },
      { id: 't4', turn_no: 4, question: '后续问题', answer: '不应导入的后续答案', status: 'SUCCESS', importable: true },
    ]
    const queries: string[] = []
    await page.route('**/evaluations/datasets/d1/history/**', async route => {
      const url = new URL(route.request().url()); queries.push(url.search)
      let data: object
      if (url.pathname.endsWith('/owners')) data = { items: [{ id: 'owner1', name: '测试设备', identity: 'R-1', conversation_count: 1 }], total: 1 }
      else if (url.pathname.endsWith('/conversations')) data = { items: [conversation], total: 1 }
      else if (url.pathname.endsWith('/turns')) data = { items: turns, total: 4, conversation }
      else {
        const start = Number(url.searchParams.get('start')), end = Number(url.searchParams.get('end'))
        data = { context: { summary: '', turns: turns.filter(t => t.turn_no >= start && t.turn_no <= end && t.importable).map(t => ({ question: t.question, answer: t.answer, turn_no: t.turn_no, source_log_id: t.id, source_conversation_id: 'c1' })) }, conversation, skipped_count: 0, start_turn_no: start, end_turn_no: end }
      }
      await route.fulfill({ json: { code: 0, data } })
    })
    let saved: { inputs: { task: string; question: string; context: { summary: string; turns: { question: string; answer: string; source_log_id: string }[] } }; reference: typeof example.reference } | undefined
    await page.route('**/evaluations/examples/e1', async route => { saved = route.request().postDataJSON(); await route.fulfill({ json: { code: 0, data: example } }) })
    await page.goto('/evaluations')
    await page.getByRole('button', { name: '查看 / 编辑', exact: true }).click()
    const editor = page.getByRole('dialog', { name: '查看 / 编辑测试题' })
    if (width > 1000) {
      expect((await page.locator('.el-dialog.example-dialog').boundingBox())!.width).toBeGreaterThan(1800)
      const reference = await editor.getByRole('region', { name: '知识库资料预览' }).boundingBox()
      const form = await editor.locator('.example-editor').boundingBox()
      expect(reference!.width).toBeGreaterThan(form!.width)
    }
    await editor.locator('.el-select').filter({ has: page.locator('input[aria-label="测试任务"]') }).click()
    await page.getByRole('option', { name: task, exact: true }).click()
    await editor.getByRole('textbox', { name: '第 1 轮问题', exact: true }).fill('旧问题')
    await editor.getByRole('textbox', { name: '第 1 轮回答', exact: true }).fill('旧回答')
    await editor.getByRole('textbox', { name: '更早的对话摘要（可选）' }).fill('不能混入的旧摘要')
    await editor.getByRole('button', { name: '从问答日志导入', exact: true }).click()
    const picker = page.getByRole('dialog', { name: '从问答日志导入', exact: true })
    await picker.getByRole('combobox', { name: '选择机器人' }).click()
    await page.getByRole('option', { name: '测试设备 · R-1', exact: true }).click()
    await picker.getByRole('button').filter({ hasText: '票价咨询会话' }).click()
    const preview = picker.getByRole('region', { name: '会话问答预览' })
    await expect(preview.getByText('票价为 99 元/人。', { exact: true })).toBeVisible()
    await expect(preview.locator('.import-turn').filter({ hasText: '失败的问题' }).getByRole('button')).toHaveCount(0)
    await preview.locator('.import-turn').filter({ hasText: '包含什么项目？' }).getByRole('button', { name: '到此问答结束' }).click()
    await picker.getByRole('button', { name: '预览待导入问答' }).click()
    const selected = picker.getByRole('region', { name: '待导入问答预览' })
    await expect(selected.locator('.import-turn')).toHaveCount(2)
    await expect(selected).toContainText('票价为 99 元/人。')
    await expect(selected).not.toContainText('不应导入的后续答案')
    await expect(editor.getByRole('textbox', { name: '第 1 轮问题', exact: true })).toHaveValue('旧问题')
    const importPanel = page.locator('.el-dialog.history-import-dialog')
    const bounds = await importPanel.boundingBox()
    expect(bounds!.width).toBeLessThan(width)
    expect(await importPanel.evaluate(el => el.scrollWidth <= el.clientWidth + 1)).toBe(true)
    await page.screenshot({ path: `/tmp/kbs-history-import-${width}.png`, animations: 'disabled' })
    await picker.getByRole('button', { name: '替换并导入', exact: true }).click()
    await expect(picker).toBeHidden()
    await expect(editor.getByRole('textbox', { name: '第 1 轮问题', exact: true })).toHaveValue(turns[0]!.question)
    await expect(editor.getByRole('textbox', { name: '第 2 轮回答', exact: true })).toHaveValue(turns[1]!.answer)
    await expect(editor.getByRole('textbox', { name: '更早的对话摘要（可选）' })).toHaveValue('')
    await editor.getByRole('textbox', { name: '第 1 轮回答', exact: true }).fill('99 元/人，已核对资料。')
    await editor.getByRole('button', { name: '保存并启用', exact: true }).click()
    await expect(editor).toBeHidden()
    expect(saved?.inputs.context.turns.map(t => t.source_log_id)).toEqual(['t1', 't2'])
    expect(saved?.inputs.context.turns[0]?.answer).toBe('99 元/人，已核对资料。')
    expect(saved?.inputs.question).toBe(example.inputs.question)
    expect(saved?.reference.reference_answer).toBe(example.reference.reference_answer)
    expect(saved?.inputs.task).toBe(task === '会话摘要' ? 'summary' : 'answer')
    expect(queries.every(query => query.includes('source_type=ROBOT'))).toBe(true)
  })
}


test('a knowledge base with a dataset cannot create another one', async ({ page }) => {
  await page.goto('/evaluations')
  await expect(page.getByRole('button', { name: '新建评测集', exact: true })).toBeDisabled()
  await expect(page.getByText('当前知识库均已建立评测集，可选择现有评测集继续添加或修改题目。')).toBeVisible()
})

test('dataset creation only offers knowledge bases without a dataset', async ({ page }) => {
  await page.route('**/evaluations/options', route => route.fulfill({ json: { code: 0, data: { knowledge_bases: [
    { id: 'kb1', name: '江源杯', dataset_id: 'd1' }, { id: 'kb2', name: '新知识库', dataset_id: null },
  ] } } }))
  await page.goto('/evaluations')
  await page.getByRole('button', { name: '新建评测集', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: '新建评测集', exact: true })
  await dialog.locator('.el-select').filter({ has: page.locator('input[aria-label="创建评测集的知识库"]') }).click()
  await expect(page.getByRole('option', { name: '江源杯 · 已有评测集', exact: true })).toHaveAttribute('aria-disabled', 'true')
  await expect(page.getByRole('option', { name: '新知识库', exact: true })).toHaveAttribute('aria-selected', 'true')
})

test('publication selection cannot borrow acceptance from another knowledge base', async ({ page }) => {
  const other = { ...dataset, id: 'd2', name: '另一个知识库评测', knowledge_base_id: 'kb2', knowledge_base_name: '新知识库' }
  let requestedDataset = ''
  await page.route('**/release-check*', async route => {
    const id = new URL(route.request().url()).searchParams.get('dataset_id') || ''
    requestedDataset = id
    await route.fulfill({ json: { code: 0, data: { eligible: id === 'd1', dataset_id: id || null, datasets: [dataset, other], evaluation_run_id: id === 'd1' ? 'r1' : null, runs: id === 'd1' ? [{ id: 'r1', name: '验收实验', eligible: true, reasons: [] }] : [], reasons: id ? ['此知识库暂无合格实验'] : ['请选择用于发布验收的知识库评测集'] } } })
  })
  await page.goto('/prompts')
  await page.locator('.prompt-editor textarea').fill(original.content + ' 请核对价格条件。')
  await page.getByRole('button', { name: '保存新版本', exact: true }).click()
  await expect(page.getByRole('button', { name: '发布所选版本', exact: true })).toBeDisabled()
  const selector = page.locator('.el-select').filter({ has: page.locator('input[aria-label="发布验收评测集"]') })
  await selector.click()
  await page.getByRole('option', { name: '宜宾江源杯知识库 · 江源杯测试集', exact: true }).click()
  await expect(page.getByRole('button', { name: '发布所选版本', exact: true })).toBeEnabled()
  await selector.click()
  await page.getByRole('option', { name: '新知识库 · 另一个知识库评测', exact: true }).click()
  await expect(page.getByRole('button', { name: '发布所选版本', exact: true })).toBeDisabled()
  await expect.poll(() => requestedDataset).toBe('d2')
  await page.getByRole('button', { name: '试测此版本', exact: true }).click()
  await expect(page).toHaveURL(/dataset=d2/)
})


test('one verdict saves without a note and persists both passing and rejected results', async ({ page }) => {
  let current: import('../src/lib/evaluations').Run = structuredClone(run) as import('../src/lib/evaluations').Run
  const requests: unknown[] = []
  await page.route('**/evaluations/runs/r1', route => route.fulfill({ json: { code: 0, data: current } }))
  await page.route('**/evaluations/runs/r1/reviews/e1', async route => {
    const body = route.request().postDataJSON(); requests.push(body)
    current = { ...current, results: [{ ...current.results![0]!, review: { ...body, reviewed_by: 'admin', reviewed_at: '2026-11-12T00:00:00Z' } }],
      summary: { ...current.summary, human_reviewed_count: 1, human_passed_count: body.candidate, human_failed_count: 1 - body.candidate, human: { baseline: null, candidate: body.candidate } } }
    await route.fulfill({ json: { code: 0, data: current } })
  })
  await page.goto('/evaluations?run=r1')
  const dialog = page.getByRole('dialog', { name: '评测对比详情' })
  await expect(dialog.getByRole('radiogroup')).toHaveCount(1)
  await expect(dialog.getByRole('combobox')).toHaveCount(0)
  await expect(dialog.locator('.answer-columns article')).toHaveCount(2)
  for (const verdict of [1, 0]) {
    await dialog.getByRole('radiogroup', { name: '本题对比结果' }).getByText(verdict ? '合格' : '不合格', { exact: true }).click()
    await dialog.getByRole('button', { name: '保存人工复核' }).click()
    const badge = dialog.getByRole('complementary', { name: '评测题目' }).locator('.question-result')
    await expect(badge).toHaveText(verdict ? '合格' : '不合格')
    await expect(badge).toHaveClass(verdict ? /el-tag--success/ : /el-tag--danger/)
    await page.keyboard.press('Escape')
    const record = page.locator('.run-records-table').getByRole('row').filter({ hasText: current.name })
    await expect(record).toContainText('全部已处理')
    await expect(record).toContainText('已确认 1 / 1 题')
    if (verdict === 0) {
      await expect(record.locator('.passed-count')).toHaveText('合格 0 题')
      await expect(record.locator('.failed-count')).toHaveText('不合格 1 题')
    } else await expect(record.locator('.review-totals')).toHaveCount(0)
    await page.getByRole('button', { name: '查看逐题对比' }).click()
    await expect(dialog.getByRole('radio', { name: verdict ? '合格' : '不合格', exact: true })).toBeChecked()
    await expect(dialog.getByRole('region', { name: '评测进度', exact: true })).toContainText('已人工确认 1 / 1 题')
    if (verdict === 1) {
      await dialog.locator('.human-review').scrollIntoViewIfNeeded()
      await page.screenshot({ path: '/tmp/kbs-evaluation-single-verdict.png', animations: 'disabled' })
    }
  }
  expect(requests).toEqual([{ candidate: 1, note: '' }, { candidate: 0, note: '' }])
})

for (const width of [1440, 390]) {
  test(`question navigation distinguishes verdicts from pending and failed answers at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1000 })
    const samples = ['票价确认', '游玩人数', '老人优惠', '儿童票价', '推荐路线'].map((name, index) => ({
      ...example, id: `e${index + 1}`, name, inputs: { ...example.inputs, question: `${name}的问题` },
    }))
    const review = { candidate: 1, note: '', reviewed_by: 'admin', reviewed_at: '2026-11-12T00:00:00Z' }
    const current = { ...run, status: 'FAILED', total: 5, completed: 4,
      summary: { ...run.summary, human_reviewed_count: 2, human_passed_count: 1, human_failed_count: 1 },
      snapshot: { ...run.snapshot, examples: samples },
      results: samples.slice(0, 4).map((sample, index) => ({ ...run.results[0]!, id: sample.id, name: sample.name,
        review: index < 2 ? { ...review, candidate: index === 0 ? 1 : 0 } : null,
        candidate: index === 3 ? { ...arm, error: '模型超时' } : arm,
      })),
    }
    await page.route('**/evaluations/runs/r1', route => route.fulfill({ json: { code: 0, data: current } }))
    await page.goto('/evaluations?run=r1')
    const dialog = page.getByRole('dialog', { name: '评测对比详情' })
    const navigation = dialog.getByRole('complementary', { name: '评测题目' })
    for (const [index, label, type] of [[0, '合格', 'success'], [1, '不合格', 'danger'], [2, '待确认', 'warning'], [3, '执行异常', 'warning'], [4, '未生成', 'info']] as const) {
      const badge = navigation.locator('.question-select').nth(index).locator('.question-result')
      await expect(badge).toHaveText(label)
      await expect(badge).toHaveClass(new RegExp(`el-tag--${type}`))
    }
    await navigation.getByRole('button').filter({ hasText: '游玩人数' }).click()
    await expect(dialog.locator('.comparison-content h3')).toHaveText('游玩人数的问题')
    await expect(dialog.getByRole('radio', { name: '不合格', exact: true })).toBeChecked()
    await navigation.scrollIntoViewIfNeeded()
    await page.screenshot({ path: `/tmp/kbs-evaluation-verdict-tags-${width}.png`, animations: 'disabled' })
    await navigation.getByRole('button').filter({ hasText: '儿童票价' }).click()
    await expect(dialog.getByText('执行失败：模型超时', { exact: true })).toBeVisible()
    await expect(dialog.getByRole('button', { name: '保存人工复核' })).toHaveCount(0)
  })
}

test('real progress refreshes from queued to running to generated without claiming acceptance', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 })
  await page.clock.install()
  let current = { ...run, status: 'PENDING', completed: 0, total: 2,
    quality_reasons: ['评测尚未成功完成', '请逐题完成人工复核'],
    snapshot: { ...run.snapshot, examples: [example, { ...example, id: 'e2', name: '套票内容' }] }, results: [] as typeof run.results }
  await page.route('**/evaluations/runs*', route => route.fulfill({ json: { code: 0, data: { items: [current] } } }))
  await page.route('**/evaluations/runs/r1', route => route.fulfill({ json: { code: 0, data: current } }))
  await page.goto('/evaluations?run=r1')
  const dialog = page.getByRole('dialog', { name: '评测对比详情' })
  const progress = dialog.getByRole('region', { name: '评测进度', exact: true })
  await expect(progress).toContainText('等待开始评测')
  await expect(progress.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '0')
  await expect(dialog.locator('.quality-notice')).toHaveCount(0)
  current = { ...current, status: 'RUNNING', completed: 1, results: run.results }
  await page.clock.runFor(4200)
  await expect(progress).toContainText('正在生成对比答案')
  await expect(progress.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '50')
  await expect(progress.getByRole('progressbar')).toHaveAttribute('aria-valuetext', '1 / 2 题')
  await expect(dialog.locator('.answer-columns article')).toHaveCount(2)
  await expect(dialog.getByRole('button', { name: '保存人工复核' })).toHaveCount(0)
  await page.screenshot({ path: '/tmp/kbs-evaluation-progress-running.png', animations: 'disabled' })
  current = { ...current, status: 'COMPLETED', completed: 2,
    results: [...run.results, { ...run.results[0]!, id: 'e2', name: '套票内容' }], quality_reasons: ['请逐题完成人工复核'] }
  await page.clock.runFor(4200)
  await expect(progress.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '100')
  await expect(progress).toContainText('已人工确认 0 / 2 题')
  await expect(progress).toContainText('执行完成不代表通过验收')
  await expect(dialog.getByRole('button', { name: '保存人工复核' })).toBeDisabled()
  await expect(dialog.getByText('请逐题完成人工复核', { exact: true })).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(page.getByRole('progressbar', { name: '评测执行进度' })).toHaveAttribute('aria-valuenow', '100')
  await page.getByRole('button', { name: '查看逐题对比' }).click()
  await expect(progress.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '100')
})

for (const [completed, total] of [[0, 0], [1, 2], [1, 1]]) {
  test(`failed progress remains accurate and cannot be approved at ${completed}/${total}`, async ({ page }) => {
    const current = { ...run, status: 'FAILED', completed, total, error_message: '模型调用超时',
      results: completed ? [{ ...run.results[0]!, candidate: { ...arm, error: 'TimeoutError' } }] : [],
      snapshot: { ...run.snapshot, examples: total ? [example] : [] }, quality_reasons: ['存在执行失败的测试题'] }
    await page.route('**/evaluations/runs/r1', route => route.fulfill({ json: { code: 0, data: current } }))
    await page.goto('/evaluations?run=r1')
    const dialog = page.getByRole('dialog', { name: '评测对比详情' })
    const progress = dialog.getByRole('region', { name: '评测进度', exact: true })
    await expect(progress).toContainText('评测执行异常')
    await expect(progress.getByRole('progressbar')).toHaveAttribute('aria-valuenow', String(total ? Math.floor(completed! / total * 100) : 0))
    await expect(dialog.getByRole('button', { name: '保存人工复核' })).toHaveCount(0)
    await expect(dialog.getByText('模型调用超时', { exact: true })).toBeVisible()
  })
}

for (const width of [1440, 390]) {
  test(`single question testing selects its versions and keeps the authoring context at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 960 })
    const selected = { ...example, id: 'e2', name: '指定题目', inputs: { ...example.inputs, question: '套票包含什么项目？' }, status: 'enabled', revision: 3 }
    const candidate = { ...original, id: 'v2', version: 2, note: '候选精简版本' }
    const summaryPrompt = { ...prompt, key: 'summarize', name: '会话摘要' }
    const single = { ...run, id: 'single1', scope: 'single', name: '单题测试 · 指定题目', total: 1,
      snapshot: { ...run.snapshot, examples: [selected], candidate: { answer_robot: candidate } },
      results: [{ ...run.results[0]!, id: selected.id, name: selected.name }],
      quality_reasons: ['单题测试仅用于调试，请使用评测集全部已启用题目完成发布验收'] }
    let saved: Record<string, unknown> | undefined
    await page.route('**/evaluations/datasets/d1/examples', route => route.fulfill({ json: { code: 0, data: { items: [example, selected] } } }))
    await page.route('**/api/v1/prompts', route => route.fulfill({ json: { code: 0, data: { items: [prompt, summaryPrompt] } } }))
    await page.route('**/prompts/answer_robot', route => route.fulfill({ json: { code: 0, data: { ...prompt, versions: [candidate, original] } } }))
    await page.route('**/prompts/summarize', route => route.fulfill({ json: { code: 0, data: { ...summaryPrompt, versions: [original] } } }))
    await page.route('**/evaluations/runs*', async route => {
      if (route.request().method() === 'POST') { saved = route.request().postDataJSON(); await route.fulfill({ status: 202, json: { code: 0, data: single } }) }
      else await route.fulfill({ json: { code: 0, data: { items: saved ? [single, run] : [run] } } })
    })
    await page.route('**/evaluations/runs/single1', route => route.fulfill({ json: { code: 0, data: single } }))
    await page.goto('/evaluations')
    await page.getByRole('row').filter({ hasText: selected.name }).getByRole('button', { name: '单题测试', exact: true }).click()
    const setup = page.getByRole('dialog', { name: '单题测试', exact: true })
    await expect(setup).toContainText(selected.inputs.question)
    await expect(setup).toContainText('1 题 × 2 组回答')
    await expect(setup.getByRole('combobox')).toHaveCount(1)
    await expect(setup.getByText('会话摘要', { exact: true })).toHaveCount(0)
    await setup.locator('.el-select').filter({ has: page.getByRole('combobox', { name: '机器人简洁回答候选版本', exact: true }) }).click()
    await page.getByRole('option', { name: 'v2 · 候选精简版本', exact: true }).click()
    const panel = page.locator('.el-dialog.single-run-dialog')
    expect(await panel.evaluate(el => el.scrollWidth <= el.clientWidth + 1)).toBe(true)
    await page.screenshot({ path: `/tmp/kbs-single-evaluation-${width}.png`, animations: 'disabled' })
    await setup.getByRole('button', { name: '开始单题测试', exact: true }).click()
    await expect(setup).toBeHidden()
    expect(saved).toMatchObject({ dataset_id: 'd1', example_id: 'e2', expected_revision: 3, overrides: { answer_robot: 'v2' } })
    const detail = page.getByRole('dialog', { name: '评测对比详情' })
    await expect(detail.getByText('单题测试 · 非验收结论', { exact: true })).toBeVisible()
    await expect(detail.getByRole('complementary', { name: '评测题目' }).getByRole('button')).toHaveCount(1)
    await expect(detail.locator('.comparison-content h3')).toHaveText(selected.inputs.question)
    await expect(detail.locator('.answer-columns article')).toHaveCount(2)
    await expect(detail.getByRole('button', { name: '返回提示词，检查发布条件' })).toHaveCount(0)
    await page.keyboard.press('Escape')
    await expect(page.getByRole('tab', { name: '测试题与人工标注' })).toHaveAttribute('aria-selected', 'true')
    await page.getByRole('tab', { name: '实验记录' }).click()
    await expect(page.getByRole('row').filter({ hasText: single.name })).toContainText('单题测试')
  })
}

test('single question error keeps the selected version for correction without falling back to the whole set', async ({ page }) => {
  const requests: Record<string, unknown>[] = []
  await page.route('**/evaluations/runs*', async route => {
    if (route.request().method() === 'POST') {
      requests.push(route.request().postDataJSON())
      await route.fulfill({ status: 409, json: { code: 409, message: '测试题已修改，请刷新题目后重新发起单题测试' } })
    } else await route.fulfill({ json: { code: 0, data: { items: [] } } })
  })
  await page.goto('/evaluations')
  await page.getByRole('button', { name: '单题测试', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: '单题测试', exact: true })
  await dialog.getByRole('button', { name: '开始单题测试', exact: true }).click()
  await expect(dialog.getByText('测试题已修改，请刷新题目后重新发起单题测试')).toBeVisible()
  await expect(dialog.getByRole('button', { name: '开始单题测试', exact: true })).toBeEnabled()
  expect(requests).toHaveLength(1)
  expect(requests[0]).toMatchObject({ example_id: 'e1', expected_revision: 1, overrides: {} })
  await dialog.getByRole('button', { name: '取消', exact: true }).click()
  await expect(dialog).toBeHidden()
  await expect(page.getByRole('tab', { name: '测试题与人工标注' })).toHaveAttribute('aria-selected', 'true')
})

for (const scope of ['single', 'dataset']) {
  test(`comparison exposes frozen conversation history for ${scope} evaluations`, async ({ page }) => {
    const history = { summary: '一家八口计划出游，想减少步行。', turns: [
      { turn_no: 2, question: '我们一共8个人。', answer: '请问老人和小孩各有几位？' },
      { turn_no: 3, question: '一个老人，两个小孩。', answer: '可以优先考虑步行较少的路线。' },
    ] }
    const sample = { ...example, inputs: { ...example.inputs, question: '这样一共多少钱？', context: history } }
    const current = { ...run, scope, snapshot: { ...run.snapshot, examples: [sample] }, results: [{ ...run.results[0]!,
      baseline: { ...arm, outputs: { ...arm.outputs, resolved_question: '8人游玩一共多少钱？' } },
      candidate: { ...arm, outputs: { ...arm.outputs, resolved_question: '有老人小孩的团体游玩费用是多少？' } },
    }] }
    await page.route('**/evaluations/runs/r1', route => route.fulfill({ json: { code: 0, data: current } }))
    await page.goto('/evaluations?run=r1')
    const dialog = page.getByRole('dialog', { name: '评测对比详情' })
    const context = dialog.getByRole('region', { name: '本次评测的历史上下文', exact: true })
    await expect(context).toContainText('一家八口计划出游，想减少步行。')
    await expect(context).toContainText('我们一共8个人。')
    await expect(context).toContainText('请问老人和小孩各有几位？')
    await expect(context).toContainText('一个老人，两个小孩。')
    await expect(context).toContainText('可以优先考虑步行较少的路线。')
    await expect(context).toContainText('2 轮')
    await expect(dialog.locator('.resolved-question')).toHaveCount(2)
    await expect(dialog.locator('.resolved-question').first()).toContainText('8人游玩一共多少钱？')
    await expect(dialog.locator('.resolved-question').last()).toContainText('有老人小孩的团体游玩费用是多少？')
    await context.locator('summary').click()
    await expect(context.getByText('我们一共8个人。', { exact: true })).toBeHidden()
    await context.locator('summary').click()
    await expect(context.getByText('我们一共8个人。', { exact: true })).toBeVisible()
    await context.scrollIntoViewIfNeeded()
    await page.screenshot({ path: `/tmp/kbs-evaluation-history-${scope}.png`, animations: 'disabled' })
  })
}
