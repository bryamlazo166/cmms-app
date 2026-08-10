// Metodologia de los indicadores: la formula y su sustitucion con los
// numeros reales del periodo. El objetivo es que la jefatura pueda cuadrar
// a mano cualquier cifra de la presentacion.
let MET = null;

document.addEventListener('DOMContentLoaded', () => {
    const hoy = new Date();
    const ant = new Date(hoy.getFullYear(), hoy.getMonth() - 1, 1);
    el('metMonth').value = `${ant.getFullYear()}-${String(ant.getMonth() + 1).padStart(2, '0')}`;
    cargar();
});

function el(id) { return document.getElementById(id); }
function nf(x, d) {
    if (x == null) return '—';
    return Number(x).toLocaleString('es-PE', {
        minimumFractionDigits: d == null ? 2 : d, maximumFractionDigits: d == null ? 2 : d });
}
function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"]/g,
        c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}
// Resalta las cifras dentro del bloque de sustitucion
function n(x, d) { return `<span class="num">${nf(x, d)}</span>`; }
function cmt(t) { return `<span class="cmt">${esc(t)}</span>`; }
// Alinea la columna de comentarios sin depender de contar espacios a mano
function fila(izq, comentario) {
    const ancho = 46;
    const relleno = ' '.repeat(Math.max(2, ancho - largoVisible(izq)));
    return izq + relleno + (comentario ? cmt(comentario) : '');
}
function largoVisible(html) { return html.replace(/<[^>]*>/g, '').length; }

async function cargar() {
    const q = new URLSearchParams({ month: el('metMonth').value, modo: el('metModo').value });
    try {
        const r = await fetch(`/api/metodologia/data?${q}`);
        MET = await r.json();
        if (MET.error) {
            el('avisoErr').innerHTML = `<div class="ficha"><div class="nota rojo">${esc(MET.error)}</div></div>`;
            return;
        }
        el('avisoErr').innerHTML = '';
        el('genAt').textContent = `generado ${MET.meta.generado}`;
        base();
        disponibilidad();
        mtbf();
        mttr();
        confiabilidad();
        ponderacion();
        capacidad();
    } catch (e) {
        el('avisoErr').innerHTML = `<div class="ficha"><div class="nota rojo">No se pudo cargar: ${esc(e.message)}</div></div>`;
    }
}
window.cargar = cargar;

function cabecera() {
    const e = MET.ejemplo;
    return cmt(`Ejemplo con datos reales · ${MET.meta.periodo} · equipo ${e.equipo}`
             + ` (${e.equipo_nombre || e.area}) — el de mayor paro del proceso`) + '\n\n';
}

// ── 01 Base de tiempo ────────────────────────────────────────────────────
function base() {
    const e = MET.ejemplo;
    el('s1').innerHTML = cabecera()
        + fila(`T  = ${n(e.dias, 0)} dias × 24 = ${n(e.tep, 0)} h`, 'horas del periodo') + '\n'
        + fila(`Pp = ${n(e.paro_planificado)} h`, 'paro planificado') + '\n'
        + fila(`Pn = ${n(e.paro_averia)} h`, 'paro por averia') + '\n'
        + fila(`uptime = ${n(e.tep, 0)} − ${n(e.paro_planificado)} − ${n(e.paro_averia)} = ${n(e.uptime)} h`,
               'horas realmente operando');

    const ots = e.ots || [];
    el('t1').innerHTML = ots.length
        ? `<tr><th>OT</th><th>Tipo</th><th>Fecha</th><th>Descripcion</th>
           <th class="num">Horas de parada</th><th>¿Entra al indicador?</th></tr>`
          + ots.map(o => `<tr class="${o.cuenta ? '' : 'apagado'}">
              <td><b>${esc(o.code)}</b></td><td>${esc(o.tipo)}</td><td>${esc(o.fecha)}</td>
              <td>${esc(o.descripcion)}</td>
              <td class="num">${o.horas ? nf(o.horas) + ' h' : '—'}</td>
              <td>${o.cuenta ? 'si' : 'no — sin parada registrada'}</td></tr>`).join('')
          + `<tr><td colspan="4"><b>Total</b></td>
             <td class="num"><b>${nf(ots.reduce((a, o) => a + o.horas, 0))} h</b></td><td></td></tr>`
        : `<tr><td class="hint">El equipo no tuvo ordenes cerradas en el periodo.</td></tr>`;
}

