// Inspección de Espesores por Ultrasonido
let _thkDashboard = [];
let _thkActiveEquipment = null;
let _thkPoints = [];
let _thkValues = {};  // { point_id: value }
let _editingInspectionId = null; // null = nueva, int = editando

document.addEventListener('DOMContentLoaded', () => {
    reloadDashboard();
});

async function reloadDashboard() {
    try {
        const res = await fetch('/api/thickness/dashboard');
        const data = await res.json();
        _thkDashboard = data.equipos || [];
        renderDashboard();
    } catch (e) {
        console.error('thickness dashboard error:', e);
    }
}

function renderDashboard() {
    const grid = document.getElementById('thkDashGrid');
    if (!grid) return;
    if (_thkDashboard.length === 0) {
        grid.innerHTML = '<div class="empty-msg">No hay equipos con puntos de espesor catalogados.<br>Ejecuta el script de inicialización primero.</div>';
        return;
    }
    grid.innerHTML = _thkDashboard.map(eq => {
        const semaphore = eq.semaphore_status || 'PENDIENTE';
        const days = eq.days_left;
        const daysText = days === null ? 'Sin inspecciones' :
            days < 0 ? `Vencida hace ${Math.abs(days)} días` :
            days === 0 ? 'Vence hoy' : `Faltan ${days} días`;
        const lastDate = eq.last_inspection_date || 'Nunca';
        const critical = eq.critical_count || 0;
        const alerts = eq.alert_count || 0;
        return `
        <div class="eq-card" onclick="openInspectionFor(${eq.equipment_id})">
            <div class="tag">${eq.equipment_tag || '?'}</div>
            <div class="name">${eq.equipment_name || ''}</div>
            <div class="row">
                <span><i class="fas fa-calendar"></i> ${lastDate}</span>
                <span class="pill ${semaphore}">${semaphore}</span>
            </div>
            <div class="row">
                <span style="color:${days !== null && days < 0 ? '#ff9690' : '#9ab0cb'};">${daysText}</span>
                <span style="color:#bfd2ec;">${eq.point_count || 0} puntos</span>
            </div>
            ${critical > 0 || alerts > 0 ? `
            <div class="row" style="margin-top:6px;border-top:1px solid #2f4257;padding-top:6px;">
                ${critical > 0 ? `<span style="color:#ff9690;"><i class="fas fa-exclamation-triangle"></i> ${critical} crítico${critical > 1 ? 's' : ''}</span>` : '<span></span>'}
                ${alerts > 0 ? `<span style="color:#ffd966;"><i class="fas fa-exclamation"></i> ${alerts} alerta${alerts > 1 ? 's' : ''}</span>` : '<span></span>'}
            </div>` : ''}
            <div style="margin-top:8px;display:flex;gap:6px;">
                <button class="btn primary" style="flex:1;font-size:.78rem;height:30px;padding:0;" onclick="event.stopPropagation();openInspectionFor(${eq.equipment_id})">
                    <i class="fas fa-plus"></i> Nueva
                </button>
                <button class="btn" style="flex:1;font-size:.78rem;height:30px;padding:0;" onclick="event.stopPropagation();openHistoryFor(${eq.equipment_id})">
                    <i class="fas fa-history"></i> Histórico
                </button>
            </div>
        </div>`;
    }).join('');
}

