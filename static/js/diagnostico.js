// Diagnostico Mensual de Gestion — datos en vivo + narrativa IA + drill-down + modo presentacion
let DIAG = null;
let PERIODOS = null;   // atajos de periodo que calcula el servidor
const CHARTS = {};
let REL = { level: 'areas', areaId: null, areaName: '', equipId: null, equipName: '' };

document.addEventListener('DOMContentLoaded', async () => {
    await cargarPeriodos();
    loadDiagnostico();
    window.addEventListener('resize', () => Object.values(CHARTS).forEach(c => c && c.resize()));
    document.addEventListener('keydown', onPresentKeys);
});

// ── Periodo analizado ────────────────────────────────────────────────────
// Por defecto se abre en el ultimo mes CON DATOS: el mes en curso suele
// tener dos dias cargados y no sirve para presentar a gerencia.
async function cargarPeriodos() {
    try {
        PERIODOS = await (await fetch('/api/diagnostico/periodos')).json();
        const sel = el('diagPreset');
        if (PERIODOS.ultimo_con_datos_label) {
            sel.options[0].textContent = `Último mes cerrado con datos (${PERIODOS.ultimo_con_datos_label})`;
        }
        sel.options[1].textContent = `Mes anterior (${PERIODOS.ultimo_mes_label})`;
        sel.options[2].textContent = `Mes en curso (${PERIODOS.mes_actual_label})`;
        el('diagMonth').value = PERIODOS.ultimo_con_datos || PERIODOS.mes_actual;
        el('diagDesde').value = PERIODOS.ultimos_30.desde;
        el('diagHasta').value = PERIODOS.ultimos_30.hasta;
    } catch (e) { console.error('periodos:', e); }
}

function onPresetChange() {
    const v = el('diagPreset').value;
    el('diagMonth').style.display = (v === 'mes') ? '' : 'none';
    el('rangoBox').style.display = (v === 'rango') ? 'inline-flex' : 'none';
    if (v !== 'rango') loadDiagnostico();
}
window.onPresetChange = onPresetChange;

// Devuelve el query string del periodo elegido
function periodoQuery() {
    const v = el('diagPreset').value;
    const P = PERIODOS || {};
    const rango = (r) => new URLSearchParams({ desde: r.desde, hasta: r.hasta }).toString();
    switch (v) {
        case 'ultimo_datos': return `month=${P.ultimo_con_datos || el('diagMonth').value}`;
        case 'ultimo_mes': return `month=${P.ultimo_mes}`;
        case 'mes_actual': return `month=${P.mes_actual}`;
        case 'mes': return `month=${el('diagMonth').value}`;
        case 'ultimos_30': return rango(P.ultimos_30);
        case 'ultimos_90': return rango(P.ultimos_90);
        case 'anio_actual': return rango(P.anio_actual);
        case 'rango': {
            const d = el('diagDesde').value, h = el('diagHasta').value;
            if (!d || !h) { alert('Elige la fecha de inicio y la de fin.'); return null; }
            if (d > h) { alert('La fecha de inicio no puede ser posterior a la de fin.'); return null; }
            return rango({ desde: d, hasta: h });
        }
        default: return `month=${el('diagMonth').value}`;
    }
}

