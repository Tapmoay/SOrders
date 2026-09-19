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

export async function login(body: LoginBody) {
  const { data } = await http.post<TokenResponse>('/auth/login', {
    phone: body.phone,
    password: body.password,
  })
  return data
}

/**
 * 登出：**服务端**把这个账号已发出的令牌全部作废（后端 `token_version` +1）。
 *
 * ⚠️ 2026-09-19 审计：H5 原来的「退出登录」只清本机 localStorage，服务端一个字都不知道 ——
 * 被复制走的令牌照样能用满 24 小时，手机丢了也没有止损手段。
 * 现在退出登录 = 真的作废（代价：同一账号的其它设备也要重新登录，这是「登出」应有的语义）。
 */
export async function logout() {
  await http.post('/auth/logout')
}

/*
 * 这里原来还有 `register()` / `sendRegisterSms()`，指向 `POST /auth/register` 与
 * `POST /auth/sms/send` ——**这两个端点在白名单里根本不存在**（后端只有 login/token/logout，
 * 账号一律由派单员在「账号管理」里开通）。于是 H5 登录页那个「注册」页签是 100% 死的：
 * 用户填完表、点「获取验证码」→ 404，点「注册」→ 404，错误提示还把 404 说成网络问题。
 * 2026-09-19 审计 H5 已把注册入口整块删掉（`_tools/qa/_check_client_contract.py` 第⑥条
 * 现在会把"H5 调了不存在的端点"直接判红，同类问题不会再出现）。
 */