async function openInspectionFor(equipmentId, inspectionId) {
    try {
        const eq = _thkDashboard.find(e => e.equipment_id === equipmentId);
        _thkActiveEquipment = eq;
        _editingInspectionId = inspectionId || null;
        // Cargar puntos del equipo
        const res = await fetch(`/api/thickness/points/${equipmentId}`);
        _thkPoints = await res.json();
        if (!_thkPoints.length) {
            alert('Este equipo no tiene puntos catalogados.');
            return;
        }
        _thkValues = {};
        document.getElementById('thkDashboard').classList.add('hidden');
        document.getElementById('thkCapture').classList.remove('hidden');
        document.getElementById('thkHistory').classList.add('hidden');

        if (_editingInspectionId) {
            // Modo edición: cargar datos existentes
            const inspRes = await fetch(`/api/thickness/inspections/${_editingInspectionId}`);
            const inspData = await inspRes.json();
            document.getElementById('captureTitle').textContent = `✏️ Editando — ${eq.equipment_tag} — ${inspData.inspection_date}`;
            document.getElementById('capInspDate').value = inspData.inspection_date || '';
            document.getElementById('capInspector').value = inspData.inspector_name || '';
            document.getElementById('capObservations').value = inspData.observations || '';
            const pdfInp = document.getElementById('capPdfUrl');
            if (pdfInp) pdfInp.value = inspData.pdf_url || '';
            // Pre-llenar valores de readings
            (inspData.readings || []).forEach(r => {
                _thkValues[r.point_id] = r.value_mm;
            });
        } else {
            document.getElementById('captureTitle').textContent = `${eq.equipment_tag} — ${eq.equipment_name}`;
            document.getElementById('capInspDate').value = new Date().toISOString().slice(0, 10);
            document.getElementById('capInspector').value = '';
            document.getElementById('capObservations').value = '';
            const pdfInp = document.getElementById('capPdfUrl');
            if (pdfInp) pdfInp.value = '';
        }
        renderCaptureSections();
        updateSummary();
    } catch (e) {
        console.error('openInspectionFor error:', e);
        alert('Error al cargar puntos.');
    }
}

function backToDashboard() {
    document.getElementById('thkDashboard').classList.remove('hidden');
    document.getElementById('thkCapture').classList.add('hidden');
    document.getElementById('thkHistory').classList.add('hidden');
    reloadDashboard();
}

function renderCaptureSections() {
    const container = document.getElementById('thkSections');
    if (!container) return;
    // Agrupar puntos por group_name
    const groups = {};
    _thkPoints.forEach(p => {
        if (!groups[p.group_name]) groups[p.group_name] = [];
        groups[p.group_name].push(p);
    });

    let html = '';

    // PALETAS DE TRIPODE (5 secciones × 3 posiciones A,B,C)
    if (groups['PALETA']) {
        html += renderTripodeTable('PALETAS DE TRIPODE', groups['PALETA'], ['A', 'B', 'C']);
    }
    // REFUERZO DE TRIPODE (5 secciones × 3 posiciones X,Y,Z)
    if (groups['REFUERZO']) {
        html += renderTripodeTable('REFUERZO DE TRIPODE', groups['REFUERZO'], ['X', 'Y', 'Z']);
    }
    // EJES DE TRIPODE (5 secciones × 4 posiciones A,B,C,EJE_CENTRAL)
    if (groups['EJE']) {
        html += renderTripodeTable('EJES DE TRIPODE', groups['EJE'], ['A', 'B', 'C', 'EJE_CENTRAL']);
    }
    // CHAQUETA INTERNA (5 secciones × 4 ángulos)
    if (groups['CHAQUETA']) {
        html += renderChaquetaTable('CHAQUETA INTERNA', groups['CHAQUETA']);
    }
    // TAPAS
    if (groups['TAPA_MOTRIZ']) {
        html += renderTapaTable('TAPA BOMBEADA MOTRIZ (Transmisión)', groups['TAPA_MOTRIZ']);
    }
    if (groups['TAPA_CONDUCIDA']) {
        html += renderTapaTable('TAPA BOMBEADA CONDUCIDA (Descarga)', groups['TAPA_CONDUCIDA']);
    }

    container.innerHTML = html;

    // Pre-llenar inputs con valores existentes (en modo edición)
    container.querySelectorAll('input.thk-input').forEach(inp => {
        const pid = inp.getAttribute('data-point-id');
        if (_thkValues[pid] != null) {
            inp.value = _thkValues[pid];
            // Aplicar coloreo
            const alarm = parseFloat(inp.getAttribute('data-alarm'));
            const scrap = parseFloat(inp.getAttribute('data-scrap'));
            inp.classList.remove('normal', 'alert', 'critical');
            if (_thkValues[pid] <= scrap) inp.classList.add('critical');
            else if (_thkValues[pid] <= alarm) inp.classList.add('alert');
            else inp.classList.add('normal');
        }
        inp.addEventListener('input', onValueChange);
    });
}

