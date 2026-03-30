const inspState = { routes: [], equipments: [], showInactive: false };

function q(id) { return document.getElementById(id); }

async function jget(url, opts) {
    const r = await fetch(url, opts);
    const d = await r.json();
    if (!r.ok || d.error) throw new Error(d.error || `HTTP ${r.status}`);
    return d;
}

function fillSelect(sel, rows, valueFn, textFn, first = 'Seleccione') {
    sel.innerHTML = `<option value="">${first}</option>` +
        rows.map(r => `<option value="${valueFn(r)}">${textFn(r)}</option>`).join('');
}

// ── KPIs ──────────────────────────────────────────────────────────────────────

function updateKPIs(kpi) {
    q('kTotal').textContent = kpi.total || 0;
    q('kGreen').textContent = kpi.green || 0;
    q('kYellow').textContent = kpi.yellow || 0;
    q('kRed').textContent = kpi.red || 0;
    q('kPending').textContent = kpi.pending || 0;
    q('kCompliance').textContent = (kpi.compliance || 0).toFixed(1) + '%';
}

// ── Render Routes ─────────────────────────────────────────────────────────────

function renderRoutes(items) {
    inspState.routes = items;
    const tbody = q('tbodyRoutes');
    if (!items.length) {
        tbody.innerHTML = '<tr><td colspan="9" style="text-align:center;color:rgba(255,255,255,.30);padding:20px">Sin rutas registradas.</td></tr>';
        return;
    }

    tbody.innerHTML = items.map(r => {
        const inactive = r.is_active === false;
        const style = inactive ? 'opacity:0.45' : '';
        const sem = inactive ? 'INACTIVO' : (r.semaphore_status || 'PENDIENTE');
        const pill = inactive ? 'INACTIVO' : (r.semaphore_status || 'PENDIENTE');
        const toggleIcon = inactive ? 'fa-rotate-left' : 'fa-ban';
        const toggleClass = inactive ? 'btn-reactivate' : 'btn-del';
        const toggleTitle = inactive ? 'Reactivar' : 'Desactivar';

        return `<tr style="${style}">
            <td>${r.code || '-'}</td>
            <td>${r.name}</td>
            <td>${r.equipment_name || '-'}</td>
            <td>${r.item_count || 0}</td>
            <td>${r.frequency_days} d</td>
            <td>${r.last_execution_date || '-'}</td>
            <td>${r.next_due_date || '-'}</td>
            <td><span class="pill ${pill}">${sem}</span></td>
            <td>
                ${inactive ? '' : `<button class="btn-icon btn-edit" title="Items" onclick="openItemsModal(${r.id})"><i class="fas fa-list-check"></i></button>`}
                <button class="btn-icon ${toggleClass}" title="${toggleTitle}" onclick="toggleRoute(${r.id}, ${inactive})"><i class="fas ${toggleIcon}"></i></button>
            </td>
        </tr>`;
    }).join('');

    // Update execution select with active routes only
    const active = items.filter(r => r.is_active !== false);
    fillSelect(q('fExecRoute'), active, r => r.id, r => `${r.code || ''} ${r.name}`, 'Seleccione ruta');
}

// ── Render Executions ─────────────────────────────────────────────────────────

function renderExecutions(rows) {
    const tbody = q('tbodyExec');
    if (!rows.length) {
        tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;color:rgba(255,255,255,.30);padding:20px">Sin historial.</td></tr>';
        return;
    }
    tbody.innerHTML = rows.map(e => {
        const resultClass = e.overall_result === 'OK' ? 'result-ok' : 'result-nok';
        const resultLabel = e.overall_result === 'OK' ? 'OK' : `${e.findings_count} hallazgo(s)`;
        return `<tr>
            <td>${e.execution_date}</td>
            <td>${e.route_name || '-'}</td>
            <td>${e.executed_by || '-'}</td>
            <td><span class="${resultClass}">${e.overall_result}</span></td>
            <td>${resultLabel}</td>
            <td>${e.created_notice_id ? 'AV-' + String(e.created_notice_id).padStart(4, '0') : '-'}</td>
            <td>${e.comments || '-'}</td>
        </tr>`;
    }).join('');
}

// ── Data Loading ──────────────────────────────────────────────────────────────

async function loadDashboard() {
    const url = inspState.showInactive
        ? '/api/inspection/dashboard?show_inactive=true'
        : '/api/inspection/dashboard';
    const data = await jget(url);
    updateKPIs(data.kpi || {});
    renderRoutes(data.items || []);
}

