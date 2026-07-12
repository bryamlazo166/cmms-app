// Diagnostico Mensual de Gestion — datos en vivo + narrativa IA + modo presentacion
let DIAG = null;
const CHARTS = {};

document.addEventListener('DOMContentLoaded', () => {
    // Default: mes actual (para presentar el mes en curso o recien cerrado)
    document.getElementById('diagMonth').value = new Date().toISOString().slice(0, 7);
    loadDiagnostico();
    window.addEventListener('resize', () => Object.values(CHARTS).forEach(c => c && c.resize()));
    document.addEventListener('keydown', onPresentKeys);
});

async function loadDiagnostico() {
    const month = document.getElementById('diagMonth').value;
    try {
        const res = await fetch(`/api/diagnostico/data?month=${month}`);
        DIAG = await res.json();
        if (DIAG.error) { alert('Error: ' + DIAG.error); return; }
        document.getElementById('genAt').textContent = `generado ${DIAG.meta.generated_at}`;
        document.getElementById('s1Title').textContent = `Resumen de ${DIAG.meta.label}`;
        document.getElementById('s6Title').textContent = `Programacion propuesta — ${DIAG.programa.label}`;
        document.getElementById('s7Title').textContent = `Detalle de OTs — ${DIAG.programa.label}`;
        renderKpis();
        renderTrend();
        renderPareto();
        renderEquipos();
        renderSalud();
        renderPrograma();
        renderOTsNext();
    } catch (e) { alert('No se pudo cargar el diagnostico: ' + e.message); }
}

// ── Helpers ──────────────────────────────────────────────────────────────
function el(id) { return document.getElementById(id); }
function chart(id) {
    const box = el(id);
    if (!box) return null;
    if (!CHARTS[id]) CHARTS[id] = echarts.init(box);
    return CHARTS[id];
}
function kpiCard(label, value, cls, delta) {
    return `<div class="kpi-item"><div class="label">${label}</div>` +
           `<div class="value ${cls || ''}">${value}</div>` +
           (delta ? `<div class="delta">${delta}</div>` : '') + `</div>`;
}
function deltaTxt(cur, prev, unit, invert) {
    if (cur == null || prev == null) return '';
    const d = Math.round((cur - prev) * 10) / 10;
    if (d === 0) return `= igual que ${unit}`;
    const better = invert ? d < 0 : d > 0;
    const arrow = d > 0 ? '▲' : '▼';
    const color = better ? '#30D158' : '#FF453A';
    return `<span style="color:${color}">${arrow} ${Math.abs(d)}</span> vs mes anterior`;
}

// ── S1: KPIs ─────────────────────────────────────────────────────────────
function renderKpis() {
    const k = DIAG.kpis_mes, p = DIAG.kpis_prev;
    const proCls = k.proactive_pct >= 75 ? 'v-good' : (k.proactive_pct >= 50 ? 'v-warn' : 'v-crit');
    const cumCls = k.cumplimiento_pct == null ? '' :
        (k.cumplimiento_pct >= 90 ? 'v-good' : (k.cumplimiento_pct >= 70 ? 'v-warn' : 'v-crit'));
    el('kpiStrip').innerHTML =
        kpiCard('OTs cerradas', k.closed_total, '', deltaTxt(k.closed_total, p.closed_total, 'mes ant.')) +
        kpiCard('% Proactivo (meta >75%)', (k.proactive_pct ?? '-') + '%', proCls, deltaTxt(k.proactive_pct, p.proactive_pct, 'pts')) +
        kpiCard('Correctivas', k.correctivas, k.correctivas > k.proactivas ? 'v-warn' : '', deltaTxt(k.correctivas, p.correctivas, '', true)) +
        kpiCard('Cumplimiento programa', k.cumplimiento_pct != null ? k.cumplimiento_pct + '%' : 'sin prog.', cumCls, `${k.programadas} programadas`) +
        kpiCard('MTTR correctivo (h)', k.mttr_h ?? '-', '', deltaTxt(k.mttr_h, p.mttr_h, 'h', true)) +
        kpiCard('Downtime del mes (h)', k.downtime_h, k.downtime_h > (p.downtime_h || 0) ? 'v-crit' : 'v-good', deltaTxt(k.downtime_h, p.downtime_h, 'h', true)) +
        kpiCard('Respuesta aviso→cierre', (k.respuesta_dias ?? '-') + ' d', '', '');
}

