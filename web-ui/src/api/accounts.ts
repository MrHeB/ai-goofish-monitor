import { http } from '@/lib/http'

export interface AccountItem {
  name: string
  path: string
}

export interface AccountDetail extends AccountItem {
  content: string
}

export async function listAccounts(): Promise<AccountItem[]> {
  return await http('/api/accounts')
}

export async function getAccount(name: string): Promise<AccountDetail> {
  return await http(`/api/accounts/${encodeURIComponent(name)}`)
}

export async function createAccount(payload: { name: string; content: string }): Promise<AccountDetail> {
  return await http('/api/accounts', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export async function updateAccount(name: string, content: string): Promise<AccountDetail> {
  return await http(`/api/accounts/${encodeURIComponent(name)}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content }),
  })
}

export async function deleteAccount(name: string): Promise<{ message: string }> {
  return await http(`/api/accounts/${encodeURIComponent(name)}`, { method: 'DELETE' })
}

export async function authorizeAccount(name: string, timeout = 300): Promise<{ message: string; path: string; cookies: number }> {
  return await http(`/api/accounts/${encodeURIComponent(name)}/authorize`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ timeout }),
  })
}

export interface QrSession {
  success: boolean
  session_id: string
  qr_code_url: string
  expires_in: number
  message?: string
}

export interface QrSessionStatus {
  status: string
  session_id: string
  account_name?: string
  message?: string
  verification_url?: string
  path?: string
  cookies?: number
}

export async function createQrSession(name: string): Promise<QrSession> {
  return await http('/api/accounts/qr/session', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name }),
  })
}

export async function getQrSessionStatus(sessionId: string): Promise<QrSessionStatus> {
  return await http(`/api/accounts/qr/${encodeURIComponent(sessionId)}/status`)
}