async function loadExecutions() {
    const data = await jget('/api/inspection/executions');
    renderExecutions(data || []);
}

async function loadCatalogs() {
    try {
        const [equips] = await Promise.all([
            jget('/api/equipments'),
        ]);
        inspState.equipments = equips;
        fillSelect(q('fEquipment'), equips, e => e.id, e => `${e.tag ? e.tag + ' - ' : ''}${e.name}`, 'Seleccione');
    } catch (_) {}
}

async function refreshAll() {
    await loadDashboard();
    await loadExecutions();
}

// ── Create Route ──────────────────────────────────────────────────────────────

async function createRoute() {
    const name = (q('fName').value || '').trim();
    if (!name) { alert('Ingresa nombre de la ruta.'); return; }
    await jget('/api/inspection/routes', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            name,
            equipment_id: q('fEquipment').value || null,
            frequency_days: Number(q('fFreq').value || 7),
            warning_days: Number(q('fWarn').value || 1),
        })
    });
    q('fName').value = '';
    await refreshAll();
}
window.createRoute = createRoute;

// ── Toggle Route Active ───────────────────────────────────────────────────────

async function toggleRoute(id, isInactive) {
    const action = isInactive ? 'Reactivar' : 'Desactivar';
    if (!confirm(`${action} esta ruta?`)) return;
    await jget(`/api/inspection/routes/${id}`, { method: 'DELETE' });
    await refreshAll();
}
window.toggleRoute = toggleRoute;

function toggleInactive() {
    inspState.showInactive = !inspState.showInactive;
    const btn = q('btnToggleInactive');
    btn.classList.toggle('active', inspState.showInactive);
    btn.innerHTML = inspState.showInactive
        ? '<i class="fas fa-eye-slash"></i> Ocultar Inactivas'
        : '<i class="fas fa-eye"></i> Mostrar Inactivas';
    refreshAll();
}
window.toggleInactive = toggleInactive;

// ── Items Modal ───────────────────────────────────────────────────────────────

async function openItemsModal(routeId) {
    const route = inspState.routes.find(r => r.id === routeId);
    if (!route) return;
    q('imRouteId').value = routeId;
    q('imRouteName').textContent = route.name;
    q('imDesc').value = '';
    q('imType').value = 'CHECK';
    q('imCriteria').value = '';
    toggleMedFields();
    await loadItems(routeId);
    q('itemsModal').classList.add('open');
}
window.openItemsModal = openItemsModal;

async function loadItems(routeId) {
    const items = await jget(`/api/inspection/routes/${routeId}/items`);
    const container = q('itemsList');
    if (!items.length) {
        container.innerHTML = '<p style="color:rgba(255,255,255,.30);text-align:center;padding:12px">Sin items. Agrega el primer item del checklist.</p>';
        return;
    }
    container.innerHTML = '<table style="min-width:auto;width:100%"><thead><tr><th>#</th><th>Descripcion</th><th>Tipo</th><th>Criterio</th><th></th></tr></thead><tbody>' +
        items.map((it, idx) => `<tr>
            <td>${idx + 1}</td>
            <td>${it.description}</td>
            <td>${it.item_type}${it.unit ? ' (' + it.unit + ')' : ''}${it.alarm_min != null || it.alarm_max != null ? ' [' + (it.alarm_min ?? '') + '-' + (it.alarm_max ?? '') + ']' : ''}</td>
            <td style="color:rgba(255,255,255,.40);font-size:.78rem">${it.criteria || '-'}</td>
            <td><button class="btn-icon btn-del" onclick="deleteItem(${it.id})"><i class="fas fa-trash"></i></button></td>
        </tr>`).join('') +
        '</tbody></table>';
}

function toggleMedFields() {
    const isMed = q('imType').value === 'MEDICION';
    q('imUnitWrap').style.display = isMed ? '' : 'none';
    q('imAlarmWrap').style.display = isMed ? '' : 'none';
}
window.toggleMedFields = toggleMedFields;

