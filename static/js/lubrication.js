const lubState = { points: [], areas: [], lines: [], systems: [], components: [], equipments: [], showInactive: false };

function q(id) { return document.getElementById(id); }
function fnum(v, d = 0) { return Number(v || 0).toLocaleString("es-PE", { minimumFractionDigits: d, maximumFractionDigits: d }); }

async function jget(url, opts) {
    const r = await fetch(url, opts);
    const d = await r.json();
    if (!r.ok || d.error) throw new Error(d.error || `HTTP ${r.status}`);
    return d;
}

function fillSelect(select, rows, valueKey, textFn, first = "Seleccione") {
    select.innerHTML = `<option value="">${first}</option>` + rows.map(r => `<option value="${r[valueKey]}">${textFn(r)}</option>`).join("");
}

async function loadCatalogs() {
    const [areas, lines, equipments, systems, components] = await Promise.all([
        jget('/api/areas'),
        jget('/api/lines'),
        jget('/api/equipments'),
        jget('/api/systems'),
        jget('/api/components')
    ]);
    lubState.areas = areas || [];
    lubState.lines = lines || [];
    lubState.equipments = equipments || [];
    lubState.systems = systems || [];
    lubState.components = components || [];

    fillSelect(q('fArea'), lubState.areas, 'id', a => a.name);
    fillSelect(q('fLine'), [], 'id', l => l.name);
    fillSelect(q('fEquipment'), [], 'id', e => `${e.tag ? e.tag + ' - ' : ''}${e.name}`);
    fillSelect(q('fSystem'), [], 'id', s => s.name);
    fillSelect(q('fComponent'), [], 'id', c => c.name);
}

function onAreaChange() {
    const areaId = Number(q('fArea').value || 0);
    const lines = lubState.lines.filter(l => Number(l.area_id) === areaId);
    fillSelect(q('fLine'), lines, 'id', l => l.name);
    fillSelect(q('fEquipment'), [], 'id', e => `${e.tag ? e.tag + ' - ' : ''}${e.name}`);
    fillSelect(q('fSystem'), [], 'id', s => s.name);
    fillSelect(q('fComponent'), [], 'id', c => c.name);
}

function onLineChange() {
    const lineId = Number(q('fLine').value || 0);
    const equips = lubState.equipments.filter(e => Number(e.line_id) === lineId);
    fillSelect(q('fEquipment'), equips, 'id', e => `${e.tag ? e.tag + ' - ' : ''}${e.name}`);
    fillSelect(q('fSystem'), [], 'id', s => s.name);
    fillSelect(q('fComponent'), [], 'id', c => c.name);
}

function onEquipmentChange() {
    const eqId = Number(q('fEquipment').value || 0);
    const systems = lubState.systems.filter(s => Number(s.equipment_id) === eqId);
    fillSelect(q('fSystem'), systems, 'id', s => s.name);
    fillSelect(q('fComponent'), [], 'id', c => c.name);
    refreshPointSelect();
}

