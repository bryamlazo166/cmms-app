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
    // Las cajas por area se rehacen con innerHTML en cada render. Si se
    // reusa la instancia vieja, esta sigue atada al div que ya se
    // desecho y pinta sobre un nodo que no esta en la pagina: la lamina
    // se quedaba congelada en la vista anterior — al pasar de mensual a
    // semanal, los graficos por area seguian mostrando los meses.
    if (CH[id] && CH[id].getDom && CH[id].getDom() !== box) {
        CH[id].dispose();
        delete CH[id];
    }
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
// Color de cada fuente del programa preventivo
const COLOR_FUENTE = { OT: '#1f4b73', LUB: NARANJA, INS: '#3AA6A0', MON: '#8A6FD1' };

// Que programas preventivos estan EN VIGOR. Un programa en implementacion
// tiene sus puntos cargados pero todavia no se le exige a nadie; cobrarle el
// plan teorico hunde el cumplimiento con trabajo que no se pidio. No hay dato
// que distinga "implementando" de "no se hizo", asi que la declaracion es
// explicita y queda a la vista en la propia lamina.
function renderFuentes() {
    const cont = el('cumpFuentes');
    if (!cont) return;
    const fs = PRES.meta.fuentes_disponibles || [];
    cont.innerHTML = `<span class="tit">Programas en vigor</span>`
        + fs.map(f => f.codigo === 'OT'
            ? `<label class="fija" title="Las ordenes siempre entran al indicador">
                 <input type="checkbox" checked disabled> ${esc(f.nombre)}</label>`
            : `<label><input type="checkbox" data-fuente="${f.codigo}"
                 ${f.en_vigor ? 'checked' : ''} onchange="guardarFuentes()"> ${esc(f.nombre)}</label>`).join('')
        + `<span class="msg" id="cumpFuentesMsg">Los programas que se estan implementando se listan
           abajo con su plan, pero no bajan el cumplimiento.</span>`;
}

async function guardarFuentes() {
    const marcadas = Array.from(document.querySelectorAll('#cumpFuentes input[data-fuente]'))
        .filter(i => i.checked).map(i => i.getAttribute('data-fuente'));
    const msg = el('cumpFuentesMsg');
    if (msg) msg.textContent = 'Guardando...';
    try {
        const r = await fetch('/api/presentacion/fuentes', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ fuentes: marcadas }),
        });
        const d = await r.json();
        if (d.error) { if (msg) msg.textContent = 'No se pudo guardar: ' + d.error; return; }
        await cargar(true);
    } catch (e) {
        if (msg) msg.textContent = 'No se pudo guardar: ' + e.message;
    }
}
window.guardarFuentes = guardarFuentes;

function renderCumplimiento() {
    renderFuentes();
    barrasCumplimiento('cumpPrevChart', PRES.cumplimiento.preventivo,
        'programadas', 'ejecutadas', 'PROGRAMADAS', 'EJECUTADAS',
        'Cumplimiento del programa preventivo', 90, true);
    tablaFuentes();
    barrasCumplimiento('cumpCorrChart', PRES.cumplimiento.correctivo,
        'programados', 'terminados', 'PROGRAMADOS', 'TERMINADOS',
        'Cumplimiento de mantenimiento correctivo programado', null, false);
}

