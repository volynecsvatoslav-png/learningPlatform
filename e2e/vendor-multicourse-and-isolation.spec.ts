import { expect, test, type APIRequestContext, type Page } from '@playwright/test'

type MailpitMessage = {
  ID: string
  Subject: string
  To: Array<{ Address: string }>
}

function requiredEnvironment(name: string): string {
  const value = process.env[name]
  if (!value) throw new Error(`${name} is required; run the E2E bootstrap commands first.`)
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
  }, { message: `waiting for one email "${subject}" to ${recipient}`, timeout: 30_000 }).toBe(1)

  return matches[0]
}

async function mailURL(request: APIRequestContext, mailpitURL: string, message: MailpitMessage): Promise<URL> {
  const detail = await request.get(new URL(`/api/v1/message/${encodeURIComponent(message.ID)}`, mailpitURL).toString())
  expect(detail.ok()).toBeTruthy()
  const body = await detail.json() as { Text?: string }
  const match = body.Text?.match(/https?:\/\/[^\s]+\/app\/[^\s]*/)?.[0]
  expect(match).toBeTruthy()
  return new URL(match as string)
}

async function loginVendor(page: Page, ownerEmail: string, ownerPassword: string, vendorName: string): Promise<void> {
  await page.goto('/vendor/')
  await page.getByLabel('Email').fill(ownerEmail)
  await page.getByLabel('Пароль').fill(ownerPassword)
  await page.getByRole('button', { name: /^Войти/ }).click()
  await expect(page.getByRole('heading', { name: vendorName })).toBeVisible()
}

async function createPublishedCourse(
  page: Page,
  names: { course: string; module: string; lesson: string; content: string },
): Promise<void> {
  await page.getByRole('button', { name: /Новый курс/ }).click()
  await page.getByLabel('Название').fill(names.course)
  await page.getByLabel('Slug').fill(`e2e-${names.course.replace(/\W+/g, '-').toLowerCase()}`)
  await page.getByLabel('Описание Markdown').fill(`Description ${names.course}`)
  const [courseResponse] = await Promise.all([
    page.waitForResponse((response) =>
      response.request().method() === 'POST'
      && response.url().includes('/api/v1/vendor/courses?vendor_id='),
    ),
    page.getByRole('button', { name: 'Сохранить курс' }).click(),
  ])
  expect(courseResponse.ok()).toBeTruthy()

  const courseRow = page.getByRole('button', { name: new RegExp(names.course) })
  await expect(courseRow).toBeVisible()
  await courseRow.click()

  await page.getByPlaceholder('Новый модуль').fill(names.module)
  const [moduleResponse] = await Promise.all([
    page.waitForResponse((response) =>
      response.request().method() === 'POST' && response.url().endsWith('/structure'),
    ),
    page.getByRole('button', { name: 'Добавить модуль' }).click(),
  ])
  expect(moduleResponse.ok()).toBeTruthy()

  await page.getByLabel(`Новый урок в ${names.module}`).fill(names.lesson)
  const lessonResponsePromise = page.waitForResponse((response) =>
    response.request().method() === 'POST' && response.url().endsWith('/structure'),
  )
  await page.getByRole('button', { name: 'Добавить урок' }).click()
  expect((await lessonResponsePromise).ok()).toBeTruthy()
  const lessonRow = page.locator('.tree-child').filter({ hasText: names.lesson })
  await expect(lessonRow).toBeVisible()
  await lessonRow.getByRole('button', { name: 'Редактировать' }).click()

  const newContent = lessonRow.getByRole('heading', { name: 'Новый контент-блок' }).locator('..')
  await newContent.getByLabel('Название').fill(names.content)
  await newContent.getByLabel('Markdown').fill(`# ${names.content}`)
  const contentResponsePromise = page.waitForResponse((response) =>
    response.request().method() === 'POST' && response.url().endsWith('/structure'),
  )
  await newContent.getByRole('button', { name: 'Добавить блок' }).click()
  expect((await contentResponsePromise).ok()).toBeTruthy()

  const lessonPublishResponsePromise = page.waitForResponse((response) =>
    response.request().method() === 'POST' && response.url().endsWith('/structure'),
  )
  await lessonRow.getByRole('button', { name: 'Опубликовать урок' }).click()
  expect((await lessonPublishResponsePromise).ok()).toBeTruthy()
  await expect(lessonRow.getByText('Опубликован в следующей ревизии')).toBeVisible()

  const publishResponsePromise = page.waitForResponse((response) =>
    response.request().method() === 'POST' && response.url().endsWith('/publish'),
  )
  await page.getByRole('button', { name: /Опубликовать ревизию/ }).click()
  expect((await publishResponsePromise).ok()).toBeTruthy()
  await page.getByRole('button', { name: 'Закрыть' }).click()
  await expect(page.getByRole('button', { name: new RegExp(`${names.course}.*published`) })).toBeVisible()
}

