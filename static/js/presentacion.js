// Indicadores Mensuales de Mantenimiento — presentacion para gerencia.
// Corre en paralelo al Diagnostico Mensual y no habla de toneladas: el unico
// dato de produccion que entra es la meta, y solo para despejar cuanta
// disponibilidad hace falta.
let PRES = null;
const CH = {};

// Paleta del informe que la jefatura ya venia presentando
const MARINO = '#123255', NARANJA = '#ED7D31', NARANJA_SUAVE = '#F5A05A';
const TINTA = '#eaf1f8', TENUE = '#93aec6', REJILLA = '#25455f';
const BIEN = '#30D158', REGULAR = '#FF9F0A', MAL = '#FF453A';

document.addEventListener('DOMContentLoaded', () => {
    const hoy = new Date();
    // Por defecto el mes anterior completo: el mes en curso no sirve para presentar
    const ant = new Date(hoy.getFullYear(), hoy.getMonth() - 1, 1);
    el('presMonth').value = `${ant.getFullYear()}-${String(ant.getMonth() + 1).padStart(2, '0')}`;
    cargar();
    window.addEventListener('resize', () => Object.values(CH).forEach(c => c && c.resize()));
    document.addEventListener('keydown', teclas);
});

function el(id) { return document.getElementById(id); }
function chart(id) {
    const box = el(id);
    if (!box) return null;
    if (!CH[id]) CH[id] = echarts.init(box);
    return CH[id];
}
function nf(x, d) {
    if (x == null) return '—';
    return Number(x).toLocaleString('es-PE', { maximumFractionDigits: d == null ? 1 : d });
}
function claseDisp(v) { return v == null ? '' : (v >= 95 ? 'v-good' : v >= 90 ? 'v-warn' : 'v-crit'); }

async function cargar() {
    const q = new URLSearchParams({
        month: el('presMonth').value,
        meses: el('presMeses').value,
        modo: el('presModo').value,
    });
    try {
        const r = await fetch(`/api/presentacion/data?${q}`);
        PRES = await r.json();
        if (PRES.error) { alert('Error: ' + PRES.error); return; }
        el('genAt').textContent = `generado ${PRES.meta.generado}`;
        renderPortada();
        renderRequerida();
        renderIndicador('disponibilidad', 'dispAreas', 'dispLineas', '%', 100);
        renderIndicador('mtbf', 'mtbfAreas', 'mtbfLineas', ' h', null);
        renderIndicador('mttr', 'mttrAreas', 'mttrLineas', ' h', null);
        renderIndicador('confiabilidad', 'confAreas', null, '%', 100);
        renderDispKpis();
        renderCumplimiento();
    } catch (e) { alert('No se pudo cargar: ' + e.message); }
}
window.cargar = cargar;

// ── Portada ──────────────────────────────────────────────────────────────
function renderPortada() {
    const m = PRES.meta;
    el('portPeriodo').textContent = m.label;
    const proc = PRES.areas.filter(a => a.es_proceso).map(a => a.area);
    el('portAreas').textContent = proc.length
        ? `Areas de proceso: ${proc.join(' · ')}` : '';
    const modo = m.modo === 'inherente' ? 'inherente' : 'operativa';
    el('dispTitulo').textContent = `Disponibilidad ${modo}`;
    el('dispMetodo').innerHTML = m.modo === 'inherente'
        ? `<b>Inherente</b>: mide la salud del activo — del tiempo disponible se descuenta el `
          + `mantenimiento planificado, asi que solo la castigan las averias (ISO 14224). `
          + `Se calcula equipo por equipo y se <b>pondera por capacidad</b>.`
        : `<b>Operativa</b>: lo que produccion realmente tuvo disponible. La castiga todo paro, `
          + `planificado o averia. Se calcula equipo por equipo y se <b>pondera por capacidad</b>.`;
    el('confMetodo').innerHTML =
        `Probabilidad de operar sin fallar durante <b>${m.horizonte_h} horas</b> seguidas: `
        + `R(t) = e<sup>−t/MTBF</sup>. Un equipo sin fallas en el mes da 100 %.`;
}

