// Programa Nocturno Semanal — calendario 7 × 4 con drag & drop
const DAY_NAMES = ['LUN', 'MAR', 'MIÉ', 'JUE', 'VIE', 'SÁB', 'DOM'];
const DAY_FULL = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo'];

let _state = {
    plans: [],
    plan: null,      // plan activo completo
    areas: [],
    providers: [],
};

document.addEventListener('DOMContentLoaded', async () => {
    await Promise.all([loadAreas(), loadProviders()]);
    await loadPlans();
});

// ── Cargas base ─────────────────────────────────────────────────────────
async function loadAreas() {
    try {
        const r = await fetch('/api/areas');
        _state.areas = await r.json();
    } catch (e) { console.error(e); _state.areas = []; }
}

async function loadProviders() {
    try {
        const r = await fetch('/api/providers');
        _state.providers = await r.json();
    } catch (e) { _state.providers = []; }
}

async function loadPlans() {
    const sel = document.getElementById('planSelect');
    sel.innerHTML = '<option value="">- Ningún plan -</option>';
    try {
        const r = await fetch('/api/weekly-plans');
        _state.plans = await r.json();
        _state.plans.forEach(p => {
            sel.insertAdjacentHTML('beforeend',
                `<option value="${p.id}">${p.code} · ${p.week_start} (${p.status})</option>`);
        });
        if (_state.plans.length > 0) {
            sel.value = _state.plans[0].id;
            await loadPlanDetail(_state.plans[0].id);
        } else {
            document.getElementById('emptyMsg').style.display = 'block';
            document.getElementById('calGrid').style.display = 'none';
        }
    } catch (e) { console.error(e); }
}

async function onPlanChange() {
    const id = document.getElementById('planSelect').value;
    if (!id) return;
    await loadPlanDetail(id);
}

async function loadPlanDetail(id) {
    try {
        const r = await fetch(`/api/weekly-plans/${id}`);
        _state.plan = await r.json();
        renderAll();
    } catch (e) { console.error(e); }
}

// ── Render ──────────────────────────────────────────────────────────────
function renderAll() {
    const p = _state.plan;
    if (!p) return;

    // Info cards
    document.getElementById('infoRow').style.display = 'grid';
    document.getElementById('infoWeek').textContent = `${p.week_start} → ${p.week_end}`;
    document.getElementById('infoCode').textContent = `${p.code || '-'} · ${p.status}`;
    const cap = p.weekly_capacity_hours;
    document.getElementById('infoCapacity').textContent = `${cap} h`;
    document.getElementById('infoTech').textContent = `${p.tech_count} téc × ${p.hours_per_night}h × 7 noches`;
    document.getElementById('infoTasks').textContent = p.items.length;
    document.getElementById('infoHours').textContent = `${p.total_hours}h planificadas`;
    document.getElementById('infoDone').textContent = p.executed_count;
    const fillPct = cap ? Math.round((p.total_hours / cap) * 100) : 0;
    document.getElementById('infoFill').textContent = `${fillPct}%`;

    // Botones
    document.getElementById('btnAuto').disabled = false;
    document.getElementById('btnPublish').disabled = false;
    document.getElementById('btnPdf').disabled = false;
    document.getElementById('btnDel').disabled = false;

    // Banner publicación
    const banner = document.getElementById('publishBanner');
    if (p.public_token) {
        banner.style.display = 'flex';
        document.getElementById('publicUrl').textContent =
            `${window.location.origin}/programa-nocturno/publico/${p.public_token}`;
    } else {
        banner.style.display = 'none';
    }

    // Calendario
    renderCalendar();
}