function renderTripodeTable(title, points, positions) {
    // Filas = posiciones (A,B,C o X,Y,Z), columnas = secciones 1..5
    const sections = [...new Set(points.map(p => p.section))].sort((a, b) => a - b);
    let html = `<div class="panel"><h4>${title}</h4><table class="thk-table"><thead><tr><th></th>`;
    sections.forEach(s => html += `<th>${s}</th>`);
    html += '</tr></thead><tbody>';
    positions.forEach(pos => {
        const label = pos === 'EJE_CENTRAL' ? 'EJE CENTRAL' : pos;
        html += `<tr><td class="label">${label}</td>`;
        sections.forEach(s => {
            const p = points.find(pt => pt.section === s && pt.position === pos);
            if (p) {
                html += `<td><input class="thk-input" type="number" step="0.01" min="0" data-point-id="${p.id}" data-nominal="${p.nominal_thickness}" data-alarm="${p.alarm_thickness}" data-scrap="${p.scrap_thickness}" placeholder="${p.last_value || ''}"></td>`;
            } else {
                html += `<td>-</td>`;
            }
        });
        html += '</tr>';
    });
    html += '</tbody></table></div>';
    return html;
}

function renderChaquetaTable(title, points) {
    const sections = [...new Set(points.map(p => p.section))].sort((a, b) => a - b);
    const positions = [
        { code: 'SUPERIOR', label: 'SUPERIOR (0°)' },
        { code: 'DERECHO', label: 'DERECHO (90°)' },
        { code: 'INFERIOR', label: 'INFERIOR (180°)' },
        { code: 'IZQUIERDO', label: 'IZQUIERDO (270°)' },
    ];
    let html = `<div class="panel"><h4>${title}</h4><table class="thk-table"><thead><tr><th>LADO DE CHAQUETA</th>`;
    sections.forEach(s => html += `<th>${s}</th>`);
    html += '</tr></thead><tbody>';
    positions.forEach(pos => {
        html += `<tr><td class="label">${pos.label}</td>`;
        sections.forEach(s => {
            const p = points.find(pt => pt.section === s && pt.position === pos.code);
            if (p) {
                html += `<td><input class="thk-input" type="number" step="0.01" min="0" data-point-id="${p.id}" data-nominal="${p.nominal_thickness}" data-alarm="${p.alarm_thickness}" data-scrap="${p.scrap_thickness}" placeholder="${p.last_value || ''}"></td>`;
            } else {
                html += `<td>-</td>`;
            }
        });
        html += '</tr>';
    });
    html += '</tbody></table></div>';
    return html;
}

function renderTapaTable(title, points) {
    // 10 puntos perimetrales
    points.sort((a, b) => {
        const na = parseInt(a.position.replace(/\D/g, '')) || 0;
        const nb = parseInt(b.position.replace(/\D/g, '')) || 0;
        return na - nb;
    });
    let html = `<div class="panel"><h4>${title}</h4><table class="thk-table"><thead><tr>`;
    points.forEach(p => html += `<th>${p.position}</th>`);
    html += '</tr></thead><tbody><tr>';
    points.forEach(p => {
        html += `<td><input class="thk-input" type="number" step="0.01" min="0" data-point-id="${p.id}" data-nominal="${p.nominal_thickness}" data-alarm="${p.alarm_thickness}" data-scrap="${p.scrap_thickness}" placeholder="${p.last_value || ''}"></td>`;
    });
    html += '</tr></tbody></table></div>';
    return html;
}

function onValueChange(e) {
    const inp = e.target;
    const value = parseFloat(inp.value);
    const pointId = inp.getAttribute('data-point-id');
    const alarm = parseFloat(inp.getAttribute('data-alarm'));
    const scrap = parseFloat(inp.getAttribute('data-scrap'));
    inp.classList.remove('normal', 'alert', 'critical');
    if (isNaN(value) || value <= 0) {
        delete _thkValues[pointId];
        updateSummary();
        return;
    }
    _thkValues[pointId] = value;
    if (value <= scrap) {
        inp.classList.add('critical');
    } else if (value <= alarm) {
        inp.classList.add('alert');
    } else {
        inp.classList.add('normal');
    }
    updateSummary();
}

