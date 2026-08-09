// Indicadores de Mantenimiento — presentacion para gerencia.
// Corre en paralelo al Diagnostico Mensual y no habla de toneladas: el unico
// dato de produccion que entra es la meta, y solo para despejar cuanta
// disponibilidad hace falta.
//
// En pantalla van los indicadores GLOBALES (planta y area). El detalle
// —equipo por equipo y las ordenes que generaron el paro— sale al hacer
// click en cualquier barra o punto.
let PRES = null;
const CH = {};

// Paleta del informe que la jefatura ya venia presentando
const MARINO = '#123255', AZUL = '#2f6f9f', AZUL_CLARO = '#63a6d8';
const NARANJA = '#ED7D31', NARANJA_SUAVE = '#F5A05A';
const TINTA = '#eaf1f8', TENUE = '#93aec6', REJILLA = '#25455f';
const BIEN = '#30D158', REGULAR = '#FF9F0A', MAL = '#FF453A';

// Configuracion de cada lamina de indicador
const IND = {
    disponibilidad: { titulo: 'Disponibilidad', unidad: '%', max: 100, subir: true,
                      corte: [95, 90] },
    mtbf:           { titulo: 'MTBF', unidad: ' h', subir: true, tep: true },
    mttr:           { titulo: 'MTTR', unidad: ' h', subir: false },
    confiabilidad:  { titulo: 'Confiabilidad', unidad: '%', max: 100, subir: true,
                      corte: [80, 60] },
};

