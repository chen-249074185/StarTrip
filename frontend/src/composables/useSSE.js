// 用 fetch + ReadableStream 解析 SSE。
// 不用 EventSource：它不能 POST、不能带 header（未来加 JWT 需要）。

function parseBlock(block) {
  let event = 'message'
  let data = ''
  for (const line of block.split('\n')) {
    if (line.startsWith('event:')) event = line.slice(6).trim()
    else if (line.startsWith('data:')) data += line.slice(5).trim()
  }
  if (!data) return null
  try {
    return { event, data: JSON.parse(data) }
  } catch {
    return { event, data }
  }
}

async function postSSE(url, body, onEvent, token) {
  const headers = { 'Content-Type': 'application/json' }
  if (token) headers.Authorization = `Bearer ${token}`
  const resp = await fetch(url, {
    method: 'POST',
    headers,
    body: JSON.stringify(body),
  })
  if (!resp.ok || !resp.body) {
    const err = new Error('请求失败: ' + resp.status)
    err.status = resp.status
    throw err
  }

  const reader = resp.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const parts = buffer.split('\n\n')
    buffer = parts.pop()
    for (const block of parts) {
      const ev = parseBlock(block)
      if (ev) onEvent(ev)
    }
  }
}

export function useSSE() {
  function streamChat({ sessionId, message, token, onEvent }) {
    return postSSE('/api/chat', { session_id: sessionId, message }, onEvent, token)
  }

  function resumeChat({ sessionId, tasks, token, onEvent }) {
    return postSSE('/api/resume', { session_id: sessionId, tasks }, onEvent, token)
  }

  return { streamChat, resumeChat }
}
