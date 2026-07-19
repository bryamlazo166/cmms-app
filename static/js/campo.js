/* Modo Campo — app móvil ligera para técnicos (PWA).
   Vistas: home / reportar falla / mis OTs / lubricación / ronda eléctrica.
   Reutiliza los endpoints existentes del CMMS; sin dependencias. */

let ME = { name: '', role: '' };
let TREE = null;
let OTS = [];
let LUBS = [];
let MOTS = [];
let currentOt = null, currentLub = null, currentMot = null;

const $ = (id) => document.getElementById(id);
const esc = (s) => { const d = document.createElement('div'); d.textContent = (s == null ? '' : String(s)); return d.innerHTML; };
const today = () => new Date().toISOString().slice(0, 10);

const TITLES = {
    home: '🔧 CMMS — Modo Campo', reportar: '🔴 Reportar Falla', ots: '📋 Mis OTs',
    ot: '📋 Orden de Trabajo', lub: '🛢 Lubricación', lubreg: '🛢 Registrar servicio',
    electrica: '⚡ Ronda Eléctrica', motreg: '⚡ Registrar medición',
};

/* ── Navegación por hash ────────────────────────────────────────────── */
function nav(view) { location.hash = '#' + view; }

function showView() {
    const h = (location.hash || '#home').slice(1);
    const view = h.split('/')[0];
    document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
    const el = $('v-' + view);
    (el || $('v-home')).classList.add('active');
    $('btnBack').style.display = view === 'home' ? 'none' : 'flex';
    $('topTitle').childNodes[0].textContent = TITLES[view] || TITLES.home;
    window.scrollTo(0, 0);
    // Cargas por vista (lazy)
    if (view === 'reportar' && !TREE) loadTree();
    if (view === 'ots') loadOts();
    if (view === 'lub' && !LUBS.length) loadLubs();
    if (view === 'electrica' && !MOTS.length) loadMots();
}
window.addEventListener('hashchange', showView);

/* ── Segmentos (radio buttons táctiles) ─────────────────────────────── */
function initSeg(id, onChange) {
    const seg = $(id);
    seg.querySelectorAll('.opt[data-v]').forEach(opt => {
        opt.onclick = () => {
            seg.querySelectorAll('.opt').forEach(o => o.classList.remove('on'));
            opt.classList.add('on');
            if (onChange) onChange(opt.dataset.v);
        };
    });
}
const segVal = (id) => $(id).querySelector('.opt.on')?.dataset.v || null;

function msg(id, ok, text) {
    const m = $(id);
    m.className = 'msg ' + (ok ? 'ok' : 'err');
    m.innerHTML = text;
    m.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}
const clearMsg = (id) => { $(id).className = 'msg'; $(id).innerHTML = ''; };

/* ── Usuario ────────────────────────────────────────────────────────── */
async function loadMe() {
    try {
        const r = await fetch('/api/auth/me');
        if (r.status === 401) { location.href = '/login?next=/campo'; return; }
        const u = await r.json();
        ME.name = u.full_name || u.username || '';
        ME.role = u.role || '';
        $('whoami').textContent = `${ME.name} · ${ME.role}`;
    } catch (e) { /* offline: se permite navegar */ }
}