// ── 02 Disponibilidad ────────────────────────────────────────────────────
function disponibilidad() {
    const e = MET.ejemplo, inh = MET.meta.modo === 'inherente';
    el('s2').innerHTML = cabecera()
        + `operativa = (${n(e.tep, 0)} − ${n(e.paro_planificado)} − ${n(e.paro_averia)}) / ${n(e.tep, 0)}\n`
        + `          = ${n(e.uptime)} / ${n(e.tep, 0)}\n\n`
        + `inherente = (${n(e.tep, 0)} − ${n(e.paro_planificado)} − ${n(e.paro_averia)}) / (${n(e.tep, 0)} − ${n(e.paro_planificado)})\n`
        + `          = ${n(e.uptime)} / ${n(e.base_inherente)}`;
    el('r2').innerHTML =
        `operativa = ${nf(e.disp_operativa)} %     inherente = ${nf(e.disp_inherente)} %`
        + `   ${inh ? '← la que se presenta' : '← se presenta la operativa'}`;
}

// ── 03 MTBF ──────────────────────────────────────────────────────────────
function mtbf() {
    const e = MET.ejemplo;
    el('s3').innerHTML = cabecera()
        + (e.fallas
            ? `MTBF = ${n(e.uptime)} / ${n(e.fallas, 0)} falla(s)`
            : fila(`sin fallas en el periodo`, 'MTBF = la base de tiempo completa'));
    el('r3').innerHTML = `MTBF = ${nf(e.mtbf)} h    (TEP del periodo = ${nf(e.tep, 0)} h)`;
}

// ── 04 MTTR ──────────────────────────────────────────────────────────────
function mttr() {
    const e = MET.ejemplo;
    el('s4').innerHTML = cabecera()
        + (e.fallas
            ? `MTTR = ${n(e.paro_del_modo)} h de parada / ${n(e.fallas, 0)} falla(s)`
            : fila(`sin fallas en el periodo`, 'MTTR = 0'));
    el('r4').innerHTML = `MTTR = ${nf(e.mttr)} h por averia`;
}

// ── 05 Confiabilidad ─────────────────────────────────────────────────────
function confiabilidad() {
    const e = MET.ejemplo;
    el('s5').innerHTML = cabecera()
        + (e.fallas
            ? `R(t) = e^(−${n(e.horizonte, 0)} / ${n(e.mtbf)})`
            : fila(`sin fallas en el periodo`, 'R(t) = 100 %'));
    el('r5').innerHTML = `R(168 h) = ${nf(e.confiabilidad)} %`;
}

// ── 06 Ponderacion por capacidad ─────────────────────────────────────────
function ponderacion() {
    const p = MET.ponderacion;
    el('s6').innerHTML = cmt(`Ejemplo con datos reales · ${MET.meta.periodo} · area ${p.area}`) + '\n\n'
        + `Σ (disponibilidad × capacidad) = ${n(p.numerador)}\n`
        + `Σ capacidad                    = ${n(p.denominador)} TM/dia\n`
        + `${n(p.numerador)} / ${n(p.denominador)}`;
    el('r6').innerHTML = `Disponibilidad del area ${esc(p.area)} = ${nf(p.resultado)} %`;

    el('t6').innerHTML =
        `<tr><th>Equipo</th><th class="num">Capacidad TM/dia</th><th class="num">Disponibilidad</th>
         <th class="num">Aporte (disp × cap)</th></tr>`
        + p.filas.map(f => `<tr class="${f.pesa ? '' : 'apagado'}">
            <td><b>${esc(f.equipo)}</b></td>
            <td class="num">${f.pesa ? nf(f.capacidad) : '0 — no pesa'}</td>
            <td class="num">${nf(f.disponibilidad)} %</td>
            <td class="num">${f.pesa ? nf(f.aporte) : '—'}</td></tr>`).join('')
        + `<tr><td><b>Total</b></td><td class="num"><b>${nf(p.denominador)}</b></td><td></td>
           <td class="num"><b>${nf(p.numerador)}</b></td></tr>`;

    const dif = (p.resultado != null && p.promedio_simple != null)
        ? Math.round((p.promedio_simple - p.resultado) * 100) / 100 : null;
    el('n6').innerHTML = dif == null
        ? 'El area no tiene equipos con capacidad configurada.'
        : `Con <b>promedio simple</b> (todos los equipos valiendo igual) el area daria `
          + `<b>${nf(p.promedio_simple)} %</b> en vez de <b>${nf(p.resultado)} %</b>: `
          + `${Math.abs(dif)} puntos de diferencia. El promedio simple oculta que el equipo que paro `
          + `es de los que mas producen — por eso se pondera.`;
}

