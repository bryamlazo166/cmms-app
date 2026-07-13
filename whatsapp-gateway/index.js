/**
 * Gateway WhatsApp (Baileys) para el CMMS.
 *
 * Transporte "tonto": mantiene la sesion de WhatsApp y reenvia cada mensaje
 * privado al webhook Flask del CMMS. Toda la logica de negocio (IA, arbol de
 * equipos, avisos, duplicados) vive en el CMMS — aqui NO.
 *
 * Flujo:
 *   privado entrante -> POST WEBHOOK_URL {phone, text, media...}
 *   respuesta Flask  -> { replies: [...], forwards: [{to, text, attach_incoming_media}] }
 *   gateway          -> envia replies al usuario y forwards a los grupos
 *
 * Anti-baneo: solo responde a quien escribe primero, con retardo humano
 * (0.8-2.5 s) e indicador "escribiendo...". Nunca inicia conversaciones.
 */
import 'dotenv/config'
import { existsSync, unlinkSync } from 'fs'
import pino from 'pino'
import qrcodeTerminal from 'qrcode-terminal'
import QRCode from 'qrcode'
import makeWASocket, {
  useMultiFileAuthState,
  fetchLatestBaileysVersion,
  DisconnectReason,
  downloadMediaMessage,
} from '@whiskeysockets/baileys'

const WEBHOOK_URL = process.env.WEBHOOK_URL || 'http://localhost:5000/api/public/whatsapp/webhook'
const GATEWAY_TOKEN = process.env.GATEWAY_TOKEN || ''
const OWNER_NUMBER = (process.env.OWNER_NUMBER || '').replace(/\D/g, '') // solo digitos
const AUTH_DIR = 'auth_info'
const QR_FILE = 'qr.png'
const MAX_MEDIA_BYTES = 16 * 1024 * 1024 // 16 MB

const logger = pino({ level: 'warn' })

// Dedup en memoria de message ids (Baileys puede re-emitir upserts)
const seenIds = new Set()
function seen(id) {
  if (!id) return false
  if (seenIds.has(id)) return true
  seenIds.add(id)
  if (seenIds.size > 500) {
    const first = seenIds.values().next().value
    seenIds.delete(first)
  }
  return false
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const humanDelay = () => sleep(800 + Math.floor(Math.random() * 1700))

function extractText(msg) {
  const m = msg.message || {}
  return (
    m.conversation ||
    m.extendedTextMessage?.text ||
    m.imageMessage?.caption ||
    m.videoMessage?.caption ||
    m.documentMessage?.caption ||
    ''
  ).trim()
}

function mediaInfo(msg) {
  const m = msg.message || {}
  if (m.imageMessage) return { type: 'image', mimetype: m.imageMessage.mimetype || 'image/jpeg' }
  if (m.videoMessage) return { type: 'video', mimetype: m.videoMessage.mimetype || 'video/mp4' }
  if (m.audioMessage) return { type: 'audio', mimetype: m.audioMessage.mimetype || 'audio/ogg' }
  if (m.documentMessage) return { type: 'document', mimetype: m.documentMessage.mimetype || 'application/octet-stream' }
  return null
}

async function postWebhook(payload) {
  const res = await fetch(WEBHOOK_URL, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-Gateway-Token': GATEWAY_TOKEN,
    },
    body: JSON.stringify(payload),
    signal: AbortSignal.timeout(120000), // el flujo IA puede tardar
  })
  if (!res.ok) throw new Error(`webhook HTTP ${res.status}`)
  return res.json()
}

async function start() {
  const { state, saveCreds } = await useMultiFileAuthState(AUTH_DIR)
  const { version } = await fetchLatestBaileysVersion()

  const sock = makeWASocket({
    version,
    auth: state,
    logger,
    markOnlineOnConnect: false, // no marcar "en linea" (mas discreto)
    syncFullHistory: false,
  })

  sock.ev.on('creds.update', saveCreds)

  sock.ev.on('connection.update', (update) => {
    const { connection, lastDisconnect, qr } = update
    if (qr) {
      console.log('\n📱 Escanea este QR con el WhatsApp del CHIP DEL BOT:')
      console.log('   (WhatsApp > Dispositivos vinculados > Vincular dispositivo)\n')
      qrcodeTerminal.generate(qr, { small: true })
      QRCode.toFile(QR_FILE, qr, { width: 400 })
        .then(() => console.log(`   QR tambien guardado en: whatsapp-gateway/${QR_FILE}\n`))
        .catch(() => {})
    }
    if (connection === 'open') {
      const me = sock.user?.id?.split(':')[0] || '?'
      console.log(`\n✅ Gateway conectado a WhatsApp como +${me}`)
      console.log(`   Webhook destino: ${WEBHOOK_URL}\n`)
      if (existsSync(QR_FILE)) { try { unlinkSync(QR_FILE) } catch {} }
    }
    if (connection === 'close') {
      const code = lastDisconnect?.error?.output?.statusCode
      if (code === DisconnectReason.loggedOut) {
        console.error('\n❌ Sesion cerrada desde el telefono (loggedOut).')
        console.error('   Borra la carpeta auth_info/ y vuelve a escanear el QR.\n')
        process.exit(1)
      }
      console.warn(`⚠️ Conexion cerrada (code ${code}). Reconectando en 3 s...`)
      setTimeout(start, 3000)
    }
  })

  sock.ev.on('messages.upsert', async ({ messages, type }) => {
    if (type !== 'notify') return
    for (const msg of messages) {
      try {
        await handleMessage(sock, msg)
      } catch (e) {
        console.error('Error procesando mensaje:', e.message)
      }
    }
  })
}

