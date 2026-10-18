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

export function useSSE() {
  async function streamChat({ sessionId, message, onEvent }) {
    const resp = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: sessionId, message }),
    })
    if (!resp.ok || !resp.body) throw new Error('请求失败: ' + resp.status)

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

  return { streamChat }
}