// ── S2: Tendencia ────────────────────────────────────────────────────────
function renderTrend() {
    const t = DIAG.trend;
    chart('trendChart').setOption({
        backgroundColor: 'transparent',
        tooltip: { trigger: 'axis' },
        legend: { textStyle: { color: '#9ab0cb' } },
        grid: { left: 50, right: 60, top: 40, bottom: 30 },
        xAxis: { type: 'category', data: t.map(x => x.month), axisLabel: { color: '#9ab0cb' } },
        yAxis: [
            { type: 'value', name: 'OTs', axisLabel: { color: '#9ab0cb' }, splitLine: { lineStyle: { color: '#233246' } } },
            { type: 'value', name: '%', min: 0, max: 100, axisLabel: { color: '#9ab0cb', formatter: '{value}%' }, splitLine: { show: false } },
        ],
        series: [
            { name: 'Correctivas', type: 'bar', stack: 'ots', data: t.map(x => x.correctivas), itemStyle: { color: '#FF453A' } },
            { name: 'Proactivas', type: 'bar', stack: 'ots', data: t.map(x => x.proactivas), itemStyle: { color: '#30D158' } },
            { name: 'Mejoras', type: 'bar', stack: 'ots', data: t.map(x => x.mejoras), itemStyle: { color: '#5AC8FA' } },
            { name: '% Proactivo', type: 'line', yAxisIndex: 1, data: t.map(x => x.proactive_pct), itemStyle: { color: '#BF5AF2' }, lineStyle: { width: 3 }, symbolSize: 8,
              markLine: { silent: true, symbol: 'none', data: [{ yAxis: 75 }], lineStyle: { color: '#30D158', type: 'dashed' }, label: { formatter: 'meta 75%', color: '#30D158' } } },
        ],
    });
}

// ── S3: Pareto ───────────────────────────────────────────────────────────
function renderPareto() {
    if (!DIAG) return;
    const win = (document.querySelector('input[name="parWin"]:checked') || {}).value || '6m';
    const data = win === 'mes' ? DIAG.pareto_mes : DIAG.pareto_6m;
    const items = (data.items || []).slice(0, 12);
    chart('paretoChart').setOption({
        backgroundColor: 'transparent',
        tooltip: { trigger: 'axis', formatter: ps => {
            const it = items[ps[0].dataIndex];
            return `<b>${it.label}</b><br/>Fallas: ${it.count}<br/>Acumulado: ${it.cum_pct}%<br/>Parada: ${it.downtime_h}h`;
        } },
        grid: { left: 50, right: 60, top: 30, bottom: 85 },
        xAxis: { type: 'category', data: items.map(i => i.label),
                 axisLabel: { rotate: 38, color: '#9ab0cb', fontSize: 10, width: 120, overflow: 'truncate' } },
        yAxis: [
            { type: 'value', name: 'Fallas', axisLabel: { color: '#9ab0cb' }, splitLine: { lineStyle: { color: '#233246' } } },
            { type: 'value', name: '%', min: 0, max: 100, axisLabel: { color: '#9ab0cb', formatter: '{value}%' }, splitLine: { show: false } },
        ],
        series: [
            { name: 'Fallas', type: 'bar', data: items.map(i => i.count), barMaxWidth: 36,
              itemStyle: { color: '#0A84FF', borderRadius: [4, 4, 0, 0] },
              label: { show: true, position: 'top', color: '#d5e2f5', fontSize: 10 } },
            { name: '% acumulado', type: 'line', yAxisIndex: 1, data: items.map(i => i.cum_pct), smooth: true,
              itemStyle: { color: '#FF9F0A' },
              markLine: { silent: true, symbol: 'none', data: [{ yAxis: 80 }], lineStyle: { color: '#FF453A', type: 'dashed' }, label: { formatter: '80%', color: '#FF453A' } } },
        ],
    });
}

// ── S4: Equipos criticos ─────────────────────────────────────────────────
function renderEquipos() {
    const eq = (DIAG.top_equipos || []).slice().reverse();
    chart('equiposChart').setOption({
        backgroundColor: 'transparent',
        tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
        legend: { textStyle: { color: '#9ab0cb' } },
        grid: { left: 210, right: 60, top: 30, bottom: 30 },
        xAxis: { type: 'value', axisLabel: { color: '#9ab0cb' }, splitLine: { lineStyle: { color: '#233246' } } },
        yAxis: { type: 'category', data: eq.map(e => e.equipo), axisLabel: { color: '#d5e2f5', width: 190, overflow: 'truncate' } },
        series: [
            { name: 'Horas de parada', type: 'bar', data: eq.map(e => e.downtime_h), itemStyle: { color: '#FF453A' },
              label: { show: true, position: 'right', color: '#d5e2f5', fontSize: 10, formatter: '{c} h' } },
            { name: 'Fallas', type: 'bar', data: eq.map(e => e.fallas), itemStyle: { color: '#FF9F0A' } },
        ],
    });
}

