// Paradas de Planta
let _allShutdowns = [];
let _activeShutdown = null;
let _allAreas = [];

document.addEventListener('DOMContentLoaded', () => {
    initYearFilter();
    loadAreas();
    loadShutdowns();
});

function initYearFilter() {
    const sel = document.getElementById('filterYear');
    const y = new Date().getFullYear();
    for (let i = y + 1; i >= y - 2; i--) {
        const opt = document.createElement('option');
        opt.value = i; opt.textContent = i;
        if (i === y) opt.selected = true;
        sel.appendChild(opt);
    }
}

async function loadAreas() {
    try {
        const res = await fetch('/api/areas');
        _allAreas = await res.json();
    } catch (e) { console.error(e); }
}

async function loadShutdowns() {
    try {
        const year = document.getElementById('filterYear').value;
        const status = document.getElementById('filterStatus').value;
        let url = `/api/shutdowns?year=${year}`;
        if (status) url += `&status=${status}`;
        const res = await fetch(url);
        _allShutdowns = await res.json();
        renderList();
    } catch (e) { console.error(e); }
}

function renderList() {
    const container = document.getElementById('shutdownList');
    if (!_allShutdowns.length) {
        container.innerHTML = '<div class="empty"><i class="fas fa-hard-hat" style="font-size:2rem;color:#444;"></i><br>No hay paradas programadas. Crea la primera con el botón "Nueva Parada".</div>';
        return;
    }
    container.innerHTML = _allShutdowns.map(s => {
        const areas = (s.areas || []).map(a => `<span class="area-badge">${a.area_name || '?'}</span>`).join('');
        const codeBadge = s.code
            ? `<span style="background:rgba(10,132,255,.18);color:#5ac8fa;padding:2px 10px;border-radius:10px;font-size:.72rem;font-weight:700;letter-spacing:.5px;margin-right:8px;">${s.code}</span>`
            : '';
        return `
        <div class="shutdown-card" onclick="openDetail(${s.id})">
            <div style="display:flex;justify-content:space-between;align-items:center;">
                <div class="title">${codeBadge}${s.name || 'Sin nombre'}</div>
                <span class="pill ${s.status}">${s.status}</span>
            </div>
            <div class="meta">
                <i class="fas fa-calendar"></i> ${s.shutdown_date} | ${s.start_time} — ${s.end_time}
                ${s.overtime ? ' <span style="color:#FF9F0A;">(+HE)</span>' : ''}
                | Tipo: ${s.shutdown_type}
            </div>
            <div style="margin-top:6px;">${areas || '<span style="color:#666;">Todas las áreas</span>'}</div>
            <div class="stats" style="color:#9ab0cb;">
                <span class="item"><strong>${s.ot_count || 0}</strong> OTs</span>
                <span class="item"><strong>${s.total_hours || 0}</strong> h estimadas</span>
                <span class="item"><strong>${s.compliance || 0}%</strong> cumplimiento</span>
                <span class="item">${s.ot_closed || 0}/${s.ot_count || 0} cerradas</span>
            </div>
        </div>`;
    }).join('');
}

async function openDetail(shutdownId) {
    try {
        const res = await fetch(`/api/shutdowns/${shutdownId}`);
        _activeShutdown = await res.json();
        document.getElementById('viewList').classList.add('hidden');
        document.getElementById('viewDetail').classList.remove('hidden');
        document.getElementById('detailTitle').textContent = _activeShutdown.name;
        renderDetail();
    } catch (e) { console.error(e); }
}

function backToList() {
    document.getElementById('viewList').classList.remove('hidden');
    document.getElementById('viewDetail').classList.add('hidden');
    _activeShutdown = null;
    loadShutdowns();
}

