import { expect, test, type APIRequestContext, type Page } from '@playwright/test'

type MailpitMessage = {
  ID: string
  Subject: string
  To: Array<{ Address: string }>
}

function requiredEnvironment(name: string): string {
  const value = process.env[name]
  if (!value) throw new Error(`${name} is required; run bootstrap_e2e_owner first.`)
  return value
}

async function waitForMail(
  request: APIRequestContext,
  mailpitURL: string,
  recipient: string,
  subject: string,
): Promise<MailpitMessage> {
  let matches: MailpitMessage[] = []
  const searchURL = new URL('/api/v1/search', mailpitURL)
  searchURL.searchParams.set('query', `to:${recipient}`)

  await expect.poll(async () => {
    const response = await request.get(searchURL.toString())
    expect(response.ok()).toBeTruthy()
    const payload = await response.json() as { messages?: MailpitMessage[] }
    matches = (payload.messages ?? []).filter((message) =>
      message.Subject === subject
      && message.To.length === 1
      && message.To[0]?.Address.toLowerCase() === recipient.toLowerCase(),
    )
    return matches.length
  }, { message: `waiting for one access email to ${recipient}`, timeout: 30_000 }).toBe(1)

  return matches[0]
}

async function sessionStatus(page: Page): Promise<{ status: number; code?: string }> {
  return page.evaluate(async () => {
    const response = await fetch('/api/v1/learner/courses', { credentials: 'include' })
    const body = await response.json().catch(() => ({})) as { code?: string }
    return { status: response.status, code: body.code }
  })
}

