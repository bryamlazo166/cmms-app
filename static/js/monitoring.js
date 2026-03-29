let monState = {
    areas: [],
    lines: [],
    equipments: [],
    points: [],
    trendChart: null,
};

function q(id) {
    return document.getElementById(id);
}

function asNum(v) {
    if (v === null || v === undefined || v === '') return null;
    const n = Number(v);
    return Number.isFinite(n) ? n : null;
}

function todayISO() {
    return new Date().toISOString().split('T')[0];
}

function semClass(status) {
    if (status === 'VERDE') return 'pill pill-green';
    if (status === 'AMARILLO') return 'pill pill-yellow';
    if (status === 'ROJO') return 'pill pill-red';
    return 'pill pill-muted';
}

async function fetchJson(url, opts) {
    const res = await fetch(url, opts);
    let data = {};
    try {
        data = await res.json();
    } catch (e) {
        data = {};
    }
    if (!res.ok || data.error) {
        throw new Error(data.error || `HTTP ${res.status}`);
    }
    return data;
}

function fillSelect(select, items, placeholder) {
    select.innerHTML = `<option value="">${placeholder}</option>` +
        items.map(x => `<option value="${x.id}">${x.name}</option>`).join('');
}

function refreshLineEquipmentFilters() {
    const areaId = q('filterArea').value;
    const lineId = q('filterLine').value;

    const lines = monState.lines.filter(l => !areaId || String(l.area_id) === String(areaId));
    fillSelect(q('filterLine'), lines, 'Linea: Todas');
    q('filterLine').value = lineId && lines.some(l => String(l.id) === String(lineId)) ? lineId : '';

    const equips = monState.equipments.filter(e => !q('filterLine').value || String(e.line_id) === String(q('filterLine').value));
    fillSelect(q('filterEquipment'), equips, 'Equipo: Todos');
}

function refreshPointHierarchyOptions() {
    fillSelect(q('pArea'), monState.areas, 'Selecciona area');
    fillSelect(q('pLine'), monState.lines, 'Selecciona linea');
    fillSelect(q('pEquip'), monState.equipments, 'Selecciona equipo');
}

function pointOptionsHtml() {
    return '<option value="">Selecciona punto</option>' + monState.points.map(p => {
        const eq = p.equipment_name || '-';
        return `<option value="${p.id}">${p.code || ''} | ${p.name} | ${eq}</option>`;
    }).join('');
}

async function loadHierarchy() {
    const [areas, lines, equips] = await Promise.all([
        fetchJson('/api/areas'),
        fetchJson('/api/lines'),
        fetchJson('/api/equipments')
    ]);
    monState.areas = areas;
    monState.lines = lines;
    monState.equipments = equips;

    fillSelect(q('filterArea'), areas, 'Area: Todas');
    fillSelect(q('filterLine'), lines, 'Linea: Todas');
    fillSelect(q('filterEquipment'), equips, 'Equipo: Todos');
    refreshPointHierarchyOptions();
}

function renderKpis(kpi) {
    q('kpiTotal').textContent = kpi.total_points || 0;
    q('kpiDue').textContent = kpi.due_today || 0;
    q('kpiOverdue').textContent = kpi.overdue || 0;
    q('kpiUpcoming').textContent = kpi.upcoming || 0;
    q('kpiSem').textContent = `${kpi.green || 0}V / ${kpi.yellow || 0}A / ${kpi.red || 0}R`;
}

function renderPending(rows) {
    const tbody = q('tablePendingBody');
    if (!rows.length) {
        tbody.innerHTML = '<tr><td colspan="7" class="muted">No hay pendientes para hoy.</td></tr>';
        return;
    }

    tbody.innerHTML = rows.map(r => {
        return `<tr>
            <td>${r.code || '-'}</td>
            <td>${r.name || '-'}</td>
            <td>${r.equipment_name || '-'}</td>
            <td>${r.measurement_type || '-'}</td>
            <td>${r.next_due_date || '-'}</td>
            <td><span class="${semClass(r.semaphore_status)}">${r.semaphore_status || 'PENDIENTE'}</span></td>
            <td><button class="btn-micro" onclick="openReadingModal(${r.point_id})">Registrar</button></td>
        </tr>`;
    }).join('');
}

