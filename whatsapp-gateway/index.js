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
import { existsSync, unlinkSync, readFileSync, writeFileSync } from 'fs'
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

// Cola de salida: Flask encola mensajes proactivos (pre-diagnostico IA para el
// grupo de mantenimiento, avisos al reportero) y el gateway los sondea y envia.
// Asi el gateway NO abre ningun puerto: sigue siendo cliente de Flask.
const OUTBOX_URL = WEBHOOK_URL.replace(/\/webhook$/, '/outbox')
const OUTBOX_ACK_URL = WEBHOOK_URL.replace(/\/webhook$/, '/outbox/ack')
const OUTBOX_POLL_MS = Number(process.env.OUTBOX_POLL_MS || 15000)

// Directorio de numeros autorizados: sirve para resolver identidades @lid
// (ver bloque "Mapa @lid <-> numero" mas abajo).
const DIRECTORY_URL = WEBHOOK_URL.replace(/\/webhook$/, '/directory')
const LIDMAP_URL = WEBHOOK_URL.replace(/\/webhook$/, '/lid-map')
const LID_MAP_FILE = 'lid_map.json'
const LID_SYNC_MS = Number(process.env.LID_SYNC_MS || 6 * 60 * 60 * 1000) // 6 h

const logger = pino({ level: 'warn' })

let currentSock = null    // socket vigente (se actualiza en cada reconexion)
let pollerStarted = false // el loop de outbox se arranca una sola vez

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
      currentSock = sock
      if (!pollerStarted) {
        pollerStarted = true
        outboxLoop()
        console.log(`🔁 Sondeo de cola de salida activo (cada ${OUTBOX_POLL_MS / 1000}s)\n`)
      }
      // Resolver de entrada las identidades @lid de los numeros autorizados:
      // asi el primer mensaje de un perfil con nombre de usuario ya entra.
      syncLidDirectory(sock, { force: true }).catch(() => {})
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

  // La libreta que sincroniza WhatsApp trae las dos caras del mismo contacto
  // (id/lid/jid): fuente gratuita de pares @lid <-> numero.
  const learnFromContacts = (contacts) => {
    const nuevos = []
    for (const c of contacts || []) {
      const lid = onlyDigits(c?.lid || (String(c?.id || '').endsWith('@lid') ? c.id : ''))
      const phone = onlyDigits(c?.jid || (String(c?.id || '').includes('@s.whatsapp.net') ? c.id : ''))
      if (lid && phone && rememberLid(lid, phone, { report: false })) {
        nuevos.push({ lid, phone })
      }
    }
    if (nuevos.length) reportLidPairs(nuevos)
  }
  sock.ev.on('contacts.upsert', learnFromContacts)
  sock.ev.on('contacts.update', learnFromContacts)
}

// ── Mapa @lid <-> numero ────────────────────────────────────────────────────
// WhatsApp esta migrando a identidades de privacidad: un contacto con "nombre
// de usuario" ya no expone su numero y el mensaje llega como
// 1575909903770074@lid. El CMMS autoriza por numero, asi que hay que traducir.
//
// Tres fuentes, de mas barata a mas cara:
//   1. El propio mensaje (key.senderPn) — cuando WhatsApp lo incluye.
//   2. La libreta de contactos que sincroniza Baileys (contacts.upsert trae
//      id/lid/jid del mismo contacto).
//   3. Consulta directa a WhatsApp (onWhatsApp) de los numeros autorizados que
//      publica el CMMS: devuelve el @lid de cada uno. Es la via fiable y no
//      exige que el tecnico haga nada.
// Cada par descubierto se guarda en disco y se reporta al CMMS, que lo archiva
// en la ficha del usuario — asi el reconocimiento sobrevive a reinicios.

const lidToPhone = new Map()
let lidMapDirty = false
let lastLidSync = 0
let lidSyncInFlight = null

function loadLidMap() {
  try {
    if (!existsSync(LID_MAP_FILE)) return
    const raw = JSON.parse(readFileSync(LID_MAP_FILE, 'utf8'))
    for (const [lid, phone] of Object.entries(raw || {})) {
      if (lid && phone) lidToPhone.set(lid, String(phone))
    }
    console.log(`🔗 Mapa de identidades @lid cargado (${lidToPhone.size} contactos)`)
  } catch (e) {
    console.warn('No pude leer lid_map.json:', e.message)
  }
}