// Desglose del periodo que se esta presentando: de donde sale el total
function tablaFuentes() {
    const t = el('cumpPrevTabla');
    if (!t) return;
    const ult = PRES.cumplimiento.preventivo[PRES.cumplimiento.preventivo.length - 1] || {};
    const fs = ult.fuentes || [];
    if (!fs.length) { t.innerHTML = ''; return; }
    t.innerHTML =
        `<tr><th>Fuente del programa</th><th class="num">Puntos / rutas</th>
         <th class="num">Programado</th><th class="num">Ejecutado</th><th class="num">Cumplimiento</th></tr>`
        + fs.map(f => f.activa ? `<tr>
            <td><span style="color:${COLOR_FUENTE[f.codigo] || AZUL};font-weight:800">●</span>
                <b>${esc(f.nombre)}</b></td>
            <td class="num">${f.puntos == null ? '—' : f.puntos}</td>
            <td class="num">${nf(f.programadas, 0)}</td>
            <td class="num">${nf(f.ejecutadas, 0)}</td>
            <td class="num" style="font-weight:700;color:${f.pct == null ? TENUE : (f.pct >= 90 ? BIEN : f.pct >= 70 ? REGULAR : MAL)}">${f.pct == null ? '—' : nf(f.pct) + ' %'}</td>
         </tr>` : `<tr style="opacity:.55">
            <td><span style="color:${TENUE};font-weight:800">○</span> ${esc(f.nombre)}
                <span class="hint">— en implementacion, aun sin ejecuciones registradas</span></td>
            <td class="num">${f.puntos == null ? '—' : f.puntos}</td>
            <td class="num" colspan="3">no entra al indicador
                <span class="hint">(el plan seria ${nf(f.plan_teorico, 0)})</span></td>
         </tr>`).join('')
        + `<tr><td><b>TOTAL DEL PROGRAMA</b></td><td class="num"></td>
           <td class="num"><b>${nf(ult.programadas, 0)}</b></td>
           <td class="num"><b>${nf(ult.ejecutadas, 0)}</b></td>
           <td class="num" style="font-weight:800;color:${ult.pct >= 90 ? BIEN : ult.pct >= 70 ? REGULAR : MAL}">${nf(ult.pct)} %</td></tr>`
        + `<tr><td colspan="5" class="hint">El indicador que se venia presentando —solo OTs— cerro en
           ${ult.solo_ot && ult.solo_ot.pct != null ? nf(ult.solo_ot.pct) + ' %' : '—'}
           (${(ult.solo_ot || {}).ejecutadas || 0} de ${(ult.solo_ot || {}).programadas || 0} ordenes).
           La diferencia es el trabajo preventivo que no pasa por una OT.</td></tr>`;
}