function renderDetail() {
    const s = _activeShutdown;
    const codeBadge = s.code
        ? `<span style="background:rgba(10,132,255,.18);color:#5ac8fa;padding:3px 12px;border-radius:10px;font-size:.78rem;font-weight:700;letter-spacing:.5px;margin-right:10px;vertical-align:middle;">${s.code}</span>`
        : '';

    // Info general
    document.getElementById('detailInfo').innerHTML = `
        <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px;">
            <div>
                <h3 style="margin:0;color:#FF9F0A;">${codeBadge}${s.name}</h3>
                <div style="color:#9ab0cb;font-size:.88rem;margin-top:6px;">
                    <i class="fas fa-calendar"></i> ${s.shutdown_date} | ${s.start_time} — ${s.end_time}
                    ${s.overtime ? ' <span style="color:#FF9F0A;">(+Horas Extra)</span>' : ''}
                    | <span class="pill ${s.status}">${s.status}</span>
                </div>
                <div style="margin-top:6px;">${(s.areas || []).map(a => `<span class="area-badge">${a.area_name}</span>`).join('')}</div>
            </div>
            <div style="display:flex;gap:16px;text-align:center;flex-wrap:wrap;">
                <div><div style="font-size:1.8rem;font-weight:700;color:#5ac8fa;">${s.ot_count || 0}</div><div style="font-size:.75rem;color:#9ab0cb;">OTs Total</div></div>
                <div><div style="font-size:1.8rem;font-weight:700;color:#30D158;">${s.ot_closed || 0}</div><div style="font-size:.75rem;color:#9ab0cb;">Cerradas</div></div>
                <div><div style="font-size:1.8rem;font-weight:700;color:#FF9F0A;">${s.total_hours || 0}h</div><div style="font-size:.75rem;color:#9ab0cb;">Horas Est.</div></div>
                <div><div style="font-size:1.8rem;font-weight:700;color:${s.compliance >= 80 ? '#30D158' : '#FF453A'};">${s.compliance || 0}%</div><div style="font-size:.75rem;color:#9ab0cb;">Cumplimiento</div></div>
                <div><div style="font-size:1.8rem;font-weight:700;color:#BF5AF2;">${s.technician_count || 0}</div><div style="font-size:.75rem;color:#9ab0cb;">Técnicos</div></div>
            </div>
        </div>`;

    // Requerimientos a producción
    const prodReq = document.getElementById('detailProdReq');
    if (s.production_requirements && s.production_requirements.trim()) {
        prodReq.style.display = 'block';
        document.getElementById('prodReqContent').textContent = s.production_requirements;
    } else {
        prodReq.style.display = 'none';
    }

    // Alerta de faltantes de repuestos
    if (s.materials_shortage && s.materials_shortage > 0) {
        const alertBanner = `<div class="panel" style="background:linear-gradient(90deg,#3d1414,#240c0c);border:1px solid #FF453A;color:#ffb8b0;">
            <i class="fas fa-exclamation-triangle" style="color:#FF453A;"></i>
            <b>Atención:</b> ${s.materials_shortage} repuesto(s) requerido(s) tienen stock insuficiente. Revise "Repuestos Necesarios" abajo.
        </div>`;
        const info = document.getElementById('detailInfo');
        if (!document.getElementById('shortageBanner')) {
            info.insertAdjacentHTML('afterend', `<div id="shortageBanner">${alertBanner}</div>`);
        }
    } else {
        const existing = document.getElementById('shortageBanner');
        if (existing) existing.remove();
    }

    // OTs por área — con columnas Área / Línea / Equipo y orden jerárquico
    const container = document.getElementById('detailOTsByArea');
    const byArea = s.by_area || {};
    if (!Object.keys(byArea).length) {
        container.innerHTML = '<div class="panel"><div class="empty">No hay OTs asignadas. Use "Crear OT Nueva" o "Vincular OTs" para agregar trabajos.</div></div>';
    } else {
        container.innerHTML = Object.entries(byArea).map(([area, ots]) => `
            <div class="panel">
                <h3><i class="fas fa-industry"></i> ${area} <span style="color:#9ab0cb;font-weight:400;font-size:.85rem;">(${ots.length} actividades)</span></h3>
                <div class="ot-row head" style="grid-template-columns: 0.9fr 1fr 1.2fr 2.2fr 0.8fr 0.6fr 0.8fr 0.5fr;">
                    <div>OT</div><div>Línea</div><div>Equipo</div><div>Actividad</div><div>Tipo</div><div>Hrs</div><div>Estado</div><div></div>
                </div>
                ${ots.map(ot => {
                    const hasMaterials = (ot.materials || []).length > 0;
                    const hasShortage = (ot.materials || []).some(m => m.stock !== null && m.stock !== undefined && !m.sufficient);
                    const matBadge = hasMaterials
                        ? `<button onclick="event.stopPropagation();toggleMaterials(${ot.id})" style="background:${hasShortage ? 'rgba(255,69,58,.15)' : 'rgba(48,209,88,.15)'};color:${hasShortage ? '#ff6b63' : '#30D158'};border:1px solid ${hasShortage ? 'rgba(255,69,58,.4)' : 'rgba(48,209,88,.4)'};border-radius:10px;padding:1px 8px;font-size:.68rem;cursor:pointer;margin-left:6px;" title="Ver repuestos">
                            <i class="fas fa-box"></i> ${ot.materials.length}${hasShortage ? ' ⚠' : ''}
                        </button>`
                        : '';
                    return `
                    <div class="ot-row" style="grid-template-columns: 0.9fr 1fr 1.2fr 2.2fr 0.8fr 0.6fr 0.8fr 0.5fr;">
                        <div style="font-weight:700;color:#5ac8fa;">${ot.code || 'OT-' + ot.id}${matBadge}</div>
                        <div style="color:#d5e2f5;font-size:.84rem;">${ot.line_name || '-'}</div>
                        <div style="color:#FF9F0A;">${ot.equipment_tag || '-'} <span style="color:#9ab0cb;font-size:.78rem;">${ot.equipment_name && ot.equipment_name !== '-' ? '— ' + ot.equipment_name : ''}</span></div>
                        <div style="color:#d5e2f5;">${ot.description || '-'}</div>
                        <div style="color:#9ab0cb;font-size:.82rem;">${ot.maintenance_type || '-'}</div>
                        <div>${ot.estimated_duration || '-'}</div>
                        <div><span class="pill ${ot.status === 'Cerrada' ? 'COMPLETADA' : (ot.status === 'En Progreso' ? 'EN_CURSO' : 'PLANIFICADA')}">${ot.status || '-'}</span></div>
                        <div style="text-align:right;">
                            <button onclick="removeOtFromShutdown(${ot.id}, '${(ot.code || 'OT-' + ot.id).replace(/'/g, '')}')"
                                title="Desvincular OT de esta parada"
                                style="background:rgba(255,69,58,.15);color:#ff6b63;border:1px solid rgba(255,69,58,.4);
                                    border-radius:6px;padding:4px 8px;font-size:.72rem;cursor:pointer;">
                                <i class="fas fa-unlink"></i>
                            </button>
                        </div>
                    </div>
                    ${hasMaterials ? `
                    <div id="mats-${ot.id}" style="display:none;padding:8px 14px;background:rgba(10,132,255,.05);border-left:3px solid #0a84ff;margin:0 8px 8px 8px;border-radius:4px;">
                        <div style="color:#5ac8fa;font-size:.78rem;font-weight:700;margin-bottom:4px;"><i class="fas fa-box"></i> Repuestos requeridos para esta OT</div>
                        ${ot.materials.map(m => `
                            <div style="display:grid;grid-template-columns:100px 1fr 80px 100px;gap:10px;padding:4px 0;border-bottom:1px solid rgba(255,255,255,.05);font-size:.82rem;align-items:center;">
                                <div style="color:#FF9F0A;font-family:monospace;">${m.code}</div>
                                <div style="color:#d5e2f5;">${m.name}</div>
                                <div style="text-align:right;color:#fff;"><b>${m.quantity}</b> ${m.unit || ''}</div>
                                <div style="text-align:right;">
                                    ${m.stock === null || m.stock === undefined
                                        ? '<span style="color:#9ab0cb;font-size:.75rem;">Sin stock BD</span>'
                                        : m.sufficient
                                            ? `<span style="color:#30D158;font-size:.75rem;"><i class="fas fa-check"></i> Stock ${m.stock}</span>`
                                            : `<span style="color:#FF453A;font-size:.75rem;"><i class="fas fa-exclamation-triangle"></i> Solo ${m.stock}</span>`
                                    }
                                </div>
                            </div>`).join('')}
                    </div>` : ''}
                    `;
                }).join('')}
            </div>
        `).join('');
    }

    // Resumen
    document.getElementById('detailSummary').innerHTML = `
        <h3><i class="fas fa-chart-bar"></i> Resumen</h3>
        <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:10px;font-size:.88rem;">
            <div style="padding:8px;background:#1b212b;border-radius:8px;">Total actividades: <strong>${s.ot_count || 0}</strong></div>
            <div style="padding:8px;background:#1b212b;border-radius:8px;">Horas-hombre estimadas: <strong>${s.total_hours || 0} h</strong></div>
            <div style="padding:8px;background:#1b212b;border-radius:8px;">Horas reales: <strong>${s.total_real_hours || 0} h</strong></div>
            <div style="padding:8px;background:#1b212b;border-radius:8px;">OTs con repuestos: <strong>${s.ots_with_materials || 0}</strong></div>
            <div style="padding:8px;background:#1b212b;border-radius:8px;">Cumplimiento: <strong>${s.compliance || 0}%</strong></div>
            ${s.materials_shortage ? `<div style="padding:8px;background:rgba(255,69,58,.12);border:1px solid rgba(255,69,58,.3);border-radius:8px;color:#ff6b63;">⚠ Faltantes de stock: <strong>${s.materials_shortage}</strong></div>` : ''}
            ${s.observations ? `<div style="padding:8px;background:#1b212b;border-radius:8px;grid-column:span 2;">Observaciones: ${s.observations}</div>` : ''}
        </div>
    `;
}