async function handleMessage(sock, msg) {
  const jid = msg.key?.remoteJid || ''
  if (!jid || msg.key?.fromMe) return
  if (jid.endsWith('@g.us')) return // v1: solo privados; los grupos son salida
  if (jid === 'status@broadcast') return
  if (!msg.message) return
  if (seen(msg.key.id)) return

  const phone = jid.split('@')[0].replace(/\D/g, '')
  const text = extractText(msg)
  const media = mediaInfo(msg)

  // ── Comandos locales del gateway (no llegan a Flask) ──────────────────
  if (text.toLowerCase() === 'ping') {
    await humanDelay()
    await sock.sendMessage(jid, { text: 'pong 🏓 (gateway OK)' })
    return
  }
  // /grupos: lista JIDs de los grupos donde esta el bot (solo el owner).
  // Sirve para configurar grupo_destino en bot_whatsapp_users.
  if (text === '/grupos' && OWNER_NUMBER && phone === OWNER_NUMBER) {
    const groups = await sock.groupFetchAllParticipating()
    const lines = Object.values(groups).map((g) => `• ${g.subject}\n  ${g.id}`)
    await sock.sendMessage(jid, {
      text: lines.length ? `📋 Grupos del bot:\n\n${lines.join('\n')}` : 'El bot no esta en ningun grupo todavia.',
    })
    return
  }

  // ── Descargar media si existe ─────────────────────────────────────────
  let mediaPayload = null
  let mediaBuffer = null
  if (media) {
    try {
      mediaBuffer = await downloadMediaMessage(msg, 'buffer', {}, {
        logger,
        reuploadRequest: sock.updateMediaMessage,
      })
      if (mediaBuffer && mediaBuffer.length <= MAX_MEDIA_BYTES) {
        mediaPayload = { type: media.type, mimetype: media.mimetype, base64: mediaBuffer.toString('base64') }
      } else if (mediaBuffer) {
        await sock.sendMessage(jid, { text: '⚠️ El archivo pesa mas de 16 MB, no puedo procesarlo. Manda una version mas liviana.' })
        mediaBuffer = null
      }
    } catch (e) {
      console.warn('No se pudo descargar media:', e.message)
    }
  }

  if (!text && !mediaPayload) return // stickers, reacciones, etc: ignorar

  // ── Reenviar al CMMS ──────────────────────────────────────────────────
  console.log(`📩 ${phone} (${msg.pushName || '?'}): ${text ? text.slice(0, 80) : `[${media?.type}]`}`)
  await sock.sendPresenceUpdate('composing', jid)

  let result
  try {
    result = await postWebhook({
      message_id: msg.key.id,
      from: jid,
      phone,
      push_name: msg.pushName || '',
      text,
      media: mediaPayload,
      timestamp: Number(msg.messageTimestamp) || Math.floor(Date.now() / 1000),
    })
  } catch (e) {
    console.error('Webhook fallo:', e.message)
    await humanDelay()
    await sock.sendMessage(jid, { text: '⚠️ No pude comunicarme con el CMMS. Intenta de nuevo en unos minutos.' })
    return
  }

  // ── Respuestas al usuario ─────────────────────────────────────────────
  for (const reply of result?.replies || []) {
    await humanDelay()
    await sock.sendMessage(jid, { text: String(reply) })
  }

  // ── Reenvios a grupos (aviso ordenado) ────────────────────────────────
  for (const fwd of result?.forwards || []) {
    if (!fwd?.to) continue
    await humanDelay()
    if (fwd.attach_incoming_media && mediaBuffer && media) {
      const content = media.type === 'video'
        ? { video: mediaBuffer, caption: fwd.text || '' }
        : media.type === 'image'
          ? { image: mediaBuffer, caption: fwd.text || '' }
          : { document: mediaBuffer, mimetype: media.mimetype, caption: fwd.text || '' }
      await sock.sendMessage(fwd.to, content)
    } else if (fwd.text) {
      await sock.sendMessage(fwd.to, { text: fwd.text })
    }
    console.log(`📤 Reenviado a grupo ${fwd.to}`)
  }
}

console.log('🚀 Iniciando gateway WhatsApp del CMMS...')
if (!GATEWAY_TOKEN) console.warn('⚠️ GATEWAY_TOKEN vacio — configura .env antes de produccion.')
start().catch((e) => {
  console.error('Fallo fatal al iniciar:', e)
  process.exit(1)
})
