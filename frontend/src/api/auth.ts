import { http } from './client'

import type { UserRole } from './user'

export type { UserRole } from './user'

export interface LoginBody {
  /**
   * 登录名（用户名或手机号）。请求体使用字段名 `phone`，与后端 LoginRequest 一致，
   * 避免部分环境下仅传 username 时的校验差异。
   */
  phone: string
  password: string
}

export interface TokenResponse {
  access_token: string
  token_type: string
  role: UserRole
  user_id: number
}

export interface RegisterBody {
  username: string
  password: string
  phone: string
  verification_code: string
}

export interface SendSmsResponse {
  ok: boolean
  expires_in: number
  /** 仅当服务端开启短信明文回显（开发）时存在 */
  code?: string
}

export async function login(body: LoginBody) {
  const { data } = await http.post<TokenResponse>('/auth/login', {
    phone: body.phone,
    password: body.password,
  })
  return data
}

export async function register(body: RegisterBody) {
  const { data } = await http.post<TokenResponse>('/auth/register', body)
  return data
}

export async function sendRegisterSms(phone: string) {
  const { data } = await http.post<SendSmsResponse>('/auth/sms/send', { phone })
  return data
}