function barrasCumplimiento(id, datos, kProg, kEjec, lProg, lEjec, titulo, meta, porFuente) {
    const c = chart(id);
    if (!c) return;
    const series = [
        { name: lProg, type: 'bar', data: datos.map(d => d[kProg]),
          itemStyle: { color: degradado('#9fb4c6'), borderRadius: [4, 4, 0, 0] }, barMaxWidth: 48,
          label: { show: true, position: 'top', color: TINTA, fontSize: 11 } },
    ];
    // Lo ejecutado se apila por fuente: el total no esconde de donde sale.
    // Las fuentes en implementacion no se dibujan — no entran al indicador.
    const activas = porFuente
        ? (datos[datos.length - 1].fuentes || []).filter(f => f.activa) : [];
    const codigos = activas.map(f => f.codigo);
    if (codigos.length > 1) {
        activas.forEach(ref => {
            series.push({
                name: ref.nombre, type: 'bar', stack: 'ejec', barMaxWidth: 48,
                data: datos.map(d => {
                    const f = (d.fuentes || []).find(x => x.codigo === ref.codigo);
                    return f ? f.ejecutadas : 0;
                }),
                itemStyle: { color: degradado(COLOR_FUENTE[ref.codigo] || AZUL) },
            });
        });
        // Total ejecutado encima de la pila
        series[series.length - 1].label = {
            show: true, position: 'top', color: TINTA, fontSize: 11,
            formatter: p => nf(datos[p.dataIndex][kEjec], 0),
        };
    } else {
        series.push({ name: lEjec, type: 'bar', data: datos.map(d => d[kEjec]),
            itemStyle: { color: degradado(AZUL), borderRadius: [4, 4, 0, 0] }, barMaxWidth: 48,
            label: { show: true, position: 'top', color: TINTA, fontSize: 11 } });
    }
    series.push(
        { name: '% CUMPLIMIENTO', type: 'line', yAxisIndex: 1, smooth: true,
          data: datos.map(d => d.pct), itemStyle: { color: NARANJA },
          lineStyle: { width: 3 }, symbolSize: 10, connectNulls: true, z: 4,
          label: { show: true, position: 'top', color: NARANJA, formatter: '{c}%', fontSize: 12, fontWeight: 700 } });
    const t = tendencia(datos.map(d => d.pct));
    if (t) {
        series.push({ name: 'Tendencia', type: 'line', yAxisIndex: 1, data: t.vals,
            symbol: 'none', z: 3,
            lineStyle: { width: 2, type: 'dashed', color: t.pend >= 0 ? BIEN : MAL } });
    }
    if (meta) {
        // La linea de meta cuelga de la serie de %, que ya no esta en una
        // posicion fija: con el desglose por fuente el numero de barras varia.
        const pct = series.find(s => s.name === '% CUMPLIMIENTO');
        pct.markLine = { silent: true, symbol: 'none', data: [{ yAxis: meta }],
            lineStyle: { color: BIEN, type: 'dashed' },
            label: { formatter: `meta ${meta}%`, color: BIEN } };
    }
    c.setOption({
        backgroundColor: 'transparent',
        title: { text: titulo, left: 'center', textStyle: { color: TINTA, fontSize: 14, fontWeight: 700 } },
        tooltip: { trigger: 'axis', backgroundColor: 'rgba(10,25,38,.95)',
                   borderColor: REJILLA, textStyle: { color: TINTA },
                   formatter: ps => `<b>${esc((datos[ps[0].dataIndex] || {}).nombre || '')}</b><br/>`
                       + ps.filter(p => p.value)
                           .map(p => `${p.marker} ${p.seriesName}: <b>${nf(p.value)}`
                                + `${p.seriesName.indexOf('%') === 0 ? ' %' : ''}</b>`).join('<br/>') },
        legend: { textStyle: { color: TENUE, fontSize: 11 }, top: 24, itemWidth: 15 },
        grid: { left: 56, right: 56, top: codigos.length > 1 ? 84 : 66, bottom: 34 },
        xAxis: { type: 'category', data: datos.map(d => d.label),
                 axisLine: { lineStyle: { color: REJILLA } },
                 axisLabel: { color: TINTA, fontWeight: 700 } },
        yAxis: [
            { type: 'value', name: codigos.length > 1 ? 'Actividades' : 'OTs',
              axisLabel: { color: TENUE },
              splitLine: { lineStyle: { color: REJILLA, type: 'dashed' } } },
            { type: 'value', name: '%', min: 0, max: 100,
              axisLabel: { color: TENUE, formatter: '{value}%' }, splitLine: { show: false } },
        ],
        series,
    }, true);
}

// ── Guion: que decir en cada lamina ──────────────────────────────────────
// Se arma con reglas fijas sobre los numeros que ya estan en pantalla, sin
// IA: la lectura de estos indicadores es determinista (si la real esta bajo
// la requerida hay brecha; si el MTBF baja y el MTTR sube el problema es de
// respuesta, no de frecuencia). Una IA aqui añadiria espera y el riesgo de
// inventar una causa que no esta en los datos, delante de la gerencia.
function sec(n, titulo, que, decir, pregunta) {
    return `<div class="gsec">
        <div class="gtit"><span class="gn">${n}</span> ${titulo}</div>
        ${que ? `<div class="gque">${que}</div>` : ''}
        <div class="gdi">${decir}</div>
        ${pregunta ? `<div class="gpre">${pregunta}</div>` : ''}
    </div>`;
}
function pp(x) { return `${x >= 0 ? '+' : ''}${nf(x)}`; }
function peorPor(lista, campo, menorEsPeor) {
    const v = lista.filter(a => a.actual[campo] != null);
    if (!v.length) return null;
    return v.reduce((p, a) => (menorEsPeor
        ? (a.actual[campo] < p.actual[campo] ? a : p)
        : (a.actual[campo] > p.actual[campo] ? a : p)));
}
function rumbo(campo, serie, subirEsBueno) {
    const t = tendencia(serie.map(s => s[campo]));
    if (!t) return { txt: '', bueno: null };
    if (Math.abs(t.pend) < 0.01) return { txt: 'se mantiene estable', bueno: true };
    const sube = t.pend > 0;
    return { txt: sube ? 'viene subiendo' : 'viene bajando',
             bueno: subirEsBueno ? sube : !sube };
}