const _STOP_TOK = new Set(['el','la','los','las','del','de','al','un','una','lo','que']);
function _tokenize(s) {
    if (!s) return [];
    return String(s).toLowerCase().split(/[\s,;/#-]+/)
        .filter(t => t && !_STOP_TOK.has(t) && (t.length >= 2 || /^\d+$/.test(t)));
}
function _pointBlob(p) {
    return [p.code, p.name, p.equipment_name, p.equipment_tag, p.system_name, p.component_name]
        .filter(Boolean).join(' ').toLowerCase();
}
function getFilteredPoints() {
    let pts = lubState.points || [];
    const eqId = Number(q('fEquipment').value || 0);
    if (eqId) pts = pts.filter(p => Number(p.equipment_id) === eqId);
    const tokens = _tokenize(q('fPointSearch') ? q('fPointSearch').value : '');
    if (tokens.length) {
        pts = pts.filter(p => {
            const blob = _pointBlob(p);
            return tokens.every(t => blob.includes(t));
        });
    }
    return pts;
}
function renderPointSelect() {
    const sel = q('fPoint');
    if (!sel) return;
    const filtered = getFilteredPoints();
    const total = (lubState.points || []).length;
    const countEl = q('fPointCount');
    if (countEl) countEl.textContent = filtered.length === total
        ? `(${total})`
        : `(${filtered.length}/${total})`;
    if (!filtered.length) {
        sel.innerHTML = '<option value="">Sin coincidencias — ajusta el filtro</option>';
        return;
    }
    sel.innerHTML = '<option value="">Seleccione punto</option>' + filtered.map(p => {
        const eq = p.equipment_tag || p.equipment_name || '';
        return `<option value="${p.id}">${p.code || ''} — ${p.name}${eq ? ' [' + eq + ']' : ''}</option>`;
    }).join('');
    if (filtered.length === 1) sel.value = String(filtered[0].id);
}
function refreshPointSelect() { renderPointSelect(); }

function onSystemChange() {
    const sysId = Number(q('fSystem').value || 0);
    const comps = lubState.components.filter(c => Number(c.system_id) === sysId);
    fillSelect(q('fComponent'), comps, 'id', c => c.name);
}

function updateKPIs(d) {
    q('kpiTotal').textContent = fnum(d.total);
    q('kpiGreen').textContent = fnum(d.green);
    q('kpiYellow').textContent = fnum(d.yellow);
    q('kpiRed').textContent = fnum(d.red);
    q('kpiPending').textContent = fnum(d.pending);
    q('kpiCompliance').textContent = `${fnum(d.compliance_percent, 1)}%`;
}

function renderPoints(points) {
    const tbody = q('tbodyPoints');
    lubState.points = points || [];
    if (!points || !points.length) {
        tbody.innerHTML = '<tr><td colspan="11">Sin puntos registrados.</td></tr>';
        renderPointSelect();
        return;
    }
    tbody.innerHTML = points.map(p => {
        const inactive = p.is_active === false;
        const rowStyle = inactive ? 'opacity:0.45;' : '';
        const semaphore = inactive ? 'INACTIVO' : (p.semaphore_status || 'PENDIENTE');
        const pillClass = inactive ? 'INACTIVO' : (p.semaphore_status || '');
        const toggleIcon = inactive ? 'fa-rotate-left' : 'fa-ban';
        const toggleTitle = inactive ? 'Reactivar' : 'Desactivar';
        const toggleClass = inactive ? 'btn-reactivate' : 'btn-del';
        return `<tr style="${rowStyle}">
            <td>${p.code || '-'}</td>
            <td>${p.name || '-'}</td>
            <td>${p.equipment_name || '-'}</td>
            <td>${p.system_name || '-'}</td>
            <td>${p.component_name || '-'}</td>
            <td>${p.lubricant_name || '-'}</td>
            <td>${p.frequency_days || '-'} d</td>
            <td>${p.last_service_date || '-'}</td>
            <td>${p.next_due_date || '-'}</td>
            <td><span class="pill ${pillClass}">${semaphore}</span></td>
            <td>
                ${inactive ? '' : `<button class="btn-icon btn-edit" title="Editar" onclick="openEditModal(${p.id})"><i class="fas fa-pen"></i></button>`}
                <button class="btn-icon ${toggleClass}" title="${toggleTitle}" onclick="togglePoint(${p.id}, ${inactive})"><i class="fas ${toggleIcon}"></i></button>
            </td>
        </tr>`;
    }).join('');

    renderPointSelect();
}

function renderExecutions(rows) {
    const tbody = q('tbodyExec');
    if (!rows || !rows.length) {
        tbody.innerHTML = '<tr><td colspan="8">Sin historial.</td></tr>';
        return;
    }
    tbody.innerHTML = rows.map(r => `
        <tr>
            <td>${r.execution_date || '-'}</td>
            <td>${r.point_name || '-'}</td>
            <td>${r.action_type || '-'}</td>
            <td>${r.quantity_used ? fnum(r.quantity_used, 2) : '-'} ${r.quantity_unit || ''}</td>
            <td>${r.executed_by || '-'}</td>
            <td>${r.anomaly_detected || r.leak_detected ? 'Si' : 'No'}</td>
            <td>${r.created_notice_code || '-'}</td>
            <td>${r.comments || '-'}</td>
        </tr>
    `).join('');
}

async function loadDashboard() {
    const url = lubState.showInactive
        ? '/api/lubrication/dashboard?show_inactive=true'
        : '/api/lubrication/dashboard';
    const data = await jget(url);
    updateKPIs(data.kpi || {});
    renderPoints(data.items || []);
}

async function loadExecutions() {
    const data = await jget('/api/lubrication/executions');
    renderExecutions(data || []);
}

async function createPoint() {
    const payload = {
        name: (q('fName').value || '').trim(),
        area_id: q('fArea').value || null,
        line_id: q('fLine').value || null,
        equipment_id: q('fEquipment').value || null,
        system_id: q('fSystem').value || null,
        component_id: q('fComponent').value || null,
        lubricant_name: (q('fLub').value || '').trim() || null,
        frequency_days: Number(q('fFreq').value || 30),
        warning_days: Number(q('fWarn').value || 3)
    };
    if (!payload.name) {
        alert('Ingresa nombre del punto.');
        return;
    }
    await jget('/api/lubrication/points', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    });
    q('fName').value = '';
    q('fLub').value = '';
    await refreshAll();
}

async function registerExecution() {
    const payload = {
        point_id: Number(q('fPoint').value || 0),
        execution_date: q('fExecDate').value || new Date().toISOString().slice(0, 10),
        quantity_used: q('fQty').value ? Number(q('fQty').value) : null,
        executed_by: (q('fBy').value || '').trim() || null,
        anomaly_detected: q('fAnom').value === '1',
        create_notice: true,
        comments: q('fAnom').value === '1' ? 'Anomalia detectada durante lubricacion' : 'Servicio de lubricacion ejecutado'
    };
    if (!payload.point_id) {
        alert('Selecciona un punto para registrar ejecucion.');
        return;
    }
    await jget('/api/lubrication/executions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    });
    q('fQty').value = '';
    q('fBy').value = '';
    await refreshAll();
}

async function togglePoint(id, isCurrentlyInactive) {
    const action = isCurrentlyInactive ? 'Reactivar' : 'Desactivar';
    if (!confirm(`${action} este punto?`)) return;
    await jget(`/api/lubrication/points/${id}`, { method: 'DELETE' });
    await refreshAll();
}
window.togglePoint = togglePoint;

function toggleInactiveFilter() {
    lubState.showInactive = !lubState.showInactive;
    const btn = q('btnToggleInactive');
    if (btn) {
        btn.classList.toggle('active', lubState.showInactive);
        btn.innerHTML = lubState.showInactive
            ? '<i class="fas fa-eye-slash"></i> Ocultar Inactivos'
            : '<i class="fas fa-eye"></i> Mostrar Inactivos';
    }
    refreshAll();
}
window.toggleInactiveFilter = toggleInactiveFilter;

function openEditModal(id) {
    const p = lubState.points.find(x => x.id === id);
    if (!p) return;

    q('eId').value = p.id;
    q('eName').value = p.name || '';
    q('eLub').value = p.lubricant_name || '';
    q('eFreq').value = p.frequency_days || 30;
    q('eWarn').value = p.warning_days || 3;
    q('eLastDate').value = p.last_service_date || '';

    // Populate equipment select
    fillSelect(q('eEquipment'), lubState.equipments, 'id', e => `${e.tag ? e.tag + ' - ' : ''}${e.name}`);
    q('eEquipment').value = p.equipment_id || '';

    const systems = lubState.systems.filter(s => Number(s.equipment_id) === Number(p.equipment_id || 0));
    fillSelect(q('eSystem'), systems, 'id', s => s.name);
    q('eSystem').value = p.system_id || '';

    const comps = lubState.components.filter(c => Number(c.system_id) === Number(p.system_id || 0));
    fillSelect(q('eComponent'), comps, 'id', c => c.name);
    q('eComponent').value = p.component_id || '';

    q('eEquipment').onchange = () => {
        const eqId = Number(q('eEquipment').value || 0);
        fillSelect(q('eSystem'), lubState.systems.filter(s => Number(s.equipment_id) === eqId), 'id', s => s.name);
        fillSelect(q('eComponent'), [], 'id', c => c.name);
    };
    q('eSystem').onchange = () => {
        const sysId = Number(q('eSystem').value || 0);
        fillSelect(q('eComponent'), lubState.components.filter(c => Number(c.system_id) === sysId), 'id', c => c.name);
    };

    q('editModal').classList.add('open');
}
window.openEditModal = openEditModal;

function closeEditModal() {
    q('editModal').classList.remove('open');
}
window.closeEditModal = closeEditModal;

async function saveEdit() {
    const id = q('eId').value;
    const payload = {
        name: q('eName').value.trim(),
        equipment_id: q('eEquipment').value || null,
        system_id: q('eSystem').value || null,
        component_id: q('eComponent').value || null,
        lubricant_name: q('eLub').value.trim() || null,
        frequency_days: Number(q('eFreq').value || 30),
        warning_days: Number(q('eWarn').value || 3),
        last_service_date: q('eLastDate').value || null
    };
    if (!payload.name) { alert('El nombre es obligatorio.'); return; }
    try {
        await jget(`/api/lubrication/points/${id}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        closeEditModal();
        await refreshAll();
    } catch (e) {
        alert(`Error al guardar: ${e.message}`);
    }
}
window.saveEdit = saveEdit;

async function refreshAll() {
    await loadDashboard();
    await loadExecutions();
}

async function boot() {
    try {
        q('fExecDate').value = new Date().toISOString().slice(0, 10);
        await loadCatalogs();
        await refreshAll();
        q('fArea').addEventListener('change', onAreaChange);
        q('fLine').addEventListener('change', onLineChange);
        q('fEquipment').addEventListener('change', onEquipmentChange);
        q('fSystem').addEventListener('change', onSystemChange);
        q('btnCreate').addEventListener('click', createPoint);
        q('btnExec').addEventListener('click', registerExecution);
        if (q('fPointSearch')) q('fPointSearch').addEventListener('input', renderPointSelect);
    } catch (e) {
        alert(`Error inicializando lubricacion: ${e.message}`);
    }
}

document.addEventListener('DOMContentLoaded', boot);
