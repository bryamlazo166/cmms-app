/* Predictivo de Espesores — resumen por equipo, detalle por zona y análisis IA. */
let _selectedEq = null;

function esc(s) {
    const d = document.createElement('div');
    d.textContent = (s == null ? '' : String(s));
    return d.innerHTML;
}

function pill(status) {
    if (!status) return '<span class="pill SIN_DATOS">SIN DATOS</span>';
    const label = status === 'SIN_TENDENCIA' ? 'SIN TENDENCIA'
        : status === 'DATO_DUDOSO' ? 'DATO DUDOSO' : status;
    return `<span class="pill ${esc(status)}">${esc(label)}</span>`;
}

function fmtMonths(m) {
    if (m == null) return '—';
    if (m < 1) return '< 1 mes';
    if (m < 24) return `${m.toFixed(1)} meses`;
    return `${(m / 12).toFixed(1)} años`;
}

function fmtRate(r) {
    return r == null ? '—' : `${r.toFixed(2)} mm/año`;
}

async function loadSummary() {
    const grid = document.getElementById('summaryGrid');
    try {
        const r = await fetch('/api/thickness/predictive/summary');
        const data = await r.json();
        if (!r.ok) { grid.innerHTML = `<div class="empty">Error: ${esc(data.error || r.statusText)}</div>`; return; }
        if (!data.length) { grid.innerHTML = '<div class="empty">No hay equipos con puntos de espesor.</div>'; return; }
        grid.innerHTML = data.map(eq => {
            let worstHtml = '<span class="muted">Sin mediciones aún — programar 1ª campaña UT</span>';
            if (eq.worst && eq.worst.status) {
                const w = eq.worst;
                const sec = w.section ? ` s${w.section}` : '';
                let proj = '';
                if (w.months_to_scrap != null) {
                    proj = `<br>⏳ Llega al retiro en <b>${esc(fmtMonths(w.months_to_scrap))}</b> (${esc(w.scrap_date || '')})`;
                } else if (w.status === 'CRITICO') {
                    proj = '<br>🚨 <b>Ya está bajo el espesor de retiro</b>';
                }
                worstHtml = `Peor punto: <b>${esc(w.group_name)}${esc(sec)} ${esc(w.position)}</b> — ` +
                    `${w.current != null ? w.current.toFixed(1) : '?'} mm (retiro ${w.scrap})` +
                    `${w.rate_mm_yr ? ` · ${esc(fmtRate(w.rate_mm_yr))}` : ''}${proj}`;
            }
            const needs2nd = eq.campaigns === 1 ? ' · <span class="muted">falta 2ª campaña para tendencia</span>' : '';
            return `
            <div class="eq-card ${_selectedEq === eq.equipment_id ? 'sel' : ''}" onclick="loadDetail(${eq.equipment_id})" id="card-${eq.equipment_id}">
                <div style="display:flex;justify-content:space-between;align-items:center">
                    <span class="tag">[${esc(eq.tag || '?')}]</span>
                    ${pill(eq.semaforo)}
                </div>
                <div class="name">${esc(eq.name)}</div>
                <div class="row">
                    <span>📋 ${eq.campaigns} campaña(s)${eq.last_inspection ? ' · últ. ' + esc(eq.last_inspection) : ''}</span>
                </div>
                <div class="row">
                    <span>📍 ${eq.points_with_rate}/${eq.points_total} puntos con tendencia</span>
                    ${eq.interventions ? `<span class="interv">♻ ${eq.interventions} reemplazo(s) detectado(s)</span>` : ''}
                </div>
                <div class="worst">${worstHtml}${needs2nd}</div>
            </div>`;
        }).join('');
    } catch (e) {
        grid.innerHTML = `<div class="empty">Error: ${esc(e.message)}</div>`;
    }
}

