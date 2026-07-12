// Diagnostico Mensual de Gestion — datos en vivo + narrativa IA + drill-down + modo presentacion
let DIAG = null;
const CHARTS = {};
let REL = { level: 'areas', areaId: null, areaName: '', equipId: null, equipName: '' };

document.addEventListener('DOMContentLoaded', () => {
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
        const m = DIAG.meta;
        document.getElementById('genAt').textContent = `generado ${m.generated_at}`;
        document.getElementById('s1Title').textContent =
            `Resumen de ${m.label}` + (m.en_curso ? ` (en curso — dia ${m.dia_hoy})` : '');
        document.getElementById('s1Method').textContent = m.en_curso
            ? `Mes en curso: KPIs parciales al dia ${m.dia_hoy} de ${DIAG.kpis_mes.dias_mes}, comparados con ${m.prev_label} completo. Benchmarks SMRP: cumplimiento >90%, proactivo >75%.`
            : `Indicadores de ${m.label} vs. ${m.prev_label}. Benchmarks SMRP: cumplimiento >90%, proactivo >75%.`;
        renderKpis();
        renderSemanas();
        renderConsolidado();
        renderTrend();
        renderTrendKpi();
        renderPareto();
        renderEquipos();
        loadReliability('areas');
        renderSalud();
        renderPrograma();
        renderOTsNext();
        closeDetail('paretoDetail'); closeDetail('equiposDetail'); closeDetail('relDetail');
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
function kpiCard(label, value, cls, delta, onclick) {
    return `<div class="kpi-item ${onclick ? 'click' : ''}" ${onclick ? `onclick="${onclick}"` : ''}>` +
           `<div class="label">${label}</div>` +
           `<div class="value ${cls || ''}">${value}</div>` +
           (delta ? `<div class="delta">${delta}</div>` : '') + `</div>`;
}
function deltaTxt(cur, prev, unit, invert) {
    if (cur == null || prev == null) return '';
    const d = Math.round((cur - prev) * 10) / 10;
    if (d === 0) return `= igual que mes ant.`;
    const better = invert ? d < 0 : d > 0;
    const arrow = d > 0 ? '▲' : '▼';
    const color = better ? '#30D158' : '#FF453A';
    return `<span style="color:${color}">${arrow} ${Math.abs(d)}${unit || ''}</span> vs mes ant.`;
}
function monthWindow() {
    const m = DIAG.meta.month;
    const k = DIAG.kpis_mes;
    const end = k.en_curso
        ? new Date().toISOString().slice(0, 10)
        : `${m}-${String(k.dias_mes).padStart(2, '0')}`;
    return { start: `${m}-01`, end };
}
function closeDetail(id) { const p = el(id); if (p) p.classList.remove('open'); }
function openDetail(id) { const p = el(id); if (p) p.classList.add('open'); }
function goToSlide(n) {
    if (document.body.classList.contains('presenting')) { showSlide(n); return; }
    const ss = document.querySelectorAll('[data-slide]');
    if (ss[n]) ss[n].scrollIntoView({ behavior: 'smooth' });
}
window.goToSlide = goToSlide;
window.closeDetail = closeDetail;

const OTS_COLS = `<tr><th>OT</th><th>Fecha</th><th>Equipo</th><th>Modo de falla</th><th class="num">Parada (h)</th><th class="num">Durac. (h)</th><th>Descripcion / Trabajo realizado</th></tr>`;
function otsRows(rows) {
    if (!rows.length) return `<tr><td colspan="7" style="color:#9ab0cb">Sin OTs en esta seleccion.</td></tr>`;
    return rows.map(r =>
        `<tr><td style="color:#5AC8FA;font-weight:600">${r.code}</td><td>${r.fecha}</td>` +
        `<td>${r.equipo}</td><td>${r.modo}</td>` +
        `<td class="num" style="color:${r.downtime_h > 0 ? '#FF453A' : '#9ab0cb'}">${r.downtime_h || '-'}</td>` +
        `<td class="num">${r.duracion_h || '-'}</td>` +
        `<td>${r.descripcion}${r.ejecucion ? `<div style="color:#30D158;font-size:.76rem">✔ ${r.ejecucion}</div>` : ''}</td></tr>`
    ).join('');
}
async function fetchOtsDetail(params) {
    const q = new URLSearchParams({ month: DIAG.meta.month, ...params });
    const res = await fetch(`/api/diagnostico/ots-detail?${q}`);
    return res.json();
}

// ── S1: KPIs ─────────────────────────────────────────────────────────────
function renderKpis() {
    const k = DIAG.kpis_mes, p = DIAG.kpis_prev;
    const proCls = k.proactive_pct >= 75 ? 'v-good' : (k.proactive_pct >= 50 ? 'v-warn' : 'v-crit');
    const cumCls = k.cumplimiento_pct == null ? '' :
        (k.cumplimiento_pct >= 90 ? 'v-good' : (k.cumplimiento_pct >= 70 ? 'v-warn' : 'v-crit'));
    el('kpiStrip').innerHTML =
        kpiCard('OTs cerradas', k.closed_total, '', deltaTxt(k.closed_total, p.closed_total, '')) +
        kpiCard('% Proactivo (meta >75%)', (k.proactive_pct ?? '-') + '%', proCls, deltaTxt(k.proactive_pct, p.proactive_pct, ' pts')) +
        kpiCard('Correctivas', k.correctivas, k.correctivas > k.proactivas ? 'v-warn' : '', deltaTxt(k.correctivas, p.correctivas, '', true)) +
        kpiCard('Cumplimiento programa', k.cumplimiento_pct != null ? k.cumplimiento_pct + '%' : 'sin prog.', cumCls, `${k.programadas} programadas`) +
        kpiCard('Downtime (h)', k.downtime_h, k.downtime_h > (p.downtime_h || 0) ? 'v-crit' : 'v-good', deltaTxt(k.downtime_h, p.downtime_h, 'h', true)) +
        kpiCard('Respuesta aviso→cierre', (k.respuesta_dias ?? '-') + ' d', '', '');

    const dispCls = k.disponibilidad_pct >= 95 ? 'v-good' : (k.disponibilidad_pct >= 90 ? 'v-warn' : 'v-crit');
    el('kpiStrip2').innerHTML =
        kpiCard('MTBF (h)', k.mtbf_h ?? '-', '', deltaTxt(k.mtbf_h, p.mtbf_h, 'h'), 'goToSlide(6)') +
        kpiCard('MTTR (h)', k.mttr_h ?? '-', '', deltaTxt(k.mttr_h, p.mttr_h, 'h', true), 'goToSlide(6)') +
        kpiCard('Disponibilidad', (k.disponibilidad_pct ?? '-') + '%', dispCls, deltaTxt(k.disponibilidad_pct, p.disponibilidad_pct, ' pts'), 'goToSlide(6)') +
        kpiCard('Confiabilidad R(7d)', k.confiabilidad_pct != null ? k.confiabilidad_pct + '%' : '-', '', deltaTxt(k.confiabilidad_pct, p.confiabilidad_pct, ' pts'), 'goToSlide(6)');
}

// ── S2: Indicadores por semana del mes ───────────────────────────────────
function renderSemanas() {
    const s = DIAG.semanas || [];
    el('semTitle').textContent = `Indicadores por semana — ${DIAG.meta.label}`;
    const labels = s.map(x => `${x.semana} (${x.rango})`);

    chart('semMixChart').setOption({
        backgroundColor: 'transparent',
        title: { text: 'Mezcla de trabajo por semana', textStyle: { color: '#9ab0cb', fontSize: 13 } },
        tooltip: { trigger: 'axis' },
        legend: { textStyle: { color: '#9ab0cb' }, top: 0, right: 0 },
        grid: { left: 40, right: 50, top: 42, bottom: 30 },
        xAxis: { type: 'category', data: labels, axisLabel: { color: '#9ab0cb', fontSize: 10 } },
        yAxis: [
            { type: 'value', name: 'OTs', axisLabel: { color: '#9ab0cb' }, splitLine: { lineStyle: { color: '#233246' } } },
            { type: 'value', name: '%', min: 0, max: 100, axisLabel: { color: '#9ab0cb', formatter: '{value}%' }, splitLine: { show: false } },
        ],
        series: [
            { name: 'Correctivas', type: 'bar', stack: 'w', data: s.map(x => x.correctivas), itemStyle: { color: '#FF453A' } },
            { name: 'Proactivas', type: 'bar', stack: 'w', data: s.map(x => x.proactivas), itemStyle: { color: '#30D158' } },
            { name: 'Mejoras', type: 'bar', stack: 'w', data: s.map(x => x.mejoras), itemStyle: { color: '#5AC8FA' } },
            { name: '% Proactivo', type: 'line', yAxisIndex: 1, data: s.map(x => x.proactive_pct), itemStyle: { color: '#BF5AF2' }, connectNulls: true },
        ],
    });

    chart('semKpiChart').setOption({
        backgroundColor: 'transparent',
        title: { text: 'Cumplimiento, disponibilidad y downtime', textStyle: { color: '#9ab0cb', fontSize: 13 } },
        tooltip: { trigger: 'axis' },
        legend: { textStyle: { color: '#9ab0cb' }, top: 0, right: 0 },
        grid: { left: 44, right: 52, top: 42, bottom: 30 },
        xAxis: { type: 'category', data: labels, axisLabel: { color: '#9ab0cb', fontSize: 10 } },
        yAxis: [
            { type: 'value', name: '%', min: 0, max: 100, axisLabel: { color: '#9ab0cb', formatter: '{value}%' }, splitLine: { lineStyle: { color: '#233246' } } },
            { type: 'value', name: 'h', axisLabel: { color: '#9ab0cb' }, splitLine: { show: false } },
        ],
        series: [
            { name: 'Downtime (h)', type: 'bar', yAxisIndex: 1, data: s.map(x => x.downtime_h), itemStyle: { color: '#FF453A', opacity: .55 }, barMaxWidth: 30 },
            { name: 'Cumplimiento %', type: 'line', data: s.map(x => x.cumplimiento_pct), itemStyle: { color: '#0A84FF' }, lineStyle: { width: 3 }, connectNulls: true,
              markLine: { silent: true, symbol: 'none', data: [{ yAxis: 90 }], lineStyle: { color: '#0A84FF', type: 'dashed' }, label: { formatter: 'meta 90%', color: '#0A84FF' } } },
            { name: 'Disponibilidad %', type: 'line', data: s.map(x => x.disponibilidad_pct), itemStyle: { color: '#30D158' }, connectNulls: true },
        ],
    });

    const fila = (nombre, fn, fmt) =>
        `<tr><td><b>${nombre}</b></td>` + s.map(x => {
            if (x.futura) return `<td class="num" style="color:#4a5361">—</td>`;
            const v = fn(x);
            return `<td class="num">${v == null ? '-' : (fmt ? fmt(v) : v)}</td>`;
        }).join('') + `</tr>`;
    el('semTable').innerHTML =
        `<tr><th>Indicador</th>${s.map(x => `<th class="num">${x.semana}<br>(${x.rango})${x.futura ? ' *' : ''}</th>`).join('')}</tr>` +
        fila('OTs cerradas', x => x.closed_total) +
        fila('Correctivas', x => x.correctivas) +
        fila('Proactivas', x => x.proactivas) +
        fila('% Proactivo', x => x.proactive_pct, v => v + '%') +
        fila('Programadas', x => x.programadas) +
        fila('Cumplimiento', x => x.cumplimiento_pct, v => v + '%') +
        fila('MTBF (h)', x => x.mtbf_h) +
        fila('MTTR (h)', x => x.mttr_h) +
        fila('Disponibilidad', x => x.disponibilidad_pct, v => v + '%') +
        fila('Downtime (h)', x => x.downtime_h) +
        (s.some(x => x.futura) ? `<tr><td colspan="${s.length + 1}" style="color:#5a7aa0;font-size:.72rem">* semana futura del mes en curso</td></tr>` : '');
}

// ── S3: Cuadro consolidado 12 meses ──────────────────────────────────────
function renderConsolidado() {
    const t = DIAG.trend;
    const cols = t.map(x => `<th class="num">${x.month}${x.en_curso ? '*' : ''}</th>`).join('');
    const fila = (nombre, fn, fmt) =>
        `<tr><td><b>${nombre}</b></td>` +
        t.map(x => {
            const v = fn(x);
            return `<td class="num">${v == null ? '-' : (fmt ? fmt(v) : v)}</td>`;
        }).join('') + `</tr>`;
    el('consolidadoTable').innerHTML =
        `<tr><th>Indicador</th>${cols}</tr>` +
        fila('OTs cerradas', x => x.closed_total) +
        fila('Correctivas', x => x.correctivas) +
        fila('Proactivas (PM+PdM)', x => x.proactivas) +
        fila('% Proactivo', x => x.proactive_pct, v => v + '%') +
        fila('MTBF (h)', x => x.mtbf_h) +
        fila('MTTR (h)', x => x.mttr_h) +
        fila('Disponibilidad', x => x.disponibilidad_pct, v => v + '%') +
        fila('Confiabilidad R(7d)', x => x.confiabilidad_pct, v => v + '%') +
        fila('Downtime (h)', x => x.downtime_h) +
        `<tr><td colspan="${t.length + 1}" style="color:#5a7aa0;font-size:.72rem">* mes en curso: calculado con los dias transcurridos</td></tr>`;
}

// ── S3: Tendencia ────────────────────────────────────────────────────────
function renderTrend() {
    const t = DIAG.trend;
    chart('trendChart').setOption({
        backgroundColor: 'transparent',
        title: { text: 'Mezcla de trabajo', textStyle: { color: '#9ab0cb', fontSize: 13 } },
        tooltip: { trigger: 'axis' },
        legend: { textStyle: { color: '#9ab0cb' }, top: 0, right: 0 },
        grid: { left: 44, right: 52, top: 40, bottom: 30 },
        xAxis: { type: 'category', data: t.map(x => x.month), axisLabel: { color: '#9ab0cb', fontSize: 10 } },
        yAxis: [
            { type: 'value', name: 'OTs', axisLabel: { color: '#9ab0cb' }, splitLine: { lineStyle: { color: '#233246' } } },
            { type: 'value', name: '%', min: 0, max: 100, axisLabel: { color: '#9ab0cb', formatter: '{value}%' }, splitLine: { show: false } },
        ],
        series: [
            { name: 'Correctivas', type: 'bar', stack: 'ots', data: t.map(x => x.correctivas), itemStyle: { color: '#FF453A' } },
            { name: 'Proactivas', type: 'bar', stack: 'ots', data: t.map(x => x.proactivas), itemStyle: { color: '#30D158' } },
            { name: 'Mejoras', type: 'bar', stack: 'ots', data: t.map(x => x.mejoras), itemStyle: { color: '#5AC8FA' } },
            { name: '% Proactivo', type: 'line', yAxisIndex: 1, data: t.map(x => x.proactive_pct), itemStyle: { color: '#BF5AF2' }, lineStyle: { width: 3 }, symbolSize: 7,
              markLine: { silent: true, symbol: 'none', data: [{ yAxis: 75 }], lineStyle: { color: '#30D158', type: 'dashed' }, label: { formatter: 'meta 75%', color: '#30D158' } } },
        ],
    });
}

function renderTrendKpi() {
    const t = DIAG.trend;
    chart('trendKpiChart').setOption({
        backgroundColor: 'transparent',
        title: { text: 'Confiabilidad de planta', textStyle: { color: '#9ab0cb', fontSize: 13 } },
        tooltip: { trigger: 'axis' },
        legend: { textStyle: { color: '#9ab0cb' }, top: 0, right: 0 },
        grid: { left: 50, right: 55, top: 40, bottom: 30 },
        xAxis: { type: 'category', data: t.map(x => x.month), axisLabel: { color: '#9ab0cb', fontSize: 10 } },
        yAxis: [
            { type: 'value', name: 'horas', axisLabel: { color: '#9ab0cb' }, splitLine: { lineStyle: { color: '#233246' } } },
            { type: 'value', name: '%', min: 0, max: 100, axisLabel: { color: '#9ab0cb', formatter: '{value}%' }, splitLine: { show: false } },
        ],
        series: [
            { name: 'MTBF (h)', type: 'line', data: t.map(x => x.mtbf_h), itemStyle: { color: '#BF5AF2' }, lineStyle: { width: 2 }, connectNulls: true },
            { name: 'MTTR (h)', type: 'line', data: t.map(x => x.mttr_h), itemStyle: { color: '#FF9F0A' }, lineStyle: { width: 2 }, connectNulls: true },
            { name: 'Disponibilidad %', type: 'line', yAxisIndex: 1, data: t.map(x => x.disponibilidad_pct), itemStyle: { color: '#30D158' }, lineStyle: { width: 3 }, areaStyle: { opacity: .08 } },
        ],
    });
}

// ── S4: Pareto (con drill-down a OTs) ────────────────────────────────────
function renderPareto() {
    if (!DIAG) return;
    const win = (document.querySelector('input[name="parWin"]:checked') || {}).value || '6m';
    const data = win === 'mes' ? DIAG.pareto_mes : DIAG.pareto_6m;
    const items = (data.items || []).slice(0, 12);
    const c = chart('paretoChart');
    c.setOption({
        backgroundColor: 'transparent',
        tooltip: { trigger: 'axis', formatter: ps => {
            const it = items[ps[0].dataIndex];
            return `<b>${it.label}</b><br/>Fallas: ${it.count}<br/>Acumulado: ${it.cum_pct}%<br/>Parada: ${it.downtime_h}h<br/><i>Clic para ver las OTs</i>`;
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
    c.off('click');
    c.on('click', async (ev) => {
        const it = items[ev.dataIndex];
        if (!it) return;
        el('paretoDetailTitle').textContent = `OTs con modo "${it.label}" (${win === 'mes' ? DIAG.meta.label : 'ultimos 6 meses'})`;
        el('paretoDetailTable').innerHTML = `<tr><td style="color:#9ab0cb">Cargando...</td></tr>`;
        openDetail('paretoDetail');
        const d = await fetchOtsDetail({ window: win, failure_mode: it.label });
        el('paretoDetailTable').innerHTML = OTS_COLS + otsRows(d.rows || []);
    });
}

// ── S5: Equipos criticos (con drill-down a OTs) ──────────────────────────
function renderEquipos() {
    const eq = (DIAG.top_equipos || []).slice().reverse();
    const c = chart('equiposChart');
    c.setOption({
        backgroundColor: 'transparent',
        tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' },
            formatter: ps => `<b>${ps[0].name}</b><br/>` + ps.map(p => `${p.seriesName}: ${p.value}`).join('<br/>') + '<br/><i>Clic para ver las OTs</i>' },
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
    c.off('click');
    c.on('click', async (ev) => {
        const item = eq[ev.dataIndex];
        if (!item) return;
        el('equiposDetailTitle').textContent = `OTs correctivas de ${item.equipo} (ultimos 6 meses)`;
        el('equiposDetailTable').innerHTML = `<tr><td style="color:#9ab0cb">Cargando...</td></tr>`;
        openDetail('equiposDetail');
        const params = item.equipment_id ? { window: '6m', equipment_id: item.equipment_id } : { window: '6m', sin_equipo: '1' };
        const d = await fetchOtsDetail(params);
        el('equiposDetailTable').innerHTML = OTS_COLS + otsRows(d.rows || []);
    });
}

// ── S6: Confiabilidad drill-down (Area → Equipo → Fallas) ────────────────
function relParams() {
    const { start, end } = monthWindow();
    return `start_date=${start}&end_date=${end}&mode=operativa`;
}
function relBreadcrumb() {
    let html = REL.level === 'areas'
        ? `<span class="current">Areas</span>`
        : `<span onclick="loadReliability('areas')">Areas</span>`;
    if (REL.level !== 'areas') {
        html += `<span class="sep">›</span>`;
        html += REL.level === 'equipments'
            ? `<span class="current">${REL.areaName}</span>`
            : `<span onclick="loadReliability('equipments', ${REL.areaId}, '${REL.areaName}')">${REL.areaName}</span>`;
    }
    el('relBreadcrumb').innerHTML = html;
}
function relKpiStrip(k) {
    el('relKpis').innerHTML =
        kpiCard('Disponibilidad', (k.availability ?? '-') + '%', (k.availability >= 95 ? 'v-good' : k.availability >= 90 ? 'v-warn' : 'v-crit')) +
        kpiCard('Confiabilidad', (k.reliability ?? '-') + '%', '') +
        kpiCard('MTBF (h)', k.mtbf ?? '-', '') +
        kpiCard('MTTR (h)', k.mttr ?? '-', '');
}
async function loadReliability(level, id, name) {
    try {
        closeDetail('relDetail');
        if (level === 'areas') {
            REL = { level: 'areas', areaId: null, areaName: '', equipId: null, equipName: '' };
            const res = await fetch(`/api/indicators/areas?${relParams()}`);
            const data = await res.json();
            const areas = data.areas || [];
            relBreadcrumb();
            const avg = arr => arr.length ? Math.round(arr.reduce((s, x) => s + x, 0) / arr.length * 100) / 100 : null;
            const totalFail = areas.reduce((s, a) => s + (a.failure_count || 0), 0);
            const totalDown = areas.reduce((s, a) => s + (a.downtime_hours || 0), 0);
            relKpiStrip({
                availability: avg(areas.map(a => a.availability || 0)),
                reliability: avg(areas.map(a => a.reliability || 0)),
                mtbf: totalFail ? Math.round(((data.period?.hours || 0) * areas.length - totalDown) / totalFail * 10) / 10 : null,
                mttr: totalFail ? Math.round(totalDown / totalFail * 10) / 10 : null,
            });
            relChartBars(areas.map(a => a.area_name), areas, (idx) => {
                const a = areas[idx];
                loadReliability('equipments', a.area_id, a.area_name);
            });
        } else if (level === 'equipments') {
            REL.level = 'equipments'; REL.areaId = id; REL.areaName = name;
            const res = await fetch(`/api/indicators/area/${id}/equipments?${relParams()}`);
            const data = await res.json();
            const eqs = data.equipments || [];
            relBreadcrumb();
            const totalFail = eqs.reduce((s, e) => s + (e.failure_count || 0), 0);
            const totalDown = eqs.reduce((s, e) => s + (e.downtime_hours || 0), 0);
            const avg = arr => arr.length ? Math.round(arr.reduce((s, x) => s + x, 0) / arr.length * 100) / 100 : null;
            relKpiStrip({
                availability: avg(eqs.map(e => e.availability || 0)),
                reliability: avg(eqs.map(e => e.reliability || 0)),
                mtbf: totalFail ? Math.round(((data.period?.hours || 0) * eqs.length - totalDown) / totalFail * 10) / 10 : null,
                mttr: totalFail ? Math.round(totalDown / totalFail * 10) / 10 : null,
            });
            relChartBars(eqs.map(e => e.equipment_tag || e.equipment_name), eqs, async (idx) => {
                const e = eqs[idx];
                await relFailures(e.equipment_id, e.equipment_tag || e.equipment_name);
            });
        }
    } catch (e) { console.error('loadReliability:', e); }
}
window.loadReliability = loadReliability;

function relChartBars(names, rows, onClick) {
    const c = chart('relChart');
    c.setOption({
        backgroundColor: 'transparent',
        tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' },
            formatter: ps => `<b>${ps[0].name}</b><br/>` + ps.map(p => `${p.seriesName}: ${p.value}`).join('<br/>') + '<br/><i>Clic para profundizar</i>' },
        legend: { textStyle: { color: '#9ab0cb' } },
        grid: { left: 60, right: 40, top: 34, bottom: 60 },
        xAxis: { type: 'category', data: names, axisLabel: { rotate: 25, color: '#9ab0cb', fontSize: 10 } },
        yAxis: [
            { type: 'value', name: '%', min: 0, max: 100, axisLabel: { color: '#9ab0cb' }, splitLine: { lineStyle: { color: '#233246' } } },
            { type: 'value', name: 'h', axisLabel: { color: '#9ab0cb' }, splitLine: { show: false } },
        ],
        series: [
            { name: 'Disponibilidad %', type: 'bar', data: rows.map(r => r.availability), itemStyle: { color: '#30D158' }, barMaxWidth: 26 },
            { name: 'Confiabilidad %', type: 'bar', data: rows.map(r => r.reliability), itemStyle: { color: '#5AC8FA' }, barMaxWidth: 26 },
            { name: 'MTBF h', type: 'line', yAxisIndex: 1, data: rows.map(r => r.mtbf), itemStyle: { color: '#BF5AF2' } },
            { name: 'MTTR h', type: 'line', yAxisIndex: 1, data: rows.map(r => r.mttr), itemStyle: { color: '#FF9F0A' } },
        ],
    });
    c.off('click');
    c.on('click', ev => onClick(ev.dataIndex));
}

async function relFailures(equipId, label) {
    const res = await fetch(`/api/indicators/equipment/${equipId}/failures?${relParams()}`);
    const data = await res.json();
    const ots = data.all_ots || [];
    el('relDetailTitle').textContent =
        `Fallas de ${label} — MTBF ${data.mtbf ?? '-'}h · MTTR ${data.mttr ?? '-'}h · Disp ${data.availability ?? '-'}% · Conf ${data.reliability ?? '-'}%`;
    el('relDetailTable').innerHTML =
        `<tr><th>OT</th><th>Tipo</th><th>Modo</th><th class="num">Parada (h)</th><th>Estado</th><th>Descripcion</th></tr>` +
        (ots.length ? ots.map(o =>
            `<tr><td style="color:#5AC8FA;font-weight:600">${o.code || 'OT-' + o.id}</td>` +
            `<td>${o.maintenance_type || '-'}</td><td>${o.failure_mode || '-'}</td>` +
            `<td class="num" style="color:${(o.downtime_hours_calc || 0) > 0 ? '#FF453A' : '#9ab0cb'}">${o.downtime_hours_calc || '-'}</td>` +
            `<td>${o.status}</td><td>${(o.description || '-').slice(0, 130)}</td></tr>`).join('')
         : `<tr><td colspan="6" style="color:#9ab0cb">Sin OTs cerradas del periodo para este equipo.</td></tr>`);
    openDetail('relDetail');
}

// ── S7: Salud del sistema ────────────────────────────────────────────────
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

// ── S8: Programacion (resto del mes + siguiente) ─────────────────────────
function progCards(pg, extraCard) {
    const cap = pg.capacidad;
    const utilCls = cap.utilizacion_pct == null ? '' :
        (cap.utilizacion_pct > 90 ? 'v-crit' : (cap.utilizacion_pct > 60 ? 'v-warn' : 'v-good'));
    return kpiCard('OTs programadas', pg.ots_programadas.length, '', extraCard || '') +
        kpiCard('Lubricaciones', pg.totales_rutinas.lubricacion, '', 'vencen en el periodo') +
        kpiCard('Inspecciones', pg.totales_rutinas.inspeccion, '', 'vencen en el periodo') +
        kpiCard('Megados', pg.totales_rutinas.megado, '', 'vencen en el periodo') +
        kpiCard('Capacidad', cap.horas_disponibles + ' h', '', `${cap.tecnicos} tecnicos x ${cap.dias_habiles} dias`) +
        kpiCard('Carga programada', cap.horas_programadas + ' h', utilCls, cap.utilizacion_pct != null ? cap.utilizacion_pct + '% de uso' : '');
}

function renderPrograma() {
    const pa = DIAG.programa_actual;
    const block = el('progActualBlock');
    if (pa) {
        block.style.display = 'block';
        el('progActualTitle').textContent = `Lo que queda de ${pa.label} (desde ${pa.desde}) — incluye rutinas vencidas arrastradas`;
        el('progActualStrip').innerHTML = progCards(pa);
    } else {
        block.style.display = 'none';
    }

    const pg = DIAG.programa;
    el('progNextTitle').textContent = `Mes siguiente: ${pg.label}`;
    el('progStrip').innerHTML = progCards(pg, `${pg.ots_sin_fecha} abiertas sin fecha por asignar`);

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
    const pa = DIAG.programa_actual;
    const pg = DIAG.programa;
    const paradas = pg.paradas_proximas || [];
    el('s9Title').textContent = pa
        ? `Detalle de OTs — resto de ${pa.label} y ${pg.label}`
        : `Detalle de OTs — ${pg.label}`;

    const head = `<tr><th>Fecha</th><th>OT</th><th>Equipo</th><th>Tipo</th><th class="num">Horas</th><th>Estado</th><th>Descripcion</th></tr>`;
    const rowsOf = list => list.map(o =>
        `<tr><td>${o.fecha || '-'}</td><td style="color:#5AC8FA;font-weight:600">${o.code}</td>` +
        `<td>${o.equipo}</td><td>${o.tipo}</td><td class="num">${o.horas || '-'}</td>` +
        `<td>${o.status}</td><td>${o.descripcion}</td></tr>`).join('');

    let html = head;
    if (pa) {
        html += `<tr><td colspan="7" style="color:#FF9F0A;font-weight:700">RESTO DE ${pa.label.toUpperCase()}</td></tr>`;
        html += pa.ots_programadas.length ? rowsOf(pa.ots_programadas)
            : `<tr><td colspan="7" style="color:#9ab0cb">Sin OTs con fecha en lo que queda del mes.</td></tr>`;
    }
    html += `<tr><td colspan="7" style="color:#30D158;font-weight:700;padding-top:12px">${pg.label.toUpperCase()}</td></tr>`;
    html += pg.ots_programadas.length ? rowsOf(pg.ots_programadas)
        : `<tr><td colspan="7" style="color:#9ab0cb">Aun no hay OTs con fecha en ${pg.label}. ` +
          `Programa el backlog (${pg.ots_sin_fecha} OTs sin fecha) desde Ordenes de Trabajo.</td></tr>`;
    if (paradas.length) {
        html += `<tr><td colspan="7" style="color:#FF9F0A;font-weight:700;padding-top:12px">PARADAS PROXIMAS (coordinar ventanas con produccion)</td></tr>`;
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