function renderCalendar() {
    const p = _state.plan;
    const grid = document.getElementById('calGrid');
    document.getElementById('emptyMsg').style.display = 'none';
    grid.style.display = 'grid';

    // Solo mostrar las 4 áreas principales (secado, cocción, molino, triturado)
    // Si la planta tiene más, mostrar todas; si no están, usar las existentes.
    const mainAreaNames = ['SECADO', 'COCCION', 'COCCIÓN', 'MOLINO', 'TRITURADO'];
    let areasToShow = _state.areas.filter(a =>
        mainAreaNames.some(n => a.name.toUpperCase().includes(n))
    );
    if (areasToShow.length === 0) areasToShow = _state.areas;

    const weekStart = new Date(p.week_start + 'T00:00:00');
    const capacityPerDay = p.capacity_per_day;

    // Encabezado: columna vacía + 7 días
    let html = '<div class="cal-head"></div>';
    for (let d = 0; d < 7; d++) {
        const date = new Date(weekStart);
        date.setDate(weekStart.getDate() + d);
        const hoursUsed = p.hours_per_day[d] || 0;
        const pctUsed = capacityPerDay ? (hoursUsed / capacityPerDay) * 100 : 0;
        const barCls = pctUsed > 100 ? 'over' : '';
        const isWeekend = d >= 5;
        html += `<div class="cal-head cal-head-day ${isWeekend ? 'weekend' : ''}">
            ${DAY_NAMES[d]}
            <span class="date">${date.getDate()}/${date.getMonth() + 1}</span>
            <div class="cal-head-hours">
                ${hoursUsed.toFixed(1)}h / ${capacityPerDay}h
                <div class="bar"><span class="${barCls}" style="width:${Math.min(100, pctUsed)}%;"></span></div>
            </div>
        </div>`;
    }

    // Filas: una por área
    areasToShow.forEach(area => {
        html += `<div class="area-cell">${area.name}</div>`;
        for (let d = 0; d < 7; d++) {
            const key = `(${d}, ${area.id})`;
            const items = (p.grid && p.grid[key]) || [];
            html += `<div class="cell" data-day="${d}" data-area="${area.id}" ondragover="event.preventDefault()">`;
            items.sort((a, b) => (a.order_index || 0) - (b.order_index || 0));
            items.forEach(it => {
                html += _itemHTML(it);
            });
            html += `<button class="cell-add-btn" onclick="openAddItem(${d}, ${area.id})"><i class="fas fa-plus"></i> Agregar</button>`;
            html += `</div>`;
        }
    });

    grid.innerHTML = html;

    // Activar drag & drop en cada celda
    grid.querySelectorAll('.cell').forEach(cell => {
        new Sortable(cell, {
            group: 'wn-items',
            animation: 150,
            filter: '.cell-add-btn',
            preventOnFilter: false,
            onEnd: async (evt) => {
                const itemId = parseInt(evt.item.dataset.itemId, 10);
                const newDay = parseInt(evt.to.dataset.day, 10);
                const newArea = parseInt(evt.to.dataset.area, 10);
                if (!itemId) return;
                try {
                    await fetch(`/api/weekly-plans/${_state.plan.id}/items/${itemId}`, {
                        method: 'PUT',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({
                            day_of_week: newDay, area_id: newArea,
                            order_index: evt.newIndex,
                        }),
                    });
                    await loadPlanDetail(_state.plan.id);
                } catch (e) { alert('Error moviendo ítem: ' + e.message); }
            },
        });
    });
}

function _itemHTML(it) {
    const done = it.status === 'EJECUTADO';
    return `<div class="item type-${it.source_type || 'custom'} ${done ? 'done' : ''}" data-item-id="${it.id}" draggable="true">
        <div class="item-code">${it.source_code || it.source_type || '—'}</div>
        <div class="item-desc" title="${(it.description || '').replace(/"/g,'&quot;')}">${it.description || it.source_name || '(sin desc.)'}</div>
        <div class="item-meta">
            <span>${it.equipment_tag || ''}</span>
            <span><i class="far fa-clock"></i> ${it.estimated_hours}h</span>
        </div>
        <div class="item-actions">
            ${done ? '' : `<button onclick="executeItem(${it.id})" title="Marcar ejecutado"><i class="fas fa-check"></i></button>`}
            <button class="del" onclick="deleteItem(${it.id})" title="Eliminar"><i class="fas fa-times"></i></button>
        </div>
    </div>`;
}

// ── Crear plan nuevo ────────────────────────────────────────────────────
function openNewPlanModal() {
    const today = new Date();
    document.getElementById('npDate').value = today.toISOString().slice(0, 10);
    const sel = document.getElementById('npProvider');
    sel.innerHTML = '<option value="">- Sin asignar -</option>' +
        _state.providers.map(p => `<option value="${p.id}">${p.name}</option>`).join('');
    document.getElementById('npTech').value = 2;
    document.getElementById('npHours').value = 12;
    document.getElementById('npNotes').value = '';
    document.getElementById('newPlanModal').classList.add('open');
}

function closeModal(id) {
    document.getElementById(id).classList.remove('open');
}