function updateSummary() {
    const total = _thkPoints.length;
    let filled = 0, normal = 0, alert = 0, critical = 0;
    _thkPoints.forEach(p => {
        const v = _thkValues[p.id];
        if (v == null) return;
        filled++;
        if (v <= p.scrap_thickness) critical++;
        else if (v <= p.alarm_thickness) alert++;
        else normal++;
    });
    document.getElementById('sumTotal').textContent = total;
    document.getElementById('sumFilled').textContent = filled;
    document.getElementById('sumNormal').textContent = normal;
    document.getElementById('sumAlert').textContent = alert;
    document.getElementById('sumCritical').textContent = critical;
}

async function saveInspection() {
    if (!_thkActiveEquipment) return;
    const date = document.getElementById('capInspDate').value;
    const inspector = document.getElementById('capInspector').value.trim();
    const observations = document.getElementById('capObservations').value.trim();
    const pdfUrl = (document.getElementById('capPdfUrl').value || '').trim();
    if (!date) { alert('Seleccione la fecha de inspección.'); return; }
    if (!inspector) { alert('Ingrese el nombre del inspector.'); return; }
    const filled = Object.keys(_thkValues).length;
    if (filled === 0) {
        alert('Debe ingresar al menos una medición.');
        return;
    }
    if (filled < _thkPoints.length) {
        if (!confirm(`Solo llenó ${filled} de ${_thkPoints.length} puntos. ¿Guardar de todos modos?`)) return;
    }
    const readings = Object.entries(_thkValues).map(([pid, val]) => ({
        point_id: parseInt(pid),
        value_mm: val,
    }));
    try {
        const isEdit = !!_editingInspectionId;
        const url = isEdit
            ? `/api/thickness/inspections/${_editingInspectionId}/edit`
            : '/api/thickness/inspections';
        const method = isEdit ? 'PUT' : 'POST';
        const res = await fetch(url, {
            method,
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                equipment_id: _thkActiveEquipment.equipment_id,
                inspection_date: date,
                inspector_name: inspector,
                observations: observations,
                pdf_url: pdfUrl || null,
                frequency_days: 60,
                readings: readings,
            })
        });
        if (!res.ok) {
            const err = await res.json();
            alert('Error: ' + (err.error || 'No se pudo guardar'));
            return;
        }
        const data = await res.json();
        const action = isEdit ? 'actualizada' : 'guardada';
        let msg = `✅ Inspección ${action} (${filled} puntos).`;
        if (data.critical_points > 0) {
            msg += `\n\n⚠️ Se detectaron ${data.critical_points} puntos críticos.` + (isEdit ? '' : ' Se generó un aviso automático de alta prioridad.');
        } else if (data.alert_points > 0) {
            msg += `\n\n⚠️ ${data.alert_points} puntos en alerta — vigilar próxima inspección.`;
        }
        _editingInspectionId = null;
        alert(msg);
        backToDashboard();
    } catch (e) {
        console.error('saveInspection error:', e);
        alert('Error al guardar.');
    }
}

