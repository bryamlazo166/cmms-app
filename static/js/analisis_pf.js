// Ingenieria de Confiabilidad — curva P-F con datos reales del CMMS
let PF_CHART = null;
let EQUIPOS = [];

document.addEventListener('DOMContentLoaded', () => {
    reloadAll();
    window.addEventListener('resize', () => { if (PF_CHART) PF_CHART.resize(); });
});

function el(id) { return document.getElementById(id); }
function months() { return el('pfMonths').value; }

async function reloadAll() {
    await Promise.all([loadPrecursores(), loadEquipos()]);
}
window.reloadAll = reloadAll;

// ── Precursores ──────────────────────────────────────────────────────────
async function loadPrecursores() {
    try {
        const res = await fetch(`/api/pf/precursores?months=${months()}`);
        const data = await res.json();
        if (data.error) { console.error(data.error); return; }
        const r = data.resumen;
        el('ventanaTxt').textContent = r.ventana_dias;

        const pctCls = r.pct_con_senal >= 60 ? 'v-good' : (r.pct_con_senal >= 30 ? 'v-warn' : 'v-crit');
        el('precKpis').innerHTML =
            kpi('Fallas analizadas', r.fallas_analizadas, '') +
            kpi('Con señal previa', `${r.con_senal_previa} (${r.pct_con_senal}%)`, pctCls, 'detectables a tiempo') +
            kpi('Sin monitoreo previo', r.sin_monitoreo, r.sin_monitoreo > 0 ? 'v-crit' : 'v-good', 'equipos sin punto predictivo') +
            kpi('Intervalo P-F observado', r.intervalo_pf_promedio_dias != null ? r.intervalo_pf_promedio_dias + ' dias' : 'sin datos', '', 'anticipacion promedio de la señal');

        el('pfLectura').innerHTML = interpretacion(r);

        // Tabla detalle
        const rows = data.fallas || [];
        el('precTable').innerHTML =
            `<tr><th>Fecha</th><th>OT</th><th>Equipo</th><th>Modo de falla</th><th class="num">Parada (h)</th><th>Señal previa</th><th>Señales detectadas (fecha · tipo · detalle)</th></tr>` +
            (rows.length ? rows.map(f =>
                `<tr><td>${f.fecha}</td><td style="color:#5AC8FA;font-weight:600">${f.code}</td>` +
                `<td>${f.equipo}</td><td>${f.modo}</td>` +
                `<td class="num" style="color:${f.downtime_h > 0 ? '#FF453A' : '#9ab0cb'}">${f.downtime_h || '-'}</td>` +
                `<td>${f.senal_previa
                    ? `<span class="pill si">SI · ${f.anticipacion_dias} d antes</span>`
                    : (f.tenia_monitoreo ? `<span class="pill no">NO</span>` : `<span class="pill mon">SIN MONITOREO</span>`)}</td>` +
                `<td style="font-size:.78rem;color:#9ab0cb">${(f.senales || []).map(s => `${s.fecha} · ${s.tipo} · ${s.detalle}`).join('<br>') || '-'}</td></tr>`
            ).join('') : `<tr><td colspan="7" style="color:#9ab0cb">Sin fallas en el periodo.</td></tr>`);
    } catch (e) { console.error('loadPrecursores:', e); }
}

function kpi(label, value, cls, delta) {
    return `<div class="kpi-item"><div class="label">${label}</div>` +
           `<div class="value ${cls || ''}">${value}</div>` +
           (delta ? `<div class="delta">${delta}</div>` : '') + `</div>`;
}