async function createPlan() {
    const payload = {
        week_start: document.getElementById('npDate').value,
        provider_id: parseInt(document.getElementById('npProvider').value, 10) || null,
        tech_count: parseInt(document.getElementById('npTech').value, 10),
        hours_per_night: parseFloat(document.getElementById('npHours').value),
        notes: document.getElementById('npNotes').value,
    };
    try {
        const r = await fetch('/api/weekly-plans', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(payload),
        });
        const j = await r.json();
        if (!r.ok) return alert('Error: ' + (j.error || 'desconocido'));
        closeModal('newPlanModal');
        await loadPlans();
        document.getElementById('planSelect').value = j.id;
        await loadPlanDetail(j.id);
    } catch (e) { alert('Error de red: ' + e.message); }
}

// ── Auto-plan ───────────────────────────────────────────────────────────
async function autoPlan() {
    if (!_state.plan) return;
    if (!confirm('Auto-planificar llenará toda la capacidad semanal con preventivos. ¿Continuar?')) return;
    try {
        const r = await fetch(`/api/weekly-plans/${_state.plan.id}/auto-plan`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({clear_existing: true}),
        });
        const j = await r.json();
        if (!r.ok) return alert('Error: ' + (j.error || 'desconocido'));
        alert(`${j.items_placed} tareas distribuidas. Ocupación por noche: ${j.fill_pct.map(p=>p+'%').join(' · ')}`);
        await loadPlanDetail(_state.plan.id);
    } catch (e) { alert('Error: ' + e.message); }
}

// ── Publicar ────────────────────────────────────────────────────────────
async function publishPlan() {
    if (!_state.plan) return;
    try {
        const r = await fetch(`/api/weekly-plans/${_state.plan.id}/publish`, { method: 'POST' });
        const j = await r.json();
        if (!r.ok) return alert('Error: ' + (j.error || 'desconocido'));
        await loadPlanDetail(_state.plan.id);
    } catch (e) { alert('Error: ' + e.message); }
}

function copyPublicUrl() {
    const url = document.getElementById('publicUrl').textContent;
    navigator.clipboard.writeText(url).then(() => {
        alert('URL copiada. Compártela con el proveedor.');
    });
}

// ── PDF ────────────────────────────────────────────────────────────────
function exportPdf() {
    if (!_state.plan) return;
    window.open(`/api/weekly-plans/${_state.plan.id}/report/pdf`, '_blank');
}

// ── Eliminar plan ──────────────────────────────────────────────────────
async function deletePlan() {
    if (!_state.plan) return;
    if (!confirm(`¿Eliminar el plan ${_state.plan.code}? Esta acción no se puede deshacer.`)) return;
    try {
        const r = await fetch(`/api/weekly-plans/${_state.plan.id}`, { method: 'DELETE' });
        if (!r.ok) return alert('Error eliminando plan');
        _state.plan = null;
        await loadPlans();
    } catch (e) { alert('Error: ' + e.message); }
}

// ── Ejecutar ítem ──────────────────────────────────────────────────────
async function executeItem(itemId) {
    const notes = prompt('Notas de ejecución (opcional):') || '';
    try {
        const r = await fetch(`/api/weekly-plans/${_state.plan.id}/items/${itemId}/execute`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ notes, executed_by: 'jefe_mtto' }),
        });
        const j = await r.json();
        if (!r.ok) return alert('Error: ' + (j.error || 'desconocido'));
        alert(`Ejecutado. Se generó OT ${j.work_order_code}.`);
        await loadPlanDetail(_state.plan.id);
    } catch (e) { alert('Error: ' + e.message); }
}

// ── Eliminar ítem ──────────────────────────────────────────────────────
async function deleteItem(itemId) {
    if (!confirm('¿Eliminar este ítem del plan?')) return;
    try {
        await fetch(`/api/weekly-plans/${_state.plan.id}/items/${itemId}`, { method: 'DELETE' });
        await loadPlanDetail(_state.plan.id);
    } catch (e) { alert('Error: ' + e.message); }
}

// ── Agregar ítem manual ────────────────────────────────────────────────
let _addItemCtx = { day: 0, area_id: null, sourceType: null, sources: [] };