async function openHistoryFor(equipmentId) {
    const eq = _thkDashboard.find(e => e.equipment_id === equipmentId);
    if (!eq) return;
    document.getElementById('thkDashboard').classList.add('hidden');
    document.getElementById('thkCapture').classList.add('hidden');
    document.getElementById('thkHistory').classList.remove('hidden');
    document.getElementById('historyTitle').textContent = `Histórico — ${eq.equipment_tag} ${eq.equipment_name}`;
    try {
        const res = await fetch(`/api/thickness/inspections?equipment_id=${equipmentId}`);
        const inspections = await res.json();
        const list = document.getElementById('historyList');
        if (!inspections.length) {
            list.innerHTML = '<div class="empty-msg">Sin inspecciones registradas para este equipo.</div>';
            return;
        }
        list.innerHTML = `
        <table class="thk-table" style="width:100%;">
            <thead>
                <tr>
                    <th>Fecha</th>
                    <th>Inspector</th>
                    <th>Puntos</th>
                    <th>Críticos</th>
                    <th>Alertas</th>
                    <th>Estado</th>
                    <th>Próxima</th>
                    <th>PDF</th>
                    <th>Acciones</th>
                </tr>
            </thead>
            <tbody>
                ${inspections.map(i => `
                    <tr>
                        <td>${i.inspection_date || '-'}</td>
                        <td>${i.inspector_name || '-'}</td>
                        <td>${i.total_points || 0}</td>
                        <td style="color:${i.critical_points > 0 ? '#ff9690' : '#bfd2ec'};">${i.critical_points || 0}</td>
                        <td style="color:${i.alert_points > 0 ? '#ffd966' : '#bfd2ec'};">${i.alert_points || 0}</td>
                        <td><span class="pill ${i.semaphore_status}">${i.semaphore_status}</span></td>
                        <td>${i.next_due_date || '-'}</td>
                        <td>${i.pdf_url
                            ? `<a href="${i.pdf_url}" target="_blank" style="color:#5ac8fa;font-size:1.1rem;" title="Abrir PDF"><i class="fas fa-file-pdf"></i></a>`
                            : `<button class="btn" style="font-size:.7rem;height:24px;padding:0 8px;" onclick="attachPdfToInspection(${i.id})">+</button>`
                        }</td>
                        <td style="display:flex;gap:4px;justify-content:center;">
                            <button onclick="editInspection(${i.equipment_id}, ${i.id})" style="background:rgba(10,132,255,.18);color:#5ac8fa;border:none;border-radius:6px;width:28px;height:28px;cursor:pointer;" title="Editar"><i class="fas fa-edit"></i></button>
                            <button onclick="deleteInspection(${i.id})" style="background:rgba(255,69,58,.16);color:#ff6b61;border:none;border-radius:6px;width:28px;height:28px;cursor:pointer;" title="Eliminar"><i class="fas fa-trash"></i></button>
                        </td>
                    </tr>
                `).join('')}
            </tbody>
        </table>`;
    } catch (e) {
        console.error('openHistoryFor error:', e);
    }
}

async function attachPdfToInspection(inspectionId) {
    const url = prompt('Pega el enlace del PDF en Google Drive:');
    if (!url || !url.trim()) return;
    try {
        const res = await fetch(`/api/thickness/inspections/${inspectionId}/pdf`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ pdf_url: url.trim() })
        });
        if (!res.ok) {
            const err = await res.json();
            alert('Error: ' + (err.error || 'No se pudo guardar'));
            return;
        }
        // Recargar histórico del equipo activo
        const eq = _thkActiveEquipment;
        if (eq) openHistoryFor(eq.equipment_id);
    } catch (e) {
        console.error('attachPdf error:', e);
    }
}

function editInspection(equipmentId, inspectionId) {
    openInspectionFor(equipmentId, inspectionId);
}

async function deleteInspection(inspectionId) {
    if (!confirm('¿Eliminar esta inspección? Se borrarán todas las mediciones asociadas.')) return;
    try {
        const res = await fetch(`/api/thickness/inspections/${inspectionId}`, { method: 'DELETE' });
        if (!res.ok) {
            const err = await res.json();
            alert('Error: ' + (err.error || 'No se pudo eliminar'));
            return;
        }
        alert('✅ Inspección eliminada.');
        const eq = _thkActiveEquipment;
        if (eq) openHistoryFor(eq.equipment_id);
        else backToDashboard();
    } catch (e) {
        console.error('deleteInspection error:', e);
    }
}

window.reloadDashboard = reloadDashboard;
window.openInspectionFor = openInspectionFor;
window.openHistoryFor = openHistoryFor;
window.backToDashboard = backToDashboard;
window.saveInspection = saveInspection;
window.attachPdfToInspection = attachPdfToInspection;
window.editInspection = editInspection;
window.deleteInspection = deleteInspection;