/* ══ REPORTAR FALLA ══════════════════════════════════════════════════ */
async function loadTree() {
    try {
        const r = await fetch('/api/notices/tree');
        TREE = await r.json();
        const nat = { numeric: true, sensitivity: 'base' };
        TREE.equipments.sort((a, b) => (a.tag || a.name || '').localeCompare(b.tag || b.name || '', 'es', nat));
        fillSel('rArea', TREE.areas, '- Área -');
        fillSel('rLine', [], '- Línea -');
        fillSel('rEquip', [], '- Equipo -');
        fillSel('rSys', [], '- Sistema (opcional) -');
        fillSel('rComp', [], '- Componente (opcional) -');
        $('rArea').onchange = () => {
            fillSel('rLine', TREE.lines.filter(l => l.area_id == $('rArea').value), '- Línea -');
            fillSel('rEquip', [], '- Equipo -'); fillSel('rSys', [], '- Sistema (opcional) -'); fillSel('rComp', [], '- Componente (opcional) -');
        };
        $('rLine').onchange = () => {
            const eqs = TREE.equipments.filter(e => e.line_id == $('rLine').value)
                .map(e => ({ id: e.id, name: (e.tag ? `[${e.tag}] ` : '') + e.name }));
            fillSel('rEquip', eqs, '- Equipo -');
            fillSel('rSys', [], '- Sistema (opcional) -'); fillSel('rComp', [], '- Componente (opcional) -');
        };
        $('rEquip').onchange = () => {
            fillSel('rSys', TREE.systems.filter(s => s.equipment_id == $('rEquip').value), '- Sistema (opcional) -');
            fillSel('rComp', [], '- Componente (opcional) -');
        };
        $('rSys').onchange = () => {
            fillSel('rComp', TREE.components.filter(c => c.system_id == $('rSys').value), '- Componente (opcional) -');
        };
    } catch (e) {
        msg('rMsg', false, 'No se pudo cargar el árbol de equipos. Revisa tu conexión.');
    }
}

function fillSel(id, items, placeholder) {
    $(id).innerHTML = `<option value="">${placeholder}</option>` +
        items.map(i => `<option value="${i.id}">${esc(i.name)}</option>`).join('');
}

$('rPhoto') && ($('rPhoto').onchange = () => {
    const f = $('rPhoto').files[0];
    $('rPhotoName').textContent = f ? `📎 ${f.name}` : '';
});