function generarGuion() {
    const m = PRES.meta;
    const areas = PRES.areas.filter(a => a.es_proceso);
    const pl = PRES.planta.actual;
    const semanal = m.vista === 'semana';
    const acum = semanal && PRES.planta.acumulado.length
        ? PRES.planta.acumulado[PRES.planta.acumulado.length - 1] : null;
    let h = '';

    // ── Apertura ────────────────────────────────────────────────────────
    h += sec('00', 'Como abrir',
        semanal
            ? `Es el cierre de la ${m.periodo_actual.toLowerCase()}. En pantalla estan todas las semanas
               corridas del mes: la barra es la semana sola y la linea naranja es el acumulado.`
            : `Es el cierre de ${m.label}, comparado con los meses anteriores.`,
        `"Presento los indicadores de mantenimiento de <b>${esc(m.periodo_actual)}</b>.
         Son las tres areas de proceso: ${areas.map(a => esc(a.area)).join(', ')}.
         Todo esta medido <b>equipo por equipo y ponderado por capacidad</b>, no por promedio simple:
         un digestor grande pesa mas que uno chico.
         La disponibilidad que presento es la <b>${m.modo}</b>${m.modo === 'inherente'
             ? ', que descuenta el mantenimiento planificado y solo la castigan las averias'
             : ', que castiga todo paro, planificado o averia'}."`,
        `<b>Si preguntan por que ponderada:</b> <span class="q">"Porque las areas tienen equipos de
         capacidades distintas. Con promedio simple, parar el digestor mas grande pesaria igual que
         parar el mas chico, y eso no es lo que pierde la planta."</span>`);

    // ── 01 Disponibilidad requerida ─────────────────────────────────────
    const req = PRES.requerida || [];
    if (!req.length) {
        h += sec('01', 'Disponibilidad requerida', '',
            `"No hay meta de produccion cargada para este periodo, asi que esta lamina va vacia."`,
            `<b>Accion:</b> cargar la meta en Produccion vs Mantenimiento antes de presentar.`);
    } else {
        const imp = req.filter(r => !r.alcanzable);
        const apretada = req.filter(r => r.alcanzable).sort((a, b) => a.brecha_pp - b.brecha_pp)[0];
        const holgada = req.filter(r => r.alcanzable).sort((a, b) => b.brecha_pp - a.brecha_pp)[0];
        let d = `"Esta lamina traduce la meta de produccion a lenguaje de mantenimiento.
            No hablo de toneladas: hablo de <b>cuanta disponibilidad necesito</b> y de
            <b>cuantas horas de parada me puedo gastar</b>.<br><br>`;
        req.forEach(r => {
            d += `${esc(r.area)} necesita <b>${nf(r.requerida_pct)} %</b> y esta en
                  <b>${nf(r.real_pct)} %</b>${r.alcanzable
                    ? ` — ${r.brecha_pp >= 0 ? 'cumple' : 'no alcanza'}, ${pp(r.brecha_pp)} puntos.`
                    : ` — <b>imposible</b>.`}<br>`;
        });
        if (apretada) {
            d += `<br>El area mas apretada es <b>${esc(apretada.area)}</b>: el presupuesto del periodo es
                  de <b>${nf(apretada.presupuesto_h)} horas</b> de parada, llevo consumidas
                  <b>${nf(apretada.consumido_h)}</b>, y me quedan
                  <b>${nf(apretada.saldo_h)} horas</b>${apretada.saldo_h < 0
                    ? ' — es decir, ya me pase' : ''}."`;
        } else { d += `"`; }
        h += sec('01', 'Disponibilidad requerida para cumplir la meta',
            `Barra = disponibilidad real. Linea roja punteada = la que hace falta. Si la barra pasa la
             linea, esa etapa no es el problema.`,
            d,
            (imp.length
                ? `<div class="gav"><b>Ojo:</b> ${imp.map(r => esc(r.area)).join(' y ')}
                   ${imp.length > 1 ? 'necesitan' : 'necesita'} mas del 100 %. Di esto tal cual:
                   <span class="q">"Ni parando cero horas se alcanza. La meta esta por encima de la
                   capacidad instalada de esa etapa. Es una conversacion sobre la meta o sobre ampliar
                   capacidad, no sobre mantenimiento."</span></div>`
                : '')
            + `<b>Si preguntan de donde sale el presupuesto de horas:</b>
               <span class="q">"De la meta y de la capacidad instalada. Si necesito
               ${apretada ? nf(apretada.requerida_pct) : '—'} % de disponibilidad, el resto del tiempo
               es lo que me puedo permitir parar. Es el mismo numero que usa Produccion vs
               Mantenimiento."</span>`
            + (holgada && holgada !== apretada
                ? `<br><b>Si te aprietan por ${esc(holgada.area)}:</b> <span class="q">"Tiene
                   ${nf(holgada.saldo_h)} horas de saldo. No es donde esta el riesgo."</span>` : ''));
    }

    // ── 02 Disponibilidad ───────────────────────────────────────────────
    const peorD = peorPor(areas, 'disponibilidad', true);
    const rD = rumbo('disponibilidad', PRES.planta.serie, true);
    h += sec('02', `Disponibilidad ${esc(m.modo)}`,
        `Tarjeta de planta arriba, y una caja por area. La linea verde o roja de cada caja es la
         tendencia del periodo.`,
        `"La planta cerro en <b>${nf(pl.disponibilidad)} %</b>${rD.txt ? ` y ${rD.txt}` : ''}${
            semanal && acum ? `. El acumulado del mes va en <b>${nf(acum.disponibilidad)} %</b>` : ''}.<br><br>`
        // Las horas de paro del area son la SUMA de horas-equipo: en COCCION los
        // 9 digestores paran en paralelo, asi que decir "590 horas de paro" a
        // secas suena a que el area estuvo detenida 590 h y no es eso.
        + areas.map(a => `${esc(a.area)}: <b>${nf(a.actual.disponibilidad)} %</b>`
            + `, ${a.actual.fallas} averia${a.actual.fallas === 1 ? '' : 's'}`
            + ` y ${nf(a.actual.horas_paro)} horas-equipo de parada`).join('.<br>')
        + `.<br><br>${peorD ? `La que manda es <b>${esc(peorD.area)}</b> con
             ${nf(peorD.actual.disponibilidad)} %${peorD.actual.fallas
                ? `, por ${peorD.actual.fallas} averia${peorD.actual.fallas === 1 ? '' : 's'}` : ''}.` : ''}"`,
        `<b>Si preguntan que paso exactamente:</b> haz click en la barra de esa area en la pantalla —
         se abre el detalle con los equipos y las ordenes de ese periodo, con sus horas de parada.
         <span class="q">"Lo tengo aqui mismo, orden por orden."</span>`
        + `<br><b>Si preguntan por las horas-equipo:</b> <span class="q">"Es la suma de lo que paro
           cada equipo. En coccion los digestores trabajan en paralelo, asi que esas horas no son
           horas de area detenida: por eso la disponibilidad se pondera por capacidad y no se saca
           restando esa suma."</span>`
        + `<br><b>Si preguntan por que no coincide con Produccion:</b> <span class="q">"Produccion
           mide la operativa, que castiga tambien el mantenimiento planificado. Yo presento la
           inherente, que mide la salud del equipo. Las dos estan calculadas, es el mismo dato leido
           de dos formas."</span>`);

    // ── 03 MTBF ─────────────────────────────────────────────────────────
    const peorM = peorPor(areas, 'mtbf', true);
    const rM = rumbo('mtbf', PRES.planta.serie, true);
    h += sec('03', 'MTBF — tiempo medio entre fallas',
        `Se lee contra el TEP (la linea punteada gris): son las horas que tuvo el periodo. Cuanto mas
         cerca del TEP, menos veces paro.`,
        `"El MTBF de planta es de <b>${nf(pl.mtbf)} horas</b> contra un TEP de
         <b>${nf(pl.tep, 0)}</b>${rM.txt ? `, y ${rM.txt}` : ''}.
         ${peorM ? `El area con el MTBF mas corto es <b>${esc(peorM.area)}</b>, con
          ${nf(peorM.actual.mtbf)} horas: ahi es donde mas seguido se para.` : ''}
         Subir el MTBF es trabajo de <b>preventivo y de causa raiz</b>: espaciar las fallas."`,
        `<b>Si preguntan por que el MTBF es tan alto o tan bajo:</b> <span class="q">"Es horas de
         operacion divididas entre numero de averias. Un area con una sola averia en el mes tiene un
         MTBF enorme aunque esa averia haya durado dias — por eso el MTBF hay que leerlo junto al
         MTTR, no solo."</span>`);

    // ── 04 MTTR ─────────────────────────────────────────────────────────
    const peorR = peorPor(areas, 'mttr', false);
    const rR = rumbo('mttr', PRES.planta.serie, false);
    h += sec('04', 'MTTR — tiempo medio de reparacion',
        `Aqui <b>bajar es mejorar</b>. La tendencia verde significa que estamos respondiendo mas rapido.`,
        `"El MTTR de planta es de <b>${nf(pl.mttr)} horas</b> por averia${rR.txt ? ` y ${rR.txt}` : ''}.
         ${peorR && peorR.actual.mttr > 0 ? `El mas alto es <b>${esc(peorR.area)}</b> con
          ${nf(peorR.actual.mttr)} horas.` : ''}
         Este numero es el tiempo que el equipo estuvo <b>detenido</b>, no las horas-hombre:
         incluye la espera de repuesto, de grua y de permiso. Por eso puede salir alto aunque la
         reparacion en si sea corta — y esa espera es justamente lo que hay que atacar."`,
        `<b>Si preguntan como bajarlo:</b> <span class="q">"Repuestos criticos en almacen,
         procedimiento de intervencion listo antes de parar, y decidir mas rapido. Hoy no puedo
         separar cuanto es espera y cuanto es reparacion efectiva porque no registramos la hora de
         inicio de la intervencion; si lo registramos, el proximo mes lo puedo partir."</span>`);

    // ── 05 Cumplimiento preventivo ──────────────────────────────────────
    const cp = PRES.cumplimiento.preventivo[PRES.cumplimiento.preventivo.length - 1];
    const fuentes = (cp.fuentes || []).filter(f => f.activa);
    const fuera = (cp.fuentes || []).filter(f => !f.activa);
    const floja = fuentes.filter(f => f.pct != null).sort((a, b) => a.pct - b.pct)[0];
    h += sec('05', 'Cumplimiento del programa preventivo',
        `La barra clara es lo que pide el programa; la de color es lo ejecutado, separado por fuente.`,
        `"El programa preventivo cerro en <b>${nf(cp.pct)} %</b>: ${cp.ejecutadas} actividades
         ejecutadas de ${cp.programadas} que pide el programa.<br><br>`
        + fuentes.map(f => `${esc(f.nombre)}: <b>${f.ejecutadas} de ${f.programadas}</b>`
            + (f.pct != null ? ` (${nf(f.pct)} %)` : '')).join('.<br>')
        + `.<br><br>Esto <b>no son solo las ordenes de trabajo</b>: la lubricacion, las rutas de
           inspeccion y el monitoreo tambien son preventivo y viven fuera de las OTs. Presentar solo
           las ordenes daria ${cp.solo_ot && cp.solo_ot.pct != null ? nf(cp.solo_ot.pct) + ' %' : '—'},
           que es cierto pero cuenta una parte chica del trabajo."`,
        (floja && floja.pct != null && floja.pct < 90
            ? `<div class="gav"><b>Prepara esta:</b> lo mas flojo es
               <b>${esc(floja.nombre)}</b> con ${nf(floja.pct)} %. Antes de presentar confirma si es
               que <b>no se hizo</b> o que <b>no se registro</b> — son dos conversaciones muy
               distintas y te la van a preguntar.</div>` : '')
        + (fuera.length
            ? `<b>Si preguntan por ${fuera.map(f => esc(f.nombre)).join(' y ')}:</b>
               <span class="q">"${fuera.length > 1 ? 'Estan' : 'Esta'} en implementacion. Los programas
               que todavia no estan en vigor se listan con su plan pero no entran al indicador,
               porque seria cobrar trabajo que aun no se le exige a nadie. El dia que arranquen,
               entran."</span><br>` : '')
        + `<b>Referencia:</b> SMRP pide mas de 90 %.`);

    // ── 06 Correctivo programado ────────────────────────────────────────
    const cc = PRES.cumplimiento.correctivo[PRES.cumplimiento.correctivo.length - 1];
    h += sec('06', 'Cumplimiento de correctivo programado',
        `Correctivos que tenian fecha planificada, contra los que se terminaron dentro del periodo.`,
        cc.programados
            ? `"De ${cc.programados} correctivos programados se terminaron <b>${cc.terminados}</b>:
               <b>${nf(cc.pct)} %</b>. ${cc.pct >= 90
                 ? 'Lo programado se esta cumpliendo.'
                 : 'Lo que queda abierto pasa al backlog y compite con el preventivo del proximo periodo.'}"`
            : `"No hubo correctivos con fecha programada en el periodo."`,
        `<b>Si preguntan la diferencia con el preventivo:</b> <span class="q">"El preventivo es lo que
         yo decido hacer para que no falle. El correctivo programado es una falla que ya ocurrio pero
         que pude planificar en vez de atender de emergencia. Que suba este numero es bueno: significa
         que estoy planificando en vez de apagando incendios."</span>`);

    // ── 07 Confiabilidad ────────────────────────────────────────────────
    const peorC = peorPor(areas, 'confiabilidad', true);
    h += sec('07', 'Confiabilidad',
        `Probabilidad de operar ${m.horizonte_h} horas seguidas sin fallar. Un equipo sin averias da 100 %.`,
        `"La confiabilidad de planta es <b>${nf(pl.confiabilidad)} %</b>: esa es la probabilidad de
         aguantar <b>${nf(m.horizonte_h, 0)} horas seguidas</b> — una semana de operacion continua —
         sin una averia.
         ${peorC ? `La mas baja es <b>${esc(peorC.area)}</b> con ${nf(peorC.actual.confiabilidad)} %.` : ''}
         <br><br>Confiabilidad no es solo que no falle: es <b>controlar y predecir</b> la falla. Sobre
         esto se actua con ruta predictiva, analisis causa raiz, mejoras de diseño y monitoreo en
         linea."`,
        `<b>Si preguntan de donde sale ese porcentaje:</b> <span class="q">"Es R(t) = e elevado a
         menos t sobre MTBF, con t de una semana. Sale del MTBF, no es una opinion. Esta la formula
         resuelta con estos mismos numeros en el modulo Como se calculan."</span>`);

    // ── Cierre ──────────────────────────────────────────────────────────
    const compromisos = [];
    if (peorD) compromisos.push(`atacar <b>${esc(peorD.area)}</b>, que es la que baja la disponibilidad`);
    if (peorR && peorR.actual.mttr > 0) compromisos.push(`bajar el MTTR de <b>${esc(peorR.area)}</b>
        (${nf(peorR.actual.mttr)} h) revisando repuestos y tiempos de espera`);
    if (floja && floja.pct != null && floja.pct < 90)
        compromisos.push(`cerrar la brecha de <b>${esc(floja.nombre)}</b> en el programa preventivo`);
    h += sec('08', 'Como cerrar',
        `Tres compromisos concretos, sacados de los mismos numeros. No prometas mas de tres.`,
        `"Me llevo tres cosas de este periodo: ${compromisos.map((c, i) =>
            `${i + 1}) ${c}`).join('; ')}.
         ${req.length && req.some(r => !r.alcanzable)
            ? 'Y dejo sobre la mesa que hay una meta por encima de la capacidad instalada, que no se resuelve con mantenimiento.'
            : 'Los numeros estan en el sistema y cualquiera puede abrirlos orden por orden.'}"`,
        `<b>Si te piden el detalle despues:</b> el modulo <b>Como se calculan</b> tiene cada formula
         resuelta con estos mismos numeros y las ordenes que la alimentan.`);

    return h;
}

