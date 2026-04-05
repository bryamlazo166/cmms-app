document.addEventListener('DOMContentLoaded', () => {
    loadDashboardData();
});

async function loadDashboardData() {
    try {
        const res = await fetch('/api/dashboard-stats');
        const data = await res.json();

        if (data.error) {
            console.error(data.error);
            return;
        }

        // 1. Update KPIs
        animateValue("kpiOpenOTs", 0, data.kpi.open_ots, 1000);
        animateValue("kpiPendingNotices", 0, data.kpi.pending_notices, 1000);
        animateValue("kpiClosedOTs", 0, data.kpi.closed_ots, 1000);
        animateValue("kpiActiveTechs", 0, data.kpi.active_techs, 1000);

        // 2. Charts
        renderStatusChart(data.charts.status);
        renderTypeChart(data.charts.types);
        renderFailureChart(data.charts.failures);

        // 3. Recent Activity
        renderRecentActivity(data.recent);

    } catch (e) {
        console.error("Dashboard Load Error:", e);
    }
}

function animateValue(id, start, end, duration) {
    const obj = document.getElementById(id);
    let startTimestamp = null;
    const step = (timestamp) => {
        if (!startTimestamp) startTimestamp = timestamp;
        const progress = Math.min((timestamp - startTimestamp) / duration, 1);
        obj.innerHTML = Math.floor(progress * (end - start) + start);
        if (progress < 1) {
            window.requestAnimationFrame(step);
        }
    };
    window.requestAnimationFrame(step);
}

function renderStatusChart(data) {
    const ctx = document.getElementById('statusChart').getContext('2d');
    const labels = Object.keys(data);
    const values = Object.values(data);

    const colors = {
        'Abierta': '#FF9F0A',
        'Programada': '#0A84FF',
        'En Progreso': '#5AC8FA',
        'Cerrada': '#30D158'
    };

    new Chart(ctx, {
        type: 'bar', // or 'doughnut'
        data: {
            labels: labels,
            datasets: [{
                label: 'Cantidad de OTs',
                data: values,
                backgroundColor: labels.map(l => colors[l] || '#777'),
                borderWidth: 0,
                borderRadius: 4
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false }
            },
            scales: {
                y: { grid: { color: 'rgba(255,255,255,0.08)' } },
                x: { grid: { display: false } }
            }
        }
    });
}