function saveLidMap() {
  if (!lidMapDirty) return
  try {
    writeFileSync(LID_MAP_FILE, JSON.stringify(Object.fromEntries(lidToPhone), null, 2))
    lidMapDirty = false
  } catch (e) {
    console.warn('No pude guardar lid_map.json:', e.message)
  }
}

const onlyDigits = (v) => String(v || '').split('@')[0].split(':')[0].replace(/\D/g, '')

/** Registra un par y avisa al CMMS si es nuevo. */
function rememberLid(lid, phone, { report = true } = {}) {
  const l = onlyDigits(lid)
  const p = onlyDigits(phone)
  if (!l || !p || l === p) return false
  if (lidToPhone.get(l) === p) return false
  lidToPhone.set(l, p)
  lidMapDirty = true
  saveLidMap()
  console.log(`🔗 Identidad @lid ${l} = numero ${p}`)
  if (report) reportLidPairs([{ lid: l, phone: p }])
  return true
}

async function reportLidPairs(pairs) {
  if (!pairs.length) return
  try {
    await fetch(LIDMAP_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Gateway-Token': GATEWAY_TOKEN },
      body: JSON.stringify({ pairs }),
      signal: AbortSignal.timeout(30000),
    })
  } catch (e) {
    // No es critico: el mapa local ya resuelve; el CMMS lo aprendera despues.
    console.warn('No pude reportar el mapa @lid al CMMS:', e.message)
  }
}

/**
 * Pregunta a WhatsApp el @lid de cada numero autorizado en el CMMS.
 * `force` salta el intervalo minimo (se usa cuando llega un @lid desconocido).
 */