async function addItem() {
    const routeId = q('imRouteId').value;
    const desc = (q('imDesc').value || '').trim();
    if (!desc) { alert('Descripcion es obligatoria.'); return; }
    await jget(`/api/inspection/routes/${routeId}/items`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            description: desc,
            item_type: q('imType').value,
            unit: q('imUnit').value || null,
            alarm_min: q('imAlarmMin').value ? Number(q('imAlarmMin').value) : null,
            alarm_max: q('imAlarmMax').value ? Number(q('imAlarmMax').value) : null,
            criteria: q('imCriteria').value || null,
        })
    });
    q('imDesc').value = '';
    q('imCriteria').value = '';
    await loadItems(routeId);
    await refreshAll();
}
window.addItem = addItem;

async function deleteItem(itemId) {
    if (!confirm('Eliminar este item?')) return;
    await jget(`/api/inspection/items/${itemId}`, { method: 'DELETE' });
    await loadItems(q('imRouteId').value);
    await refreshAll();
}
window.deleteItem = deleteItem;

// ── Execution Modal ───────────────────────────────────────────────────────────

async function openExecutionModal() {
    const routeId = q('fExecRoute').value;
    if (!routeId) { alert('Selecciona una ruta.'); return; }

    const route = inspState.routes.find(r => r.id === Number(routeId));
    q('emRouteId').value = routeId;
    q('emRouteName').textContent = route ? route.name : '';
    q('emComments').value = '';

    // Load items for checklist
    const items = await jget(`/api/inspection/routes/${routeId}/items`);
    if (!items.length) {
        alert('Esta ruta no tiene items configurados. Agrega items primero.');
        return;
    }

    const checklist = q('emChecklist');
    checklist.innerHTML = items.map(it => {
        let inputHtml = '';
        if (it.item_type === 'CHECK') {
            inputHtml = `<select data-item="${it.id}" data-type="CHECK" class="cl-result">
                <option value="OK">OK</option>
                <option value="NO_OK">NO OK</option>
            </select>`;
        } else if (it.item_type === 'MEDICION') {
            inputHtml = `<input data-item="${it.id}" data-type="MEDICION" class="cl-result" type="number" step="any" placeholder="${it.unit || 'valor'}">`;
        } else {
            inputHtml = `<input data-item="${it.id}" data-type="TEXTO" class="cl-result" type="text" placeholder="Texto...">`;
        }

        const criteriaHtml = it.criteria ? `<div class="cl-criteria">${it.criteria}</div>` : '';
        const rangeHtml = (it.item_type === 'MEDICION' && (it.alarm_min != null || it.alarm_max != null))
            ? `<div class="cl-criteria">Rango: ${it.alarm_min ?? '—'} a ${it.alarm_max ?? '—'} ${it.unit || ''}</div>`
            : '';

        return `<li>
            <div><div class="cl-desc">${it.description}</div>${criteriaHtml}${rangeHtml}</div>
            <div class="cl-input">${inputHtml}</div>
            <div class="cl-obs"><input data-obs="${it.id}" placeholder="Observacion..." type="text"></div>
        </li>`;
    }).join('');

    q('execModal').classList.add('open');
}
window.openExecutionModal = openExecutionModal;

async function submitExecution() {
    const routeId = q('emRouteId').value;
    const resultEls = q('emChecklist').querySelectorAll('.cl-result');
    const results = [];

    resultEls.forEach(el => {
        const itemId = Number(el.dataset.item);
        const type = el.dataset.type;
        const obsEl = q('emChecklist').querySelector(`[data-obs="${itemId}"]`);

        const entry = { item_id: itemId, observation: obsEl ? obsEl.value.trim() || null : null };

        if (type === 'CHECK') {
            entry.result = el.value;
        } else if (type === 'MEDICION') {
            entry.value = el.value ? Number(el.value) : null;
            entry.result = 'OK'; // backend will auto-determine from thresholds
        } else {
            entry.text_value = el.value || null;
            entry.result = 'OK';
        }
        results.push(entry);
    });

    await jget('/api/inspection/executions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            route_id: Number(routeId),
            execution_date: q('fExecDate').value || new Date().toISOString().slice(0, 10),
            executed_by: q('fExecBy').value.trim() || null,
            comments: q('emComments').value.trim() || null,
            results,
            create_notice: true,
        })
    });

    closeModal('execModal');
    await refreshAll();
}
window.submitExecution = submitExecution;

function closeModal(id) {
    q(id).classList.remove('open');
}
window.closeModal = closeModal;

// ── Boot ──────────────────────────────────────────────────────────────────────

async function boot() {
    q('fExecDate').value = new Date().toISOString().slice(0, 10);
    await loadCatalogs();
    await refreshAll();
}

document.addEventListener('DOMContentLoaded', boot);
