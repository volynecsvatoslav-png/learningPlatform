import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { ApiError, vendorApi } from '../lib/api'

export function VendorPasswordResetPage() {
  const parts = window.location.pathname.split('/').filter(Boolean)
  const uid = parts.at(-2) ?? ''
  const token = parts.at(-1) ?? ''
  const [password, setPassword] = useState('')
  const [confirmation, setConfirmation] = useState('')
  const [mismatch, setMismatch] = useState(false)
  const reset = useMutation({ mutationFn: () => vendorApi.resetPassword(uid, token, password) })
  const invalidLink = reset.error instanceof ApiError && reset.error.code === 'INVALID_RESET_LINK'
  return <main className="auth-layout"><section className="auth-card"><p className="eyebrow">Кабинет вендора</p><h1>Новый пароль</h1><p className="muted">Задайте новый пароль длиной не менее 15 символов.</p>{reset.isSuccess ? <><p className="form-success">Пароль изменен. Теперь можно войти в кабинет.</p><a className="primary-action" href="/vendor/">Перейти ко входу →</a></> : <form onSubmit={(event) => { event.preventDefault(); const differs = password !== confirmation; setMismatch(differs); if (!differs) reset.mutate() }}><label>Новый пароль<input type="password" minLength={15} value={password} onChange={(event) => { setPassword(event.target.value) }} required /></label><label>Подтверждение пароля<input type="password" minLength={15} value={confirmation} onChange={(event) => { setConfirmation(event.target.value) }} required /></label><button className="primary-action" type="submit" disabled={reset.isPending}>Изменить пароль</button>{mismatch && <p className="form-error">Пароли не совпадают.</p>}{reset.isError && <p className="form-error">{invalidLink ? 'Ссылка недействительна или уже использована.' : 'Пароль не соответствует требованиям безопасности.'}</p>}</form>}</section></main>
}