async function syncLidDirectory(sock, { force = false } = {}) {
  if (!sock) return false
  if (!force && Date.now() - lastLidSync < LID_SYNC_MS) return false
  if (lidSyncInFlight) return lidSyncInFlight
  // Aunque sea forzado, no mas de una consulta por minuto (anti-baneo).
  if (force && Date.now() - lastLidSync < 60000) return false

  lidSyncInFlight = (async () => {
    let users = []
    try {
      const res = await fetch(DIRECTORY_URL, {
        headers: { 'X-Gateway-Token': GATEWAY_TOKEN },
        signal: AbortSignal.timeout(30000),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      users = (await res.json())?.users || []
    } catch (e) {
      console.warn('No pude leer el directorio de numeros del CMMS:', e.message)
      return false
    }

    const phones = users.map((u) => onlyDigits(u.phone)).filter(Boolean)
    if (!phones.length) return false

    // Los pares que el CMMS ya tiene guardados entran gratis al mapa local.
    for (const u of users) {
      if (u.lid) rememberLid(u.lid, u.phone, { report: false })
    }

    const nuevos = []
    try {
      // Consulta en bloques: una sola query con cientos de numeros es lenta y
      // llamativa; de a 20 pasa desapercibida.
      for (let i = 0; i < phones.length; i += 20) {
        const lote = phones.slice(i, i + 20)
        const results = (await sock.onWhatsApp(...lote)) || []
        for (const r of results) {
          if (!r?.lid || !r?.jid) continue
          if (rememberLid(r.lid, r.jid, { report: false })) {
            nuevos.push({ lid: onlyDigits(r.lid), phone: onlyDigits(r.jid) })
          }
        }
        if (i + 20 < phones.length) await sleep(1500)
      }
    } catch (e) {
      console.warn('Consulta de identidades @lid a WhatsApp fallo:', e.message)
    }

    lastLidSync = Date.now()
    if (nuevos.length) {
      console.log(`🔗 ${nuevos.length} identidad(es) @lid resueltas y enviadas al CMMS`)
      await reportLidPairs(nuevos)
    }
    return true
  })().finally(() => { lidSyncInFlight = null })

  return lidSyncInFlight
}

/**
 * Devuelve { phone, lid }: el numero real si se pudo resolver y la identidad
 * @lid si el chat viene por esa via. Al menos uno de los dos siempre llega.
 */
async function resolveIdentity(sock, msg, jid) {
  if (!jid.endsWith('@lid')) {
    // Chat normal: el jid ya es el numero. Aprovechar para aprender su @lid.
    const lid = onlyDigits(msg.key?.senderLid || msg.key?.participantLid || '')
    const phone = onlyDigits(jid)
    if (lid) rememberLid(lid, phone)
    return { phone, lid }
  }

  const lid = onlyDigits(jid)

  // 1) El propio mensaje trae el numero verdadero.
  const alt = msg.key?.senderPn || msg.key?.participantPn ||
              msg.key?.remoteJidAlt || msg.key?.participantAlt || ''
  if (alt) {
    const phone = onlyDigits(alt)
    if (phone) {
      rememberLid(lid, phone)
      return { phone, lid }
    }
  }

  // 2) Mapa ya conocido (disco / sincronizaciones previas).
  const cached = lidToPhone.get(lid)
  if (cached) return { phone: cached, lid }

  // 3) Preguntar a WhatsApp por los numeros autorizados y reintentar.
  await syncLidDirectory(sock, { force: true })
  const resolved = lidToPhone.get(lid)
  if (resolved) return { phone: resolved, lid }

  console.warn(`⚠️ Identidad @lid ${lid} sin numero conocido (perfil con nombre de usuario). ` +
               `El CMMS le pedira al usuario que la registre.`)
  return { phone: '', lid }
}

async function handleMessage(sock, msg) {
  const jid = msg.key?.remoteJid || ''
  if (!jid || msg.key?.fromMe) return
  if (jid.endsWith('@g.us')) return // v1: solo privados; los grupos son salida
  if (jid === 'status@broadcast') return
  if (!msg.message) return
  if (seen(msg.key.id)) return

  const { phone, lid } = await resolveIdentity(sock, msg, jid)
  const text = extractText(msg)
  const media = mediaInfo(msg)

  // ── Comandos locales del gateway (no llegan a Flask) ──────────────────
  if (text.toLowerCase() === 'ping') {
    await humanDelay()
    await sock.sendMessage(jid, { text: 'pong 🏓 (gateway OK)' })
    return
  }
  // /id: devuelve como identifica el bot a quien escribe. Sirve cuando un
  // perfil con nombre de usuario oculta el numero y hay que vincular el
  // codigo de identidad a mano en el panel del CMMS.
  if (text.toLowerCase() === '/id') {
    await humanDelay()
    const lineas = ['🪪 Asi te identifico:', '']
    lineas.push(`• Nombre del perfil: ${msg.pushName || '(sin nombre)'}`)
    lineas.push(`• Numero detectado: ${phone || 'oculto por WhatsApp'}`)
    if (lid) lineas.push(`• Codigo de identidad: ${lid}`)
    if (!phone) {
      lineas.push('', 'Pasale el codigo de identidad al administrador del CMMS: '
        + 'con eso te habilita en un minuto.')
    }
    await sock.sendMessage(jid, { text: lineas.join('\n') })
    return
  }
  // /grupos: lista JIDs de los grupos donde esta el bot (solo el owner).
  // Sirve para configurar grupo_destino en bot_whatsapp_users.
  if (text === '/grupos' && OWNER_NUMBER && phone === OWNER_NUMBER) {
    const groups = await sock.groupFetchAllParticipating()
    const lines = Object.values(groups).map((g) => `• ${g.subject}\n  ${g.id}`)
    // Tambien al log: permite configurar grupo_destino sin copiar JIDs a mano
    console.log(`📋 GRUPOS DEL BOT:\n${lines.join('\n') || '(ninguno)'}`)
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
  const quien = phone || `lid:${lid}`
  console.log(`📩 ${quien} (${msg.pushName || '?'}): ${text ? text.slice(0, 80) : `[${media?.type}]`}`)
  await sock.sendPresenceUpdate('composing', jid)

  let result
  try {
    result = await postWebhook({
      message_id: msg.key.id,
      from: jid,
      // Si WhatsApp oculto el numero se manda el lid en ambos campos: el CMMS
      // compara los dos y sabe que 'phone' no es un telefono de verdad.
      phone: phone || lid,
      lid,
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
      // media del MENSAJE ACTUAL (ej: evidencia recien enviada)
      const content = media.type === 'video'
        ? { video: mediaBuffer, caption: fwd.text || '' }
        : media.type === 'image'
          ? { image: mediaBuffer, caption: fwd.text || '' }
          : { document: mediaBuffer, mimetype: media.mimetype, caption: fwd.text || '' }
      await sock.sendMessage(fwd.to, content)
    } else if (fwd.media_base64) {
      // media guardada por Flask en la sesion (ej: foto que vino con el
      // primer mensaje del reporte, antes de confirmar)
      const buf = Buffer.from(fwd.media_base64, 'base64')
      const content = fwd.media_type === 'video'
        ? { video: buf, caption: fwd.text || '' }
        : fwd.media_type === 'image'
          ? { image: buf, caption: fwd.text || '' }
          : { document: buf, mimetype: fwd.mimetype || 'application/octet-stream', caption: fwd.text || '' }
      await sock.sendMessage(fwd.to, content)
    } else if (fwd.text) {
      await sock.sendMessage(fwd.to, { text: fwd.text })
    }
    console.log(`📤 Reenviado a grupo ${fwd.to}`)
  }
}

// ── Cola de salida (mensajes proactivos: pre-diagnostico IA, avisos) ────────

async function pollOutboxOnce() {
  if (!currentSock) return
  let messages = []
  try {
    const res = await fetch(OUTBOX_URL, {
      headers: { 'X-Gateway-Token': GATEWAY_TOKEN },
      signal: AbortSignal.timeout(30000),
    })
    if (!res.ok) return
    const data = await res.json()
    messages = data?.messages || []
  } catch (e) {
    return // Flask no disponible: reintentar en el proximo ciclo
  }
  if (!messages.length) return

  const results = []
  for (const m of messages) {
    if (!m?.to || !m?.body) { results.push({ id: m?.id, ok: false }); continue }
    try {
      await humanDelay()
      if (m.media_base64) {
        const buf = Buffer.from(m.media_base64, 'base64')
        const content = m.media_type === 'video'
          ? { video: buf, caption: m.body }
          : m.media_type === 'image'
            ? { image: buf, caption: m.body }
            : { document: buf, caption: m.body }
        await currentSock.sendMessage(m.to, content)
      } else {
        await currentSock.sendMessage(m.to, { text: m.body })
      }
      results.push({ id: m.id, ok: true })
      console.log(`📤 Outbox enviado #${m.id} -> ${m.to}`)
    } catch (e) {
      console.warn(`Outbox #${m.id} fallo:`, e.message)
      results.push({ id: m.id, ok: false })
    }
  }

  try {
    await fetch(OUTBOX_ACK_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Gateway-Token': GATEWAY_TOKEN },
      body: JSON.stringify({ results }),
      signal: AbortSignal.timeout(30000),
    })
  } catch (e) {
    console.warn('Outbox ack fallo:', e.message) // el reclaim de Flask lo recupera
  }
}

async function outboxLoop() {
  let ticks = 0
  const ticksPorSync = Math.max(1, Math.round(LID_SYNC_MS / OUTBOX_POLL_MS))
  for (;;) {
    try { await pollOutboxOnce() } catch (e) { console.warn('outboxLoop:', e.message) }
    // Refrescar el mapa @lid cada LID_SYNC_MS: capta las altas de numeros
    // nuevas en el CMMS sin reiniciar el gateway.
    if (++ticks % ticksPorSync === 0) {
      try { await syncLidDirectory(currentSock) } catch (e) { console.warn('syncLid:', e.message) }
    }
    await sleep(OUTBOX_POLL_MS)
  }
}

console.log('🚀 Iniciando gateway WhatsApp del CMMS...')
loadLidMap()
if (!GATEWAY_TOKEN) console.warn('⚠️ GATEWAY_TOKEN vacio — configura .env antes de produccion.')
start().catch((e) => {
  console.error('Fallo fatal al iniciar:', e)
  process.exit(1)
})