function openAddItem(day, areaId) {
    _addItemCtx = { day, area_id: areaId, sourceType: null, sources: [] };
    const area = _state.areas.find(a => a.id === areaId);
    document.getElementById('addItemContext').textContent =
        `Agregar a ${DAY_FULL[day]} · ${area ? area.name : ''}`;
    document.getElementById('aiSourcePicker').style.display = 'none';
    document.getElementById('aiDesc').value = '';
    document.getElementById('aiHours').value = 1;
    document.getElementById('aiSourceType').value = '';
    document.querySelectorAll('.btn-item-src').forEach(b => b.style.filter = 'grayscale(50%)');
    document.getElementById('addItemModal').classList.add('open');
}

async function setAddItemSrc(srcType) {
    _addItemCtx.sourceType = srcType;
    document.getElementById('aiSourceType').value = srcType;
    document.querySelectorAll('.btn-item-src').forEach(b => {
        b.style.filter = b.dataset.src === srcType ? 'none' : 'grayscale(50%)';
    });

    const picker = document.getElementById('aiSourcePicker');
    if (srcType === 'custom') {
        picker.style.display = 'none';
        document.getElementById('aiDesc').value = '';
        return;
    }
    picker.style.display = 'block';
    const sel = document.getElementById('aiSourceId');
    sel.innerHTML = '<option value="">- Cargando -</option>';
    try {
        // Usamos el endpoint de preventive-sources del shutdown para obtener la lista
        // pero como el plan no tiene shutdown_id, creamos un endpoint alternativo:
        // por simplicidad, usamos una llamada directa a las colecciones.
        // Mejor: endpoint /api/preventive-sources?source_type=...&area_id=...
        const r = await fetch(`/api/preventive-sources?source_type=${srcType}&area_id=${_addItemCtx.area_id}`);
        _addItemCtx.sources = await r.json();
        if (!_addItemCtx.sources.length) {
            sel.innerHTML = '<option value="">Sin puntos disponibles</option>';
            return;
        }
        const icon = s => s === 'ROJO' ? '🔴' : (s === 'AMARILLO' ? '🟡' : '🟢');
        sel.innerHTML = '<option value="">- Elige -</option>' +
            _addItemCtx.sources.map(s =>
                `<option value="${s.source_id}">${icon(s.semaphore)} ${s.code || ''} — ${s.name}</option>`
            ).join('');
    } catch (e) {
        sel.innerHTML = '<option value="">Error cargando</option>';
    }
}

function aiOnSourceSelected() {
    const sid = parseInt(document.getElementById('aiSourceId').value, 10);
    if (!sid) return;
    const src = _addItemCtx.sources.find(s => s.source_id === sid);
    if (!src) return;
    document.getElementById('aiDesc').value = src.description || src.name || '';
}

async function confirmAddItem() {
    const srcType = document.getElementById('aiSourceType').value;
    const payload = {
        day_of_week: _addItemCtx.day,
        area_id: _addItemCtx.area_id,
        source_type: srcType || 'custom',
        source_id: parseInt(document.getElementById('aiSourceId').value, 10) || null,
        description: document.getElementById('aiDesc').value.trim(),
        estimated_hours: parseFloat(document.getElementById('aiHours').value) || 1,
    };
    if (srcType && srcType !== 'custom' && payload.source_id) {
        const src = _addItemCtx.sources.find(s => s.source_id === payload.source_id);
        if (src) {
            payload.source_code = src.code;
            payload.source_name = src.name;
            payload.equipment_tag = src.equipment_tag;
        }
    }
    if (!payload.description) return alert('Describe la tarea o elige un punto.');
    try {
        const r = await fetch(`/api/weekly-plans/${_state.plan.id}/items`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(payload),
        });
        if (!r.ok) return alert('Error agregando ítem');
        closeModal('addItemModal');
        await loadPlanDetail(_state.plan.id);
    } catch (e) { alert('Error: ' + e.message); }
}

// Exports
window.onPlanChange = onPlanChange;
window.openNewPlanModal = openNewPlanModal;
window.closeModal = closeModal;
window.createPlan = createPlan;
window.autoPlan = autoPlan;
window.publishPlan = publishPlan;
window.copyPublicUrl = copyPublicUrl;
window.exportPdf = exportPdf;
window.deletePlan = deletePlan;
window.executeItem = executeItem;
window.deleteItem = deleteItem;
window.openAddItem = openAddItem;
window.setAddItemSrc = setAddItemSrc;
window.aiOnSourceSelected = aiOnSourceSelected;
window.confirmAddItem = confirmAddItem;