test('vendor creates a course, grants access, and replaces the learner session', async ({
  browser,
  request,
}) => {
  const ownerEmail = requiredEnvironment('E2E_OWNER_EMAIL')
  const ownerPassword = requiredEnvironment('E2E_OWNER_PASSWORD')
  const vendorName = requiredEnvironment('E2E_VENDOR_NAME')
  const baseURL = process.env.E2E_BASE_URL ?? 'http://localhost:5173'
  const mailpitURL = process.env.E2E_MAILPIT_URL ?? 'http://localhost:8025'
  const unique = `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`
  const courseTitle = `E2E course ${unique}`
  const courseSlug = `e2e-course-${unique}`
  const moduleTitle = `E2E module ${unique}`
  const lessonTitle = `E2E lesson ${unique}`
  const contentTitle = `E2E content ${unique}`
  const lessonContent = `# E2E content ${unique}`
  const learnerEmail = `learner-${unique}@example.com`
  const expectedSubject = `Доступ к курсу: ${courseTitle}`

  const vendorContext = await browser.newContext({ baseURL })
  const vendor = await vendorContext.newPage()

  await vendor.goto('/vendor/')
  await vendor.getByLabel('Email').fill(ownerEmail)
  await vendor.getByLabel('Пароль').fill(ownerPassword)
  await vendor.getByRole('button', { name: /^Войти/ }).click()
  await expect(vendor.getByRole('heading', { name: vendorName })).toBeVisible()
  // Reload also verifies that /vendor/me restores the authenticated server session.
  await vendor.reload()
  await expect(vendor.getByRole('heading', { name: vendorName })).toBeVisible()

  await vendor.getByRole('button', { name: /Новый курс/ }).click()
  await vendor.getByLabel('Название').fill(courseTitle)
  await vendor.getByLabel('Slug').fill(courseSlug)
  await vendor.getByLabel('Описание Markdown').fill(`Description ${unique}`)
  const [courseResponse] = await Promise.all([
    vendor.waitForResponse((response) =>
      response.request().method() === 'POST'
      && response.url().includes('/api/v1/vendor/courses?vendor_id='),
    ),
    vendor.getByRole('button', { name: 'Сохранить курс' }).click(),
  ])
  expect(courseResponse.ok()).toBeTruthy()

  const courseRow = vendor.getByRole('button', { name: new RegExp(courseTitle) })
  await expect(courseRow).toBeVisible()
  await courseRow.click()

  await vendor.getByPlaceholder('Новый модуль').fill(moduleTitle)
  const [moduleResponse] = await Promise.all([
    vendor.waitForResponse((response) =>
      response.request().method() === 'POST' && response.url().endsWith('/structure'),
    ),
    vendor.getByRole('button', { name: 'Добавить модуль' }).click(),
  ])
  expect(moduleResponse.ok()).toBeTruthy()

  await vendor.getByLabel(`Новый урок в ${moduleTitle}`).fill(lessonTitle)
  const lessonResponsePromise = vendor.waitForResponse((response) =>
    response.request().method() === 'POST' && response.url().endsWith('/structure'),
  )
  await vendor.getByRole('button', { name: 'Добавить урок' }).click()
  expect((await lessonResponsePromise).ok()).toBeTruthy()
  const lessonRow = vendor.locator('.tree-child').filter({ hasText: lessonTitle })
  await expect(lessonRow).toBeVisible()
  await lessonRow.getByRole('button', { name: 'Редактировать' }).click()

  const newContent = lessonRow.getByRole('heading', { name: 'Новый контент-блок' }).locator('..')
  await newContent.getByLabel('Название').fill(contentTitle)
  await newContent.getByLabel('Markdown').fill(lessonContent)
  const contentResponsePromise = vendor.waitForResponse((response) =>
    response.request().method() === 'POST' && response.url().endsWith('/structure'),
  )
  await newContent.getByRole('button', { name: 'Добавить блок' }).click()
  expect((await contentResponsePromise).ok()).toBeTruthy()

  const lessonPublishResponsePromise = vendor.waitForResponse((response) =>
    response.request().method() === 'POST' && response.url().endsWith('/structure'),
  )
  await lessonRow.getByRole('button', { name: 'Опубликовать урок' }).click()
  expect((await lessonPublishResponsePromise).ok()).toBeTruthy()
  await expect(lessonRow.getByText('Опубликован в следующей ревизии')).toBeVisible()

  const publishResponsePromise = vendor.waitForResponse((response) =>
    response.request().method() === 'POST' && response.url().endsWith('/publish'),
  )
  await vendor.getByRole('button', { name: /Опубликовать ревизию/ }).click()
  expect((await publishResponsePromise).ok()).toBeTruthy()
  await vendor.getByRole('button', { name: 'Закрыть' }).click()
  await expect(vendor.getByRole('button', { name: new RegExp(`${courseTitle}.*published`) })).toBeVisible()

  const accessPanel = vendor.getByRole('heading', { name: 'Ученики' }).locator('..')
  await accessPanel.getByPlaceholder('email ученика').fill(learnerEmail)
  await accessPanel.locator('select').selectOption({ label: courseTitle })
  const grantResponsePromise = vendor.waitForResponse((response) =>
    response.request().method() === 'POST' && response.url().endsWith('/api/v1/vendor/access/grant'),
  )
  await accessPanel.getByRole('button', { name: 'Выдать доступ' }).click()
  expect((await grantResponsePromise).ok()).toBeTruthy()
  await expect(accessPanel.getByText(learnerEmail, { exact: true })).toBeVisible()

  const message = await waitForMail(request, mailpitURL, learnerEmail, expectedSubject)
  const detail = await request.get(new URL(`/api/v1/message/${encodeURIComponent(message.ID)}`, mailpitURL).toString())
  expect(detail.ok()).toBeTruthy()
  const body = await detail.json() as { Text?: string }
  const emailedAccessURL = body.Text?.match(/https?:\/\/[^\s]+\/app\/access\/[^\s]+/)?.[0]
  expect(emailedAccessURL).toBeTruthy()
  const accessPath = new URL(emailedAccessURL as string).pathname
  await vendorContext.close()

  const first = await browser.newContext({ baseURL })
  const firstPage = await first.newPage()
  await firstPage.goto(accessPath)
  await expect(firstPage.getByRole('heading', { name: courseTitle })).toBeVisible()
  await firstPage.getByRole('button', { name: /Открыть курс/ }).click()
  await expect(firstPage.getByRole('heading', { name: courseTitle })).toBeVisible()
  await expect(firstPage.getByText(`E2E content ${unique}`, { exact: true })).toBeVisible()

  const second = await browser.newContext({ baseURL })
  const secondPage = await second.newPage()
  await secondPage.goto(accessPath)
  await secondPage.getByRole('button', { name: /Открыть курс/ }).click()
  await expect(secondPage.getByRole('heading', { name: courseTitle })).toBeVisible()

  expect(await sessionStatus(firstPage)).toEqual({ status: 401, code: 'SESSION_REVOKED' })
  await firstPage.reload()
  await expect(firstPage.getByRole('heading', { name: /Сессия открыта на другом устройстве/ })).toBeVisible()

  expect((await sessionStatus(secondPage)).status).toBe(200)
  await expect(secondPage.getByRole('heading', { name: courseTitle })).toBeVisible()
  await expect(secondPage.getByText(`E2E content ${unique}`, { exact: true })).toBeVisible()
  await expect(secondPage.getByRole('button', { name: /Отметить урок завершённым/ })).toBeVisible()

  await first.close()
  await second.close()
})