function interpretacion(r) {
    const partes = [];
    if (r.fallas_analizadas === 0) return 'Sin fallas cerradas en el periodo seleccionado.';
    if (r.sin_monitoreo > 0) {
        partes.push(`<b>${r.sin_monitoreo}</b> fallas ocurrieron en equipos <b>sin ningun punto de monitoreo</b>: ` +
            `esa es la lista de puntos predictivos que conviene crear primero (ver detalle abajo, filas "SIN MONITOREO").`);
    }
    if (r.con_senal_previa > 0 && r.intervalo_pf_promedio_dias != null) {
        partes.push(`Cuando SI hubo señal, aparecio en promedio <b>${r.intervalo_pf_promedio_dias} dias antes</b> de la falla — ` +
            `esa es tu ventana real para planificar el trabajo en vez de correr: pedir repuesto, programar la parada y evitar el downtime no planificado.`);
        partes.push(`Regla practica: la frecuencia de inspeccion/medicion de cada punto debe ser <b>menor a la mitad del intervalo P-F</b> ` +
            `(aqui: medir al menos cada ${Math.max(1, Math.floor(r.intervalo_pf_promedio_dias / 2))} dias en los equipos criticos).`);
    } else {
        partes.push(`Todavia no hay suficientes mediciones predictivas para estimar el intervalo P-F: al registrar megados, ` +
            `corrientes y vibracion (modulos Motores Electricos y Monitoreo), este analisis se llena solo.`);
    }
    return partes.join('<br><br>');
}

// ── Timeline por equipo ──────────────────────────────────────────────────
async function loadEquipos() {
    try {
        const res = await fetch('/api/pf/equipos');
        EQUIPOS = await res.json();
        const sel = el('pfEquipo');
        sel.innerHTML = '';
        EQUIPOS.forEach(e => {
            const o = document.createElement('option');
            o.value = e.id;
            o.textContent = `[${e.tag || '-'}] ${e.name} — ${e.fallas} fallas · ${e.lecturas_monitoreo + e.tests_electricos} mediciones`;
            sel.appendChild(o);
        });
        if (EQUIPOS.length) loadTimeline();
    } catch (e) { console.error('loadEquipos:', e); }
}

async function loadTimeline() {
    const eqId = el('pfEquipo').value;
    if (!eqId) return;
    try {
        const res = await fetch(`/api/pf/timeline?equipment_id=${eqId}&months=${months()}`);
        const data = await res.json();
        if (data.error) { console.error(data.error); return; }
        renderTimeline(data);
        renderEventsTable(data);
    } catch (e) { console.error('loadTimeline:', e); }
}
window.loadTimeline = loadTimeline;