// ── 01 Disponibilidad requerida ──────────────────────────────────────────
function renderRequerida() {
    const req = PRES.requerida || [];
    if (!req.length) {
        el('reqAvisos').innerHTML = `<div class="aviso">No hay meta de produccion cargada para `
            + `${PRES.meta.label}, o las areas no tienen capacidad configurada en Alcance de Indicadores.</div>`;
        el('reqTable').innerHTML = '';
        chart('reqChart').clear();
        return;
    }
    const imposibles = req.filter(r => !r.alcanzable);
    el('reqAvisos').innerHTML = imposibles.length
        ? `<div class="aviso rojo"><b>${imposibles.map(r => r.area).join(' y ')} `
          + `${imposibles.length > 1 ? 'necesitarian' : 'necesitaria'} mas del 100 % de disponibilidad</b> `
          + `para cumplir la meta del mes (${imposibles.map(r => r.requerida_pct + ' %').join(', ')}). `
          + `Ni parando cero horas alcanzan: la meta esta por encima de la capacidad instalada de esas etapas. `
          + `Es una conversacion sobre la meta o sobre ampliar capacidad, no sobre mantenimiento.</div>`
        : '';

    const c = chart('reqChart');
    c.setOption({
        backgroundColor: 'transparent',
        tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
        legend: { textStyle: { color: TENUE }, top: 0 },
        grid: { left: 50, right: 30, top: 40, bottom: 40 },
        xAxis: { type: 'category', data: req.map(r => r.area),
                 axisLabel: { color: TINTA, fontWeight: 600 } },
        yAxis: { type: 'value', name: '%', max: v => Math.max(110, Math.ceil(v.max)),
                 axisLabel: { color: TENUE, formatter: '{value}%' },
                 splitLine: { lineStyle: { color: REJILLA } } },
        series: [
            { name: 'Disponibilidad real', type: 'bar', data: req.map(r => r.real_pct),
              itemStyle: { color: NARANJA, borderRadius: [4, 4, 0, 0] }, barMaxWidth: 54,
              label: { show: true, position: 'top', color: TINTA, formatter: '{c}%', fontSize: 11 } },
            { name: 'Disponibilidad requerida', type: 'line', data: req.map(r => r.requerida_pct),
              itemStyle: { color: MAL }, lineStyle: { width: 3, type: 'dashed' }, symbolSize: 9,
              label: { show: true, color: MAL, formatter: '{c}%', fontSize: 11 },
              markLine: { silent: true, symbol: 'none', data: [{ yAxis: 100 }],
                          lineStyle: { color: TENUE, type: 'dotted' },
                          label: { formatter: 'limite fisico 100%', color: TENUE } } },
        ],
    }, true);

    el('reqTable').innerHTML =
        `<tr><th>Area</th><th class="num">Disponibilidad requerida</th><th class="num">Real</th>
         <th class="num">Brecha</th><th class="num">Presupuesto de parada</th>
         <th class="num">Consumido</th><th class="num">Saldo</th></tr>` +
        req.map(r => `<tr>
            <td><b>${r.area}</b></td>
            <td class="num" style="color:${r.alcanzable ? TINTA : MAL};font-weight:700">${nf(r.requerida_pct)} %${r.alcanzable ? '' : ' ⚠'}</td>
            <td class="num">${nf(r.real_pct)} %</td>
            <td class="num" style="color:${r.brecha_pp >= 0 ? BIEN : MAL};font-weight:700">${r.brecha_pp >= 0 ? '+' : ''}${nf(r.brecha_pp)} pp</td>
            <td class="num">${r.alcanzable ? nf(r.presupuesto_h) + ' h' : '—'}</td>
            <td class="num">${nf(r.consumido_h)} h</td>
            <td class="num" style="color:${r.saldo_h >= 0 ? BIEN : MAL};font-weight:700">${r.alcanzable ? (r.saldo_h >= 0 ? '+' : '') + nf(r.saldo_h) + ' h' : '—'}</td>
        </tr>`).join('') +
        `<tr><td colspan="7" class="hint">El presupuesto son las horas de parada que se pueden gastar
         en el mes sin incumplir la meta. El saldo negativo indica por cuantas horas se paso el area.</td></tr>`;
}

// ── KPIs de disponibilidad del mes ───────────────────────────────────────
function renderDispKpis() {
    const areas = PRES.areas.filter(a => a.es_proceso);
    el('dispKpis').innerHTML = areas.map(a => {
        const act = a.actual, prev = a.serie[a.serie.length - 2];
        let delta = '';
        if (prev && prev.disponibilidad != null && act.disponibilidad != null) {
            const d = Math.round((act.disponibilidad - prev.disponibilidad) * 10) / 10;
            const col = d >= 0 ? BIEN : MAL;
            delta = d === 0 ? 'igual que el mes anterior'
                : `<span style="color:${col}">${d > 0 ? '▲' : '▼'} ${Math.abs(d)} pts</span> vs ${prev.label}`;
        }
        return `<div class="kpi-item"><div class="label">${a.area}</div>
            <div class="value ${claseDisp(act.disponibilidad)}">${nf(act.disponibilidad)} %</div>
            <div class="delta">${delta}</div></div>`;
    }).join('');
}