async function grantAccess(page: Page, learnerEmail: string, courseTitles: string[]): Promise<void> {
  const accessPanel = page.getByRole('heading', { name: 'Ученики' }).locator('..')
  await accessPanel.getByPlaceholder('email ученика').fill(learnerEmail)
  await accessPanel.locator('select').selectOption(courseTitles.map((title) => ({ label: title })))
  const grantResponsePromise = page.waitForResponse((response) =>
    response.request().method() === 'POST' && response.url().endsWith('/api/v1/vendor/access/grant'),
  )
  await accessPanel.getByRole('button', { name: 'Выдать доступ' }).click()
  expect((await grantResponsePromise).ok()).toBeTruthy()
  await expect(accessPanel.getByText(learnerEmail, { exact: true })).toHaveCount(courseTitles.length)
}

async function openLearnerAccess(page: Page, url: URL): Promise<void> {
  await page.goto(url.toString())
  await expect(
    page.locator('h1').filter({ hasText: /Все курсы|Перенос входа/ }).first(),
  ).toBeVisible({ timeout: 15_000 })
  const transfer = page.getByRole('button', { name: 'Перенести вход на это устройство' })
  if (await transfer.isVisible().catch(() => false)) {
    await transfer.click()
  }
  await expect(page.getByRole('heading', { name: 'Все курсы' })).toBeVisible()
}

async function learnerCourses(page: Page): Promise<Array<{ id: string; title: string }>> {
  return page.evaluate(async () => {
    const response = await fetch('/api/v1/learner/courses', { credentials: 'include' })
    if (response.status !== 200) throw new Error(`courses list status ${response.status}`)
    return await response.json() as Array<{ id: string; title: string }>
  })
}

async function statusOf(page: Page, path: string): Promise<number> {
  return page.evaluate(async (url) => {
    const response = await fetch(url, { credentials: 'include' })
    return response.status
  }, path)
}

async function assertCourseHidden(page: Page, courseId: string): Promise<void> {
  expect(await statusOf(page, `/api/v1/learner/courses/${courseId}`)).toBe(404)
  expect(await statusOf(page, `/api/v1/learner/courses/${courseId}/offline-manifest`)).toBe(404)
  expect(await statusOf(page, `/api/v1/learner/courses/${courseId}/progress`)).toBe(404)
  expect(await statusOf(
    page,
    `/api/v1/learner/courses/${courseId}/media/00000000-0000-0000-0000-000000000001/stream-url`,
  )).toBe(404)
  expect(await statusOf(
    page,
    `/api/v1/learner/courses/${courseId}/offline-media/00000000-0000-0000-0000-000000000002/00000000-0000-0000-0000-000000000003`,
  )).toBe(404)
}

