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
        return `
        <div class="shutdown-card" onclick="openDetail(${s.id})">
            <div style="display:flex;justify-content:space-between;align-items:center;">
                <div class="title">${s.name || 'Sin nombre'}</div>
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

    // Info general
    document.getElementById('detailInfo').innerHTML = `
        <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px;">
            <div>
                <h3 style="margin:0;color:#FF9F0A;">${s.name}</h3>
                <div style="color:#9ab0cb;font-size:.88rem;margin-top:4px;">
                    <i class="fas fa-calendar"></i> ${s.shutdown_date} | ${s.start_time} — ${s.end_time}
                    ${s.overtime ? ' <span style="color:#FF9F0A;">(+Horas Extra)</span>' : ''}
                    | <span class="pill ${s.status}">${s.status}</span>
                </div>
                <div style="margin-top:6px;">${(s.areas || []).map(a => `<span class="area-badge">${a.area_name}</span>`).join('')}</div>
            </div>
            <div style="display:flex;gap:16px;text-align:center;">
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

    // OTs por área
    const container = document.getElementById('detailOTsByArea');
    const byArea = s.by_area || {};
    if (!Object.keys(byArea).length) {
        container.innerHTML = '<div class="panel"><div class="empty">No hay OTs asignadas. Use "Crear OT Nueva" o "Vincular OTs" para agregar trabajos.</div></div>';
    } else {
        container.innerHTML = Object.entries(byArea).map(([area, ots]) => `
            <div class="panel">
                <h3><i class="fas fa-industry"></i> ${area} (${ots.length} actividades)</h3>
                <div class="ot-row head" style="grid-template-columns: 1fr 1fr 2fr 1fr 0.6fr 0.8fr 0.6fr;">
                    <div>OT</div><div>Equipo</div><div>Actividad</div><div>Técnico</div><div>Hrs</div><div>Estado</div><div></div>
                </div>
                ${ots.map(ot => `
                    <div class="ot-row" style="grid-template-columns: 1fr 1fr 2fr 1fr 0.6fr 0.8fr 0.6fr;">
                        <div style="font-weight:700;color:#5ac8fa;">${ot.code || 'OT-' + ot.id}</div>
                        <div style="color:#FF9F0A;">${ot.equipment_tag || '-'}</div>
                        <div style="color:#d5e2f5;">${ot.description || '-'}</div>
                        <div style="color:#bfd2ec;">${ot.technician_name || '-'}</div>
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
                `).join('')}
            </div>
        `).join('');
    }

    // Resumen
    document.getElementById('detailSummary').innerHTML = `
        <h3><i class="fas fa-chart-bar"></i> Resumen</h3>
        <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:10px;font-size:.88rem;">
            <div style="padding:8px;background:#1b212b;border-radius:8px;">Total actividades: <strong>${s.ot_count || 0}</strong></div>
            <div style="padding:8px;background:#1b212b;border-radius:8px;">Horas-hombre estimadas: <strong>${s.total_hours || 0} h</strong></div>
            <div style="padding:8px;background:#1b212b;border-radius:8px;">Técnicos involucrados: <strong>${s.technician_count || 0}</strong></div>
            <div style="padding:8px;background:#1b212b;border-radius:8px;">Cumplimiento: <strong>${s.compliance || 0}%</strong></div>
            ${s.observations ? `<div style="padding:8px;background:#1b212b;border-radius:8px;grid-column:span 2;">Observaciones: ${s.observations}</div>` : ''}
        </div>
    `;
}

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

// ── Exportar PDF ────────────────────────────────────────
async function exportShutdownPdf() {
    const content = document.getElementById('printArea');
    if (!content) return;
    try {
        const canvas = await html2canvas(content, { backgroundColor: '#0a0e14', scale: 1.5, useCORS: true, logging: false });
        const imgData = canvas.toDataURL('image/png');
        const { jsPDF } = window.jspdf;
        const pdf = new jsPDF({ orientation: 'landscape', unit: 'mm', format: 'a4' });
        const pageW = pdf.internal.pageSize.getWidth();
        const imgW = pageW - 10;
        const imgH = (canvas.height * imgW) / canvas.width;
        const pageH = pdf.internal.pageSize.getHeight();
        let heightLeft = imgH;
        let position = 5;
        pdf.addImage(imgData, 'PNG', 5, position, imgW, imgH);
        heightLeft -= (pageH - 10);
        while (heightLeft > 0) {
            position = heightLeft - imgH + 5;
            pdf.addPage();
            pdf.addImage(imgData, 'PNG', 5, position, imgW, imgH);
            heightLeft -= (pageH - 10);
        }
        const date = _activeShutdown ? _activeShutdown.shutdown_date : new Date().toISOString().slice(0, 10);
        pdf.save(`Programa_Parada_${date}.pdf`);
    } catch (e) { console.error('exportPdf error:', e); alert('Error al generar PDF'); }
}

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

    // Limpiar formulario
    document.getElementById('cotDesc').value = '';
    document.getElementById('cotDuration').value = '4';
    document.getElementById('cotTechs').value = '1';
    document.getElementById('cotPriority').value = 'Normal';
    document.getElementById('cotType').value = 'Mejora';

    // Cargar taxonomia si no esta cargada
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
        priority: document.getElementById('cotPriority').value,
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