async function loadDetail(eqId) {
    _selectedEq = eqId;
    document.querySelectorAll('.eq-card').forEach(c => c.classList.remove('sel'));
    const card = document.getElementById(`card-${eqId}`);
    if (card) card.classList.add('sel');

    const panel = document.getElementById('detailPanel');
    const zonesEl = document.getElementById('detailZones');
    const narrBox = document.getElementById('narrativeBox');
    narrBox.style.display = 'none'; narrBox.textContent = '';
    panel.style.display = '';
    zonesEl.innerHTML = '<div class="empty">Cargando detalle…</div>';
    try {
        const r = await fetch(`/api/thickness/predictive/${eqId}`);
        const d = await r.json();
        if (!r.ok) { zonesEl.innerHTML = `<div class="empty">Error: ${esc(d.error || r.statusText)}</div>`; return; }
        document.getElementById('detailTitle').innerHTML =
            `<i class="fas fa-ruler-vertical"></i> [${esc(d.tag)}] ${esc(d.name)} &nbsp;${pill(d.semaforo)}` +
            ` <span class="muted" style="font-size:.78rem">· ${d.campaigns} campañas · últ. ${esc(d.last_inspection || '—')}</span>`;

        zonesEl.innerHTML = d.zones.map(z => {
            const rows = z.points.map(p => {
                const sec = p.section != null ? ` s${p.section}` : '';
                let interv = (p.interventions || []).map(iv =>
                    `<span class="interv" title="Subió de ${iv.from_mm} a ${iv.to_mm} mm">♻ ${esc(iv.date)}</span>`).join(' ');
                if (p.discarded) {
                    interv += ` <span class="muted" title="Lecturas mayores al nominal ×1.10 — dato de relleno o nominal mal configurado. No se usan en la proyección.">⚠ ${p.discarded} descartada(s)</span>`;
                }
                const rowCls = (p.status === 'CRITICO' || p.status === 'ROJO') ? `r-${p.status}` : '';
                return `<tr class="${rowCls}">
                    <td>${esc(p.position)}${esc(sec)}</td>
                    <td class="num">${p.current != null ? p.current.toFixed(1) : '<span class="muted">sin medir</span>'}</td>
                    <td class="num muted">${p.nominal ?? '—'} / ${p.alarm ?? '—'} / ${p.scrap ?? '—'}</td>
                    <td class="num">${esc(fmtRate(p.rate_mm_yr))}</td>
                    <td class="num">${esc(fmtMonths(p.months_to_scrap))}</td>
                    <td class="num">${esc(p.scrap_date || '—')}</td>
                    <td>${pill(p.status)}</td>
                    <td class="num muted">${p.n_total || 0}</td>
                    <td>${interv || ''}</td>
                </tr>`;
            }).join('');
            return `
            <div class="zone-head"><h4>${esc(z.group_name)}</h4>${pill(z.worst_status)}
                ${z.worst_months != null ? `<span class="muted" style="font-size:.78rem">peor punto: ${esc(fmtMonths(z.worst_months))}</span>` : ''}
            </div>
            <div class="twrap"><table>
                <thead><tr>
                    <th>Punto</th><th>Actual (mm)</th><th>Nom/Alarma/Retiro</th><th>Tasa</th>
                    <th>Vida remanente</th><th>Fecha límite</th><th>Estado</th><th>Nº med.</th><th>Reemplazos</th>
                </tr></thead>
                <tbody>${rows}</tbody>
            </table></div>`;
        }).join('');
        panel.scrollIntoView({ behavior: 'smooth', block: 'start' });
    } catch (e) {
        zonesEl.innerHTML = `<div class="empty">Error: ${esc(e.message)}</div>`;
    }
}

async function loadNarrative() {
    if (!_selectedEq) return;
    const btn = document.getElementById('btnNarrative');
    const box = document.getElementById('narrativeBox');
    btn.disabled = true;
    btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Analizando…';
    box.style.display = ''; box.textContent = 'La IA está analizando las proyecciones de este equipo…';
    try {
        const r = await fetch(`/api/thickness/predictive/${_selectedEq}/narrative`, { method: 'POST' });
        const d = await r.json();
        box.textContent = r.ok ? d.narrative : `No se pudo generar el análisis: ${d.error || r.statusText}`;
    } catch (e) {
        box.textContent = 'Error de red generando el análisis.';
    } finally {
        btn.disabled = false;
        btn.innerHTML = '<i class="fas fa-robot"></i> Análisis IA';
    }
}

document.addEventListener('DOMContentLoaded', loadSummary);
