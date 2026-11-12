import { expect, test } from '@playwright/test'

const conversation = { id: 'c1', title: '宜宾旅游咨询', owner_name: '管理员', knowledge_base_name: '宜宾', turn_count: 1, last_message_at: '2026-11-12T00:00:00Z' }
const turn = { id: 't1', conversation_id: 'c1', turn_no: 1, question: '宜宾有哪些景点？', answer: '蜀南竹海。', status: 'SUCCESS', sources: [] }
const trace = {
  source: 'langsmith', question: turn.question, status: 'SUCCESS', latency_ms: 2400,
  message: '已读取 LangSmith 追踪。', content_captured: true, truncated: false,
  runs: [
    { id: 'root', name: 'rag.turn', status: 'success', run_type: 'chain', latency_ms: 2400, total_tokens: 125, inputs: {}, outputs: { answer: '蜀南竹海。' } },
    { id: 'memory', parent_id: 'root', name: 'prepare_memory', status: 'success', run_type: 'chain', latency_ms: 40, inputs: {}, outputs: { summary: '旅游咨询' } },
    { id: 'llm', parent_id: 'root', name: 'ChatDeepSeek', status: 'success', run_type: 'llm', latency_ms: 1800, input_tokens: 100, output_tokens: 25, inputs: { prompt: '合成测试提示词' }, outputs: { answer: '合成回答内容' } },
  ],
  local: { run_id: 'root', pipeline_version: 'rag-v2', prompt_version: 'grounded-v2', retrieval: {
    vector: [{ id: 1 }], lexical: ['a'], selected: ['a'], reranker: 'lexical',
    ranked: [{ chunk_id: 'a', document_title: '宜宾旅游指南', score: 0.8, rerank_score: 0.9 }],
  } },
}

test.beforeEach(async ({ page }) => {
  await page.route('**/api/v1/**', async route => {
    const path = new URL(route.request().url()).pathname
    let data: unknown
    if (path.endsWith('/auth/refresh')) data = { access_token: 'test-token', user: { display_name: 'Admin' }, pages: [{ code: 'qa_logs', name: '问答日志', route_path: '/qa-logs', route_name: 'QALogs', component_key: 'QALogs', page_type: 'menu', is_visible: true }] }
    else if (path.endsWith('/admin/qa-users')) data = { items: [{ id: 'owner', name: '管理员', conversation_count: 1 }], total: 1 }
    else if (path.endsWith('/admin/qa-conversations')) data = { items: [conversation], next_cursor: null }
    else if (path.endsWith('/turns')) data = { conversation, items: [turn], next_before: null }
    else if (path.endsWith('/trace')) data = trace
    else throw new Error(`Unexpected request: ${path}`)
    return route.fulfill({ json: { code: 0, data } })
  })
  await page.goto('/qa-logs')
  await page.locator('.owner-item').click()
  await page.locator('.audit-conversation').click()
})