function toggleMaterials(otId) {
    const el = document.getElementById(`mats-${otId}`);
    if (el) el.style.display = el.style.display === 'none' ? 'block' : 'none';
}
window.toggleMaterials = toggleMaterials;

// ── Modal Crear/Editar ──────────────────────────────────
function openCreateModal() {
    document.getElementById('modalTitle').textContent = 'Nueva Parada';
    document.getElementById('modalId').value = '';
    // Default: próximo domingo
    const today = new Date();
    const daysUntilSunday = (7 - today.getDay()) % 7 || 7;
    const nextSunday = new Date(today);
    nextSunday.setDate(today.getDate() + daysUntilSunday);
    document.getElementById('modalDate').value = nextSunday.toISOString().slice(0, 10);
    document.getElementById('modalType').value = 'TOTAL';
    document.getElementById('modalStart').value = '07:00';
    document.getElementById('modalEnd').value = '19:00';
    document.getElementById('modalProdReq').value = '';
    document.getElementById('modalObs').value = '';
    renderAreaCheckboxes([]);
    document.getElementById('shutdownModal').showModal();
}

function editCurrentShutdown() {
    if (!_activeShutdown) return;
    const s = _activeShutdown;
    document.getElementById('modalTitle').textContent = 'Editar Parada';
    document.getElementById('modalId').value = s.id;
    document.getElementById('modalDate').value = s.shutdown_date;
    document.getElementById('modalType').value = s.shutdown_type;
    document.getElementById('modalStart').value = s.start_time;
    document.getElementById('modalEnd').value = s.end_time;
    document.getElementById('modalProdReq').value = s.production_requirements || '';
    document.getElementById('modalObs').value = s.observations || '';
    const selectedIds = (s.areas || []).map(a => a.area_id);
    renderAreaCheckboxes(selectedIds);
    document.getElementById('shutdownModal').showModal();
}