// ── Laminas por indicador: una grafica de area + desglose por linea ──────
function renderIndicador(campo, idAreas, idLineas, unidad, maximo) {
    const areas = PRES.areas.filter(a => a.es_proceso);
    const cont = el(idAreas);
    if (!cont) return;

    // Una caja por area con su tendencia mensual
    cont.innerHTML = areas.map((a, i) =>
        `<div class="chart-box" id="${campo}_area_${i}" style="height:250px;"></div>`).join('');

    areas.forEach((a, i) => {
        const c = chart(`${campo}_area_${i}`);
        const datos = a.serie.map(s => s[campo]);
        const series = [{
            name: campo.toUpperCase(), type: 'line', data: datos,
            itemStyle: { color: MARINO === '#123255' ? '#2f6f9f' : MARINO },
            lineStyle: { width: 3 }, symbolSize: 9,
            label: { show: true, position: 'top', color: TINTA, fontSize: 11,
                     formatter: p => nf(p.value) + (unidad === '%' ? '%' : '') },
        }];
        // El MTBF se lee contra el TEP, como en el informe actual
        if (campo === 'mtbf') {
            series.push({
                name: 'TEP', type: 'line', data: a.serie.map(s => s.tep),
                itemStyle: { color: NARANJA_SUAVE }, lineStyle: { width: 2 }, symbolSize: 7,
                label: { show: true, position: 'top', color: NARANJA_SUAVE, fontSize: 10 },
            });
        }
        c.setOption({
            backgroundColor: 'transparent',
            title: { text: `${tituloDe(campo)} — ${a.area}`, left: 'center',
                     textStyle: { color: TINTA, fontSize: 13, fontWeight: 700 } },
            tooltip: { trigger: 'axis' },
            legend: campo === 'mtbf' ? { textStyle: { color: TENUE }, bottom: 0 } : undefined,
            grid: { left: 48, right: 22, top: 46, bottom: campo === 'mtbf' ? 44 : 28 },
            xAxis: { type: 'category', data: a.serie.map(s => s.label),
                     axisLabel: { color: TENUE, fontWeight: 600 } },
            yAxis: { type: 'value', min: 0, max: maximo || undefined,
                     axisLabel: { color: TENUE, formatter: unidad === '%' ? '{value}%' : '{value}' },
                     splitLine: { lineStyle: { color: REJILLA } } },
            series,
        }, true);
    });

    if (!idLineas) return;

    // Desglose por linea del ultimo mes, agrupado por mes como en el informe
    const c = chart(idLineas);
    const meses = PRES.meta.meses;
    const etiquetas = [];
    areas.forEach(a => a.lineas.forEach(l => {
        const nom = `${l.etiqueta}`;
        if (!etiquetas.some(e => e.k === nom + a.area)) {
            etiquetas.push({ k: nom + a.area, et: nom, area: a.area, fila: l });
        }
    }));
    c.setOption({
        backgroundColor: 'transparent',
        title: { text: `${tituloDe(campo)} por linea — ultimos ${meses.length} meses`,
                 left: 'center', textStyle: { color: TINTA, fontSize: 13, fontWeight: 700 } },
        tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' },
                   formatter: ps => {
                       const it = etiquetas[ps[0].dataIndex];
                       return `<b>${it.et}</b> <span style="opacity:.7">(${it.area})</span><br/>`
                            + ps.map(p => `${p.seriesName}: ${nf(p.value)}${unidad === '%' ? '%' : ' h'}`).join('<br/>');
                   } },
        legend: { textStyle: { color: TENUE }, top: 24 },
        grid: { left: 50, right: 24, top: 62, bottom: 58 },
        xAxis: { type: 'category', data: etiquetas.map(e => e.et),
                 axisLabel: { color: TINTA, rotate: 32, fontSize: 10 } },
        yAxis: { type: 'value', min: 0, max: maximo || undefined,
                 axisLabel: { color: TENUE, formatter: unidad === '%' ? '{value}%' : '{value}' },
                 splitLine: { lineStyle: { color: REJILLA } } },
        series: meses.map((m, i) => ({
            name: m.label, type: 'bar',
            data: etiquetas.map(e => {
                const v = e.fila.valores.find(x => x.month === m.month);
                return v ? v[campo] : null;
            }),
            itemStyle: { color: escalaMes(i, meses.length), borderRadius: [3, 3, 0, 0] },
        })),
    }, true);
}