async function loadDiagnostico() {
    const q = periodoQuery();
    if (q === null) return;
    try {
        const res = await fetch(`/api/diagnostico/data?${q}`);
        DIAG = await res.json();
        if (DIAG.error) { alert('Error: ' + DIAG.error); return; }
        const m = DIAG.meta;
        document.getElementById('genAt').textContent = `generado ${m.generated_at}`;
        document.getElementById('s1Title').textContent =
            `Resumen de ${m.label}` + (m.en_curso ? ' (periodo en curso)' : '');
        document.getElementById('s1Method').textContent = m.en_curso
            ? `Periodo en curso: KPIs parciales con ${m.dias} de ${m.dias_nominales} dias transcurridos, comparados con ${m.prev_label}. Benchmarks SMRP: cumplimiento >90%, proactivo >75%.`
            : `Indicadores de ${m.label} (${m.dias} dias) vs. ${m.prev_label}. Benchmarks SMRP: cumplimiento >90%, proactivo >75%.`;
        renderPortada();
        renderKpis();
        renderProduccion();
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
        ['paretoDetail', 'equiposDetail', 'relDetail', 'prodDetail', 'semDetail', 'trendDetail']
            .forEach(closeDetail);
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
    // Ventana real del periodo analizado (mes completo o rango libre)
    const m = DIAG.meta;
    const hoy = (PERIODOS && PERIODOS.hoy) || new Date().toISOString().slice(0, 10);
    return { start: m.desde, end: m.hasta > hoy ? hoy : m.hasta };
}
function nf(x, d) {
    if (x == null) return '—';
    return Number(x).toLocaleString('es-PE', { maximumFractionDigits: d == null ? 1 : d });
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

const OTS_COLS = `<tr><th>OT</th><th>Fecha</th><th>Equipo</th><th>Tipo</th><th>Modo de falla</th><th>Estado</th><th class="num">Parada (h)</th><th class="num">Durac. (h)</th><th>Descripcion / Trabajo realizado</th></tr>`;
function otsRows(rows) {
    if (!rows.length) return `<tr><td colspan="9" style="color:#9ab0cb">Sin OTs en esta seleccion.</td></tr>`;
    return rows.map(r =>
        `<tr><td style="color:#5AC8FA;font-weight:600">${r.code}</td><td>${r.fecha}</td>` +
        `<td>${r.equipo}</td><td>${r.tipo || '-'}</td><td>${r.modo}</td><td>${r.status}</td>` +
        `<td class="num" style="color:${r.downtime_h > 0 ? '#FF453A' : '#9ab0cb'}">${r.downtime_h || '-'}</td>` +
        `<td class="num">${r.duracion_h || '-'}</td>` +
        `<td>${r.descripcion}${r.ejecucion ? `<div style="color:#30D158;font-size:.76rem">✔ ${r.ejecucion}</div>` : ''}</td></tr>`
    ).join('');
}
// Version con impacto en produccion (TM y sacos por OT)
const OTS_COLS_PROD = `<tr><th>OT</th><th>Fecha</th><th>Equipo</th><th>Tipo</th><th>Modo de falla</th><th class="num">Parada (h)</th><th class="num">TM perdidas</th><th class="num">Sacos (50kg)</th><th>Descripcion / Trabajo realizado</th></tr>`;
function otsRowsProd(rows) {
    if (!rows.length) return `<tr><td colspan="9" style="color:#9ab0cb">Sin OTs en esta seleccion.</td></tr>`;
    return rows.map(r =>
        `<tr><td style="color:#5AC8FA;font-weight:600">${r.code}</td><td>${r.fecha}</td>` +
        `<td>${r.equipo}</td><td>${r.tipo || '-'}</td><td>${r.modo}</td>` +
        `<td class="num" style="color:${r.downtime_h > 0 ? '#FF453A' : '#9ab0cb'}">${r.downtime_h || '-'}</td>` +
        `<td class="num" style="color:#FF9F0A;font-weight:700">${r.tons_lost ?? '-'}</td>` +
        `<td class="num">${r.sacks_lost != null ? r.sacks_lost.toLocaleString() : '-'}</td>` +
        `<td>${r.descripcion}${r.ejecucion ? `<div style="color:#30D158;font-size:.76rem">✔ ${r.ejecucion}</div>` : ''}</td></tr>`
    ).join('');
}
async function fetchOtsDetail(params) {
    const q = new URLSearchParams({ month: DIAG.meta.month, ...params });
    const res = await fetch(`/api/diagnostico/ots-detail?${q}`);
    return res.json();
}
// Panel de detalle generico: llena <panel>Title y <panel>Table y lo abre
async function showOtsPanel(panel, title, params) {
    el(panel + 'Title').textContent = title;
    el(panel + 'Table').innerHTML = `<tr><td style="color:#9ab0cb">Cargando...</td></tr>`;
    openDetail(panel);
    const d = await fetchOtsDetail(params);
    if (d.error) { el(panel + 'Table').innerHTML = `<tr><td style="color:#FF453A">${d.error}</td></tr>`; return; }
    const prod = params.tons === '1';
    el(panel + 'Table').innerHTML = (prod ? OTS_COLS_PROD : OTS_COLS) +
        (prod ? otsRowsProd(d.rows || []) : otsRows(d.rows || []));
}
// Serie del grafico -> filtro tipo del backend
const TIPO_SERIE = { 'Correctivas': 'correctivo', 'Proactivas': 'proactivo', 'Mejoras': 'mejora', '% Proactivo': 'proactivo' };

// ── S0: Portada — el veredicto del periodo ───────────────────────────────
function renderPortada() {
    const po = DIAG.portada;
    if (!po) return;
    el('portPeriodo').textContent =
        `Diagnóstico de gestión · ${po.periodo}` + (po.en_curso ? ' · periodo en curso' : '');
    el('portTitular').textContent = po.titular;
    el('portSub').textContent = po.subtitulo;
    const v = el('portVeredicto');
    v.textContent = po.veredicto;
    v.className = `veredicto ${po.color}`;

    el('portCifras').innerHTML = (po.cifras || []).map(c => {
        let dl = '';
        if (c.delta && c.delta.valor) {
            const col = c.delta.mejor ? '#30D158' : '#FF453A';
            const flecha = c.delta.valor > 0 ? '▲' : '▼';
            dl = `<div class="dl" style="color:${col}">${flecha} ${Math.abs(c.delta.valor)}${c.delta.unidad} vs periodo anterior</div>`;
        }
        return `<div class="port-cifra ${c.estado || 'neutro'}">
            <div class="l">${c.label}</div>
            <div class="v">${c.valor == null ? '—' : nf(c.valor)}<small>${c.valor == null ? '' : c.unidad}</small></div>
            <div class="p">${c.pie || ''}</div>${dl}</div>`;
    }).join('');

    el('portHechos').innerHTML = (po.hechos || []).map(h => `<li>${h}</li>`).join('')
        || '<li style="color:#9ab0cb">Sin hallazgos relevantes en el periodo.</li>';
    el('portAcciones').innerHTML = (po.acciones || []).map(a => `<li>${a}</li>`).join('')
        || '<li style="color:#9ab0cb">Sin acciones críticas pendientes.</li>';

    // Avisos que afectan la lectura de las cifras: no se ocultan
    const pr = DIAG.produccion || {};
    const avisos = [];
    if (pr.disponible && pr.utilizacion_pct != null) {
        if (pr.utilizacion_pct > 100) {
            avisos.push(`<i class="fas fa-triangle-exclamation"></i> <b>La capacidad configurada ` +
                `(${nf(pr.capacidad.harina_tm_dia)} TM/día = ${nf(pr.capacidad.harina_tm_dia * 30.4, 0)} TM/mes) ` +
                `es menor que la producción registrada (${nf(pr.produccion_real_tons, 0)} TM/mes)</b>. ` +
                `Revisa en Alcance de Indicadores el % de llenado, las llenadas por día o el rendimiento: ` +
                `si la capacidad queda corta, las toneladas perdidas salen infladas.`);
        } else {
            avisos.push(`<i class="fas fa-circle-info"></i> La planta puede procesar ` +
                `<b>${nf(pr.capacidad.harina_tm_dia)} TM/día</b> de harina con ` +
                `${pr.capacidad.operativos} digestores operativos. La producción registrada ` +
                `(${nf(pr.produccion_real_tons, 0)} TM/mes) es el <b>${pr.utilizacion_pct}%</b> de esa capacidad: ` +
                `las toneladas perdidas están valoradas a capacidad instalada.`);
        }
    }
    if (pr.disponible && (pr.auxiliares || {}).ots) {
        avisos.push(`<i class="fas fa-gears"></i> Solo restan toneladas los equipos donde se ` +
            `transforma el producto (digestores, secadores y molinos). Las ` +
            `<b>${pr.auxiliares.ots} OTs con ${nf(pr.auxiliares.horas)} h de parada</b> de los ` +
            `${pr.auxiliares.equipos_distintos} equipos auxiliares — transportadores, ciclones, ` +
            `percoladores, fajas — están en los indicadores de mantenimiento pero no en estas toneladas.`);
    }
    if (pr.disponible && (pr.sin_capacidad || {}).ots) {
        avisos.push(`<i class="fas fa-triangle-exclamation"></i> <b>${pr.sin_capacidad.ots} OTs ` +
            `con ${nf(pr.sin_capacidad.horas)} h de parada no suman toneladas</b> porque su equipo ` +
            `produce pero no tiene capacidad configurada${pr.sin_capacidad.equipos.length ? ' (' + pr.sin_capacidad.equipos.join(', ') + ')' : ' o la OT no tiene equipo asignado'}. ` +
            `Complétala en Alcance de Indicadores.`);
    }
    if (pr.disponible && (pr.paradas_largas || []).length) {
        avisos.push(`<i class="fas fa-stopwatch"></i> <b>Verificar paradas largas:</b> ` +
            pr.paradas_largas.map(x => `${x.code} ${x.equipo} ${x.dias} días (${x.desde} → ${x.hasta})`).join(' · ') +
            `. Si se registró el tiempo transcurrido en vez del tiempo detenido, las toneladas salen infladas.`);
    }
    if (pr.techo_aplicado) {
        avisos.push(`<i class="fas fa-scale-balanced"></i> Las horas de parada registradas superaban ` +
            `la capacidad instalada del periodo: la pérdida se limitó al máximo físico posible.`);
    }
    el('portAvisos').innerHTML = avisos.map(a => `<div class="port-aviso">${a}</div>`).join('');
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
        kpiCard('MTBF (h)', k.mtbf_h ?? '-', '', deltaTxt(k.mtbf_h, p.mtbf_h, 'h'), 'goToSlide(8)') +
        kpiCard('MTTR (h)', k.mttr_h ?? '-', '', deltaTxt(k.mttr_h, p.mttr_h, 'h', true), 'goToSlide(8)') +
        kpiCard('Disponibilidad', (k.disponibilidad_pct ?? '-') + '%', dispCls, deltaTxt(k.disponibilidad_pct, p.disponibilidad_pct, ' pts'), 'goToSlide(8)') +
        kpiCard('Confiabilidad R(7d)', k.confiabilidad_pct != null ? k.confiabilidad_pct + '%' : '-', '', deltaTxt(k.confiabilidad_pct, p.confiabilidad_pct, ' pts'), 'goToSlide(8)');
}

// ── S2: Impacto en Produccion (TM y sacos de harina no producidos) ───────
function renderProduccion() {
    const pr = DIAG.produccion || {};
    const slide = el('prodSlide');
    if (!pr.disponible) {
        if (slide) slide.querySelector('.kpi-strip').innerHTML =
            kpiCard('Sin capacidad configurada', '-', '',
                pr.motivo || 'Registra la capacidad de los equipos en Alcance de Indicadores');
        return;
    }
    el('prodTitle').textContent = `Impacto del mantenimiento en la produccion — ${DIAG.meta.label}`;
    const deltaTons = deltaTxt(pr.tons_lost_mes, pr.tons_lost_prev, ' TM', true);
    const pctCls = pr.pct_de_capacidad == null ? '' :
        (pr.pct_de_capacidad <= 2 ? 'v-good' : (pr.pct_de_capacidad <= 5 ? 'v-warn' : 'v-crit'));
    el('prodStripKpis').innerHTML =
        kpiCard('TM de harina no producidas', nf(pr.tons_lost_mes), pr.tons_lost_mes > pr.tons_lost_prev ? 'v-crit' : 'v-good', deltaTons) +
        kpiCard('Sacos de 50 kg', pr.sacks_lost_mes.toLocaleString('es-PE'), '', 'harina que no llego a ensacarse') +
        kpiCard('Materia prima sin cocinar', nf(pr.tons_mp_lost_mes) + ' TM', '', `por los digestores parados · ${nf(pr.horas_paro)} h en total`) +
        kpiCard('% de la capacidad del periodo', pr.pct_de_capacidad != null ? pr.pct_de_capacidad + '%' : '-', pctCls,
            `capacidad: ${nf(pr.capacidad_periodo_tons, 0)} TM en ${pr.dias} dias`) +
        kpiCard('TM perdidas 12 meses', nf(pr.tons_lost_12m), '', `${pr.sacks_lost_12m.toLocaleString('es-PE')} sacos acumulados`);

    // Avisos de la lamina (mismos que la portada, en corto)
    const av = [];
    if ((pr.auxiliares || {}).ots) {
        av.push(`${pr.auxiliares.ots} OTs con ${nf(pr.auxiliares.horas)} h de parada en ` +
            `${pr.auxiliares.equipos_distintos} equipos auxiliares (transportadores, ciclones, fajas): ` +
            `no restan toneladas porque no es donde se produce la harina.`);
    }
    if ((pr.sin_capacidad || {}).ots) {
        av.push(`${pr.sin_capacidad.ots} OTs con ${nf(pr.sin_capacidad.horas)} h de parada no suman toneladas: ` +
            `su equipo produce pero no tiene capacidad configurada en Alcance de Indicadores.`);
    }
    if ((pr.paradas_largas || []).length) {
        av.push(`Paradas de mas de 3 dias a verificar: ` +
            pr.paradas_largas.map(x => `${x.code} ${x.equipo} (${x.dias} d)`).join(' · '));
    }
    el('prodAvisos').innerHTML = av.length
        ? `<div style="background:rgba(255,159,10,.09);border:1px solid rgba(255,159,10,.34);border-radius:8px;padding:9px 13px;color:#FF9F0A;font-size:.82rem;margin:4px 0 12px;">`
          + av.map(a => `<div>${a}</div>`).join('') + `</div>`
        : '';

    const s = pr.serie || [];
    chart('prodSerieChart').setOption({
        backgroundColor: 'transparent',
        title: { text: 'TM no producidas por mes', textStyle: { color: '#9ab0cb', fontSize: 13 } },
        tooltip: { trigger: 'axis', formatter: ps => {
            const it = s[ps[0].dataIndex];
            return `<b>${it.month}</b><br/>TM perdidas: ${it.tons_lost}<br/>Sacos (50kg): ${it.sacks_lost.toLocaleString()}`;
        } },
        grid: { left: 55, right: 20, top: 40, bottom: 30 },
        xAxis: { type: 'category', data: s.map(x => x.month), axisLabel: { color: '#9ab0cb', fontSize: 10 } },
        yAxis: { type: 'value', name: 'TM', axisLabel: { color: '#9ab0cb' }, splitLine: { lineStyle: { color: '#233246' } } },
        series: [{
            name: 'TM perdidas', type: 'bar', data: s.map(x => x.tons_lost),
            itemStyle: { color: '#FF9F0A', borderRadius: [4, 4, 0, 0] }, barMaxWidth: 30,
            label: { show: true, position: 'top', color: '#d5e2f5', fontSize: 9 },
        }],
    });

    const te = (pr.top_equipos || []).slice().reverse();
    const cte = chart('prodEquiposChart');
    cte.setOption({
        backgroundColor: 'transparent',
        title: { text: 'Top equipos por TM perdidas (mes)', textStyle: { color: '#9ab0cb', fontSize: 13 } },
        tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' },
            formatter: ps => { const t = te[ps[0].dataIndex]; return `<b>${t.equipo}</b><br/>${t.tons_lost} TM · ${t.sacks_lost.toLocaleString()} sacos<br/><i>Clic para ver las OTs</i>`; } },
        grid: { left: 170, right: 50, top: 40, bottom: 30 },
        xAxis: { type: 'value', axisLabel: { color: '#9ab0cb' }, splitLine: { lineStyle: { color: '#233246' } } },
        yAxis: { type: 'category', data: te.map(t => t.equipo), axisLabel: { color: '#d5e2f5', width: 155, overflow: 'truncate', fontSize: 10 } },
        series: [{
            name: 'TM', type: 'bar', data: te.map(t => t.tons_lost),
            itemStyle: { color: '#FF453A' },
            label: { show: true, position: 'right', color: '#d5e2f5', fontSize: 10, formatter: '{c} TM' },
        }],
    });
    cte.off('click');
    cte.on('click', ev => {
        const t = te[ev.dataIndex];
        if (!t) return;
        const params = { window: 'mes', tipo: 'todas', con_downtime: '1', tons: '1' };
        if (t.equipment_id) params.equipment_id = t.equipment_id; else params.sin_equipo = '1';
        showOtsPanel('prodDetail',
            `OTs con paro de ${t.equipo} — ${DIAG.meta.label} (${t.tons_lost} TM · ${t.sacks_lost.toLocaleString()} sacos)`,
            params);
    });

    // Las tres etapas en serie: la planta saca lo que permita la mas corta
    const cap = pr.capacidad || {};
    const et = cap.etapas || [];
    el('prodEtapas').innerHTML = !et.length ? '' :
        `<div class="etapas">` + et.map((e, i) =>
            `<div class="etapa ${e.cuello_botella ? 'cuello' : ''}">
                <div class="et-nom">${e.etapa}</div>
                <div class="et-rol">${e.rol}</div>
                <div class="et-val">${nf(e.tm_dia)}<small> TM/día</small></div>
                <div class="et-pie">${e.operativos} de ${e.equipos} operativos` +
                (e.fuera_servicio.length ? ` · fuera: ${e.fuera_servicio.join(', ')}` : '') +
                `</div>${e.cuello_botella ? '<div class="et-tag">marca el ritmo</div>' : ''}
            </div>` + (i < et.length - 1 ? '<div class="et-flecha">→</div>' : '')
        ).join('') + `</div>`;

    const dig = cap.digestores || [];
    el('prodCapTable').innerHTML =
        `<tr><th>Equipo</th><th class="num">kg por llenada</th><th class="num">% llenado</th>` +
        `<th class="num">Llenadas/dia</th><th class="num">TM/dia</th><th class="num">TM/h</th><th>Estado</th></tr>` +
        (dig.length ? dig.map(d =>
            `<tr style="${d.en_servicio ? '' : 'opacity:.55'}"><td><b>${d.tag}</b> ${d.nombre}</td>` +
            `<td class="num">${d.kg_llenada.toLocaleString('es-PE')}</td>` +
            `<td class="num">${d.fill_pct}%</td><td class="num">${d.llenadas_dia}</td>` +
            `<td class="num" style="color:#5AC8FA;font-weight:700">${nf(d.tm_dia, 2)}</td>` +
            `<td class="num">${nf(d.tm_hora, 3)}</td>` +
            `<td>${d.en_servicio ? '<span style="color:#30D158">Operativo</span>'
                : `<span style="color:#FF453A">Fuera de servicio</span> <span style="color:#5a7aa0;font-size:.74rem">${d.motivo || ''}</span>`}</td></tr>`).join('')
            : '') +
        `<tr style="border-top:2px solid #344964"><td colspan="4" style="text-align:right"><b>Materia prima que entra a coccion</b></td>` +
        `<td class="num" style="color:#30D158;font-weight:700">${nf(cap.planta_tm_dia)}</td>` +
        `<td class="num" style="color:#30D158;font-weight:700">${nf(cap.planta_tm_hora, 3)}</td>` +
        `<td>${cap.operativos} digestores operativos</td></tr>` +
        `<tr><td colspan="4" style="text-align:right"><b>Con rendimiento ${cap.rendimiento_pct}% → harina generada</b></td>` +
        `<td class="num" style="color:#FF9F0A;font-weight:700">${nf(cap.harina_tm_dia)}</td>` +
        `<td class="num">${nf(cap.harina_tm_hora, 3)}</td>` +
        `<td>${nf(pr.capacidad_periodo_tons, 0)} TM en el periodo</td></tr>` +
        // Secadores y molinos: procesan la harina que ya salio de coccion
        `<tr><td colspan="7" style="padding-top:12px;color:#9ab0cb;font-size:.78rem">` +
        `<b>Equipos que PROCESAN esa harina</b> — su capacidad ya esta en harina, no se le vuelve a aplicar el rendimiento</td></tr>` +
        ((cap.productivos || []).filter(p => !p.por_lotes).map(p =>
            `<tr style="opacity:.9"><td><b>${p.tag}</b> ${p.nombre} <span style="color:#5a7aa0;font-size:.74rem">(${p.etapa})</span></td>` +
            `<td class="num" colspan="3" style="color:#5a7aa0;font-size:.76rem">procesa harina, no trabaja por lotes</td>` +
            `<td class="num" style="color:#5AC8FA;font-weight:700">${nf(p.harina_tm_dia, 2)}</td>` +
            `<td class="num">${nf(p.tm_hora, 3)}</td>` +
            `<td>${p.en_servicio ? '<span style="color:#30D158">Operativo</span>' : '<span style="color:#FF453A">Fuera de servicio</span>'}</td></tr>`).join(''));

    // Perdida por area
    const areas = pr.por_area || [];
    el('prodMetasTable').innerHTML =
        `<tr><th>Area</th><th class="num">Equipos que pararon</th><th class="num">OTs con paro</th>` +
        `<th class="num">Horas de parada</th><th class="num">Materia prima (TM)</th>` +
        `<th class="num">TM no producidas</th><th class="num">Sacos (50kg)</th>` +
        `<th class="num">% de la capacidad</th><th class="num">% del total perdido</th></tr>` +
        (areas.length ? areas.map(a =>
            `<tr><td><b>${a.area}</b></td>` +
            `<td class="num">${a.equipos}</td>` +
            `<td class="num">${a.ots}</td><td class="num">${nf(a.horas_paro)}</td>` +
            `<td class="num">${nf(a.tons_mp_lost)}</td>` +
            `<td class="num" style="color:${a.tons_lost > 0 ? '#FF453A' : '#30D158'};font-weight:700">${nf(a.tons_lost)}</td>` +
            `<td class="num">${a.sacks_lost.toLocaleString('es-PE')}</td>` +
            `<td class="num">${a.pct_de_capacidad != null ? a.pct_de_capacidad + '%' : '-'}</td>` +
            `<td class="num">${pr.tons_lost_mes ? Math.round(a.tons_lost / pr.tons_lost_mes * 100) + '%' : '-'}</td></tr>`).join('')
        : `<tr><td colspan="9" style="color:#9ab0cb">Sin paradas con impacto en el periodo.</td></tr>`);
}

// ── S3: Indicadores por semana del mes ───────────────────────────────────
function weekRange(x) {
    // El backend ya entrega las fechas exactas de cada bloque semanal
    return { desde: x.desde, hasta: x.hasta };
}

function renderSemanas() {
    const s = DIAG.semanas || [];
    el('semTitle').textContent = `Indicadores semana a semana — ${DIAG.meta.label}`;
    const labels = s.map(x => `${x.semana} (${x.rango})`);

    const cMix = chart('semMixChart');
    cMix.setOption({
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
    // Filtro dinamico: clic en una barra -> OTs de ese tipo en esa semana
    cMix.off('click');
    cMix.on('click', ev => {
        const x = s[ev.dataIndex];
        if (!x) return;
        const tipo = TIPO_SERIE[ev.seriesName] || 'todas';
        const { desde, hasta } = weekRange(x);
        showOtsPanel('semDetail',
            `OTs ${ev.seriesName.toLowerCase()} — ${x.semana} (${x.rango} de ${DIAG.meta.label})`,
            { tipo, desde, hasta });
    });

    const cKpi = chart('semKpiChart');
    cKpi.setOption({
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
    // Downtime/Disponibilidad -> OTs que causaron el paro; Cumplimiento -> lo programado
    cKpi.off('click');
    cKpi.on('click', ev => {
        const x = s[ev.dataIndex];
        if (!x) return;
        const { desde, hasta } = weekRange(x);
        if (ev.seriesName === 'Cumplimiento %') {
            showOtsPanel('semDetail',
                `OTs programadas — ${x.semana} (${x.rango} de ${DIAG.meta.label}) · cumplimiento ${x.cumplimiento_pct ?? '-'}%`,
                { programadas: '1', tipo: 'todas', desde, hasta });
        } else {
            showOtsPanel('semDetail',
                `OTs que causaron el downtime — ${x.semana} (${x.rango} de ${DIAG.meta.label}) · ${x.downtime_h} h`,
                { tipo: 'todas', con_downtime: '1', desde, hasta });
        }
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
        fila('Horas de parada', x => x.downtime_h) +
        fila('TM no producidas', x => x.tons_lost) +
        (s.some(x => x.futura) ? `<tr><td colspan="${s.length + 1}" style="color:#5a7aa0;font-size:.72rem">* bloque aun no transcurrido</td></tr>` : '');
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
    const c = chart('trendChart');
    c.setOption({
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
    // Clic en una barra -> OTs de ese tipo en ese mes
    c.off('click');
    c.on('click', ev => {
        const x = t[ev.dataIndex];
        if (!x) return;
        const tipo = TIPO_SERIE[ev.seriesName] || 'todas';
        showOtsPanel('trendDetail',
            `OTs ${ev.seriesName.toLowerCase()} — ${x.label || x.month}`,
            { month: x.month, window: 'mes', tipo });
    });
}

function renderTrendKpi() {
    const t = DIAG.trend;
    const c = chart('trendKpiChart');
    c.setOption({
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
    // Clic en cualquier punto -> OTs que causaron el downtime de ese mes
    c.off('click');
    c.on('click', ev => {
        const x = t[ev.dataIndex];
        if (!x) return;
        showOtsPanel('trendDetail',
            `OTs que causaron el downtime — ${x.label || x.month} (${x.downtime_h} h)`,
            { month: x.month, window: 'mes', tipo: 'todas', con_downtime: '1' });
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
// Evolucion mensual del alcance visible en el drill-down (planta/area/equipo)
async function loadEvolucion(params, etiqueta) {
    try {
        const q = new URLSearchParams({ month: DIAG.meta.month, months: 12, ...(params || {}) });
        const res = await fetch(`/api/diagnostico/evolucion?${q}`);
        const data = await safeJson(res);
        if (data.error) { console.error(data.error); return; }
        const s = data.serie || [];
        el('relEvoTitle').textContent = `Evolucion mensual — ${data.alcance || etiqueta || 'Planta completa'}`;
        chart('relEvoChart').setOption({
            backgroundColor: 'transparent',
            tooltip: { trigger: 'axis' },
            legend: { textStyle: { color: '#9ab0cb' }, top: 0, right: 0 },
            grid: { left: 50, right: 55, top: 34, bottom: 28 },
            xAxis: { type: 'category', data: s.map(x => x.month + (x.en_curso ? '*' : '')), axisLabel: { color: '#9ab0cb', fontSize: 10 } },
            yAxis: [
                { type: 'value', name: '% / h', axisLabel: { color: '#9ab0cb' }, splitLine: { lineStyle: { color: '#233246' } } },
                { type: 'value', name: 'fallas / TM', axisLabel: { color: '#9ab0cb' }, splitLine: { show: false } },
            ],
            series: [
                { name: 'Disponibilidad %', type: 'line', data: s.map(x => x.disponibilidad_pct), itemStyle: { color: '#30D158' }, lineStyle: { width: 3 }, areaStyle: { opacity: .07 } },
                { name: 'MTTR h', type: 'line', data: s.map(x => x.mttr_h), itemStyle: { color: '#FF9F0A' }, connectNulls: true },
                { name: 'Fallas', type: 'bar', yAxisIndex: 1, data: s.map(x => x.fallas), itemStyle: { color: '#FF453A', opacity: .5 }, barMaxWidth: 18 },
                { name: 'TM no producidas', type: 'line', yAxisIndex: 1, data: s.map(x => x.tons_lost), itemStyle: { color: '#5AC8FA' }, lineStyle: { type: 'dashed' }, connectNulls: true },
            ],
        }, true);
    } catch (e) { console.error('loadEvolucion:', e); }
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
            loadEvolucion({}, 'Planta completa');
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
            loadEvolucion({ area_id: id }, name);
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
    loadEvolucion({ equipment_id: equipId }, label);
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

// ── Narrativa IA (asincrona: el POST devuelve un job y se consulta) ──────
async function safeJson(res) {
    const text = await res.text();
    try { return JSON.parse(text); }
    catch (_) {
        throw new Error(`el servidor respondio HTTP ${res.status} con contenido no valido ` +
            `(posible timeout o sesion expirada). Intenta de nuevo.`);
    }
}

let NARR_JOB = null;  // ultimo job de narrativa terminado OK (se incrusta en el informe)

const NARR_ESPERA_MAX_MS = 20 * 60 * 1000;   // 20 min: la IA redacta 700-1000 palabras
const NARR_FALLOS_SEGUIDOS = 8;              // ~24 s sin poder leer el estado

async function generarNarrativa() {
    if (!DIAG) return;
    const box = el('narrativaBox');
    box.textContent = 'Generando analisis ejecutivo con IA...';
    try {
        const res = await fetch('/api/diagnostico/narrativa', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(DIAG),
        });
        const data = await safeJson(res);
        if (data.error) { box.textContent = 'Error: ' + data.error; return; }
        // Analisis ya hecho de este mismo periodo: se devuelve al instante
        if (data.narrativa) {
            box.textContent = data.narrativa;
            if (data.job_id) NARR_JOB = data.job_id;
            return;
        }

        const jobId = data.job_id;
        const estimado = data.espera_estimada_s || 120;
        const inicio = Date.now();
        let fallos = 0;

        while (Date.now() - inicio < NARR_ESPERA_MAX_MS) {
            await new Promise(r => setTimeout(r, 3000));
            const seg = Math.round((Date.now() - inicio) / 1000);
            box.textContent = `Generando analisis ejecutivo con IA... ${seg}s de ` +
                `~${estimado}s estimados. Puedes seguir usando el diagnostico: ` +
                `el analisis sigue corriendo en el servidor.`;

            let st;
            try {
                st = await safeJson(await fetch(`/api/diagnostico/narrativa/${jobId}`));
                fallos = 0;
            } catch (_) {
                // Antes se reintentaba en silencio para siempre y el usuario
                // acababa viendo solo "tardo demasiado". Si el servidor deja
                // de responder JSON (sesion caida, reinicio), se dice.
                if (++fallos >= NARR_FALLOS_SEGUIDOS) {
                    box.textContent = 'Se perdio la conexion con el servidor mientras se ' +
                        'generaba el analisis (puede ser la sesion expirada). Recarga la ' +
                        'pagina e intenta de nuevo: si el analisis alcanzo a terminar, ' +
                        'saldra al instante.';
                    return;
                }
                continue;
            }
            if (st.status === 'OK') {
                box.textContent = st.narrativa;
                NARR_JOB = jobId;
                return;
            }
            if (st.status === 'ERROR') { box.textContent = 'Error: ' + st.error; return; }
            if (st.error) { box.textContent = 'Error: ' + st.error; return; }
        }
        // Se agoto la espera del navegador, pero el trabajo sigue vivo en el
        // servidor: al volver a pulsar se recupera sin repetir la generacion.
        box.textContent = 'El analisis sigue generandose en el servidor (lleva mas de 20 ' +
            'minutos). Vuelve a pulsar "Narrativa IA" en un momento para recogerlo, o ' +
            'elige un periodo mas corto.';
    } catch (e) { box.textContent = 'Error generando narrativa: ' + e.message; }
}
window.generarNarrativa = generarNarrativa;

// ── Informe HTML descargable (plantilla ejecutiva, se abre sin conexion) ─
function descargarInforme() {
    const q = periodoQuery();
    if (q === null) return;
    let url = `/api/diagnostico/informe?${q}&download=1`;
    if (NARR_JOB) url += `&narrativa_job=${NARR_JOB}`;  // incluye la narrativa ya generada
    window.location.href = url;
}
window.descargarInforme = descargarInforme;

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