function renderAreaCheckboxes(selectedIds) {
    const container = document.getElementById('areaCheckboxes');
    container.innerHTML = _allAreas.map(a => `
        <label><input type="checkbox" value="${a.id}" ${selectedIds.includes(a.id) ? 'checked' : ''}> ${a.name}</label>
    `).join('');
}

function toggleAreaChecks() {
    const type = document.getElementById('modalType').value;
    document.getElementById('areaChecksGroup').style.display = type === 'PARCIAL' ? 'block' : 'block';
}

async function saveShutdown() {
    const id = document.getElementById('modalId').value;
    const areaChecks = document.querySelectorAll('#areaCheckboxes input:checked');
    const areaIds = Array.from(areaChecks).map(c => parseInt(c.value));
    const type = document.getElementById('modalType').value;

    const payload = {
        shutdown_date: document.getElementById('modalDate').value,
        shutdown_type: type,
        start_time: document.getElementById('modalStart').value,
        end_time: document.getElementById('modalEnd').value,
        area_ids: type === 'TOTAL' ? _allAreas.map(a => a.id) : areaIds,
        production_requirements: document.getElementById('modalProdReq').value.trim(),
        observations: document.getElementById('modalObs').value.trim(),
    };

    if (!payload.shutdown_date) { alert('Seleccione una fecha.'); return; }

    try {
        const url = id ? `/api/shutdowns/${id}` : '/api/shutdowns';
        const method = id ? 'PUT' : 'POST';
        const res = await fetch(url, {
            method, headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        if (!res.ok) {
            const err = await res.json();
            alert('Error: ' + (err.error || 'No se pudo guardar'));
            return;
        }
        document.getElementById('shutdownModal').close();
        if (id && _activeShutdown) {
            openDetail(parseInt(id));
        } else {
            loadShutdowns();
        }
    } catch (e) { console.error(e); alert('Error de conexión'); }
}

// ── Modal Agregar OTs ───────────────────────────────────
async function openAddOTModal() {
    if (!_activeShutdown) return;
    try {
        const res = await fetch(`/api/shutdowns/${_activeShutdown.id}/suggestions`);
        const ots = await res.json();
        const container = document.getElementById('suggestedOTs');
        if (!ots.length) {
            container.innerHTML = '<div class="empty">No hay OTs disponibles para agregar.</div>';
        } else {
            container.innerHTML = ots.map(ot => `
                <label style="display:flex;align-items:center;gap:10px;padding:8px;border-bottom:1px solid rgba(255,255,255,.06);cursor:pointer;font-size:.88rem;">
                    <input type="checkbox" value="${ot.id}" style="accent-color:#30D158;">
                    <span style="font-weight:700;color:#5ac8fa;min-width:70px;">${ot.code || 'OT-' + ot.id}</span>
                    <span style="color:#FF9F0A;min-width:80px;">${ot.equipment_tag || '-'}</span>
                    <span style="color:#d5e2f5;flex:1;">${ot.description || '-'}</span>
                    <span class="pill PLANIFICADA">${ot.status}</span>
                </label>
            `).join('');
        }
        document.getElementById('addOTModal').showModal();
    } catch (e) { console.error(e); }
}

async function confirmAddOTs() {
    const checks = document.querySelectorAll('#suggestedOTs input:checked');
    const ids = Array.from(checks).map(c => parseInt(c.value));
    if (!ids.length) { alert('Seleccione al menos una OT.'); return; }
    try {
        const res = await fetch(`/api/shutdowns/${_activeShutdown.id}/add-ot`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ot_ids: ids })
        });
        if (res.ok) {
            document.getElementById('addOTModal').close();
            openDetail(_activeShutdown.id);
        }
    } catch (e) { console.error(e); }
}

// ── Exportar Reporte Ejecutivo PDF (servidor) ───────────
function exportShutdownPdf() {
    if (!_activeShutdown || !_activeShutdown.id) return;
    window.open(`/api/shutdowns/${_activeShutdown.id}/report/pdf`, '_blank');
}

// ── Exportar Reporte Ejecutivo Excel ────────────────────
function exportShutdownExcel() {
    if (!_activeShutdown || !_activeShutdown.id) return;
    window.location.href = `/api/shutdowns/${_activeShutdown.id}/report/excel`;
}

window.exportShutdownExcel = exportShutdownExcel;

window.loadShutdowns = loadShutdowns;
window.openCreateModal = openCreateModal;
window.openDetail = openDetail;
window.backToList = backToList;
window.saveShutdown = saveShutdown;
window.editCurrentShutdown = editCurrentShutdown;
window.openAddOTModal = openAddOTModal;
window.confirmAddOTs = confirmAddOTs;
window.exportShutdownPdf = exportShutdownPdf;
window.toggleAreaChecks = toggleAreaChecks;


// ── Crear OT nueva dentro de la parada (plan de trabajos aprovechados) ───
let _cotAreas = [];
let _cotLines = [];
let _cotEquips = [];
let _cotSystems = [];
let _cotComponents = [];