function tituloDe(campo) {
    return { disponibilidad: 'Disponibilidad', mtbf: 'MTBF', mttr: 'MTTR',
             confiabilidad: 'Confiabilidad' }[campo] || campo;
}
// Degradado del informe: los meses antiguos mas claros, el actual naranja
function escalaMes(i, n) {
    if (i === n - 1) return NARANJA;
    const pal = ['#dfe6ed', '#b3c2d0', '#7f95ab', '#546e88'];
    return pal[Math.min(i, pal.length - 1)];
}

// ── 05 y 06 Cumplimiento ─────────────────────────────────────────────────
function renderCumplimiento() {
    barrasCumplimiento('cumpPrevChart', PRES.cumplimiento.preventivo,
        'programadas', 'ejecutadas', 'PROGRAMADAS', 'EJECUTADAS',
        'Cumplimiento de mantenimiento preventivo', 90);
    barrasCumplimiento('cumpCorrChart', PRES.cumplimiento.correctivo,
        'programados', 'terminados', 'PROGRAMADOS', 'TERMINADOS',
        'Cumplimiento de mantenimiento correctivo programado', null);
}

function barrasCumplimiento(id, datos, kProg, kEjec, lProg, lEjec, titulo, meta) {
    const c = chart(id);
    const series = [
        { name: lProg, type: 'bar', data: datos.map(d => d[kProg]),
          itemStyle: { color: '#c9d4de' }, barMaxWidth: 46,
          label: { show: true, position: 'top', color: TINTA, fontSize: 11 } },
        { name: lEjec, type: 'bar', data: datos.map(d => d[kEjec]),
          itemStyle: { color: MARINO === '#123255' ? '#1f4b73' : MARINO }, barMaxWidth: 46,
          label: { show: true, position: 'top', color: TINTA, fontSize: 11 } },
        { name: '% CUMPLIMIENTO', type: 'line', yAxisIndex: 1,
          data: datos.map(d => d.pct), itemStyle: { color: NARANJA },
          lineStyle: { width: 3 }, symbolSize: 9, connectNulls: true,
          label: { show: true, position: 'top', color: NARANJA, formatter: '{c}%', fontSize: 12, fontWeight: 700 } },
    ];
    if (meta) {
        series[2].markLine = { silent: true, symbol: 'none', data: [{ yAxis: meta }],
            lineStyle: { color: BIEN, type: 'dashed' },
            label: { formatter: `meta ${meta}%`, color: BIEN } };
    }
    c.setOption({
        backgroundColor: 'transparent',
        title: { text: titulo, left: 'center', textStyle: { color: TINTA, fontSize: 14, fontWeight: 700 } },
        tooltip: { trigger: 'axis' },
        legend: { textStyle: { color: TENUE }, top: 26 },
        grid: { left: 56, right: 56, top: 66, bottom: 34 },
        xAxis: { type: 'category', data: datos.map(d => d.label),
                 axisLabel: { color: TINTA, fontWeight: 600 } },
        yAxis: [
            { type: 'value', name: 'OTs', axisLabel: { color: TENUE },
              splitLine: { lineStyle: { color: REJILLA } } },
            { type: 'value', name: '%', min: 0, max: 100,
              axisLabel: { color: TENUE, formatter: '{value}%' }, splitLine: { show: false } },
        ],
        series,
    }, true);
}

// ── Modo presentacion ────────────────────────────────────────────────────
let idx = 0;
function slides() { return Array.from(document.querySelectorAll('[data-slide]')); }
function showSlide(i) {
    const ss = slides();
    idx = Math.max(0, Math.min(i, ss.length - 1));
    ss.forEach((s, j) => s.classList.toggle('active', j === idx));
    el('slideCnt').textContent = `${idx + 1}/${ss.length}`;
    setTimeout(() => Object.values(CH).forEach(c => c && c.resize()), 60);
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
        setTimeout(() => Object.values(CH).forEach(c => c && c.resize()), 60);
    }
}
function nextSlide() { showSlide(idx + 1); }
function prevSlide() { showSlide(idx - 1); }
window.togglePresent = togglePresent;
window.nextSlide = nextSlide;
window.prevSlide = prevSlide;

function teclas(e) {
    if (!document.body.classList.contains('presenting')) return;
    if (e.key === 'ArrowRight' || e.key === 'PageDown' || e.key === ' ') { e.preventDefault(); nextSlide(); }
    else if (e.key === 'ArrowLeft' || e.key === 'PageUp') { e.preventDefault(); prevSlide(); }
    else if (e.key === 'Escape') { togglePresent(); }
}