// ── S5: Salud del sistema ────────────────────────────────────────────────
function renderSalud() {
    const b = DIAG.backlog, pr = DIAG.predictivo, al = DIAG.almacen, inf = DIAG.informes;
    el('saludStrip').innerHTML =
        kpiCard('Backlog (OTs abiertas)', b.total, b.total > 60 ? 'v-warn' : '', `${b.horas_estimadas} h estimadas`) +
        kpiCard('Con tecnico asignado', `${b.con_tecnico}/${b.total}`, b.con_tecnico < b.total / 2 ? 'v-crit' : 'v-good', `${b.programadas} programadas`) +
        kpiCard('OTs >30 dias', b.aging['30-60'] + b.aging['>60'], (b.aging['30-60'] + b.aging['>60']) > 15 ? 'v-warn' : '', `${b.aging['sin_fecha']} sin fecha`) +
        kpiCard('Megado pendiente', `${pr.megado_pendiente}/${pr.electricos}`, pr.megado_pendiente > 0 ? 'v-crit' : 'v-good', 'motores sin prueba') +
        kpiCard('Almacen bajo minimo', `${al.bajo_minimo}/${al.items}`, al.quiebres > 0 ? 'v-crit' : 'v-warn', `${al.quiebres} quiebres`) +
        kpiCard('Informes proveedor', `${inf.pendientes}/${inf.requeridos}`, inf.pendientes > inf.requeridos / 2 ? 'v-crit' : '', 'pendientes');

    const r = DIAG.rutinas;
    const row = (nombre, c) => {
        const tot = Object.values(c).reduce((a, x) => a + x, 0);
        const verde = c.VERDE || 0;
        const pct = tot ? Math.round(verde / tot * 100) : 0;
        return `<tr><td>${nombre}</td><td class="num">${tot}</td>` +
               `<td class="num" style="color:#30D158">${verde}</td>` +
               `<td class="num" style="color:#FF9F0A">${c.AMARILLO || 0}</td>` +
               `<td class="num" style="color:#FF453A">${c.ROJO || 0}</td>` +
               `<td class="num">${(c.PENDIENTE || 0) + (c['-'] || 0)}</td>` +
               `<td class="num" style="color:${pct >= 90 ? '#30D158' : pct >= 70 ? '#FF9F0A' : '#FF453A'}">${pct}%</td></tr>`;
    };
    el('rutinasTable').innerHTML =
        `<tr><th>Rutina</th><th class="num">Puntos</th><th class="num">Verde</th><th class="num">Amarillo</th><th class="num">Rojo</th><th class="num">Pend.</th><th class="num">Al dia</th></tr>` +
        row('Lubricacion', r.lubricacion) + row('Inspeccion', r.inspeccion) + row('Monitoreo', r.monitoreo);
}

// ── S6: Programacion proximo mes ─────────────────────────────────────────
function renderPrograma() {
    const pg = DIAG.programa, cap = pg.capacidad;
    const utilCls = cap.utilizacion_pct == null ? '' :
        (cap.utilizacion_pct > 90 ? 'v-crit' : (cap.utilizacion_pct > 60 ? 'v-warn' : 'v-good'));
    el('progStrip').innerHTML =
        kpiCard('OTs programadas', pg.ots_programadas.length, '', `${pg.ots_sin_fecha} abiertas sin fecha por asignar`) +
        kpiCard('Lubricaciones que vencen', pg.totales_rutinas.lubricacion, '', '') +
        kpiCard('Inspecciones que vencen', pg.totales_rutinas.inspeccion, '', '') +
        kpiCard('Megados que vencen', pg.totales_rutinas.megado, '', '') +
        kpiCard('Capacidad disponible', cap.horas_disponibles + ' h', '', `${cap.tecnicos} tecnicos x ${cap.dias_habiles} dias`) +
        kpiCard('Carga programada', cap.horas_programadas + ' h', utilCls, cap.utilizacion_pct != null ? cap.utilizacion_pct + '% de utilizacion' : '');

    const rs = pg.rutinas_semana;
    chart('progChart').setOption({
        backgroundColor: 'transparent',
        tooltip: { trigger: 'axis' },
        legend: { textStyle: { color: '#9ab0cb' } },
        grid: { left: 50, right: 30, top: 36, bottom: 30 },
        xAxis: { type: 'category', data: rs.semanas, axisLabel: { color: '#9ab0cb' } },
        yAxis: { type: 'value', name: 'Tareas', axisLabel: { color: '#9ab0cb' }, splitLine: { lineStyle: { color: '#233246' } } },
        series: [
            { name: 'Lubricacion', type: 'bar', stack: 'r', data: rs.lubricacion, itemStyle: { color: '#30D158' } },
            { name: 'Inspeccion', type: 'bar', stack: 'r', data: rs.inspeccion, itemStyle: { color: '#5AC8FA' } },
            { name: 'Monitoreo', type: 'bar', stack: 'r', data: rs.monitoreo, itemStyle: { color: '#BF5AF2' } },
            { name: 'Megado', type: 'bar', stack: 'r', data: rs.megado, itemStyle: { color: '#FF9F0A' } },
        ],
    });
}

