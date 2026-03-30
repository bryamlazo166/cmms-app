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

// ── Industrial KPIs (MTBF, MTTR, Availability) ──────────────────────────────

let kpiData = null;

async function loadKPIs() {
    const days = document.getElementById('kpiDays').value;
    const level = document.getElementById('kpiLevel').value;
    const areaId = document.getElementById('kpiArea').value;
    const lineId = document.getElementById('kpiLine').value;

    let url = `/api/dashboard-kpis?days=${days}&level=${level}`;
    if (areaId) url += `&area_id=${areaId}`;
    if (lineId) url += `&line_id=${lineId}`;

    try {
        const res = await fetch(url);
        kpiData = await res.json();
        if (kpiData.error) throw new Error(kpiData.error);
        renderGlobalKPIs(kpiData.kpis);
        renderKPITable(kpiData.items, level);
        populateAreaFilter(kpiData.areas, kpiData.lines);
    } catch (e) {
        console.error('KPI load error:', e);
    }
}

function renderGlobalKPIs(k) {
    document.getElementById('gMtbf').textContent = k.global_mtbf != null ? k.global_mtbf : '-';
    document.getElementById('gMttr').textContent = k.global_mttr != null ? k.global_mttr : '-';
    document.getElementById('gAvail').textContent = k.global_availability != null ? k.global_availability + '%' : '-';
    document.getElementById('gRatio').textContent = k.ratio_preventive != null ? k.ratio_preventive + '%' : '-';
    document.getElementById('gDown').textContent = k.global_downtime_h != null ? k.global_downtime_h : '-';
    document.getElementById('gFails').textContent = k.total_failures || 0;
}

function availColor(v) {
    if (v == null) return 'rgba(255,255,255,.40)';
    if (v >= 95) return '#30D158';
    if (v >= 85) return '#FFD60A';
    return '#FF453A';
}

function renderKPITable(items, level) {
    const labels = { equipment: 'Equipo', line: 'Linea', area: 'Area' };
    document.getElementById('levelLabel').textContent = labels[level] || 'Equipo';

    const tbody = document.getElementById('kpiTableBody');
    if (!items.length) {
        tbody.innerHTML = '<tr><td colspan="9" style="text-align:center;color:rgba(255,255,255,.30);padding:24px">Sin datos para el periodo seleccionado.</td></tr>';
        return;
    }

    tbody.innerHTML = items.map(it => {
        const ac = availColor(it.availability);
        return `<tr style="border-bottom:1px solid rgba(255,255,255,.06);cursor:pointer" onclick="showDrilldown(${JSON.stringify(it.id)}, '${it.label.replace(/'/g, "\\'")}')">
            <td style="padding:9px 10px;color:rgba(255,255,255,.85);font-size:.84rem">${it.label}</td>
            <td style="padding:9px 10px;color:rgba(255,255,255,.65);font-size:.84rem;text-align:right">${it.total_ots}</td>
            <td style="padding:9px 10px;color:#FF453A;font-size:.84rem;text-align:right;font-weight:600">${it.failures}</td>
            <td style="padding:9px 10px;color:#5AC8FA;font-size:.84rem;text-align:right">${it.mtbf != null ? it.mtbf : '-'}</td>
            <td style="padding:9px 10px;color:#FF9F0A;font-size:.84rem;text-align:right">${it.mttr != null ? it.mttr : '-'}</td>
            <td style="padding:9px 10px;color:${ac};font-size:.84rem;text-align:right;font-weight:700">${it.availability != null ? it.availability + '%' : '-'}</td>
            <td style="padding:9px 10px;color:rgba(255,255,255,.65);font-size:.84rem;text-align:right">${it.reliability != null ? it.reliability + '%' : '-'}</td>
            <td style="padding:9px 10px;color:rgba(255,255,255,.65);font-size:.84rem;text-align:right">${it.downtime_hours}</td>
            <td style="padding:9px 10px;color:#BF5AF2;font-size:.84rem;text-align:right">${it.ratio_preventive != null ? it.ratio_preventive + '%' : '-'}</td>
        </tr>`;
    }).join('');
}

function showDrilldown(id, label) {
    if (!kpiData) return;
    const item = kpiData.items.find(it => it.id === id);
    if (!item || !item.ots.length) return;

    document.getElementById('drilldownLabel').textContent = label;
    const tbody = document.getElementById('drilldownBody');
    tbody.innerHTML = item.ots.map(ot => `<tr style="border-bottom:1px solid rgba(255,255,255,.06)">
        <td style="padding:7px 10px;color:#0A84FF;font-size:.82rem;font-weight:600">${ot.code || '-'}</td>
        <td style="padding:7px 10px;color:rgba(255,255,255,.70);font-size:.82rem">${ot.date || '-'}</td>
        <td style="padding:7px 10px;color:rgba(255,255,255,.85);font-size:.82rem">${ot.equipment || '-'}</td>
        <td style="padding:7px 10px;color:rgba(255,255,255,.65);font-size:.82rem">${ot.type || '-'}</td>
        <td style="padding:7px 10px;color:rgba(255,255,255,.65);font-size:.82rem">${ot.failure_mode || '-'}</td>
        <td style="padding:7px 10px;color:#FF9F0A;font-size:.82rem;text-align:right">${ot.repair_h || '-'}</td>
        <td style="padding:7px 10px;color:rgba(255,255,255,.55);font-size:.80rem">${ot.description || '-'}</td>
    </tr>`).join('');

    document.getElementById('drilldownPanel').style.display = '';
    document.getElementById('drilldownPanel').scrollIntoView({ behavior: 'smooth' });
}

function populateAreaFilter(areas, lines) {
    const areaEl = document.getElementById('kpiArea');
    const currentVal = areaEl.value;
    // Only populate if empty (first load)
    if (areaEl.options.length <= 1) {
        (areas || []).forEach(a => {
            const opt = document.createElement('option');
            opt.value = a.id;
            opt.textContent = a.name;
            areaEl.appendChild(opt);
        });
    }
    if (currentVal) areaEl.value = currentVal;

    // Store lines for line filter
    window._kpiLines = lines || [];
}

// Area filter change → populate line filter
document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('kpiArea').addEventListener('change', function() {
        const lineEl = document.getElementById('kpiLine');
        const areaId = this.value;
        if (!areaId) {
            lineEl.style.display = 'none';
            lineEl.value = '';
            return;
        }
        const filtered = (window._kpiLines || []).filter(l => String(l.area_id) === String(areaId));
        lineEl.innerHTML = '<option value="">Todas las lineas</option>' +
            filtered.map(l => `<option value="${l.id}">${l.name}</option>`).join('');
        lineEl.style.display = '';
    });

    document.getElementById('kpiLevel').addEventListener('change', loadKPIs);

    // Auto-load KPIs after dashboard data
    setTimeout(loadKPIs, 500);
});