document.addEventListener('DOMContentLoaded', () => {
    const hoy = new Date();
    // Por defecto el mes anterior completo: el mes en curso no sirve para presentar
    const ant = new Date(hoy.getFullYear(), hoy.getMonth() - 1, 1);
    el('presMonth').value = `${ant.getFullYear()}-${String(ant.getMonth() + 1).padStart(2, '0')}`;
    cambioMes();
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
function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"]/g,
        c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}
function color(campo, v) {
    const cfg = IND[campo];
    if (v == null || !cfg || !cfg.corte) return AZUL;
    return v >= cfg.corte[0] ? BIEN : v >= cfg.corte[1] ? REGULAR : MAL;
}
function clase(campo, v) {
    const cfg = IND[campo];
    if (v == null || !cfg || !cfg.corte) return '';
    return v >= cfg.corte[0] ? 'v-good' : v >= cfg.corte[1] ? 'v-warn' : 'v-crit';
}
// Degradado vertical para las barras, que es lo que le da cuerpo al grafico
function degradado(c) {
    return { type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
             colorStops: [{ offset: 0, color: c }, { offset: 1, color: c + '55' }] };
}

// ── Semanas del mes: bloques de 7 dias desde el dia 1 ────────────────────
// Espeja _bloques_semana del backend. No se usan semanas ISO porque una
// semana ISO se reparte entre dos meses y las semanas dejarian de sumar el mes.
function semanasDelMes(ym) {
    const y = +ym.slice(0, 4), m = +ym.slice(5, 7);
    const dias = new Date(y, m, 0).getDate();
    const b = [];
    for (let d = 1; d <= dias;) { const h = Math.min(d + 6, dias); b.push([d, h]); d = h + 1; }
    if (b.length > 1 && (b[b.length - 1][1] - b[b.length - 1][0] + 1) < 3) {
        const u = b.pop(); b[b.length - 1][1] = u[1];
    }
    return b;
}

// Al cambiar de mes se rearma el selector de vista: una entrada por semana
// (acumulando desde la semana 1) y el cierre mensual contra los meses previos.
function cambioMes() {
    const ym = el('presMonth').value;
    if (!ym) return;
    const sel = el('presVista');
    const previo = sel.value;
    const bloques = semanasDelMes(ym);
    let html = bloques.map((b, i) =>
        `<option value="s${i + 1}">Semana ${i + 1} (dias ${b[0]}–${b[1]})</option>`).join('');
    html += `<option value="mes">Mes completo — vs meses anteriores</option>`;
    sel.innerHTML = html;
    sel.value = (previo && Array.from(sel.options).some(o => o.value === previo)) ? previo : 'mes';
    cargar();
}
window.cambioMes = cambioMes;

async function cargar(refrescar) {
    const vista = el('presVista').value || 'mes';
    const q = new URLSearchParams({
        month: el('presMonth').value,
        vista: vista === 'mes' ? 'mes' : 'semana',
        semana: vista === 'mes' ? 0 : vista.slice(1),
        meses: el('presMeses').value,
        modo: el('presModo').value,
    });
    if (refrescar) q.set('refrescar', '1');
    try {
        const r = await fetch(`/api/presentacion/data?${q}`);
        PRES = await r.json();
        if (PRES.error) { alert('Error: ' + PRES.error); return; }
        el('genAt').textContent = `generado ${PRES.meta.generado}`;
        el('presMeses').style.display = PRES.meta.vista === 'mes' ? '' : 'none';
        renderPortada();
        renderRequerida();
        Object.keys(IND).forEach(campo => renderIndicador(campo));
        renderCumplimiento();
    } catch (e) { alert('No se pudo cargar: ' + e.message); }
}
window.cargar = cargar;

// ── Portada y textos de metodo ───────────────────────────────────────────
function renderPortada() {
    const m = PRES.meta;
    el('portPeriodo').textContent = m.vista === 'semana'
        ? `${m.periodo_actual} — acumulado desde la semana 1`
        : m.label;
    const proc = PRES.areas.filter(a => a.es_proceso).map(a => a.area);
    el('portAreas').textContent = proc.length
        ? `Areas de proceso: ${proc.join(' · ')}` : '';
    document.querySelectorAll('[data-peri]').forEach(n => { n.textContent = m.periodo_actual; });

    const modo = m.modo === 'inherente' ? 'inherente' : 'operativa';
    el('dispTitulo').textContent = `Disponibilidad ${modo}`;
    el('dispMetodo').innerHTML = (m.modo === 'inherente'
        ? `<b>Inherente</b>: mide la salud del activo — del tiempo disponible se descuenta el `
          + `mantenimiento planificado, asi que solo la castigan las averias (ISO 14224). `
          + `Se calcula equipo por equipo y se <b>pondera por capacidad</b>.`
        : `<b>Operativa</b>: lo que produccion realmente tuvo disponible. La castiga todo paro, `
          + `planificado o averia. Se calcula equipo por equipo y se <b>pondera por capacidad</b>.`)
        + (m.vista === 'semana'
            ? ` <span class="hint">La barra es el resultado de esa semana sola; la linea es el acumulado del mes hasta esa semana.</span>`
            : '');
    el('confMetodo').innerHTML =
        `Probabilidad de operar sin fallar durante <b>${m.horizonte_h} horas</b> seguidas: `
        + `R(t) = e<sup>−t/MTBF</sup>. Un equipo sin fallas en el periodo da 100 %.`;
}

// ── 01 Disponibilidad requerida ──────────────────────────────────────────
function renderRequerida() {
    const req = PRES.requerida || [];
    if (!req.length) {
        el('reqAvisos').innerHTML = `<div class="aviso">No hay meta de produccion cargada para `
            + `${PRES.meta.label}, o las areas no tienen capacidad configurada en Alcance de Indicadores.</div>`;
        el('reqTable').innerHTML = '';
        const c0 = chart('reqChart'); if (c0) c0.clear();
        return;
    }
    const imposibles = req.filter(r => !r.alcanzable);
    el('reqAvisos').innerHTML = imposibles.length
        ? `<div class="aviso rojo"><b>${imposibles.map(r => r.area).join(' y ')} `
          + `${imposibles.length > 1 ? 'necesitarian' : 'necesitaria'} mas del 100 % de disponibilidad</b> `
          + `para cumplir la meta del periodo (${imposibles.map(r => r.requerida_pct + ' %').join(', ')}). `
          + `Ni parando cero horas alcanzan: la meta esta por encima de la capacidad instalada de esas etapas. `
          + `Es una conversacion sobre la meta o sobre ampliar capacidad, no sobre mantenimiento.</div>`
        : '';

    const c = chart('reqChart');
    c.setOption({
        backgroundColor: 'transparent',
        tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
        legend: { textStyle: { color: TENUE }, top: 0 },
        grid: { left: 54, right: 30, top: 40, bottom: 40 },
        xAxis: { type: 'category', data: req.map(r => r.area),
                 axisLine: { lineStyle: { color: REJILLA } },
                 axisLabel: { color: TINTA, fontWeight: 700 } },
        yAxis: { type: 'value', name: '%', max: v => Math.max(110, Math.ceil(v.max)),
                 axisLabel: { color: TENUE, formatter: '{value}%' },
                 splitLine: { lineStyle: { color: REJILLA, type: 'dashed' } } },
        series: [
            { name: 'Disponibilidad real', type: 'bar', data: req.map(r => r.real_pct),
              itemStyle: { color: p => degradado(color('disponibilidad', p.value)),
                           borderRadius: [5, 5, 0, 0] }, barMaxWidth: 62,
              label: { show: true, position: 'top', color: TINTA, formatter: '{c}%',
                       fontSize: 12, fontWeight: 700 } },
            { name: 'Disponibilidad requerida', type: 'line', data: req.map(r => r.requerida_pct),
              itemStyle: { color: MAL }, lineStyle: { width: 3, type: 'dashed' }, symbolSize: 10,
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
            <td><b>${esc(r.area)}</b></td>
            <td class="num" style="color:${r.alcanzable ? TINTA : MAL};font-weight:700">${nf(r.requerida_pct)} %${r.alcanzable ? '' : ' ⚠'}</td>
            <td class="num">${nf(r.real_pct)} %</td>
            <td class="num" style="color:${r.brecha_pp >= 0 ? BIEN : MAL};font-weight:700">${r.brecha_pp >= 0 ? '+' : ''}${nf(r.brecha_pp)} pp</td>
            <td class="num">${r.alcanzable ? nf(r.presupuesto_h) + ' h' : '—'}</td>
            <td class="num">${nf(r.consumido_h)} h</td>
            <td class="num" style="color:${r.saldo_h >= 0 ? BIEN : MAL};font-weight:700">${r.alcanzable ? (r.saldo_h >= 0 ? '+' : '') + nf(r.saldo_h) + ' h' : '—'}</td>
        </tr>`).join('') +
        `<tr><td colspan="7" class="hint">El presupuesto son las horas de parada que se pueden gastar
         en el periodo sin incumplir la meta. El saldo negativo indica por cuantas horas se paso el area.</td></tr>`;
}

// ── Linea de tendencia (minimos cuadrados sobre la serie) ────────────────
function tendencia(vals) {
    const pts = [];
    vals.forEach((v, i) => { if (v != null) pts.push([i, Number(v)]); });
    if (pts.length < 3) return null;
    const n = pts.length;
    const sx = pts.reduce((a, p) => a + p[0], 0), sy = pts.reduce((a, p) => a + p[1], 0);
    const sxy = pts.reduce((a, p) => a + p[0] * p[1], 0);
    const sxx = pts.reduce((a, p) => a + p[0] * p[0], 0);
    const den = n * sxx - sx * sx;
    if (!den) return null;
    const b = (n * sxy - sx * sy) / den, a = (sy - b * sx) / n;
    return { pend: b, vals: vals.map((_, i) => Math.round((a + b * i) * 100) / 100) };
}

function chipTendencia(campo, serie) {
    const t = tendencia(serie.map(s => s[campo]));
    if (!t) return '';
    const cfg = IND[campo], sube = t.pend > 0.001, baja = t.pend < -0.001;
    if (!sube && !baja) return `<span class="trend">→ estable</span>`;
    const bueno = cfg.subir ? sube : baja;
    const paso = PRES.meta.vista === 'semana' ? '/sem' : '/mes';
    return `<span class="trend" style="color:${bueno ? BIEN : MAL}">`
         + `${sube ? '▲' : '▼'} ${nf(Math.abs(t.pend))}${cfg.unidad === '%' ? ' pp' : ' h'}${paso}</span>`;
}

// ── Laminas 02/03/04/07: global de planta + una caja por area ────────────
function renderIndicador(campo) {
    const cfg = IND[campo];
    const areas = PRES.areas.filter(a => a.es_proceso);
    const pref = { disponibilidad: 'disp', mtbf: 'mtbf', mttr: 'mttr', confiabilidad: 'conf' }[campo];

    // Tarjetas: primero PLANTA, luego cada area
    const tarjeta = (nom, serie, planta) => {
        const act = serie[serie.length - 1] || {}, prev = serie[serie.length - 2];
        let delta = '';
        if (prev && prev[campo] != null && act[campo] != null) {
            const d = Math.round((act[campo] - prev[campo]) * 10) / 10;
            const bueno = cfg.subir ? d >= 0 : d <= 0;
            delta = d === 0 ? `igual que ${prev.label}`
                : `<span style="color:${bueno ? BIEN : MAL}">${d > 0 ? '▲' : '▼'} ${nf(Math.abs(d))}`
                  + `${cfg.unidad === '%' ? ' pp' : ' h'}</span> vs ${prev.label}`;
        }
        return `<div class="kpi-item${planta ? ' planta' : ''}"><div class="label">${esc(nom)}</div>
            <div class="value ${clase(campo, act[campo])}">${nf(act[campo])}${cfg.unidad}</div>
            <div class="delta">${delta}</div></div>`;
    };
    const kpis = el(pref + 'Kpis');
    if (kpis) {
        kpis.innerHTML = tarjeta('Planta (proceso)', PRES.planta.serie, true)
            + areas.map(a => tarjeta(a.area, a.serie, false)).join('');
    }

    // Grafico global de la planta
    const gid = pref + 'Global';
    if (el(gid)) {
        pintar(gid, campo, PRES.planta, `${cfg.titulo} — PLANTA (areas de proceso, ponderado por capacidad)`,
               { barras: true, area_id: 0 });
    }

    // Una caja por area, separadas como en el informe
    const cont = el(pref + 'Areas');
    if (!cont) return;
    cont.innerHTML = areas.map((a, i) => {
        const act = a.serie[a.serie.length - 1] || {};
        return `<div class="area-card">
            <div class="area-head"><span class="dot"></span><span class="nom">${esc(a.area)}</span>
              ${chipTendencia(campo, a.serie)}
              <span class="val ${clase(campo, act[campo])}">${nf(act[campo])}${cfg.unidad}</span></div>
            <div class="chart-box" id="${pref}_area_${i}"></div></div>`;
    }).join('');
    areas.forEach((a, i) => pintar(`${pref}_area_${i}`, campo, a, null,
                                   { barras: false, area_id: a.area_id }));
}

// Dibuja una serie de indicador: valor del periodo + acumulado (vista
// semanal) + linea de tendencia. Al hacer click se abre el detalle de OTs.
function pintar(id, campo, bloque, titulo, opt) {
    const c = chart(id);
    if (!c) return;
    const cfg = IND[campo], m = PRES.meta;
    const serie = bloque.serie, ejes = serie.map(s => s.label);
    const vals = serie.map(s => s[campo]);
    const series = [];

    if (opt.barras) {
        series.push({
            name: cfg.titulo, type: 'bar', data: vals, barMaxWidth: 58, z: 2,
            itemStyle: { color: p => degradado(color(campo, p.value)), borderRadius: [5, 5, 0, 0] },
            label: { show: true, position: 'top', color: TINTA, fontSize: 12, fontWeight: 700,
                     formatter: p => nf(p.value) + (cfg.unidad === '%' ? '%' : '') },
        });
    } else {
        series.push({
            name: cfg.titulo, type: 'line', data: vals, smooth: true, z: 3,
            itemStyle: { color: AZUL_CLARO }, lineStyle: { width: 3, color: AZUL_CLARO }, symbolSize: 8,
            areaStyle: { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
                colorStops: [{ offset: 0, color: 'rgba(99,166,216,.34)' },
                             { offset: 1, color: 'rgba(99,166,216,0)' }] } },
            label: { show: true, position: 'top', color: TINTA, fontSize: 11,
                     formatter: p => nf(p.value) + (cfg.unidad === '%' ? '%' : '') },
        });
    }

    // Acumulado del mes hasta cada semana: responde "¿como va el mes?"
    const acum = bloque.acumulado || [];
    if (m.vista === 'semana' && acum.length === serie.length) {
        series.push({
            name: 'Acumulado del mes', type: 'line', data: acum.map(s => s[campo]),
            smooth: true, symbolSize: 7, z: 4,
            itemStyle: { color: NARANJA }, lineStyle: { width: 3, color: NARANJA },
        });
    }

    // El MTBF se lee contra el TEP, como en el informe actual
    if (cfg.tep) {
        series.push({
            name: 'TEP (horas del periodo)', type: 'line', data: serie.map(s => s.tep),
            itemStyle: { color: TENUE }, lineStyle: { width: 2, type: 'dotted', color: TENUE },
            symbol: 'none', z: 1,
        });
    }

    const t = tendencia(vals);
    if (t) {
        const bueno = cfg.subir ? t.pend >= 0 : t.pend <= 0;
        series.push({
            name: 'Tendencia', type: 'line', data: t.vals, symbol: 'none', z: 5,
            lineStyle: { width: 2, type: 'dashed', color: bueno ? BIEN : MAL, opacity: .9 },
            itemStyle: { color: bueno ? BIEN : MAL },
        });
    }

    c.setOption({
        backgroundColor: 'transparent',
        title: titulo ? { text: titulo, left: 'center',
                          textStyle: { color: TINTA, fontSize: 13, fontWeight: 700 } } : undefined,
        tooltip: {
            trigger: 'axis',
            backgroundColor: 'rgba(10,25,38,.95)', borderColor: REJILLA,
            textStyle: { color: TINTA },
            formatter: ps => {
                const s = serie[ps[0].dataIndex] || {};
                return `<b>${esc(s.nombre || s.label)}</b><br/>`
                    + ps.map(p => `${p.marker} ${p.seriesName}: <b>${nf(p.value)}${cfg.unidad}</b>`).join('<br/>')
                    + `<br/><span style="opacity:.7">${s.fallas || 0} averia(s) · ${nf(s.horas_paro)} h de paro`
                    + ` · ${s.ots || 0} OT cerradas</span>`
                    + `<br/><span style="opacity:.55">click para ver las ordenes</span>`;
            },
        },
        legend: (series.length > 1 && opt.barras)
            ? { textStyle: { color: TENUE }, bottom: 0, itemWidth: 16 } : undefined,
        grid: { left: 52, right: 24, top: titulo ? 46 : 22,
                bottom: (series.length > 1 && opt.barras) ? 42 : 26 },
        xAxis: { type: 'category', data: ejes,
                 axisLine: { lineStyle: { color: REJILLA } },
                 axisLabel: { color: TINTA, fontWeight: 700 } },
        yAxis: { type: 'value', min: 0, max: cfg.max || undefined,
                 axisLabel: { color: TENUE, formatter: cfg.unidad === '%' ? '{value}%' : '{value}' },
                 splitLine: { lineStyle: { color: REJILLA, type: 'dashed' } } },
        series,
    }, true);

    c.off('click');
    c.on('click', p => abrirDetalle(opt.area_id, p.dataIndex));
    c.getZr().off('click');
    c.getZr().on('click', ev => { if (!ev.target) abrirDetalle(opt.area_id, serie.length - 1); });
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
    if (!c) return;
    const series = [
        { name: lProg, type: 'bar', data: datos.map(d => d[kProg]),
          itemStyle: { color: degradado('#9fb4c6'), borderRadius: [4, 4, 0, 0] }, barMaxWidth: 48,
          label: { show: true, position: 'top', color: TINTA, fontSize: 11 } },
        { name: lEjec, type: 'bar', data: datos.map(d => d[kEjec]),
          itemStyle: { color: degradado(AZUL), borderRadius: [4, 4, 0, 0] }, barMaxWidth: 48,
          label: { show: true, position: 'top', color: TINTA, fontSize: 11 } },
        { name: '% CUMPLIMIENTO', type: 'line', yAxisIndex: 1, smooth: true,
          data: datos.map(d => d.pct), itemStyle: { color: NARANJA },
          lineStyle: { width: 3 }, symbolSize: 10, connectNulls: true, z: 4,
          label: { show: true, position: 'top', color: NARANJA, formatter: '{c}%', fontSize: 12, fontWeight: 700 } },
    ];
    const t = tendencia(datos.map(d => d.pct));
    if (t) {
        series.push({ name: 'Tendencia', type: 'line', yAxisIndex: 1, data: t.vals,
            symbol: 'none', z: 3,
            lineStyle: { width: 2, type: 'dashed', color: t.pend >= 0 ? BIEN : MAL } });
    }
    if (meta) {
        series[2].markLine = { silent: true, symbol: 'none', data: [{ yAxis: meta }],
            lineStyle: { color: BIEN, type: 'dashed' },
            label: { formatter: `meta ${meta}%`, color: BIEN } };
    }
    c.setOption({
        backgroundColor: 'transparent',
        title: { text: titulo, left: 'center', textStyle: { color: TINTA, fontSize: 14, fontWeight: 700 } },
        tooltip: { trigger: 'axis', backgroundColor: 'rgba(10,25,38,.95)',
                   borderColor: REJILLA, textStyle: { color: TINTA },
                   formatter: ps => `<b>${esc((datos[ps[0].dataIndex] || {}).nombre || '')}</b><br/>`
                       + ps.map(p => `${p.marker} ${p.seriesName}: <b>${nf(p.value)}</b>`).join('<br/>') },
        legend: { textStyle: { color: TENUE }, top: 26 },
        grid: { left: 56, right: 56, top: 66, bottom: 34 },
        xAxis: { type: 'category', data: datos.map(d => d.label),
                 axisLine: { lineStyle: { color: REJILLA } },
                 axisLabel: { color: TINTA, fontWeight: 700 } },
        yAxis: [
            { type: 'value', name: 'OTs', axisLabel: { color: TENUE },
              splitLine: { lineStyle: { color: REJILLA, type: 'dashed' } } },
            { type: 'value', name: '%', min: 0, max: 100,
              axisLabel: { color: TENUE, formatter: '{value}%' }, splitLine: { show: false } },
        ],
        series,
    }, true);
}

// ── Drill-down: las ordenes detras del indicador ─────────────────────────
async function abrirDetalle(areaId, i) {
    const per = (PRES.meta.periodos || [])[i];
    if (!per) return;
    const q = new URLSearchParams({
        area_id: areaId || 0, desde: per.desde, hasta: per.hasta,
        modo: PRES.meta.modo, horizonte: PRES.meta.horizonte_h,
    });
    el('modalDet').classList.add('open');
    el('detTitulo').textContent = 'Cargando...';
    el('detSub').textContent = per.nombre;
    el('detKpis').innerHTML = ''; el('detEquipos').innerHTML = ''; el('detOts').innerHTML = '';
    try {
        const r = await fetch(`/api/presentacion/detalle?${q}`);
        const d = await r.json();
        if (d.error) { el('detTitulo').textContent = 'Error: ' + d.error; return; }
        el('detTitulo').textContent = d.titulo;
        el('detSub').textContent = `${per.nombre} · ${per.desde} a ${per.hasta} · `
            + `${d.dias} dias (TEP ${nf(d.tep, 0)} h) · disponibilidad ${d.modo}`;
        const s = d.resumen;
        el('detKpis').innerHTML = [
            ['Disponibilidad', nf(s.disponibilidad) + ' %', clase('disponibilidad', s.disponibilidad)],
            ['MTBF', nf(s.mtbf) + ' h', ''],
            ['MTTR', nf(s.mttr) + ' h', ''],
            ['Confiabilidad', nf(s.confiabilidad) + ' %', clase('confiabilidad', s.confiabilidad)],
            ['Averias', nf(s.fallas, 0), ''],
            ['Horas de paro', nf(s.horas_paro) + ' h', ''],
        ].map(([l, v, cl]) => `<div class="kpi-item"><div class="label">${l}</div>
            <div class="value ${cl}" style="font-size:1.25rem">${v}</div></div>`).join('');

        el('detEquipos').innerHTML = d.equipos.length
            ? `<tr><th>Equipo</th><th class="num">Disponibilidad</th><th class="num">MTBF</th>
               <th class="num">MTTR</th><th class="num">Averias</th><th class="num">Horas de paro</th>
               <th class="num">OTs</th></tr>`
              + d.equipos.map(e => `<tr><td><b>${esc(e.equipo)}</b></td>
                <td class="num ${clase('disponibilidad', e.disponibilidad)}">${nf(e.disponibilidad)} %</td>
                <td class="num">${nf(e.mtbf)} h</td><td class="num">${nf(e.mttr)} h</td>
                <td class="num">${e.fallas}</td><td class="num">${nf(e.horas_paro)} h</td>
                <td class="num">${e.ots}</td></tr>`).join('')
            : `<tr><td class="hint">Sin movimiento de equipos en el periodo.</td></tr>`;

        el('detOts').innerHTML = d.ots.length
            ? `<tr><th>OT</th><th>Equipo</th><th>Tipo</th><th>Descripcion</th>
               <th>Fecha</th><th class="num">Horas de paro</th><th>Paro</th></tr>`
              + d.ots.map(o => `<tr><td><b>${esc(o.code)}</b></td><td>${esc(o.equipo)}</td>
                <td>${esc(o.tipo)}</td><td>${esc(o.descripcion)}</td><td>${esc(o.fecha)}</td>
                <td class="num">${o.horas_paro ? nf(o.horas_paro) + ' h' : '—'}</td>
                <td>${o.horas_paro ? `<span class="tag ${o.planificado ? 'plan' : 'aver'}">`
                    + `${o.planificado ? 'planificado' : 'averia'}</span>` : '—'}</td></tr>`).join('')
            : `<tr><td class="hint">No hay ordenes cerradas en el periodo para esta area.</td></tr>`;
    } catch (e) {
        el('detTitulo').textContent = 'No se pudo cargar el detalle: ' + e.message;
    }
}
function cerrarDetalle() { el('modalDet').classList.remove('open'); }
window.abrirDetalle = abrirDetalle;
window.cerrarDetalle = cerrarDetalle;

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
    if (e.key === 'Escape' && el('modalDet').classList.contains('open')) { cerrarDetalle(); return; }
    if (!document.body.classList.contains('presenting')) return;
    if (e.key === 'ArrowRight' || e.key === 'PageDown' || e.key === ' ') { e.preventDefault(); nextSlide(); }
    else if (e.key === 'ArrowLeft' || e.key === 'PageUp') { e.preventDefault(); prevSlide(); }
    else if (e.key === 'Escape') { togglePresent(); }
}