async function openCreateOTInShutdownModal() {
    if (!_activeShutdown || !_activeShutdown.id) return alert('No hay parada seleccionada');
    document.getElementById('cotShutdownId').value = _activeShutdown.id;

    // Reset selector de fuente preventiva
    cotSetSourceType('none');

    // Limpiar formulario
    document.getElementById('cotDesc').value = '';
    document.getElementById('cotDuration').value = '4';
    document.getElementById('cotTechs').value = '1';
    document.getElementById('cotType').value = 'Mejora';

    // Cargar taxonomia + proveedores si no estan cargados
    if (_cotAreas.length === 0) {
        try {
            const [a, l, e, s, c] = await Promise.all([
                fetch('/api/areas').then(r => r.json()),
                fetch('/api/lines').then(r => r.json()),
                fetch('/api/equipments').then(r => r.json()),
                fetch('/api/systems').then(r => r.json()),
                fetch('/api/components').then(r => r.json()),
            ]);
            _cotAreas = a; _cotLines = l; _cotEquips = e;
            _cotSystems = s; _cotComponents = c;
        } catch (err) {
            return alert('Error cargando taxonomia: ' + err);
        }
    }

    // Poblar Proveedores (siempre, por si se agrego alguno nuevo)
    try {
        const providers = await fetch('/api/providers').then(r => r.json());
        const provSel = document.getElementById('cotProvider');
        provSel.innerHTML = '<option value="">- Interno -</option>' +
            providers.map(p => `<option value="${p.id}">${p.name}</option>`).join('');
        provSel.value = '';
    } catch (err) {
        console.warn('No se pudieron cargar proveedores:', err);
    }

    // Poblar Areas
    const areaSel = document.getElementById('cotArea');
    areaSel.innerHTML = '<option value="">- Selecciona -</option>' +
        _cotAreas.map(a => `<option value="${a.id}">${a.name}</option>`).join('');

    // Reset cascada
    document.getElementById('cotLine').innerHTML = '<option value="">- Selecciona area -</option>';
    document.getElementById('cotEquip').innerHTML = '<option value="">- Selecciona linea -</option>';
    document.getElementById('cotSystem').innerHTML = '<option value="">- Selecciona equipo -</option>';
    document.getElementById('cotComponent').innerHTML = '<option value="">- Selecciona sistema -</option>';

    document.getElementById('createOTModal').showModal();
}

function cotOnAreaChange() {
    const aid = document.getElementById('cotArea').value;
    const lineSel = document.getElementById('cotLine');
    if (!aid) {
        lineSel.innerHTML = '<option value="">- Selecciona area -</option>';
        return;
    }
    const filtered = _cotLines.filter(l => String(l.area_id) === String(aid));
    lineSel.innerHTML = '<option value="">- Sin linea -</option>' +
        filtered.map(l => `<option value="${l.id}">${l.name}</option>`).join('');
    cotOnLineChange();
}

function cotOnLineChange() {
    const lid = document.getElementById('cotLine').value;
    const equipSel = document.getElementById('cotEquip');
    if (!lid) {
        equipSel.innerHTML = '<option value="">- Selecciona linea -</option>';
        return;
    }
    const filtered = _cotEquips.filter(e => String(e.line_id) === String(lid));
    equipSel.innerHTML = '<option value="">- Sin equipo -</option>' +
        filtered.map(e => `<option value="${e.id}">[${e.tag || '-'}] ${e.name}</option>`).join('');
    cotOnEquipChange();
}

function cotOnEquipChange() {
    const eid = document.getElementById('cotEquip').value;
    const sysSel = document.getElementById('cotSystem');
    if (!eid) {
        sysSel.innerHTML = '<option value="">- Selecciona equipo -</option>';
        return;
    }
    const filtered = _cotSystems.filter(s => String(s.equipment_id) === String(eid));
    sysSel.innerHTML = '<option value="">- Sin sistema -</option>' +
        filtered.map(s => `<option value="${s.id}">${s.name}</option>`).join('');
    cotOnSystemChange();
}

function cotOnSystemChange() {
    const sid = document.getElementById('cotSystem').value;
    const compSel = document.getElementById('cotComponent');
    if (!sid) {
        compSel.innerHTML = '<option value="">- Selecciona sistema -</option>';
        return;
    }
    const filtered = _cotComponents.filter(c => String(c.system_id) === String(sid));
    compSel.innerHTML = '<option value="">- Sin componente -</option>' +
        filtered.map(c => `<option value="${c.id}">${c.name}</option>`).join('');
}

