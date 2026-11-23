// SPDX-License-Identifier: GPL-3.0-or-later
// Built alongside nanoMuse's desktop plugin. No second agent loop lives here.
import { createServer, type IncomingMessage } from 'node:http'
import { readFileSync } from 'node:fs'
import { timingSafeEqual, randomUUID } from 'node:crypto'
import type { TaskRunner } from './task.ts'
import type { SessionId } from '@deepseek-ai/dsh-session'
import { PersistentTurns } from './persistent-turns.ts'
import { PersistentTaskEndpoint } from './persistent-task-endpoint.ts'
import { HubError, type IncomingCall } from './hub.ts'

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/
const FROM = { id: 'edith-glasses', name: 'Edith glasses', kind: 'glasses' }
const MAX_BODY = 2 * 1024 * 1024
type Options = {
  runner: TaskRunner
  journalPath: string
  account(): string
  status(): Record<string, unknown>
  token: string
  port: number
}

async function bodyOf(req: IncomingMessage): Promise<Record<string, unknown>> {
  if (!req.headers['content-type']?.startsWith('application/json')) throw new HubError('usage', 'JSON required')
  const chunks: Buffer[] = []
  let size = 0
  for await (const chunk of req) {
    size += chunk.length
    if (size > MAX_BODY) throw new HubError('usage', 'Request too large')
    chunks.push(Buffer.from(chunk))
  }
  const body: unknown = JSON.parse(Buffer.concat(chunks).toString('utf8'))
  if (!body || typeof body !== 'object' || Array.isArray(body)) throw new HubError('usage', 'Object required')
  return body as Record<string, unknown>
}

export function startBridge(options: Options) {
  if (options.token.length < 32) throw new Error('Edith bridge token must have at least 32 characters')
  const credential = Buffer.from('Bearer ' + options.token)
  const endpoint = PersistentTurns.open(options.journalPath).then(store => new PersistentTaskEndpoint(store))
  let live: { conversation: string; turn: string; account: string; call: IncomingCall; touched: number; stopping: boolean } | undefined
  const stopLive = async () => {
    const current = live
    if (!current) return { stopped: false }
    current.stopping = true
    return options.runner.stop({ call: current.call.id }, current.call)
  }
  // A crashed voice process must not leave an unattended phone task running.
  const lease = setInterval(() => {
    if (live && (Date.now() - live.touched > 30_000 || live.account !== (options.account() || 'local'))) {
      void stopLive().catch(() => undefined)
    }
  }, 1000)
  lease.unref()

  const server = createServer(async (req, res) => {
    const reply = (status: number, body: unknown) => {
      res.writeHead(status, { 'content-type': 'application/json', 'cache-control': 'no-store' })
      res.end(JSON.stringify(body))
    }
    const auth = Buffer.from(req.headers.authorization ?? '')
    // No browser origins, cookies, query tokens, redirects, or LAN listener.
    if (req.headers.origin || auth.length !== credential.length || !timingSafeEqual(auth, credential)) {
      reply(401, { error: 'unauthorized' }); return
    }
    try {
      const url = new URL(req.url ?? '/', 'http://127.0.0.1')
      if (url.pathname === '/v1/status' && req.method === 'GET') {
        reply(200, { protocol: 1, ...options.status() }); return
      }
      const args = req.method === 'GET' ? Object.fromEntries(url.searchParams) : await bodyOf(req)
      const conversation = String(args.conversation ?? '')
      const turn = String(args.turn_id ?? '')
      if (!UUID.test(conversation) || !UUID.test(turn)) throw new HubError('usage', 'Conversation and turn UUIDs required')
      const account = options.account() || 'local'
      const owner = { account, caller: FROM.id, conversation }
      const bound = await endpoint
      const current = live?.conversation === conversation && live.turn === turn && live.account === account ? live : undefined
      if (url.pathname === '/v1/task' && req.method === 'GET') {
        if (current) current.touched = Date.now()
        reply(200, bound.status(owner, turn)); return
      }
      if (url.pathname === '/v1/stop' && req.method === 'POST') {
        reply(200, current ? await stopLive() : { stopped: false }); return
      }
      if (url.pathname === '/v1/approve' && req.method === 'POST') {
        const status = bound.status(owner, turn)
        const events = (status.events ?? []) as Record<string, unknown>[]
        if (!current || current.stopping || typeof args.allow !== 'boolean' || !events.some(e => e.stage === 'approval' && e.approval_id === args.approval_id)) {
          throw new HubError('denied', 'No matching live approval')
        }
        reply(200, await options.runner.approve(args, current.call)); return
      }
      if (url.pathname !== '/v1/task' || req.method !== 'POST') { reply(404, { error: 'not_found' }); return }
      const existing = bound.status(owner, turn)
      if (existing.state !== 'unknown') { reply(200, existing); return }
      if (live) throw new HubError('busy', 'Another glasses turn is still running')
      const text = typeof args.text === 'string' ? args.text.trim() : ''
      if (!text || text.length > 8000) throw new HubError('usage', 'Text required, at most 8000 characters')
      const call: IncomingCall = { id: randomUUID(), from: FROM, event: () => undefined }
      live = { conversation, turn, account, call, touched: Date.now(), stopping: false }
      let accepted!: () => void
      const ready = new Promise<void>(resolve => { accepted = resolve })
      call.event = event => { if (event.stage === 'accepted') accepted() }
      const running = bound.run(owner, turn, call, () => {
        if (args.new_conversation !== true) throw new HubError('context_lost', 'Start a new glasses conversation')
        return options.runner.createTaskSession(FROM)
      }, async (session, event) => {
        if (live?.stopping || (options.account() || 'local') !== account) throw new HubError('cancelled', 'Cancelled before execution')
        return options.runner.task({ ...args, text, stream: true,
          edith_cancelled: () => live?.stopping || (options.account() || 'local') !== account,
        }, { ...call, event }, session as SessionId)
      }).catch(() => undefined).finally(() => {
        if (live?.call.id === call.id) live = undefined
        accepted()
      })
      void running
      await ready
      reply(202, bound.status(owner, turn))
    } catch (error) {
      const code = error instanceof HubError ? error.code : 'failed'
      reply(code === 'busy' ? 409 : code === 'usage' ? 400 : code === 'denied' ? 403 : 500, { error: code })
    }
  })
  server.requestTimeout = 10_000
  server.headersTimeout = 10_000
  server.listen(options.port, '127.0.0.1')
  server.on('close', () => { clearInterval(lease); void stopLive().catch(() => undefined) })
  return server
}

export function configuredBridge(options: Omit<Options, 'token' | 'port'>) {
  const file = process.env.EDITH_BRIDGE_TOKEN_FILE
  if (!file) return undefined
  const port = Number(process.env.EDITH_BRIDGE_PORT ?? 18765)
  if (!Number.isInteger(port) || port < 1024 || port > 65535) throw new Error('Invalid Edith bridge port')
  return startBridge({ ...options, port, token: readFileSync(file, 'utf8').trim() })
}
