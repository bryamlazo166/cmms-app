# CMMS en el VPS — espejo secundario

**Primario:** GitHub (código) + Supabase (BD + fotos) + Render (app + bot Telegram).
**Secundario:** VPS (51.79.11.222) con la app en Docker + PostgreSQL local,
sincronizado **manualmente** desde Supabase para no consumir egress.

```
┌───────────── PRIMARIO ─────────────┐        ┌───────── VPS (secundario) ─────────┐
│ GitHub ──deploy──► Render (app)    │        │ cmms-app  (Docker, puerto 8080)    │
│                      │             │  sync  │    │                               │
│                  Supabase (BD) ────┼──────► │ cmms-db   (PostgreSQL 17+pgvector) │
│                  Supabase Storage ◄┼────────┼── fotos se siguen leyendo/subiendo │
└────────────────────────────────────┘ manual │ whatsapp-gateway (pm2, ya existia) │
                                              └────────────────────────────────────┘
```

## Reglas de oro

1. **El VPS es de SOLO CONSULTA / standby.** Todo lo que se cree en el VPS se
   pierde en la siguiente sincronización (el refresh es completo). Los datos
   reales se crean en Render/Supabase.
2. **La sincronización es manual** — solo consume egress de Supabase cuando tú
   la ejecutas (~5-30 MB por corrida; la BD pesa ~30 MB).
3. **El bot de Telegram corre SOLO en Render** — el `.env` del VPS no tiene
   `TELEGRAM_TOKEN` a propósito. No agregarlo.
4. Cada sync deja un dump fechado en `~/cmms/backups/` (se conservan 10):
   sincronizar también es sacar backup.

## Operación diaria (desde Windows)

```powershell
scripts\vps_sync_bd.ps1          # sincronizar BD Supabase -> VPS (manual)
scripts\vps_actualizar_app.ps1   # actualizar código del VPS desde GitHub
```

La app del VPS queda en: **http://51.79.11.222:8080** (usuarios y claves = los
mismos de producción tras cada sync).

## Instalación desde cero (ya realizada)

```bash
ssh -i ~/.ssh/id_cmms_vps bryam16@51.79.11.222
mkdir -p ~/cmms/backups
git clone https://github.com/bryamlazo166/cmms-app.git ~/cmms/app
# copiar deploy/vps/.env real (basado en env.vps.example) — NO está en el repo
cd ~/cmms/app/deploy/vps
docker compose up -d --build
bash sync_from_supabase.sh
```

## Failover del bot de WhatsApp (si Render se cae)

El gateway (pm2 `whatsapp-bot`, mismo VPS) apunta a Render. Para conmutar al
espejo local:

```bash
# en el VPS
sed -i 's#^WEBHOOK_URL=.*#WEBHOOK_URL=http://localhost:8080/api/public/whatsapp/webhook#' ~/whatsapp-gateway/.env
~/.npm-global/bin/pm2 restart whatsapp-bot
```

⚠️ Los avisos creados así viven solo en el VPS y se pierden en el siguiente
sync — anotarlos y recrearlos en producción cuando Render vuelva. Para regresar
al primario, restaurar `WEBHOOK_URL=https://cmms-app-acfj.onrender.com/api/public/whatsapp/webhook`
y reiniciar pm2.

## Pendientes conocidos

- HTTP sin TLS en el puerto 8080: las credenciales viajan en claro. Si el espejo
  se va a usar seguido desde fuera, agregar Caddy/nginx con dominio + HTTPS.
- Las fotos NO se replican (siguen en Supabase Storage); si Supabase cae, las
  fotos no cargan aunque el espejo funcione.