async function confirmCreateOTInShutdown() {
    const shId = document.getElementById('cotShutdownId').value;
    if (!shId) return alert('Falta parada');

    const area = document.getElementById('cotArea').value;
    const equip = document.getElementById('cotEquip').value;
    const desc = document.getElementById('cotDesc').value.trim();
    if (!area) return alert('Selecciona un area');
    if (!equip) return alert('Selecciona un equipo');
    if (!desc) return alert('Escribe una descripcion');

    const sourceType = document.getElementById('cotSourceType').value || null;
    const sourceId = parseInt(document.getElementById('cotSourceId').value || 0, 10) || null;

    const payload = {
        area_id: parseInt(area, 10),
        line_id: parseInt(document.getElementById('cotLine').value, 10) || null,
        equipment_id: parseInt(equip, 10),
        system_id: parseInt(document.getElementById('cotSystem').value, 10) || null,
        component_id: parseInt(document.getElementById('cotComponent').value, 10) || null,
        description: desc,
        maintenance_type: document.getElementById('cotType').value,
        estimated_duration: parseFloat(document.getElementById('cotDuration').value) || 0,
        tech_count: parseInt(document.getElementById('cotTechs').value, 10) || 1,
        provider_id: parseInt(document.getElementById('cotProvider').value, 10) || null,
        source_type: sourceType,
        source_id: sourceId,
        status: 'Programada',
    };

    try {
        const res = await fetch(`/api/shutdowns/${shId}/work-orders`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        const data = await res.json();
        if (!res.ok) return alert('Error: ' + (data.error || res.status));
        alert(`OT creada: ${data.code}`);
        document.getElementById('createOTModal').close();
        // Recargar detalle de la parada
        if (typeof openDetail === 'function') await openDetail(shId);
    } catch (err) {
        alert('Error creando OT: ' + err);
    }
}

window.openCreateOTInShutdownModal = openCreateOTInShutdownModal;
window.cotOnAreaChange = cotOnAreaChange;
window.cotOnLineChange = cotOnLineChange;
window.cotOnEquipChange = cotOnEquipChange;
window.cotOnSystemChange = cotOnSystemChange;
window.confirmCreateOTInShutdown = confirmCreateOTInShutdown;


// ── Selector de fuente preventiva (lubricacion / inspeccion / monitoreo) ─
let _cotPreventiveSources = [];

async function cotSetSourceType(type) {
    // Actualizar estado visual de los botones
    document.querySelectorAll('#createOTModal .btn-source').forEach(btn => {
        const t = btn.getAttribute('data-source');
        if (t === type) {
            btn.classList.add('active');
            btn.style.filter = 'none';
            btn.style.opacity = '1';
            btn.style.outline = '2px solid rgba(255,255,255,.35)';
        } else {
            btn.classList.remove('active');
            btn.style.filter = 'grayscale(50%)';
            btn.style.opacity = '0.6';
            btn.style.outline = 'none';
        }
    });

    const picker = document.getElementById('cotPreventivePicker');
    const srcHid = document.getElementById('cotSourceType');
    const idHid = document.getElementById('cotSourceId');
    const info = document.getElementById('cotSourceInfo');
    info.textContent = '';
    idHid.value = '';

    if (type === 'none') {
        picker.style.display = 'none';
        srcHid.value = '';
        return;
    }

    srcHid.value = type;
    picker.style.display = 'block';

    // Cargar puntos disponibles
    const sel = document.getElementById('cotSourceSelect');
    sel.innerHTML = '<option value="">- Cargando puntos disponibles... -</option>';
    try {
        const shId = document.getElementById('cotShutdownId').value;
        const res = await fetch(`/api/shutdowns/${shId}/preventive-sources?source_type=${type}`);
        const data = await res.json();
        _cotPreventiveSources = Array.isArray(data) ? data : [];

        if (_cotPreventiveSources.length === 0) {
            sel.innerHTML = '<option value="">Sin puntos disponibles en las areas de esta parada</option>';
            info.innerHTML = '<i class="fas fa-info-circle"></i> Todos los puntos estan al dia o ya tienen OT vinculada.';
            return;
        }

        // Emoji segun semaforo
        const semIcon = s => s === 'ROJO' ? '🔴' : (s === 'AMARILLO' ? '🟡' : '🟢');
        sel.innerHTML = '<option value="">- Selecciona un punto -</option>' +
            _cotPreventiveSources.map(s =>
                `<option value="${s.source_id}">${semIcon(s.semaphore)} ${s.code || ''} — ${s.name} [${s.equipment_tag}] · venc: ${s.next_due_date}</option>`
            ).join('');
    } catch (e) {
        sel.innerHTML = '<option value="">Error al cargar puntos</option>';
        info.innerHTML = `<span style="color:#FF453A;">Error: ${e.message}</span>`;
    }
}

function cotOnSourceSelected() {
    const sel = document.getElementById('cotSourceSelect');
    const sid = parseInt(sel.value, 10);
    const idHid = document.getElementById('cotSourceId');
    const info = document.getElementById('cotSourceInfo');

    if (!sid) {
        idHid.value = '';
        info.textContent = '';
        return;
    }

    const src = _cotPreventiveSources.find(s => s.source_id === sid);
    if (!src) return;

    idHid.value = sid;

    // Auto-llenar descripcion
    document.getElementById('cotDesc').value = src.description || '';

    // Forzar tipo = Preventivo
    document.getElementById('cotType').value = 'Preventivo';

    // Auto-seleccionar taxonomia (area -> linea -> equipo -> sistema/comp)
    if (src.area_id) {
        document.getElementById('cotArea').value = src.area_id;
        cotOnAreaChange();
        setTimeout(() => {
            if (src.line_id) {
                document.getElementById('cotLine').value = src.line_id;
                cotOnLineChange();
                setTimeout(() => {
                    if (src.equipment_id) {
                        document.getElementById('cotEquip').value = src.equipment_id;
                        cotOnEquipChange();
                        setTimeout(() => {
                            if (src.system_id) {
                                document.getElementById('cotSystem').value = src.system_id;
                                cotOnSystemChange();
                                setTimeout(() => {
                                    if (src.component_id) {
                                        document.getElementById('cotComponent').value = src.component_id;
                                    }
                                }, 50);
                            }
                        }, 50);
                    }
                }, 50);
            }
        }, 50);
    }

    info.innerHTML = `<i class="fas fa-check-circle" style="color:#30D158;"></i>
        Vinculado a <b>${src.code || ''} ${src.name}</b> · al cerrar esta OT se actualiza automaticamente la proxima fecha del punto.`;
}

window.cotSetSourceType = cotSetSourceType;
window.cotOnSourceSelected = cotOnSourceSelected;


// ── Desvincular OT de una parada ─────────────────────────────────
async function removeOtFromShutdown(otId, otCode) {
    if (!_activeShutdown || !_activeShutdown.id) return;
    if (!confirm(`¿Desvincular la OT ${otCode} de esta parada?\n\nLa OT NO se elimina, solo deja de estar asociada a la parada.`)) return;
    try {
        const res = await fetch(`/api/shutdowns/${_activeShutdown.id}/remove-ot/${otId}`, {
            method: 'DELETE',
        });
        const data = await res.json();
        if (!res.ok) return alert('Error: ' + (data.error || res.status));
        // Recargar detalle
        await openDetail(_activeShutdown.id);
    } catch (e) {
        alert('Error desvinculando: ' + e);
    }
}

// ── Eliminar parada completa ─────────────────────────────────────
async function deleteCurrentShutdown() {
    if (!_activeShutdown || !_activeShutdown.id) return;
    const name = _activeShutdown.name || ('PARADA-' + _activeShutdown.id);
    const count = (_activeShutdown.ot_count != null)
        ? _activeShutdown.ot_count
        : 0;

    let msg = `¿Eliminar la parada "${name}"?`;
    if (count > 0) {
        msg += `\n\nAtencion: tiene ${count} OTs vinculadas. Las OTs NO se eliminan, solo se desvinculan de la parada (vuelven al listado como OTs sueltas).`;
    }
    msg += `\n\nEsta accion no se puede deshacer.`;
    if (!confirm(msg)) return;

    try {
        const res = await fetch(`/api/shutdowns/${_activeShutdown.id}`, {
            method: 'DELETE',
        });
        const data = await res.json();
        if (!res.ok) return alert('Error: ' + (data.error || res.status));
        alert('Parada eliminada');
        if (typeof backToList === 'function') backToList();
        if (typeof loadShutdowns === 'function') loadShutdowns();
    } catch (e) {
        alert('Error eliminando parada: ' + e);
    }
}

window.removeOtFromShutdown = removeOtFromShutdown;
window.deleteCurrentShutdown = deleteCurrentShutdown;

// ════════════════════════════════════════════════════════════════════════
// APLICAR PLANTILLA A LA PARADA (Opcion D — preview con cruce)
// ════════════════════════════════════════════════════════════════════════

let _applyTplData = null;  // {candidates, summary, ...} del preview actual

async function openApplyTemplateModal() {
    const shId = (typeof _activeShutdown !== 'undefined' && _activeShutdown) ? _activeShutdown.id : null;
    if (!shId) { alert('Abre una parada primero'); return; }
    try {
        const tpls = await (await fetch('/api/shutdown-templates?only_active=1')).json();
        const sel = document.getElementById('applyTplSelect');
        if (!tpls.length) {
            sel.innerHTML = '<option value="">(no hay plantillas — crea una primero)</option>';
        } else {
            sel.innerHTML = '<option value="">- Seleccione plantilla -</option>' +
                tpls.map(t => `<option value="${t.id}">${escapeHtmlT(t.name)} — ${t.item_count} tareas</option>`).join('');
        }
        document.getElementById('applyTplPreview').innerHTML = '<div class="empty">Selecciona una plantilla y presiona Previsualizar.</div>';
        document.getElementById('applyTplSummary').innerHTML = '';
        document.getElementById('btnCommitTpl').disabled = true;
        _applyTplData = null;
        document.getElementById('applyTplModal').showModal();
    } catch (e) { alert('Error: ' + e.message); }
}
window.openApplyTemplateModal = openApplyTemplateModal;

async function loadTemplatePreview() {
    const shId = (typeof _activeShutdown !== 'undefined' && _activeShutdown) ? _activeShutdown.id : null;
    const tplId = document.getElementById('applyTplSelect').value;
    if (!shId) { alert('Abre una parada primero'); return; }
    if (!tplId) { alert('Selecciona una plantilla'); return; }
    try {
        const r = await fetch(`/api/shutdowns/${shId}/apply-template/${tplId}`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ commit: false })
        });
        const data = await r.json();
        if (!r.ok || data.error) { alert('Error: ' + (data.error || r.statusText)); return; }
        _applyTplData = data;
        renderTplPreview();
    } catch (e) { alert('Error: ' + e.message); }
}
window.loadTemplatePreview = loadTemplatePreview;