function renderPoints(points) {
    monState.points = points;

    q('rPoint').innerHTML = pointOptionsHtml();

    const trendSel = q('trendPointSelect');
    const oldPoint = trendSel.value;
    trendSel.innerHTML = '<option value="">Grafica: Seleccionar punto</option>' + points.map(p => {
        return `<option value="${p.id}">${p.code || ''} - ${p.name}</option>`;
    }).join('');
    if (oldPoint && points.some(p => String(p.id) === String(oldPoint))) {
        trendSel.value = oldPoint;
    }

    const tbody = q('tablePointsBody');
    if (!points.length) {
        tbody.innerHTML = '<tr><td colspan="9" class="muted">No hay puntos registrados.</td></tr>';
        return;
    }

    tbody.innerHTML = points.map(p => {
        const equip = p.equipment_name || '-';
        const freq = `${p.frequency_days || 0} d`;
        return `<tr>
            <td>${p.code || '-'}</td>
            <td>${p.name || '-'}</td>
            <td>${p.measurement_type || '-'} ${p.axis ? '(' + p.axis + ')' : ''}</td>
            <td>${equip}</td>
            <td>${freq}</td>
            <td>${p.last_measurement_date || '-'}</td>
            <td>${p.next_due_date || '-'}</td>
            <td><span class="${semClass(p.semaphore_status)}">${p.semaphore_status || 'PENDIENTE'}</span></td>
            <td>
                <div class="actions-row">
                    <button class="btn-micro" onclick="openPointModal(${p.id})">Editar</button>
                    <button class="btn-micro" onclick="openReadingModal(${p.id})">Lectura</button>
                    <button class="btn-micro" onclick="showPointReadings(${p.id})">Historial</button>
                    <button class="btn-micro" onclick="disablePoint(${p.id})">Desactivar</button>
                </div>
            </td>
        </tr>`;
    }).join('');
}

function renderTrend(trendRows, axisCfg, selectedPointId) {
    const ctx = q('trendChart').getContext('2d');
    if (monState.trendChart) {
        monState.trendChart.destroy();
    }

    const selected = monState.points.find(p => String(p.id) === String(selectedPointId));
    q('trendSubtitle').textContent = selected
        ? `${selected.code || ''} - ${selected.name} | ${selected.unit || ''}`
        : 'Selecciona un punto para ver su grafica.';

    monState.trendChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: trendRows.map(r => r.reading_date),
            datasets: [{
                label: 'Valor medido',
                data: trendRows.map(r => Number(r.value)),
                borderColor: '#03dac6',
                backgroundColor: 'rgba(3, 218, 198, .15)',
                fill: true,
                pointRadius: 3,
                tension: 0.2
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                y: {
                    min: axisCfg.min,
                    max: axisCfg.max,
                    ticks: {
                        stepSize: axisCfg.step,
                        maxTicksLimit: 8
                    }
                }
            },
            plugins: {
                legend: { display: false }
            }
        }
    });
}

function currentFilters() {
    const p = new URLSearchParams();
    if (q('filterArea').value) p.set('area_id', q('filterArea').value);
    if (q('filterLine').value) p.set('line_id', q('filterLine').value);
    if (q('filterEquipment').value) p.set('equipment_id', q('filterEquipment').value);
    if (q('filterDue').value) p.set('due', q('filterDue').value);
    return p;
}

async function loadPoints() {
    const points = await fetchJson('/api/monitoring/points?' + currentFilters().toString());
    renderPoints(points);
}

async function loadDashboard() {
    const p = currentFilters();
    if (q('trendPointSelect').value) {
        p.set('point_id', q('trendPointSelect').value);
    }
    const data = await fetchJson('/api/monitoring/dashboard?' + p.toString());

    renderKpis(data.kpi || {});
    renderPending(data.pending_rows || []);

    if (!q('trendPointSelect').value && data.selected_point_id) {
        q('trendPointSelect').value = String(data.selected_point_id);
    }
    renderTrend(data.trend || [], data.trend_axis || { min: 0, max: 10, step: 2 }, data.selected_point_id);
}

async function reloadMonitoring() {
    try {
        await loadPoints();
        await loadDashboard();
    } catch (e) {
        alert('Error cargando monitoreo: ' + e.message);
    }
}

function closeModal(id) {
    q(id).close();
}

function openPointModal(id) {
    q('pointForm').reset();
    q('pointId').value = '';
    q('pointModalTitle').innerHTML = '<i class="fas fa-plus"></i> Nuevo Punto';

    if (!id) {
        q('pointModal').showModal();
        return;
    }

    const point = monState.points.find(p => p.id === id);
    if (!point) return;

    q('pointModalTitle').innerHTML = '<i class="fas fa-edit"></i> Editar Punto';
    q('pointId').value = point.id;
    q('pName').value = point.name || '';
    q('pType').value = point.measurement_type || 'VIBRACION';
    q('pAxis').value = point.axis || '';
    q('pUnit').value = point.unit || '';
    q('pFreq').value = point.frequency_days || 7;
    q('pWarn').value = point.warning_days || 1;
    q('pNMin').value = (point.normal_min === null || point.normal_min === undefined) ? '' : point.normal_min;
    q('pNMax').value = (point.normal_max === null || point.normal_max === undefined) ? '' : point.normal_max;
    q('pAMin').value = (point.alarm_min === null || point.alarm_min === undefined) ? '' : point.alarm_min;
    q('pAMax').value = (point.alarm_max === null || point.alarm_max === undefined) ? '' : point.alarm_max;
    q('pArea').value = point.area_id || '';
    q('pLine').value = point.line_id || '';
    q('pEquip').value = point.equipment_id || '';
    q('pLastDate').value = point.last_measurement_date || '';
    q('pNotes').value = point.notes || '';
    q('pointModal').showModal();
}