function renderTypeChart(data) {
    const ctx = document.getElementById('typeChart').getContext('2d');
    new Chart(ctx, {
        type: 'doughnut',
        data: {
            labels: Object.keys(data),
            datasets: [{
                data: Object.values(data),
                backgroundColor: ['#BF5AF2', '#5E5CE6', '#0A84FF', '#FF453A'],
                borderWidth: 0
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { position: 'right' }
            }
        }
    });
}

function renderFailureChart(dataArray) {
    const ctx = document.getElementById('failureChart').getContext('2d');
    const labels = dataArray.map(x => x.mode);
    const values = dataArray.map(x => x.count);

    new Chart(ctx, {
        type: 'bar',
        indexAxis: 'y', // Horizontal
        data: {
            labels: labels,
            datasets: [{
                label: 'Frecuencia',
                data: values,
                backgroundColor: '#FF453A',
                borderRadius: 4
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { display: false } },
            scales: {
                x: { grid: { color: 'rgba(255,255,255,0.08)' } },
                y: { grid: { display: false } }
            }
        }
    });
}

function renderRecentActivity(list) {
    const container = document.getElementById('activityListBody');
    if (list.length === 0) {
        container.innerHTML = '<div style="padding:20px; text-align:center; color:#666;">No hay actividad reciente</div>';
        return;
    }

    container.innerHTML = list.map(item => `
        <div class="activity-item">
            <div>
                <strong style="color: #0A84FF;">${item.code}</strong>
                <span style="color:rgba(255,255,255,.40); font-size:0.85em;"> ${item.date || ''}</span>
                ${item.equipment ? `<span style="color:#5AC8FA;font-size:0.82em;margin-left:6px">${item.equipment}</span>` : ''}
                <div style="font-size:0.88em; margin-top:3px;color:rgba(255,255,255,.65);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:380px">${item.description || '-'}</div>
            </div>
            <span class="badge ${getStatusClass(item.status)}">${item.status}</span>
        </div>
    `).join('');
}

function getStatusClass(status) {
    if (status === 'Abierta') return 'status-open';
    if (status === 'En Progreso') return 'status-progress';
    if (status === 'Cerrada') return 'status-closed';
    return '';
}

// ── Industrial KPIs — Stacked drill-down: Area → Line → Equipment → Events ──

const TH = 'padding:9px 10px;font-size:.73rem;font-weight:600;text-transform:uppercase;letter-spacing:.4px;color:rgba(255,255,255,.50);position:sticky;top:0;z-index:1;background:#2C2C2E';
const TD = 'padding:9px 10px;font-size:.84rem';
const PANEL_CSS = 'background:var(--bg-primary,#1C1C1E);border:1px solid rgba(255,255,255,.08);border-radius:14px;padding:12px';
const LEVELS = ['area', 'line', 'equipment', 'events'];

let kpiCache = {};
let selectedIds = {}; // { area: id, line: id, equipment: id }

function availColor(v) {
    if (v == null) return 'rgba(255,255,255,.40)';
    if (v >= 95) return '#30D158';
    if (v >= 85) return '#FFD60A';
    return '#FF453A';
}

function renderGlobalKPIs(k) {
    document.getElementById('gMtbf').textContent = k.global_mtbf != null ? k.global_mtbf : '-';
    document.getElementById('gMttr').textContent = k.global_mttr != null ? k.global_mttr : '-';
    document.getElementById('gAvail').textContent = k.global_availability != null ? k.global_availability + '%' : '-';
    document.getElementById('gRatio').textContent = k.ratio_preventive != null ? k.ratio_preventive + '%' : '-';
    document.getElementById('gDown').textContent = k.global_downtime_h != null ? k.global_downtime_h : '-';
    document.getElementById('gFails').textContent = k.total_failures || 0;
}

async function fetchKPIs(level, areaId, lineId) {
    const days = document.getElementById('kpiDays').value;
    let url = `/api/dashboard-kpis?days=${days}&level=${level}`;
    if (areaId) url += `&area_id=${areaId}`;
    if (lineId) url += `&line_id=${lineId}`;
    const res = await fetch(url);
    const data = await res.json();
    if (data.error) throw new Error(data.error);
    return data;
}

function hidePanelsFrom(levelIndex) {
    for (let i = levelIndex; i < LEVELS.length; i++) {
        const panel = document.getElementById('kpiPanel' + capitalize(LEVELS[i]));
        if (panel) { panel.style.display = 'none'; panel.innerHTML = ''; }
    }
}

function capitalize(s) { return s.charAt(0).toUpperCase() + s.slice(1); }

function buildKpiTable(items, level, title) {
    const levelLabels = { area: 'Area', line: 'Linea', equipment: 'Equipo' };
    const nextLevel = level === 'area' ? 'line' : level === 'line' ? 'equipment' : 'events';

    let html = `<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px">
        <h3 style="color:rgba(255,255,255,.88);font-size:.95rem;margin:0"><i class="fas fa-layer-group" style="color:var(--sys-teal,#5AC8FA);margin-right:6px"></i>${title}</h3>
    </div>`;

    if (!items.length) {
        return html + '<p style="color:rgba(255,255,255,.30);text-align:center;padding:16px">Sin datos para este periodo.</p>';
    }

    html += '<div style="overflow-x:auto;max-height:350px;border-radius:8px"><table style="width:100%;border-collapse:collapse;min-width:850px">';
    html += `<thead><tr style="background:#2C2C2E">
        <th style="${TH};text-align:left">${levelLabels[level] || 'Nombre'}</th>
        <th style="${TH};text-align:right">OTs</th><th style="${TH};text-align:right">Fallas</th>
        <th style="${TH};text-align:right">MTBF</th><th style="${TH};text-align:right">MTTR</th>
        <th style="${TH};text-align:right">Disp %</th><th style="${TH};text-align:right">Conf %</th>
        <th style="${TH};text-align:right">Parada h</th><th style="${TH};text-align:right">P/C %</th>
    </tr></thead><tbody>`;

    html += items.map(it => {
        const ac = availColor(it.availability);
        const sel = selectedIds[level] === it.id;
        const rowBg = sel ? 'background:rgba(10,132,255,.12);' : '';
        const esc = (it.label || '').replace(/"/g, '&quot;');
        return `<tr style="${rowBg}cursor:pointer;border-bottom:1px solid rgba(255,255,255,.06)" onclick="selectLevel('${level}', ${it.id}, '${esc}')">
            <td style="${TD};color:rgba(255,255,255,.88)">${sel ? '<i class="fas fa-chevron-down" style="color:#0A84FF;margin-right:5px;font-size:.7rem"></i>' : '<i class="fas fa-chevron-right" style="color:rgba(255,255,255,.20);margin-right:5px;font-size:.7rem"></i>'}${it.label}</td>
            <td style="${TD};color:rgba(255,255,255,.65);text-align:right">${it.total_ots}</td>
            <td style="${TD};color:#FF453A;text-align:right;font-weight:600">${it.failures}</td>
            <td style="${TD};color:#5AC8FA;text-align:right">${it.mtbf != null ? it.mtbf : '-'}</td>
            <td style="${TD};color:#FF9F0A;text-align:right">${it.mttr != null ? it.mttr : '-'}</td>
            <td style="${TD};color:${ac};text-align:right;font-weight:700">${it.availability != null ? it.availability + '%' : '-'}</td>
            <td style="${TD};color:rgba(255,255,255,.65);text-align:right">${it.reliability != null ? it.reliability + '%' : '-'}</td>
            <td style="${TD};color:rgba(255,255,255,.65);text-align:right">${it.downtime_hours}</td>
            <td style="${TD};color:#BF5AF2;text-align:right">${it.ratio_preventive != null ? it.ratio_preventive + '%' : '-'}</td>
        </tr>`;
    }).join('');

    html += '</tbody></table></div>';
    return html;
}

function buildEventsTable(ots, title) {
    let html = `<div style="display:flex;align-items:center;margin-bottom:8px">
        <h3 style="color:rgba(255,255,255,.88);font-size:.95rem;margin:0"><i class="fas fa-search" style="color:var(--sys-blue,#0A84FF);margin-right:6px"></i>${title}</h3>
    </div>`;

    if (!ots.length) {
        return html + '<p style="color:rgba(255,255,255,.30);text-align:center;padding:16px">Sin eventos para este equipo.</p>';
    }

    html += '<div style="overflow-x:auto;max-height:300px;border-radius:8px"><table style="width:100%;border-collapse:collapse;min-width:750px">';
    html += `<thead><tr style="background:#2C2C2E">
        <th style="${TH};text-align:left">OT</th><th style="${TH};text-align:left">Fecha</th>
        <th style="${TH};text-align:left">Tipo</th><th style="${TH};text-align:left">Modo Falla</th>
        <th style="${TH};text-align:right">Reparacion h</th><th style="${TH};text-align:left">Descripcion</th>
    </tr></thead><tbody>`;
    html += ots.map(ot => `<tr style="border-bottom:1px solid rgba(255,255,255,.06)">
        <td style="${TD};color:#0A84FF;font-weight:600">${ot.code || '-'}</td>
        <td style="${TD};color:rgba(255,255,255,.70)">${ot.date || '-'}</td>
        <td style="${TD};color:rgba(255,255,255,.65)">${ot.type || '-'}</td>
        <td style="${TD};color:rgba(255,255,255,.65)">${ot.failure_mode || '-'}</td>
        <td style="${TD};color:#FF9F0A;text-align:right">${ot.repair_h || '-'}</td>
        <td style="${TD};color:rgba(255,255,255,.55);font-size:.80rem;max-width:250px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${ot.description || '-'}</td>
    </tr>`).join('');
    html += '</tbody></table></div>';
    return html;
}

// ── Main navigation functions ────────────────────────────────────────────────

async function drillTo(level) {
    try {
        selectedIds = {};
        hidePanelsFrom(0);
        const data = await fetchKPIs('area', null, null);
        kpiCache.area = data;
        renderGlobalKPIs(data.kpis);
        const panel = document.getElementById('kpiPanelArea');
        panel.style.cssText = PANEL_CSS;
        panel.innerHTML = buildKpiTable(data.items, 'area', 'Indicadores por Area');
        loadTrends();
    } catch (e) { console.error('KPI drillTo error:', e); }
}

async function selectLevel(level, id, label) {
    try {
        // If clicking the same item again, deselect
        if (selectedIds[level] === id) {
            delete selectedIds[level];
            const nextIdx = LEVELS.indexOf(level) + 1;
            hidePanelsFrom(nextIdx);
            // Re-render current panel to remove highlight
            const panelId = 'kpiPanel' + capitalize(level);
            const panel = document.getElementById(panelId);
            panel.innerHTML = buildKpiTable(kpiCache[level].items, level,
                level === 'area' ? 'Indicadores por Area' :
                level === 'line' ? `Lineas de ${selectedIds.area_label || ''}` :
                `Equipos de ${selectedIds.line_label || ''}`);
            loadTrends();
            return;
        }

        selectedIds[level] = id;
        if (level === 'area') selectedIds.area_label = label;
        if (level === 'line') selectedIds.line_label = label;
        if (level === 'equipment') selectedIds.equipment_label = label;

        // Hide all panels below current
        const currentIdx = LEVELS.indexOf(level);
        hidePanelsFrom(currentIdx + 1);

        // Re-render current panel to show selection highlight
        const currentPanelId = 'kpiPanel' + capitalize(level);
        const currentPanel = document.getElementById(currentPanelId);
        const currentTitle = level === 'area' ? 'Indicadores por Area' :
            level === 'line' ? `Lineas de ${selectedIds.area_label || ''}` :
            `Equipos de ${selectedIds.line_label || ''}`;
        currentPanel.innerHTML = buildKpiTable(kpiCache[level].items, level, currentTitle);

        // Load next level
        if (level === 'area') {
            const data = await fetchKPIs('line', id, null);
            kpiCache.line = data;
            const panel = document.getElementById('kpiPanelLine');
            panel.style.cssText = PANEL_CSS + ';margin-top:10px';
            panel.innerHTML = buildKpiTable(data.items, 'line', `Lineas de ${label}`);
        } else if (level === 'line') {
            const data = await fetchKPIs('equipment', null, id);
            kpiCache.equipment = data;
            const panel = document.getElementById('kpiPanelEquipment');
            panel.style.cssText = PANEL_CSS + ';margin-top:10px';
            panel.innerHTML = buildKpiTable(data.items, 'equipment', `Equipos de ${label}`);
        } else if (level === 'equipment') {
            const eqData = kpiCache.equipment;
            if (eqData) {
                const item = eqData.items.find(it => it.id === id);
                if (item && item.ots) {
                    const panel = document.getElementById('kpiPanelEvents');
                    panel.style.cssText = PANEL_CSS + ';margin-top:10px';
                    panel.innerHTML = buildEventsTable(item.ots, `Eventos de ${label}`);
                }
            }
        }
        // Refresh trends with current selection
        loadTrends();
    } catch (e) { console.error('KPI selectLevel error:', e); }
}

// ── Generate Preventive OTs ──────────────────────────────────────────────────

async function generatePreventiveOTs() {
    const res = await fetch('/api/generate-preventive-ots', { method: 'POST' });
    const data = await res.json();
    if (data.error) { alert('Error: ' + data.error); return; }

    if (data.created === 0) {
        alert('No hay puntos vencidos sin aviso pendiente.\n' +
              (data.skipped ? `(${data.skipped} ya tienen aviso u OT abierta)` : ''));
    } else {
        let msg = `Se generaron ${data.created} avisos preventivos:\n\n`;
        data.items.forEach(it => {
            msg += `${it.code} - ${it.source} (${it.semaphore})\n`;
        });
        if (data.skipped) msg += `\n${data.skipped} puntos ya tenian aviso u OT abierta.`;
        msg += '\n\nRevisa el modulo de Avisos para crear OTs.';
        alert(msg);
    }
    // Reload dashboard data
    loadDashboardData();
    drillTo('area');
}

// ── Trends + Costs Charts ────────────────────────────────────────────────────

let trendAvailChart = null, trendCostChart = null;

async function loadTrends() {
    try {
        let url = '/api/dashboard-trends?months=12';
        // Pass current drill-down selection
        const label = document.getElementById('trendFilterLabel');
        if (selectedIds.equipment) {
            url += `&equipment_id=${selectedIds.equipment}`;
            if (label) label.textContent = `— ${selectedIds.equipment_label || 'Equipo'}`;
        } else if (selectedIds.line) {
            url += `&line_id=${selectedIds.line}`;
            if (label) label.textContent = `— ${selectedIds.line_label || 'Linea'}`;
        } else if (selectedIds.area) {
            url += `&area_id=${selectedIds.area}`;
            if (label) label.textContent = `— ${selectedIds.area_label || 'Area'}`;
        } else {
            if (label) label.textContent = '— Planta completa';
        }
        const res = await fetch(url);
        const data = await res.json();
        if (data.error) return;

        const months = data.trends.map(t => t.month);

        // Availability + MTBF chart
        const ctx1 = document.getElementById('trendAvailChart')?.getContext('2d');
        if (ctx1) {
            if (trendAvailChart) trendAvailChart.destroy();
            trendAvailChart = new Chart(ctx1, {
                type: 'line',
                data: {
                    labels: months,
                    datasets: [
                        {
                            label: 'Disponibilidad %',
                            data: data.trends.map(t => t.availability),
                            borderColor: '#30D158', backgroundColor: 'rgba(48,209,88,.12)',
                            fill: true, tension: 0.3, yAxisID: 'y',
                        },
                        {
                            label: 'MTBF (h)',
                            data: data.trends.map(t => t.mtbf),
                            borderColor: '#5AC8FA', borderDash: [4, 4],
                            fill: false, tension: 0.3, yAxisID: 'y1',
                        }
                    ]
                },
                options: {
                    responsive: true, maintainAspectRatio: false,
                    plugins: { legend: { labels: { color: 'rgba(255,255,255,.60)', font: { size: 11 } } } },
                    scales: {
                        x: { ticks: { color: 'rgba(255,255,255,.40)', font: { size: 10 } }, grid: { color: 'rgba(255,255,255,.06)' } },
                        y: { position: 'left', min: 0, max: 100, ticks: { color: '#30D158', font: { size: 10 } }, grid: { color: 'rgba(255,255,255,.06)' }, title: { display: true, text: 'Disp %', color: 'rgba(255,255,255,.40)' } },
                        y1: { position: 'right', ticks: { color: '#5AC8FA', font: { size: 10 } }, grid: { display: false }, title: { display: true, text: 'MTBF h', color: 'rgba(255,255,255,.40)' } },
                    }
                }
            });
        }

        // Cost chart
        const ctx2 = document.getElementById('trendCostChart')?.getContext('2d');
        if (ctx2) {
            if (trendCostChart) trendCostChart.destroy();
            trendCostChart = new Chart(ctx2, {
                type: 'bar',
                data: {
                    labels: months,
                    datasets: [
                        { label: 'Costo HH ($)', data: data.trends.map(t => t.cost_hh), backgroundColor: 'rgba(10,132,255,.50)', borderRadius: 3, stack: 'cost' },
                        { label: 'Costo Materiales ($)', data: data.trends.map(t => t.cost_materials), backgroundColor: 'rgba(255,159,10,.50)', borderRadius: 3, stack: 'cost' },
                    ]
                },
                options: {
                    responsive: true, maintainAspectRatio: false,
                    plugins: { legend: { labels: { color: 'rgba(255,255,255,.60)', font: { size: 11 } } } },
                    scales: {
                        x: { stacked: true, ticks: { color: 'rgba(255,255,255,.40)', font: { size: 10 } }, grid: { color: 'rgba(255,255,255,.06)' } },
                        y: { stacked: true, ticks: { color: 'rgba(255,255,255,.50)', font: { size: 10 } }, grid: { color: 'rgba(255,255,255,.06)' }, title: { display: true, text: 'Costo $', color: 'rgba(255,255,255,.40)' } },
                    }
                }
            });
        }

        // Cost table
        const tbody = document.getElementById('costTableBody');
        if (tbody && data.costs && data.costs.length) {
            const TD = 'padding:7px 10px;font-size:.82rem;border-bottom:1px solid rgba(255,255,255,.05)';
            tbody.innerHTML = data.costs.map(c => `<tr>
                <td style="${TD};color:#0A84FF;font-weight:600">${c.code}</td>
                <td style="${TD};color:rgba(255,255,255,.75)">${c.equipment}</td>
                <td style="${TD};color:rgba(255,255,255,.55)">${c.type || '-'}</td>
                <td style="${TD};text-align:right;color:rgba(255,255,255,.60)">${c.hh}h</td>
                <td style="${TD};text-align:right;color:#5AC8FA">$${c.cost_hh}</td>
                <td style="${TD};text-align:right;color:#FF9F0A">$${c.cost_materials}</td>
                <td style="${TD};text-align:right;color:#30D158;font-weight:600">$${c.cost_total}</td>
            </tr>`).join('');
        } else if (tbody) {
            tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;color:rgba(255,255,255,.30);padding:20px">Sin datos de costos.</td></tr>';
        }
    } catch (e) { console.error('Trends load error:', e); }
}

// ── Failure Recurrence ────────────────────────────────────────────────────
async function loadRecurrence() {
    const months = document.getElementById('recurrenceMonths')?.value || 6;
    const tbody = document.getElementById('recurrenceBody');
    if (!tbody) return;
    try {
        const res = await fetch(`/api/failure-recurrence?months=${months}&limit=15`);
        const data = await res.json();
        const items = data.by_component || [];
        if (!items.length) {
            tbody.innerHTML = '<tr><td colspan="8" style="text-align:center;color:rgba(255,255,255,.30);padding:20px">Sin datos de recurrencia en este periodo.</td></tr>';
            return;
        }
        tbody.innerHTML = items.map((r, i) => {
            const severity = r.wo_count >= 5 ? '#FF453A' : r.wo_count >= 3 ? '#FF9F0A' : '#30D158';
            const mtbf = r.mtbf_days ? `${r.mtbf_days}` : '-';
            const lastDate = r.last_wo ? r.last_wo.split('T')[0] : '-';
            return `<tr style="border-bottom:1px solid rgba(255,255,255,.05)">
                <td style="padding:7px 10px;font-size:.80rem;color:#888">${i + 1}</td>
                <td style="padding:7px 10px;font-size:.80rem;color:#ddd;font-weight:600">${r.component_name}</td>
                <td style="padding:7px 10px;font-size:.80rem;color:#aaa">${r.system_name}</td>
                <td style="padding:7px 10px;font-size:.80rem;color:#aaa">${r.equipment_name} [${r.equipment_tag}]</td>
                <td style="padding:7px 10px;font-size:.80rem;color:#aaa">${r.line_name}</td>
                <td style="padding:7px 10px;font-size:.80rem;text-align:center"><span style="background:${severity};color:#fff;padding:2px 8px;border-radius:999px;font-weight:700;font-size:.75rem">${r.wo_count}</span></td>
                <td style="padding:7px 10px;font-size:.80rem;text-align:center;color:${r.mtbf_days && r.mtbf_days < 30 ? '#FF453A' : '#ddd'}">${mtbf}</td>
                <td style="padding:7px 10px;font-size:.80rem;color:#888">${lastDate}</td>
            </tr>`;
        }).join('');
    } catch (e) {
        console.error('Recurrence error:', e);
        tbody.innerHTML = '<tr><td colspan="8" style="text-align:center;color:#FF6B61;padding:20px">Error cargando datos.</td></tr>';
    }
}

document.addEventListener('DOMContentLoaded', () => {
    setTimeout(() => drillTo('area'), 500);
    loadRecurrence();
});