function renderTplPreview() {
    if (!_applyTplData) return;
    const { candidates, summary } = _applyTplData;
    const onlyOk = document.getElementById('applyTplOnlyOk').checked;
    const visible = onlyOk ? candidates.filter(c => c.status !== 'duplicate') : candidates;

    document.getElementById('applyTplSummary').innerHTML =
        `<strong>${summary.total}</strong> candidatas — ` +
        `<span style="color:#30D158;">${summary.ok} ok</span> · ` +
        `<span style="color:#FF9F0A;">${summary.preventive_near} con preventivo cercano</span> · ` +
        `<span style="color:#9ab0cb;">${summary.duplicate} ya existen</span>`;

    if (!visible.length) {
        document.getElementById('applyTplPreview').innerHTML = '<div class="empty">Sin candidatas visibles.</div>';
        document.getElementById('btnCommitTpl').disabled = true;
        return;
    }

    // Agrupar por description del item (cabecera)
    const byItem = new Map();
    visible.forEach(c => {
        const k = c.item_description_template || c.description;
        if (!byItem.has(k)) byItem.set(k, []);
        byItem.get(k).push(c);
    });

    const html = ['<div style="font-size:.85rem;">'];
    html.push(`<div style="margin-bottom:8px;">
        <button class="btn-icon" onclick="toggleAllTpl(true)" style="background:rgba(48,209,88,.15);color:#30D158;border:1px solid rgba(48,209,88,.3);padding:4px 10px;border-radius:6px;">Marcar todas (ok)</button>
        <button class="btn-icon" onclick="toggleAllTpl(false)" style="background:rgba(255,255,255,.06);color:#9ab0cb;padding:4px 10px;border-radius:6px;">Desmarcar todas</button>
    </div>`);

    for (const [tplDesc, group] of byItem) {
        html.push(`<div style="margin-bottom:14px;">
            <div style="font-weight:700;color:#FF9F0A;padding:6px 0;border-bottom:1px solid #344964;">
                ${escapeHtmlT(tplDesc)} <span style="color:#9ab0cb;font-weight:400;font-size:.78rem;">(${group.length})</span>
            </div>`);
        for (const c of group) {
            const dup = c.status === 'duplicate';
            const warn = c.status === 'preventive_near';
            const bg = dup ? 'rgba(255,255,255,.03)' : warn ? 'rgba(255,159,10,.07)' : 'transparent';
            const checkColor = dup ? '#666' : warn ? '#FF9F0A' : '#30D158';
            html.push(`<div style="display:grid;grid-template-columns:30px 110px 1fr 220px;gap:8px;padding:6px 8px;align-items:center;background:${bg};border-radius:4px;margin-top:2px;">
                <input type="checkbox" class="tpl-cand-cb" data-key="${c.key}" data-status="${c.status}" ${dup ? 'disabled' : 'checked'} style="accent-color:${checkColor};transform:scale(1.2);">
                <span style="color:#5ac8fa;font-weight:700;">${escapeHtmlT(c.equipment_tag || '?')}</span>
                <span style="color:${dup ? '#666' : '#eff6ff'};">${escapeHtmlT(c.description)}</span>
                <span style="font-size:.75rem;color:${dup ? '#666' : warn ? '#FF9F0A' : '#9ab0cb'};">${dup ? '🚫 ' : warn ? '⚠️ ' : '✅ '}${escapeHtmlT(c.hint || c.equipment_name || '')}</span>
            </div>`);
        }
        html.push('</div>');
    }
    html.push('</div>');
    document.getElementById('applyTplPreview').innerHTML = html.join('');
    updateCommitButtonState();
    document.querySelectorAll('.tpl-cand-cb').forEach(cb => cb.addEventListener('change', updateCommitButtonState));
}

