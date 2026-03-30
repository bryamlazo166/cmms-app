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
                <span style="color:#aaa; font-size:0.9em;"> - ${item.date || 'Sin Fecha'}</span>
                <div style="font-size:0.9em; margin-top:3px;">${item.description || 'Sin descripción'}</div>
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

// ── Industrial KPIs — Progressive drill-down: Area → Line → Equipment → Events

const TH = 'padding:9px 10px;font-size:.73rem;font-weight:600;text-transform:uppercase;letter-spacing:.4px;color:rgba(255,255,255,.50);position:sticky;top:0;z-index:1;background:#2C2C2E';
const TD = 'padding:9px 10px;font-size:.84rem;border-bottom:1px solid rgba(255,255,255,.06)';

let kpiCache = {};  // level → response data
let breadcrumb = []; // [{level, id, label}]

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

function renderBreadcrumb() {
    const el = document.getElementById('kpiBreadcrumb');
    const crumbs = [{level: 'area', id: null, label: 'Planta'}].concat(breadcrumb);
    el.innerHTML = crumbs.map((c, i) => {
        const isLast = i === crumbs.length - 1;
        const style = isLast
            ? 'color:rgba(255,255,255,.90);font-weight:600'
            : 'color:#0A84FF;cursor:pointer;text-decoration:underline';
        const click = isLast ? '' : `onclick="drillTo('${c.level}', ${c.id ? c.id : 'null'}, ${i})"`;
        return `<span style="${style}" ${click}>${c.label}</span>`;
    }).join('<span style="color:rgba(255,255,255,.25);margin:0 2px">/</span>');
}

function renderKpiRows(items, level) {
    const thead = document.getElementById('kpiTableHead');
    const tbody = document.getElementById('kpiTableBody');
    const levelLabels = { area: 'Area', line: 'Linea', equipment: 'Equipo', events: 'Eventos' };

    if (level === 'events') {
        thead.innerHTML = `<tr style="background:#2C2C2E">
            <th style="${TH};text-align:left">OT</th><th style="${TH};text-align:left">Fecha</th>
            <th style="${TH};text-align:left">Equipo</th><th style="${TH};text-align:left">Tipo</th>
            <th style="${TH};text-align:left">Modo Falla</th><th style="${TH};text-align:right">Reparacion h</th>
            <th style="${TH};text-align:left">Descripcion</th></tr>`;
        if (!items.length) {
            tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;color:rgba(255,255,255,.30);padding:24px">Sin eventos en este periodo.</td></tr>';
            return;
        }
        tbody.innerHTML = items.map(ot => `<tr style="${TD}">
            <td style="${TD};color:#0A84FF;font-weight:600">${ot.code || '-'}</td>
            <td style="${TD};color:rgba(255,255,255,.70)">${ot.date || '-'}</td>
            <td style="${TD};color:rgba(255,255,255,.85)">${ot.equipment || '-'}</td>
            <td style="${TD};color:rgba(255,255,255,.65)">${ot.type || '-'}</td>
            <td style="${TD};color:rgba(255,255,255,.65)">${ot.failure_mode || '-'}</td>
            <td style="${TD};color:#FF9F0A;text-align:right">${ot.repair_h || '-'}</td>
            <td style="${TD};color:rgba(255,255,255,.55);font-size:.80rem">${ot.description || '-'}</td>
        </tr>`).join('');
        return;
    }

    thead.innerHTML = `<tr style="background:#2C2C2E">
        <th style="${TH};text-align:left">${levelLabels[level] || 'Nombre'}</th>
        <th style="${TH};text-align:right">OTs</th><th style="${TH};text-align:right">Fallas</th>
        <th style="${TH};text-align:right">MTBF (h)</th><th style="${TH};text-align:right">MTTR (h)</th>
        <th style="${TH};text-align:right">Disp %</th><th style="${TH};text-align:right">Conf %</th>
        <th style="${TH};text-align:right">Parada h</th><th style="${TH};text-align:right">P/C %</th></tr>`;

    if (!items.length) {
        tbody.innerHTML = '<tr><td colspan="9" style="text-align:center;color:rgba(255,255,255,.30);padding:24px">Sin datos para el periodo seleccionado.</td></tr>';
        return;
    }

    tbody.innerHTML = items.map(it => {
        const ac = availColor(it.availability);
        const nextLevel = level === 'area' ? 'line' : level === 'line' ? 'equipment' : 'events';
        const escapedLabel = (it.label || '').replace(/'/g, "\\'");
        return `<tr style="cursor:pointer;border-bottom:1px solid rgba(255,255,255,.06)" onclick="drillNext('${nextLevel}', ${it.id}, '${escapedLabel}')">
            <td style="${TD};color:rgba(255,255,255,.88)">${it.label}<span style="color:rgba(255,255,255,.25);margin-left:6px;font-size:.75rem"><i class="fas fa-chevron-right"></i></span></td>
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
}

// Navigate to a level (called from breadcrumb or on page load)
async function drillTo(level, filterId, breadcrumbIdx) {
    try {
        if (breadcrumbIdx !== undefined) {
            breadcrumb = breadcrumb.slice(0, breadcrumbIdx);
        } else {
            breadcrumb = [];
        }

        const data = await fetchKPIs(level, null, null);
        renderGlobalKPIs(data.kpis);
        renderKpiRows(data.items, level);
        renderBreadcrumb();
        kpiCache[level] = data;
    } catch (e) {
        console.error('KPI drill error:', e);
    }
}

// Drill into next level (called from table row click)
async function drillNext(nextLevel, parentId, parentLabel) {
    try {
        // For events level, find the OTs from cached equipment data
        if (nextLevel === 'events') {
            const eqData = kpiCache['equipment'];
            if (eqData) {
                const item = eqData.items.find(it => it.id === parentId);
                if (item && item.ots) {
                    breadcrumb.push({level: 'events', id: parentId, label: parentLabel});
                    renderKpiRows(item.ots, 'events');
                    renderBreadcrumb();
                    return;
                }
            }
            return;
        }

        // Determine filter params based on current breadcrumb
        let areaId = null, lineId = null;
        if (nextLevel === 'line') {
            areaId = parentId;
        } else if (nextLevel === 'equipment') {
            lineId = parentId;
        }

        const data = await fetchKPIs(nextLevel, areaId, lineId);
        breadcrumb.push({level: nextLevel, id: parentId, label: parentLabel});
        renderGlobalKPIs(data.kpis);
        renderKpiRows(data.items, nextLevel);
        renderBreadcrumb();
        kpiCache[nextLevel] = data;
    } catch (e) {
        console.error('KPI drillNext error:', e);
    }
}

// Auto-load on page ready
document.addEventListener('DOMContentLoaded', () => {
    setTimeout(() => drillTo('area'), 500);
});