test('one global learner keeps tenant isolation between two vendors', async ({
  browser,
  request,
}) => {
  test.setTimeout(300_000)
  const ownerEmail = requiredEnvironment('E2E_OWNER_EMAIL')
  const ownerPassword = requiredEnvironment('E2E_OWNER_PASSWORD')
  const vendorAName = requiredEnvironment('E2E_VENDOR_NAME')
  const vendorBOwnerEmail = requiredEnvironment('E2E_VENDOR_B_OWNER_EMAIL')
  const vendorBOwnerPassword = requiredEnvironment('E2E_VENDOR_B_OWNER_PASSWORD')
  const vendorBName = requiredEnvironment('E2E_VENDOR_B_NAME')
  const vendorBCourseTitle = requiredEnvironment('E2E_VENDOR_B_COURSE_TITLE')
  const baseURL = process.env.E2E_BASE_URL ?? 'http://localhost:5173'
  const mailpitURL = process.env.E2E_MAILPIT_URL ?? 'http://localhost:8025'
  const unique = `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`
  const learnerEmail = process.env.E2E_LEARNER_EMAIL ?? `learner-${unique}@example.com`

  const courseA1 = {
    course: `E2E isolation A1 ${unique}`,
    module: `E2E module A1 ${unique}`,
    lesson: `E2E lesson A1 ${unique}`,
    content: `E2E content A1 ${unique}`,
  }
  const courseA2 = {
    course: `E2E isolation A2 ${unique}`,
    module: `E2E module A2 ${unique}`,
    lesson: `E2E lesson A2 ${unique}`,
    content: `E2E content A2 ${unique}`,
  }

  // Vendor A: two courses granted to the global learner.
  const vendorAContext = await browser.newContext({ baseURL })
  const vendorA = await vendorAContext.newPage()
  await loginVendor(vendorA, ownerEmail, ownerPassword, vendorAName)
  await createPublishedCourse(vendorA, courseA1)
  await createPublishedCourse(vendorA, courseA2)
  await grantAccess(vendorA, learnerEmail, [courseA1.course, courseA2.course])

  const accessMessageA = await waitForMail(
    request, mailpitURL, learnerEmail, `Доступ к курсам: ${vendorAName}`,
  )
  const emailedAccessA = await mailURL(request, mailpitURL, accessMessageA)
  const accessA = new URL(`${baseURL}/app/#${emailedAccessA.hash.replace(/^#/, '')}`)
  await vendorAContext.close()

  // Vendor B (created by bootstrap_e2e_vendor): its course B1 granted to the same learner.
  const vendorBContext = await browser.newContext({ baseURL })
  const vendorB = await vendorBContext.newPage()
  await loginVendor(vendorB, vendorBOwnerEmail, vendorBOwnerPassword, vendorBName)
  await grantAccess(vendorB, learnerEmail, [vendorBCourseTitle])

  const accessMessageB = await waitForMail(
    request, mailpitURL, learnerEmail, `Доступ к курсам: ${vendorBName}`,
  )
  const emailedAccessB = await mailURL(request, mailpitURL, accessMessageB)
  const accessB = new URL(`${baseURL}/app/#${emailedAccessB.hash.replace(/^#/, '')}`)
  await vendorBContext.close()

  // Tenant A session: one access link shows both of vendor A courses and no vendor B content.
  const learnerAContext = await browser.newContext({ baseURL })
  const learnerA = await learnerAContext.newPage()
  await openLearnerAccess(learnerA, accessA)
  await expect(learnerA.getByRole('button', { name: new RegExp(courseA1.course) })).toBeVisible()
  await expect(learnerA.getByRole('button', { name: new RegExp(courseA2.course) })).toBeVisible()
  await expect(learnerA.getByRole('button', { name: new RegExp(vendorBCourseTitle) })).toHaveCount(0)
  const vendorACourses = await learnerCourses(learnerA)
  const courseA1Row = vendorACourses.find((course) => course.title === courseA1.course)
  const courseA2Row = vendorACourses.find((course) => course.title === courseA2.course)
  expect(courseA1Row).toBeTruthy()
  expect(courseA2Row).toBeTruthy()
  expect(vendorACourses.length).toBe(2)

  // Tenant B session: shows vendor B course and no vendor A content.
  const learnerBContext = await browser.newContext({ baseURL })
  const learnerB = await learnerBContext.newPage()
  await openLearnerAccess(learnerB, accessB)
  await expect(learnerB.getByRole('button', { name: new RegExp(vendorBCourseTitle) })).toBeVisible()
  await expect(learnerB.getByRole('button', { name: new RegExp(courseA1.course) })).toHaveCount(0)
  await expect(learnerB.getByRole('button', { name: new RegExp(courseA2.course) })).toHaveCount(0)
  const vendorBCourses = await learnerCourses(learnerB)
  const courseB1Row = vendorBCourses.find((course) => course.title === vendorBCourseTitle)
  expect(courseB1Row).toBeTruthy()

  for (const foreignId of [courseA1Row?.id, courseA2Row?.id]) {
    if (foreignId) {
      expect(vendorBCourses.map((course) => course.id)).not.toContain(foreignId)
      await assertCourseHidden(learnerB, foreignId)
    }
  }
  if (courseB1Row?.id) {
    expect(vendorACourses.map((course) => course.id)).not.toContain(courseB1Row.id)
    await assertCourseHidden(learnerA, courseB1Row.id)
  }

  await learnerAContext.close()
  await learnerBContext.close()
})