for (const width of [1440, 390]) {
  test(`flow opens in centered detail dialog and returns to selected conversation at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 })
    await page.getByRole('button', { name: '查看处理流程', exact: true }).click()
    const dialog = page.getByRole('dialog', { name: '问答处理流程' })
    await expect(dialog).toBeVisible()
    await expect(dialog).not.toHaveClass(/is-fullscreen/)
    const bounds = await page.locator('.el-dialog.trace-detail-dialog').boundingBox()
    expect(bounds!.width).toBeLessThan(width)
    expect(bounds!.x).toBeGreaterThan(0)
    await expect(dialog.getByText('LangSmith 追踪', { exact: false })).toBeVisible()
    await expect(dialog.getByText('125', { exact: true })).toBeVisible()
    await dialog.locator('.trace-node').filter({ hasText: 'DeepSeek 模型调用' }).click()
    await expect(dialog.locator('.trace-payload:visible')).toContainText('合成测试提示词')
    await dialog.getByRole('tab', { name: '输出数据' }).click()
    await expect(dialog.locator('.trace-payload:visible')).toContainText('合成回答内容')
    await expect(dialog.getByText('用于回答', { exact: true })).toBeVisible()
    expect(await dialog.evaluate(el => el.scrollWidth <= el.clientWidth + 1)).toBe(true)
    if (width === 1440) await page.screenshot({ path: '/tmp/kbs-trace-detail.png', fullPage: true })
    await page.keyboard.press('Escape')
    await expect(dialog).toBeHidden()
    await expect(page.locator('.audit-conversation.selected')).toContainText(conversation.title)
    await expect(page.locator('.conversation-answer')).toContainText(turn.answer)
  })
}

test('unavailable cloud uses local flow; old log and request failure can be refreshed', async ({ page }) => {
  let attempt = 0
  await page.route('**/turns/t1/trace', async route => {
    attempt++
    if (attempt === 1) return route.fulfill({ status: 503, json: { code: 50300, message: '暂时不可用' } })
    return route.fulfill({ json: { code: 0, data: { ...trace, source: 'local', runs: [],
      message: attempt === 2 ? 'LangSmith 暂不可用，展示本地诊断。' : '此历史记录未保存流程追踪。',
      local: attempt === 2 ? { steps: trace.runs.map(({ inputs, outputs, ...step }) => step) } : {},
    } } })
  })
  await page.getByRole('button', { name: '查看处理流程', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: '问答处理流程' })
  await expect(dialog.getByText('暂时不可用', { exact: true })).toBeVisible()
  await dialog.getByRole('button', { name: '刷新流程' }).click()
  await expect(dialog.getByText('LangSmith 暂不可用，展示本地诊断。')).toBeVisible()
  await expect(dialog.locator('.trace-node')).toHaveCount(3)
  await expect(dialog.locator('.trace-payload:visible')).toContainText('未采集此内容')
  await dialog.getByRole('button', { name: '刷新流程' }).click()
  await expect(dialog.getByText('本轮暂无可展示的流程步骤')).toBeVisible()
})

test('local steps remain visible while cloud children are still syncing', async ({ page }) => {
  await page.route('**/turns/t1/trace', route => route.fulfill({ json: { code: 0, data: {
    ...trace, runs: [trace.runs[0]], local: { ...trace.local,
      steps: trace.runs.map(({ inputs, outputs, ...step }) => step) },
  } } }))
  await page.getByRole('button', { name: '查看处理流程', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: '问答处理流程' })
  await expect(dialog.locator('.trace-node')).toHaveCount(3)
  await dialog.locator('.trace-node').filter({ hasText: 'DeepSeek 模型调用' }).click()
  await expect(dialog.locator('.trace-payload:visible')).toContainText('未采集此内容')
})

for (const width of [1920, 1440]) {
  test(`deep execution trees keep complete labels and a large payload area at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: width === 1920 ? 1080 : 900 })
    const nested = Array.from({ length: 12 }, (_, i) => ({
      ...trace.runs[2], id: `nested-${i}`, parent_id: i ? `nested-${i - 1}` : 'root',
      name: i === 11 ? 'RunnableParallel<parsed,parsing_error>' : `RunnableSequence-${i}`,
      outputs: { content: '核验后的答案内容。'.repeat(800) },
    }))
    await page.route('**/turns/t1/trace', route => route.fulfill({ json: { code: 0, data: {
      ...trace, runs: [trace.runs[0], ...nested],
    } } }))
    await page.getByRole('button', { name: '查看处理流程', exact: true }).click()
    const dialog = page.locator('.el-dialog.trace-detail-dialog')
    const bounds = await dialog.boundingBox()
    expect(bounds!.width).toBeGreaterThan(1300)
    expect(bounds!.width).toBeLessThan(width)
    const leaf = dialog.locator('.trace-node-name').filter({ hasText: 'RunnableParallel<parsed,parsing_error>' })
    await leaf.click()
    await expect(dialog.locator('.trace-node-heading h3')).toHaveText('RunnableParallel<parsed,parsing_error>')
    // Deep names must have real horizontal space, not an ellipsis or clipped child area.
    const labelBounds = await leaf.evaluate(el => ({ width: el.clientWidth, scroll: el.scrollWidth }))
    expect(labelBounds.scroll).toBeLessThanOrEqual(labelBounds.width)
    const scrollArea = dialog.locator('.trace-tree-scroll')
    await expect(scrollArea).toBeVisible()
    expect(await scrollArea.evaluate(el => el.scrollWidth >= el.clientWidth)).toBe(true)
    await dialog.getByRole('tab', { name: '输出数据' }).click()
    const payload = dialog.locator('.trace-payload:visible')
    const payloadBounds = await payload.boundingBox()
    expect(payloadBounds!.height).toBeGreaterThan(330)
    expect(payloadBounds!.width).toBeGreaterThan(650)
    expect(await payload.evaluate(el => el.scrollHeight > el.clientHeight)).toBe(true)
    await payload.evaluate(el => { el.scrollTop = el.scrollHeight })
    expect(await payload.evaluate(el => el.scrollTop > 0)).toBe(true)
    expect(await dialog.evaluate(el => el.scrollWidth <= el.clientWidth + 1)).toBe(true)
    if (width === 1920) await page.screenshot({ path: '/tmp/kbs-trace-detail-expanded.png' })
  })
}