async function submitNotice() {
    clearMsg('rMsg');
    const desc = $('rDesc').value.trim();
    if (!desc) { msg('rMsg', false, 'Describe la falla, por favor.'); return; }
    const btn = $('rSubmit');
    btn.disabled = true; btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Creando…';
    const crit = segVal('rCrit') || 'Media';
    const body = {
        description: desc, criticality: crit, priority: crit,
        reporter_name: ME.name || 'Campo', reporter_type: 'MANTENIMIENTO',
        report_channel: 'SISTEMA', status: 'Pendiente',
        area_id: $('rArea').value || null, line_id: $('rLine').value || null,
        equipment_id: $('rEquip').value || null, system_id: $('rSys').value || null,
        component_id: $('rComp').value || null,
        scope: $('rEquip').value ? 'PLAN' : 'GENERAL',
    };
    try {
        const r = await fetch('/api/notices', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        const d = await r.json();
        if (!r.ok) { msg('rMsg', false, esc(d.error || 'No se pudo crear el aviso.')); return; }
        // Foto opcional
        let fotoTxt = '';
        const f = $('rPhoto').files[0];
        if (f && d.id) {
            const fd = new FormData();
            fd.append('photo', f);
            fd.append('caption', 'Foto desde Modo Campo');
            try {
                const pr = await fetch(`/api/photos/notice/${d.id}`, { method: 'POST', body: fd });
                fotoTxt = pr.ok ? '<br>📷 Foto adjuntada.' : '<br>⚠️ El aviso se creó pero la foto no se pudo subir.';
            } catch (e) { fotoTxt = '<br>⚠️ El aviso se creó pero la foto no se pudo subir.'; }
        }
        const dupTxt = d.is_duplicate ? `<br>⚠️ Posible duplicado: ${esc(d.duplicate_reason || '')}` : '';
        msg('rMsg', true, `✅ Aviso <b>${esc(d.code || '')}</b> creado.${fotoTxt}${dupTxt}`);
        $('rDesc').value = ''; $('rPhoto').value = ''; $('rPhotoName').textContent = '';
    } catch (e) {
        msg('rMsg', false, 'Error de red. Intenta de nuevo.');
    } finally {
        btn.disabled = false; btn.innerHTML = '<i class="fas fa-paper-plane"></i> Crear aviso';
    }
}

/* ══ MIS OTS ═════════════════════════════════════════════════════════ */
let otFilterMode = 'abiertas';
function otFilter(chip) {
    document.querySelectorAll('#v-ots .chip').forEach(c => c.classList.remove('on'));
    chip.classList.add('on');
    otFilterMode = chip.dataset.f;
    renderOtList();
}

async function loadOts() {
    try {
        const r = await fetch('/api/work-orders?page=1&per_page=200');
        const d = await r.json();
        if (!r.ok) { $('otList').innerHTML = `<div class="empty">${esc(d.error || 'Sin acceso a OTs')}</div>`; return; }
        OTS = d.items || d || [];
        renderOtList();
        const abiertas = OTS.filter(o => !['Cerrada', 'Anulada'].includes(o.status)).length;
        setBadge('badgeOts', abiertas);
    } catch (e) {
        $('otList').innerHTML = '<div class="empty">Error de red.</div>';
    }
}

const OT_PILL = { 'Abierta': 'p-blue', 'Programada': 'p-amber', 'En Progreso': 'p-amber', 'Cerrada': 'p-green', 'Anulada': 'p-gray' };
function renderOtList() {
    let rows = OTS;
    if (otFilterMode === 'abiertas') rows = rows.filter(o => !['Cerrada', 'Anulada'].includes(o.status));
    if (!rows.length) { $('otList').innerHTML = '<div class="empty">No tienes OTs ' + (otFilterMode === 'abiertas' ? 'abiertas 🎉' : 'registradas') + '.<br><small>Si falta alguna, pide que te asignen como personal de la OT.</small></div>'; return; }
    $('otList').innerHTML = rows.map(o => `
        <div class="card" onclick="openOt(${o.id})">
            <div class="t"><span class="code">${esc(o.code || 'OT-' + o.id)}</span>
                <span class="pill ${OT_PILL[o.status] || 'p-gray'}">${esc(o.status || '')}</span></div>
            <div class="desc">${esc(o.description || '(sin descripción)')}</div>
            <div class="sub">${esc(o.maintenance_type || '')}${o.scheduled_date ? ' · prog. ' + esc(o.scheduled_date) : ''}${o.planning_date ? ' · prog. ' + esc(o.planning_date) : ''}</div>
        </div>`).join('');
}

function openOt(id) {
    currentOt = OTS.find(o => o.id === id);
    if (!currentOt) return;
    clearMsg('otMsg');
    $('otHead').innerHTML = `
        <div class="t"><span class="code" style="font-size:1.05rem">${esc(currentOt.code || 'OT-' + id)}</span>
            <span class="pill ${OT_PILL[currentOt.status] || 'p-gray'}">${esc(currentOt.status || '')}</span></div>
        <div style="margin-top:8px">${esc(currentOt.description || '')}</div>
        <div class="kv sect">Tipo: <b>${esc(currentOt.maintenance_type || '-')}</b>
            ${currentOt.failure_mode ? ' · Falla: <b>' + esc(currentOt.failure_mode) + '</b>' : ''}</div>`;
    $('otComments').value = currentOt.execution_comments || '';
    $('otHours').value = currentOt.real_duration || '';
    $('otEndDate').value = (currentOt.real_end_date || '').slice(0, 10) || today();
    nav('ot');
}

async function saveOt(close) {
    if (!currentOt) return;
    clearMsg('otMsg');
    const body = {};
    const c = $('otComments').value.trim();
    if (c) body.execution_comments = c;
    if ($('otHours').value) body.real_duration = parseFloat($('otHours').value);
    if ($('otEndDate').value) body.real_end_date = $('otEndDate').value;
    if (close) {
        if (!c) { msg('otMsg', false, 'Para cerrar la OT escribe el comentario de lo que se hizo.'); return; }
        if (!confirm(`¿Cerrar la ${currentOt.code}? Esta acción marca el trabajo como terminado.`)) return;
        body.status = 'Cerrada';
        if (!body.real_end_date) body.real_end_date = today();
    }
    try {
        const r = await fetch(`/api/work-orders/${currentOt.id}`, {
            method: 'PUT', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        const d = await r.json();
        if (!r.ok) { msg('otMsg', false, esc(d.error || 'No se pudo guardar.')); return; }
        msg('otMsg', true, close ? `✅ <b>${esc(currentOt.code)}</b> cerrada correctamente.` : '✅ Avance guardado.');
        OTS = [];  // fuerza recarga
        if (close) setTimeout(() => nav('ots'), 1200);
    } catch (e) { msg('otMsg', false, 'Error de red.'); }
}

/* ══ LUBRICACIÓN ═════════════════════════════════════════════════════ */
let lubFilterMode = 'pendientes';
function lubFilter(chip) {
    document.querySelectorAll('#v-lub .chip').forEach(c => c.classList.remove('on'));
    chip.classList.add('on');
    lubFilterMode = chip.dataset.f;
    renderLubList();
}

async function loadLubs() {
    try {
        const r = await fetch('/api/lubrication/points');
        const d = await r.json();
        if (!r.ok) { $('lubList').innerHTML = `<div class="empty">${esc(d.error || 'Sin acceso a lubricación')}</div>`; return; }
        // Equipos fuera de servicio (overhaul): sus puntos no son trabajo
        // pendiente real — no se muestran en campo.
        LUBS = (d || []).filter(p => p.equipment_in_service !== false);
        renderLubList();
        setBadge('badgeLub', LUBS.filter(p => p.semaphore_status === 'ROJO' || p.semaphore_status === 'VENCIDO').length);
    } catch (e) { $('lubList').innerHTML = '<div class="empty">Error de red.</div>'; }
}

const LUB_PILL = { 'ROJO': 'p-red', 'VENCIDO': 'p-red', 'AMARILLO': 'p-amber', 'VERDE': 'p-green' };

// Ruta física completa: Área › Línea › Equipo › Sistema › Componente
function lubTree(p) {
    return [p.area_name, p.line_name, p.equipment_name, p.system_name, p.component_name]
        .filter(Boolean).join(' › ');
}

// Antigüedad: días de atraso (+) o días restantes (−) respecto a hoy
function lubDays(p) {
    if (!p.next_due_date) return null;
    const due = new Date(p.next_due_date + 'T00:00:00');
    const now = new Date(today() + 'T00:00:00');
    return Math.round((now - due) / 86400000);
}

function lubDueHtml(p) {
    const d = lubDays(p);
    if (d === null) return '🆕 <b>Sin servicio registrado</b> — primera lubricación pendiente';
    if (d > 0) return `⏰ <b style="color:#ff8a80">ATRASADO ${d} día${d === 1 ? '' : 's'}</b> (venció ${esc(p.next_due_date)})`;
    if (d === 0) return '⏰ <b style="color:#ffe066">VENCE HOY</b>';
    return `vence en ${-d} día${d === -1 ? '' : 's'} (${esc(p.next_due_date)})`;
}

// Orden por antigüedad: primero los más atrasados, luego los que nunca se
// lubricaron, luego por vencer — así se "liberan" las lubricaciones pasadas.
const LUB_RANK = { 'ROJO': 0, 'VENCIDO': 0, 'PENDIENTE': 1, 'AMARILLO': 2, 'VERDE': 3 };
function lubSortKey(p) {
    const d = lubDays(p);
    return [LUB_RANK[p.semaphore_status] ?? 4, -(d === null ? -99999 : d)];
}

function renderLubList() {
    const q = ($('lubSearch').value || '').toLowerCase();
    let rows = LUBS;
    if (lubFilterMode === 'pendientes') rows = rows.filter(p => p.semaphore_status !== 'VERDE');
    if (q) rows = rows.filter(p => JSON.stringify([p.name, p.code, lubTree(p), p.lubricant_name]).toLowerCase().includes(q));
    rows = [...rows].sort((a, b) => {
        const ka = lubSortKey(a), kb = lubSortKey(b);
        return ka[0] - kb[0] || ka[1] - kb[1];
    });
    if (!rows.length) { $('lubList').innerHTML = '<div class="empty">Sin puntos ' + (lubFilterMode === 'pendientes' ? 'vencidos 🎉' : '') + '</div>'; return; }
    $('lubList').innerHTML = rows.slice(0, 150).map(p => `
        <div class="card" onclick="openLub(${p.id})">
            <div class="t"><span style="font-weight:700">${esc(p.name || '')}</span>
                <span class="pill ${LUB_PILL[p.semaphore_status] || 'p-gray'}">${esc(p.semaphore_status || '—')}</span></div>
            <div class="sub" style="color:var(--cyan)">📍 ${esc(lubTree(p)) || '(sin ubicación)'}</div>
            <div class="sub">🛢 ${esc(p.lubricant_name || '-')}${p.quantity_nominal ? ` · ${p.quantity_nominal} ${esc(p.quantity_unit || '')}` : ''}</div>
            <div class="sub">${lubDueHtml(p)}${p.last_service_date ? ` · últ: ${esc(p.last_service_date)}` : ''}
                <span style="opacity:.5"> · ${esc(p.code || '')}</span></div>
        </div>`).join('');
}

function openLub(id) {
    currentLub = LUBS.find(p => p.id === id);
    if (!currentLub) return;
    clearMsg('lubMsg');
    $('lubLeak').classList.remove('on'); $('lubAnom').classList.remove('on');
    $('lubComments').value = '';
    $('lubHead').innerHTML = `
        <b>${esc(currentLub.name || '')}</b><br>
        <span class="kv" style="color:var(--cyan)">📍 ${esc(lubTree(currentLub)) || '(sin ubicación)'}</span>
        <div class="kv sect">Lubricante: <b>${esc(currentLub.lubricant_name || '-')}</b>
        · Nominal: <b>${currentLub.quantity_nominal ?? '-'} ${esc(currentLub.quantity_unit || '')}</b></div>
        <div class="kv">${lubDueHtml(currentLub)}
        ${currentLub.last_service_date ? ` · último servicio: <b>${esc(currentLub.last_service_date)}</b>` : ''}
        <span style="opacity:.5"> · ${esc(currentLub.code || '')}</span></div>`;
    if (currentLub.quantity_nominal) $('lubQty').value = currentLub.quantity_nominal;
    if (currentLub.quantity_unit) {
        const u = $('lubUnit');
        if (![...u.options].some(o => o.value === currentLub.quantity_unit)) {
            u.innerHTML += `<option>${esc(currentLub.quantity_unit)}</option>`;
        }
        u.value = currentLub.quantity_unit;
    }
    nav('lubreg');
}

async function submitLub() {
    if (!currentLub) return;
    clearMsg('lubMsg');
    const body = {
        point_id: currentLub.id,
        execution_date: today(),
        action_type: segVal('lubAction') || 'RELLENO',
        quantity_used: $('lubQty').value ? parseFloat($('lubQty').value) : null,
        quantity_unit: $('lubUnit').value,
        executed_by: ME.name || 'Campo',
        leak_detected: $('lubLeak').classList.contains('on'),
        anomaly_detected: $('lubAnom').classList.contains('on'),
        comments: $('lubComments').value.trim() || null,
    };
    try {
        const r = await fetch('/api/lubrication/executions', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        const d = await r.json();
        if (!r.ok) { msg('lubMsg', false, esc(d.error || 'No se pudo registrar.')); return; }
        const aviso = d.created_notice_id ? '<br>📣 Se generó un aviso por la fuga/anomalía reportada.' : '';
        msg('lubMsg', true, `✅ Servicio registrado en <b>${esc(currentLub.code)}</b>.${aviso}`);
        LUBS = [];  // recargar al volver
        setTimeout(() => nav('lub'), 1200);
    } catch (e) { msg('lubMsg', false, 'Error de red.'); }
}

/* ══ RONDA ELÉCTRICA ═════════════════════════════════════════════════ */
let motFilterMode = 'pendientes';
function motFilter(chip) {
    document.querySelectorAll('#v-electrica .chip').forEach(c => c.classList.remove('on'));
    chip.classList.add('on');
    motFilterMode = chip.dataset.f;
    renderMotList();
}

async function loadMots() {
    try {
        const r = await fetch('/api/motors');
        const d = await r.json();
        if (!r.ok) { $('motList').innerHTML = `<div class="empty">${esc(d.error || 'Sin acceso a motores')}</div>`; return; }
        // Motores de equipos fuera de servicio (overhaul): fuera de la ronda.
        MOTS = (d.rows || []).filter(m => m.equipment_in_service !== false);
        renderMotList();
        setBadge('badgeMot', MOTS.filter(m =>
            m.megado_status === 'ROJO' || m.measure_status === 'ROJO').length);
    } catch (e) { $('motList').innerHTML = '<div class="empty">Error de red.</div>'; }
}

const ST_PILL = { 'ROJO': 'p-red', 'AMARILLO': 'p-amber', 'VERDE': 'p-green', 'PENDIENTE': 'p-gray' };

// Ruta física del motor: Área › Línea › [TAG] Equipo
function motTree(m) {
    const eq = m.equipment_name ? (m.equipment_tag ? `[${m.equipment_tag}] ` : '') + m.equipment_name : null;
    return [m.area_name, m.line_name, eq].filter(Boolean).join(' › ');
}

// Días de atraso (+) respecto a una fecha de vencimiento
function daysLate(dueDate) {
    if (!dueDate) return null;
    const due = new Date(dueDate + 'T00:00:00');
    const now = new Date(today() + 'T00:00:00');
    return Math.round((now - due) / 86400000);
}

function dueHtml(label, dueDate, lastDate) {
    const d = daysLate(dueDate);
    let core;
    if (d === null) core = '🆕 <b>sin medición registrada</b>';
    else if (d > 0) core = `<b style="color:#ff8a80">ATRASADO ${d} día${d === 1 ? '' : 's'}</b> (venció ${esc(dueDate)})`;
    else if (d === 0) core = '<b style="color:#ffe066">VENCE HOY</b>';
    else core = `vence en ${-d} día${d === -1 ? '' : 's'} (${esc(dueDate)})`;
    return `${label}: ${core}${lastDate ? ` · últ: ${esc(lastDate)}` : ''}`;
}

// Orden por antigüedad: la medición más atrasada (corriente o megado) primero
const MOT_RANK = { 'ROJO': 0, 'AMARILLO': 1, 'PENDIENTE': 2, 'VERDE': 3 };
function motSortKey(m) {
    const rank = Math.min(MOT_RANK[m.measure_status] ?? 4, MOT_RANK[m.megado_status] ?? 4);
    const late = Math.max(daysLate(m.next_measure_due) ?? -99999, daysLate(m.next_megado_due) ?? -99999);
    return [rank, -late];
}

function renderMotList() {
    const q = ($('motSearch').value || '').toLowerCase();
    let rows = MOTS;
    if (motFilterMode === 'pendientes') rows = rows.filter(m =>
        ['ROJO', 'AMARILLO', 'PENDIENTE'].includes(m.megado_status) ||
        ['ROJO', 'AMARILLO', 'PENDIENTE'].includes(m.measure_status));
    if (q) rows = rows.filter(m => JSON.stringify([m.code, m.name, motTree(m)]).toLowerCase().includes(q));
    rows = [...rows].sort((a, b) => {
        const ka = motSortKey(a), kb = motSortKey(b);
        return ka[0] - kb[0] || ka[1] - kb[1];
    });
    if (!rows.length) { $('motList').innerHTML = '<div class="empty">Sin motores pendientes 🎉</div>'; return; }
    $('motList').innerHTML = rows.slice(0, 150).map(m => `
        <div class="card" onclick="openMot(${m.id})">
            <div class="t"><span style="font-weight:700">${esc(m.name || '')}</span>
                <span style="display:flex;gap:5px">
                    <span class="pill ${ST_PILL[m.measure_status] || 'p-gray'}">⚡ ${esc(m.measure_status || '—')}</span>
                    <span class="pill ${ST_PILL[m.megado_status] || 'p-gray'}">🧪 ${esc(m.megado_status || '—')}</span>
                </span></div>
            <div class="sub" style="color:var(--cyan)">📍 ${esc(motTree(m)) || esc(m.status || '(sin ubicación)')}</div>
            <div class="sub">${dueHtml('⚡ Corriente/Temp', m.next_measure_due, m.last_current_date)}</div>
            <div class="sub">${dueHtml('🧪 Megado', m.next_megado_due, m.last_megado_date)}
                <span style="opacity:.5"> · ${esc(m.code || '')}</span></div>
        </div>`).join('');
}

// Temperatura multipunto: filas dinámicas (punto + °C), prellenadas con los
// puntos estándar del motor; se pueden añadir puntos adicionales.
const TEMP_POINTS = ['CARCASA', 'BOBINADO', 'RODAMIENTO_LA', 'RODAMIENTO_LOA', 'BORNERA'];
function addTempRow(point) {
    const div = document.createElement('div');
    div.className = 'temp-row';
    div.innerHTML = `<input type="text" list="mTempPointsDL" class="tp-point" placeholder="Punto" value="${esc(typeof point === 'string' ? point : '')}">` +
        `<input type="number" step="0.1" class="tp-val" placeholder="°C" inputmode="decimal">` +
        `<button type="button" class="tp-del" onclick="this.parentElement.remove()">✕</button>`;
    $('mTempRows').appendChild(div);
}
function resetTempRows() {
    $('mTempRows').innerHTML = '';
    TEMP_POINTS.forEach(p => addTempRow(p));
}

function openMot(id) {
    currentMot = MOTS.find(m => m.id === id);
    if (!currentMot) return;
    clearMsg('motMsg');
    ['mCurR', 'mCurS', 'mCurT', 'mVrs', 'mVst', 'mVtr',
     'mMegRS', 'mMegST', 'mMegTR', 'mMegRG', 'mMegSG', 'mMegTG', 'mNotes'].forEach(i => $(i).value = '');
    resetTempRows();
    const m = currentMot;
    $('motHead').innerHTML = `
        <b>${esc(m.name || '')}</b> <span style="opacity:.5">· ${esc(m.code || '')}</span><br>
        <span class="kv" style="color:var(--cyan)">📍 ${esc(motTree(m)) || '(sin ubicación)'}</span>
        <div class="kv sect">Placa: <b>${m.rated_hp ?? '-'} HP</b> · <b>${m.rated_voltage_v ?? '-'} V</b>
        · I nom: <b>${m.rated_current_a ?? '-'} A</b> · Megado mín: <b>${m.megado_min_mohm ?? '-'} MΩ</b></div>
        <div class="kv">${dueHtml('⚡ Corriente/Temp', m.next_measure_due, null)}</div>
        <div class="kv">${dueHtml('🧪 Megado', m.next_megado_due, null)}</div>
        <div class="kv sect">Últ. corriente: <b>${m.last_current_r ?? '-'} / ${m.last_current_s ?? '-'} / ${m.last_current_t ?? '-'} A</b>
        (${esc(m.last_current_date || 'nunca')}) · Últ. megado: <b>${m.last_megado_mohm ?? '-'} MΩ</b> (${esc(m.last_megado_date || 'nunca')})</div>`;
    nav('motreg');
}

function switchMotForm(v) {
    $('motFormCorriente').style.display = v === 'CORRIENTE' ? '' : 'none';
    $('motFormMegado').style.display = v === 'MEGADO' ? '' : 'none';
    $('motFormTemp').style.display = v === 'TEMPERATURA' ? '' : 'none';
}

async function submitMotorTest() {
    if (!currentMot) return;
    clearMsg('motMsg');
    const type = segVal('motType');
    const body = { test_type: type, context: 'PROGRAMADO', executed_by: ME.name || 'Campo', notes: $('mNotes').value.trim() || null };
    const val = (id) => $(id).value === '' ? null : parseFloat($(id).value);
    if (type === 'CORRIENTE') {
        body.current_r = val('mCurR'); body.current_s = val('mCurS'); body.current_t = val('mCurT');
        body.voltage_rs = val('mVrs'); body.voltage_st = val('mVst'); body.voltage_tr = val('mVtr');
        if (body.current_r == null && body.current_s == null && body.current_t == null &&
            body.voltage_rs == null && body.voltage_st == null && body.voltage_tr == null) {
            msg('motMsg', false, 'Ingresa al menos una corriente o tensión.'); return;
        }
    } else if (type === 'MEGADO') {
        body.meg_rs_mohm = val('mMegRS'); body.meg_st_mohm = val('mMegST'); body.meg_tr_mohm = val('mMegTR');
        body.meg_rg_mohm = val('mMegRG'); body.meg_sg_mohm = val('mMegSG'); body.meg_tg_mohm = val('mMegTG');
        body.test_voltage_v = $('mTestV').value;
        if ([body.meg_rs_mohm, body.meg_st_mohm, body.meg_tr_mohm,
             body.meg_rg_mohm, body.meg_sg_mohm, body.meg_tg_mohm].every(v => v == null)) {
            msg('motMsg', false, 'Ingresa al menos una combinación de megado (fase-fase o fase-tierra).'); return;
        }
    } else {
        body.temp_readings = [...document.querySelectorAll('#mTempRows .temp-row')].map(row => ({
            point: row.querySelector('.tp-point').value.trim(),
            value: row.querySelector('.tp-val').value,
        })).filter(x => x.value !== '');
        if (!body.temp_readings.length) { msg('motMsg', false, 'Ingresa al menos una temperatura.'); return; }
    }
    try {
        const r = await fetch(`/api/motors/${currentMot.id}/tests`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        const d = await r.json();
        if (!r.ok) { msg('motMsg', false, esc(d.error || 'No se pudo registrar.')); return; }
        const st = d.status || (d.test && d.test.status) || null;
        let extra = '';
        if (st === 'ROJO') extra = '<br>🚨 <b>Valor fuera de rango</b> — se generó aviso correctivo automático.';
        else if (st === 'VERDE') extra = '<br>🟢 Valor dentro de rango.';
        const n = d.saved_count || 1;
        msg('motMsg', true, `✅ ${n > 1 ? n + ' mediciones registradas' : 'Medición registrada'} en <b>${esc(currentMot.code)}</b>.${extra}`);
        MOTS = [];  // recargar al volver
        setTimeout(() => nav('electrica'), 1400);
    } catch (e) { msg('motMsg', false, 'Error de red.'); }
}

/* ── Badges del home ────────────────────────────────────────────────── */
function setBadge(id, n) {
    const b = $(id);
    b.textContent = n;
    b.classList.toggle('zero', !n);
}

async function loadBadges() {
    loadOts();
    loadLubs();
    loadMots();
}

/* ── Init ───────────────────────────────────────────────────────────── */
document.addEventListener('DOMContentLoaded', () => {
    initSeg('rCrit');
    initSeg('lubAction');
    initSeg('motType', switchMotForm);
    loadMe().then(loadBadges);
    showView();
});