function renderOTsNext() {
    const rows = DIAG.programa.ots_programadas;
    const paradas = DIAG.programa.paradas_proximas || [];
    let html = `<tr><th>Fecha</th><th>OT</th><th>Equipo</th><th>Tipo</th><th class="num">Horas</th><th>Estado</th><th>Descripcion</th></tr>`;
    if (!rows.length) {
        html += `<tr><td colspan="7" style="color:#9ab0cb">Aun no hay OTs con fecha en ${DIAG.programa.label}. ` +
                `Programa el backlog (${DIAG.programa.ots_sin_fecha} OTs sin fecha) desde Ordenes de Trabajo.</td></tr>`;
    } else {
        html += rows.map(o =>
            `<tr><td>${o.fecha || '-'}</td><td style="color:#5AC8FA;font-weight:600">${o.code}</td>` +
            `<td>${o.equipo}</td><td>${o.tipo}</td><td class="num">${o.horas || '-'}</td>` +
            `<td>${o.status}</td><td>${o.descripcion}</td></tr>`).join('');
    }
    if (paradas.length) {
        html += `<tr><td colspan="7" style="color:#FF9F0A;font-weight:700;padding-top:14px">PARADAS PROXIMAS (coordinar ventanas con produccion)</td></tr>`;
        html += paradas.map(p =>
            `<tr><td>${p.fecha}</td><td colspan="2">${p.code || ''} ${p.name}</td>` +
            `<td colspan="4">${p.planificada ? 'Planificada' : 'Por averia'}</td></tr>`).join('');
    }
    el('otsNextTable').innerHTML = html;
}

// ── Narrativa IA ─────────────────────────────────────────────────────────
async function generarNarrativa() {
    if (!DIAG) return;
    const box = el('narrativaBox');
    box.textContent = 'Generando analisis ejecutivo con IA...';
    try {
        const res = await fetch('/api/diagnostico/narrativa', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(DIAG),
        });
        const data = await res.json();
        box.textContent = data.narrativa || ('Error: ' + (data.error || 'desconocido'));
    } catch (e) { box.textContent = 'Error generando narrativa: ' + e.message; }
}
window.generarNarrativa = generarNarrativa;

// ── Modo presentacion ────────────────────────────────────────────────────
let slideIdx = 0;
function slides() { return Array.from(document.querySelectorAll('[data-slide]')); }

function showSlide(i) {
    const ss = slides();
    slideIdx = Math.max(0, Math.min(i, ss.length - 1));
    ss.forEach((s, j) => s.classList.toggle('active', j === slideIdx));
    el('slideCnt').textContent = `${slideIdx + 1}/${ss.length}`;
    // Redimensionar el grafico del slide visible
    setTimeout(() => Object.values(CHARTS).forEach(c => c && c.resize()), 60);
}

function togglePresent() {
    const on = document.body.classList.toggle('presenting');
    if (on) {
        showSlide(0);
        if (document.documentElement.requestFullscreen) {
            document.documentElement.requestFullscreen().catch(() => {});
        }
    } else {
        slides().forEach(s => s.classList.remove('active'));
        if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
        setTimeout(() => Object.values(CHARTS).forEach(c => c && c.resize()), 60);
    }
}
window.togglePresent = togglePresent;
function nextSlide() { showSlide(slideIdx + 1); }
function prevSlide() { showSlide(slideIdx - 1); }
window.nextSlide = nextSlide;
window.prevSlide = prevSlide;

function onPresentKeys(e) {
    if (!document.body.classList.contains('presenting')) return;
    if (e.key === 'ArrowRight' || e.key === 'PageDown' || e.key === ' ') { e.preventDefault(); nextSlide(); }
    else if (e.key === 'ArrowLeft' || e.key === 'PageUp') { e.preventDefault(); prevSlide(); }
    else if (e.key === 'Escape') { togglePresent(); }
}