function abrirGuion() {
    if (!PRES) { alert('Primero carga los indicadores.'); return; }
    el('guionSub').textContent = `${PRES.meta.periodo_actual} · disponibilidad ${PRES.meta.modo}`
        + ` · generado con los numeros en pantalla, sin IA`;
    el('guionCuerpo').innerHTML = generarGuion();
    el('modalGuion').classList.add('open');
    document.body.classList.add('con-guion');
}
function cerrarGuion() {
    el('modalGuion').classList.remove('open');
    document.body.classList.remove('con-guion');
}
window.abrirGuion = abrirGuion;
window.cerrarGuion = cerrarGuion;

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
    el('detKpis').innerHTML = ''; el('detLineas').innerHTML = '';
    el('detEquipos').innerHTML = ''; el('detOts').innerHTML = '';
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

        // Las lineas primero: son la unidad de medida de la disponibilidad,
        // porque dentro de ellas los equipos van en serie.
        el('detLineas').innerHTML = (d.lineas || []).length
            ? `<tr><th>Línea</th><th class="num">Capacidad</th><th class="num">Disponibilidad</th>
               <th class="num">Horas de parada</th><th>Qué la detuvo</th></tr>`
              + d.lineas.map(l => `<tr class="${l.pesa ? '' : 'apagado'}">
                <td><b>${esc(l.linea)}</b> <span class="hint">${l.equipos} equipos en serie</span></td>
                <td class="num">${l.pesa ? nf(l.capacidad) + ' TM/día' : '—'}</td>
                <td class="num ${l.pesa ? clase('disponibilidad', l.disponibilidad) : ''}">${l.pesa ? nf(l.disponibilidad) + ' %' : 'no pondera'}</td>
                <td class="num">${nf(l.horas_paro)} h</td>
                <td>${l.detuvieron.length
                    ? l.detuvieron.map(x => `${esc(x.equipo)} <span class="hint">${nf(x.horas)} h`
                        + `${x.auxiliar ? ' · auxiliar' : ''}</span>`).join(' · ')
                    : '<span class="hint">sin paradas</span>'}</td></tr>`).join('')
            : `<tr><td class="hint">Sin líneas con movimiento en el periodo.</td></tr>`;

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
    if (e.key === 'Escape' && el('modalGuion').classList.contains('open')) { cerrarGuion(); return; }
    if (e.key === 'Escape' && el('modalDet').classList.contains('open')) { cerrarDetalle(); return; }
    if (!document.body.classList.contains('presenting')) return;
    if (e.key === 'ArrowRight' || e.key === 'PageDown' || e.key === ' ') { e.preventDefault(); nextSlide(); }
    else if (e.key === 'ArrowLeft' || e.key === 'PageUp') { e.preventDefault(); prevSlide(); }
    else if (e.key === 'Escape') { togglePresent(); }
}