function openReadingModal(pointId) {
    q('readingForm').reset();
    q('rDate').value = todayISO();
    q('rPoint').innerHTML = pointOptionsHtml();
    if (pointId) {
        q('rPoint').value = String(pointId);
    }
    q('readingModal').showModal();
}

let _savingPoint = false;
async function savePoint(e) {
    e.preventDefault();
    if (_savingPoint) return;
    _savingPoint = true;
    const btn = e.submitter || e.target.querySelector('button[type="submit"]');
    const origBtn = btn ? btn.innerHTML : '';
    if (btn) { btn.disabled = true; btn.innerHTML = '<i class="fas fa-circle-notch fa-spin"></i> Guardando...'; }
    try {
    const id = q('pointId').value;
    const payload = {
        name: q('pName').value,
        measurement_type: q('pType').value,
        axis: q('pAxis').value || null,
        unit: q('pUnit').value || null,
        frequency_days: asNum(q('pFreq').value),
        warning_days: asNum(q('pWarn').value),
        normal_min: asNum(q('pNMin').value),
        normal_max: asNum(q('pNMax').value),
        alarm_min: asNum(q('pAMin').value),
        alarm_max: asNum(q('pAMax').value),
        area_id: asNum(q('pArea').value),
        line_id: asNum(q('pLine').value),
        equipment_id: asNum(q('pEquip').value),
        last_measurement_date: q('pLastDate').value || null,
        notes: q('pNotes').value || null,
    };

    const url = id ? `/api/monitoring/points/${id}` : '/api/monitoring/points';
    const method = id ? 'PUT' : 'POST';

    await fetchJson(url, {
        method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    });

    closeModal('pointModal');
    await reloadMonitoring();
    } finally { _savingPoint = false; if (btn) { btn.disabled = false; btn.innerHTML = origBtn; } }
}

let _savingReading = false;
async function saveReading(e) {
    e.preventDefault();
    if (_savingReading) return;
    _savingReading = true;
    const btnR = e.submitter || e.target.querySelector('button[type="submit"]');
    const origBtnR = btnR ? btnR.innerHTML : '';
    if (btnR) { btnR.disabled = true; btnR.innerHTML = '<i class="fas fa-circle-notch fa-spin"></i> Guardando...'; }
    try {
    const payload = {
        point_id: asNum(q('rPoint').value),
        reading_date: q('rDate').value,
        value: asNum(q('rValue').value),
        executed_by: q('rBy').value || null,
        photo_url: q('rPhoto').value || null,
        notes: q('rNotes').value || null,
        is_regularization: q('rRegularized').checked,
        create_notice: true,
    };

    if (!payload.point_id || payload.value === null) {
        alert('Selecciona punto y valor.');
        return;
    }

    const res = await fetchJson('/api/monitoring/readings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    });

    closeModal('readingModal');
    if (res.created_notice_id) {
        alert('Lectura guardada. Se genero aviso: ' + (res.created_notice_code || res.created_notice_id));
    }
    await reloadMonitoring();
    } finally { _savingReading = false; if (btnR) { btnR.disabled = false; btnR.innerHTML = origBtnR; } }
}

async function disablePoint(id) {
    if (!confirm('Deseas desactivar este punto?')) return;
    await fetchJson(`/api/monitoring/points/${id}`, { method: 'DELETE' });
    await reloadMonitoring();
}

async function showPointReadings(pointId) {
    const rows = await fetchJson(`/api/monitoring/readings?point_id=${pointId}&limit=12`);
    if (!rows.length) {
        alert('No hay historial registrado para este punto.');
        return;
    }
    const lines = rows.slice(0, 8).map(r => `${r.reading_date}: ${r.value} ${r.unit || ''}`).join('\n');
    alert(lines);
}

async function initMonitoring() {
    await loadHierarchy();
    q('rDate').value = todayISO();

    q('filterArea').addEventListener('change', () => {
        refreshLineEquipmentFilters();
        reloadMonitoring();
    });
    q('filterLine').addEventListener('change', reloadMonitoring);
    q('filterEquipment').addEventListener('change', reloadMonitoring);
    q('filterDue').addEventListener('change', reloadMonitoring);
    q('trendPointSelect').addEventListener('change', loadDashboard);

    q('pointForm').addEventListener('submit', savePoint);
    q('readingForm').addEventListener('submit', saveReading);

    await reloadMonitoring();
}

document.addEventListener('DOMContentLoaded', () => {
    initMonitoring().catch(e => alert('No se pudo inicializar monitoreo: ' + e.message));
});