function renderTimeline(data) {
    const box = el('pfChart');
    if (!PF_CHART) PF_CHART = echarts.init(box);

    const series = [];
    const legends = [];
    const PALETA = ['#5AC8FA', '#BF5AF2', '#30D158', '#FFD60A', '#64D2FF', '#FF9F0A'];

    // Series de monitoreo con banda de alarma
    (data.monitoring_series || []).forEach((s, i) => {
        if (!s.readings.length) return;
        const name = `${s.tipo} ${s.code || ''} (${s.unit || ''})`;
        legends.push(name);
        const serie = {
            name, type: 'line',
            data: s.readings.map(r => [r.date, r.value]),
            itemStyle: { color: PALETA[i % PALETA.length] },
            lineStyle: { width: 2 }, symbolSize: 6, connectNulls: true,
        };
        const marks = [];
        if (s.alarm_max != null) marks.push({ yAxis: s.alarm_max, label: { formatter: `alarma ${s.alarm_max}`, color: '#FF453A' }, lineStyle: { color: '#FF453A', type: 'dashed' } });
        else if (s.normal_max != null) marks.push({ yAxis: s.normal_max, label: { formatter: `normal ${s.normal_max}`, color: '#FF9F0A' }, lineStyle: { color: '#FF9F0A', type: 'dashed' } });
        if (marks.length) serie.markLine = { silent: true, symbol: 'none', data: marks };
        series.push(serie);
    });

    // Tests electricos
    const elecColors = { MEGADO: '#BF5AF2', CORRIENTE: '#FFD60A', TEMPERATURA: '#FF9F0A' };
    Object.entries(data.electrical || {}).forEach(([tipo, pts]) => {
        if (!pts.length) return;
        const name = `Test ${tipo}`;
        legends.push(name);
        series.push({
            name, type: 'line', data: pts.map(p => [p.date, p.value]),
            itemStyle: { color: elecColors[tipo] }, lineStyle: { width: 2, type: 'dotted' }, symbolSize: 7,
        });
    });

    // Eventos como scatter en una banda inferior (valor 0 del eje derecho)
    const evSeries = [
        { name: 'FALLA', data: data.fallas, color: '#FF453A', symbol: 'triangle', size: 16,
          fmt: f => `<b>${f.code}</b> ${f.modo}<br>${f.descripcion}<br>Parada: ${f.downtime_h}h` },
        { name: 'Anomalia lubricacion', data: data.lubricacion_anomalias, color: '#FF9F0A', symbol: 'diamond', size: 12,
          fmt: e => `${e.tipo} en ${e.punto}<br>${e.comentario || ''}` },
        { name: 'Hallazgo inspeccion', data: data.inspeccion_hallazgos, color: '#5AC8FA', symbol: 'rect', size: 10,
          fmt: e => `Ruta ${e.ruta}: ${e.hallazgos} hallazgos<br>${e.comentario || ''}` },
    ];
    evSeries.forEach(ev => {
        if (!ev.data || !ev.data.length) return;
        legends.push(ev.name);
        series.push({
            name: ev.name, type: 'scatter', yAxisIndex: 1,
            data: ev.data.map(e => ({ value: [e.date, 1], _raw: e })),
            itemStyle: { color: ev.color }, symbol: ev.symbol, symbolSize: ev.size,
            tooltip: { formatter: p => `${p.marker} <b>${ev.name}</b> ${p.value[0]}<br>${ev.fmt(p.data._raw)}` },
        });
    });

    const eq = data.equipment;
    PF_CHART.clear();
    PF_CHART.setOption({
        backgroundColor: 'transparent',
        title: { text: `[${eq.tag || '-'}] ${eq.name} — desde ${data.desde}`, textStyle: { color: '#9ab0cb', fontSize: 13 } },
        tooltip: { trigger: 'item' },
        legend: { data: legends, textStyle: { color: '#9ab0cb' }, top: 22, type: 'scroll' },
        grid: { left: 55, right: 40, top: 60, bottom: 55 },
        xAxis: { type: 'time', axisLabel: { color: '#9ab0cb' } },
        yAxis: [
            { type: 'value', name: 'valor medido', axisLabel: { color: '#9ab0cb' }, splitLine: { lineStyle: { color: '#233246' } } },
            { type: 'value', min: 0, max: 8, show: false },
        ],
        dataZoom: [{ type: 'slider', bottom: 8, textStyle: { color: '#9ab0cb' } }],
        series: series.length ? series : [{ type: 'line', data: [] }],
    });

    if (!series.length) {
        PF_CHART.setOption({ title: { subtext: 'Este equipo aun no tiene mediciones ni eventos en el periodo. Registra lecturas de monitoreo o tests electricos para ver su curva P-F.', subtextStyle: { color: '#5a7aa0' } } });
    }
}

function renderEventsTable(data) {
    const rows = [];
    (data.fallas || []).forEach(f => rows.push({ fecha: f.date, tipo: '🔺 FALLA', detalle: `${f.code} · ${f.modo} · ${f.descripcion} · parada ${f.downtime_h}h` }));
    (data.lubricacion_anomalias || []).forEach(e => rows.push({ fecha: e.date, tipo: '🔶 LUBRICACION', detalle: `${e.tipo} en ${e.punto} ${e.comentario || ''}` }));
    (data.inspeccion_hallazgos || []).forEach(e => rows.push({ fecha: e.date, tipo: '🟦 INSPECCION', detalle: `Ruta ${e.ruta}: ${e.hallazgos} hallazgos ${e.comentario || ''}` }));
    rows.sort((a, b) => b.fecha.localeCompare(a.fecha));
    el('pfEventsTable').innerHTML =
        `<tr><th>Fecha</th><th>Evento</th><th>Detalle</th></tr>` +
        (rows.length ? rows.map(r => `<tr><td>${r.fecha}</td><td>${r.tipo}</td><td>${r.detalle}</td></tr>`).join('')
            : `<tr><td colspan="3" style="color:#9ab0cb">Sin eventos registrados en el periodo para este equipo.</td></tr>`);
}