// ── 07 Capacidad: una etapa por vez, cada una con su cuenta ──────────────
function capacidad() {
    const c = MET.capacidad;
    if (c) {
        el('s7').innerHTML = cmt(`Ejemplo de coccion · digestor ${c.equipo}`) + '\n\n'
            + fila(`${n(c.kg, 0)} kg × ${n(c.llenado, 0)} % × ${n(c.llenadas, 0)} llenadas / 1000`,
                   'lo que entra al digestor') + '\n'
            + fila(`= ${n(c.tm_mp)} TM/dia de materia prima`, '') + '\n'
            + fila(`× ${n(c.rendimiento, 0)} % de rendimiento`, 'lo que sale como harina');
        el('r7').innerHTML = `${esc(c.equipo)} = ${nf(c.tm_harina)} TM/dia de harina`;
    } else {
        el('s7').innerHTML = cmt('No hay digestores configurados.');
        el('r7').innerHTML = '';
    }
    etapas();
}

const TITULO_ETAPA = { COCCION: 'Cocción — genera la harina',
                       SECADOR: 'Secado — procesa la harina',
                       SECADO: 'Secado — procesa la harina',
                       MOLINO: 'Molienda — procesa la harina',
                       MOLIENDA: 'Molienda — procesa la harina' };

function etapas() {
    const cont = el('etapasBloque');
    if (!cont) return;
    const ets = MET.etapas || [];
    if (!ets.length) { cont.innerHTML = ''; el('n7').innerHTML = ''; return; }

    cont.innerHTML = ets.map((et, i) => {
        const esCuello = et.etapa === MET.cuello;
        const filas = et.filas.map(f => {
            const calc = f.por_lotes
                ? `${nf(f.kg, 0)} kg × ${nf(f.llenado, 0)} % × ${nf(f.llenadas, 0)} / 1000 `
                  + `= ${nf(f.capacidad_cruda)} TM MP × ${nf(MET.meta.rendimiento_pct, 0)} %`
                : `${nf(f.capacidad_cruda)} TM/dia configurados — sin rendimiento`;
            return `<tr class="${f.en_servicio ? '' : 'apagado'}">
                <td><b>${esc(f.equipo)}</b> <span class="hint">${esc(f.nombre)}</span></td>
                <td class="calc">${calc}</td>
                <td class="num">${f.en_servicio ? nf(f.tm_harina) + ' TM/dia'
                    : 'fuera de servicio' + (f.motivo ? ' — ' + esc(f.motivo) : '')}</td></tr>`;
        }).join('');
        return `${i ? '<div class="flecha">↓</div>' : ''}
            <div class="etapa${esCuello ? ' cuello' : ''}">
              <div class="cab"><span class="nom">${esc(TITULO_ETAPA[et.etapa] || et.etapa)}</span>
                ${esCuello ? '<span class="chip abierto">cuello de botella</span>' : ''}
                <span class="tot">${nf(et.tm_dia)} TM/día</span></div>
              <div class="como">${et.aplica_rendimiento
                  ? `Base <b>materia prima</b>: se le aplica el rendimiento de ${nf(MET.meta.rendimiento_pct, 0)} %.`
                  : `Base <b>harina</b>: la capacidad ya está en producto, no se le aplica rendimiento.`}
                  ${et.operativos} de ${et.equipos} equipos en servicio${
                  et.fuera_servicio.length ? ` · fuera: ${et.fuera_servicio.map(esc).join(', ')}` : ''}.</div>
              <div class="twrap"><table class="met">
                <tr><th>Equipo</th><th>Cómo sale su capacidad</th><th class="num">Aporta</th></tr>
                ${filas}
                <tr><td><b>Total de la etapa</b></td><td></td>
                    <td class="num"><b>${nf(et.tm_dia)} TM/día</b></td></tr>
              </table></div>
            </div>`;
    }).join('');

    const cuello = ets.find(e => e.etapa === MET.cuello);
    const otras = ets.filter(e => e.etapa !== MET.cuello && e.tm_dia > 0);
    el('n7').innerHTML = !cuello ? ''
        : `<b>Capacidad de planta = ${nf(MET.planta_tm_dia)} TM/día</b>, la de
           ${esc(TITULO_ETAPA[cuello.etapa] || cuello.etapa).split('—')[0].trim()}.
           No es la suma de las tres: van en serie, así que manda la más corta.
           ${otras.length ? `Las demás etapas tienen holgura (${otras.map(o =>
               `${esc(o.etapa)} ${nf(o.tm_dia)}`).join(' · ')} TM/día), y esa holgura no
               produce nada mientras la etapa limitante no suba.` : ''}`;
}