function toggleOnlyOk() { renderTplPreview(); }
window.toggleOnlyOk = toggleOnlyOk;

function toggleAllTpl(on) {
    document.querySelectorAll('.tpl-cand-cb').forEach(cb => {
        if (cb.disabled) return;
        cb.checked = !!on;
    });
    updateCommitButtonState();
}
window.toggleAllTpl = toggleAllTpl;

function updateCommitButtonState() {
    const btn = document.getElementById('btnCommitTpl');
    const checked = document.querySelectorAll('.tpl-cand-cb:checked').length;
    btn.disabled = checked === 0;
    btn.innerHTML = checked === 0
        ? '<i class="fas fa-check-double"></i> Generar OTs'
        : `<i class="fas fa-check-double"></i> Generar ${checked} OT${checked > 1 ? 's' : ''}`;
}

async function commitTemplate() {
    const shId = (typeof _activeShutdown !== 'undefined' && _activeShutdown) ? _activeShutdown.id : null;
    const tplId = document.getElementById('applyTplSelect').value;
    if (!shId || !tplId || !_applyTplData) return;
    const keys = Array.from(document.querySelectorAll('.tpl-cand-cb:checked')).map(cb => cb.dataset.key);
    if (!keys.length) { alert('No hay tareas seleccionadas'); return; }
    if (!confirm(`Se generaran ${keys.length} OTs en esta parada. ¿Continuar?`)) return;
    try {
        const r = await fetch(`/api/shutdowns/${shId}/apply-template/${tplId}`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ commit: true, selected_keys: keys })
        });
        const data = await r.json();
        if (!r.ok || data.error) { alert('Error: ' + (data.error || r.statusText)); return; }
        alert(`OTs generadas: ${data.created_count}\nOmitidas: ${data.skipped_count}`);
        document.getElementById('applyTplModal').close();
        if (typeof openDetail === 'function') openDetail(shId);
    } catch (e) { alert('Error: ' + e.message); }
}
window.commitTemplate = commitTemplate;

function escapeHtmlT(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g,
        c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}
