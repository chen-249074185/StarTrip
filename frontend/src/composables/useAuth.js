// 登录态：token 放 sessionStorage（同一标签页；刷新仍有效）
import { ref } from 'vue'

const token = ref(sessionStorage.getItem('startrip_token') || '')

export function useAuth() {
  async function login(username, password) {
    const resp = await fetch('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
    })
    if (!resp.ok) {
      let msg = '登录失败'
      try {
        const body = await resp.json()
        msg = body.detail || msg
      } catch {
        // 非 JSON 响应，保留默认提示
      }
      throw new Error(msg)
    }
    const body = await resp.json()
    token.value = body.data.access_token
    sessionStorage.setItem('startrip_token', token.value)
  }

  function logout() {
    token.value = ''
    sessionStorage.removeItem('startrip_token')
  }

  return { token, login, logout }
}
