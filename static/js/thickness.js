// Inspección de Espesores por Ultrasonido
let _thkDashboard = [];
let _thkActiveEquipment = null;
let _thkPoints = [];
let _thkValues = {};  // { point_id: value }
let _editingInspectionId = null; // null = nueva, int = editando

document.addEventListener('DOMContentLoaded', () => {
    reloadDashboard();
});

function downloadUTTemplate(equipmentId, tag) {
    const a = document.createElement('a');
    a.href = `/api/thickness/template/${equipmentId}`;
    a.download = `plantilla_UT_${tag || equipmentId}.xlsx`;
    document.body.appendChild(a);
    a.click();
    a.remove();
}
window.downloadUTTemplate = downloadUTTemplate;

function uploadUTTemplate(equipmentId) {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = '.xlsx';
    input.onchange = async () => {
        const f = input.files && input.files[0];
        if (!f) return;
        const fd = new FormData();
        fd.append('file', f);
        try {
            const res = await fetch('/api/thickness/upload-template', { method: 'POST', body: fd });
            const data = await res.json();
            if (!res.ok) {
                alert('Error: ' + (data.error || res.statusText));
                return;
            }
            const noticeMsg = data.notice_code ? `\nAviso creado: ${data.notice_code}` : '';
            alert(`Plantilla cargada\n${data.equipment_tag} (${data.equipment_date || data.inspection_date})\n` +
                  `Mediciones: ${data.total_readings} | Criticos: ${data.criticals} | Alertas: ${data.alerts}\n` +
                  `Semaforo: ${data.semaphore_status}${noticeMsg}`);
            reloadDashboard();
        } catch (e) {
            alert('Error de carga: ' + e.message);
        }
    };
    input.click();
}
window.uploadUTTemplate = uploadUTTemplate;

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
                <button class="btn" style="flex:1;font-size:.78rem;height:30px;padding:0;background:rgba(255,159,10,.15);color:#FF9F0A;border:1px solid rgba(255,159,10,.3);" onclick="event.stopPropagation();openAnalysisFor(${eq.equipment_id})">
                    <i class="fas fa-chart-line"></i> Análisis
                </button>
            </div>
            <div style="margin-top:6px;display:flex;gap:6px;">
                <button class="btn" style="flex:1;font-size:.75rem;height:28px;padding:0;background:rgba(48,209,88,.12);color:#30D158;border:1px solid rgba(48,209,88,.3);" onclick="event.stopPropagation();downloadUTTemplate(${eq.equipment_id}, '${(eq.equipment_tag || '').replace(/'/g, "\\'")}')">
                    <i class="fas fa-download"></i> Plantilla
                </button>
                <button class="btn" style="flex:1;font-size:.75rem;height:28px;padding:0;background:rgba(90,200,250,.12);color:#5ac8fa;border:1px solid rgba(90,200,250,.3);" onclick="event.stopPropagation();uploadUTTemplate(${eq.equipment_id})">
                    <i class="fas fa-upload"></i> Cargar
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
        html += renderTripodeTable('PALETAS DE TRIPODE', groups['PALETA'], ['A', 'B', 'C'], 'PALETA');
    }
    // REFUERZO DE TRIPODE (5 secciones × 3 posiciones X,Y,Z)
    if (groups['REFUERZO']) {
        html += renderTripodeTable('REFUERZO DE TRIPODE', groups['REFUERZO'], ['X', 'Y', 'Z'], 'REFUERZO');
    }
    // EJES DE TRIPODE (5 secciones × 4 posiciones A,B,C,EJE_CENTRAL)
    if (groups['EJE']) {
        html += renderTripodeTable('EJES DE TRIPODE', groups['EJE'], ['A', 'B', 'C', 'EJE_CENTRAL'], 'EJE');
    }
    // CHAQUETA INTERNA (5 secciones × 4 ángulos)
    if (groups['CHAQUETA']) {
        html += renderChaquetaTable('CHAQUETA INTERNA', groups['CHAQUETA']);
    }
    // TAPAS
    if (groups['TAPA_MOTRIZ']) {
        html += renderTapaTable('TAPA BOMBEADA MOTRIZ (Transmisión)', groups['TAPA_MOTRIZ'], 'TAPA_MOTRIZ');
    }
    if (groups['TAPA_CONDUCIDA']) {
        html += renderTapaTable('TAPA BOMBEADA CONDUCIDA (Descarga)', groups['TAPA_CONDUCIDA'], 'TAPA_CONDUCIDA');
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

const REF_IMAGES = {
    PALETA:         { src: '/static/images/thickness/tripode.png',        alt: 'Vista lateral del trípode — secciones 1 a 5' },
    REFUERZO:       { src: '/static/images/thickness/tripode.png',        alt: 'Vista lateral del trípode — secciones 1 a 5' },
    EJE:            { src: '/static/images/thickness/tripode.png',        alt: 'Vista lateral del trípode — ejes A/B/C y eje central' },
    CHAQUETA:       { src: '/static/images/thickness/chaqueta.png',       alt: 'Chaqueta interna — lados Superior/Derecho/Inferior/Izquierdo' },
    TAPA_MOTRIZ:    { src: '/static/images/thickness/tapa_motriz.png',    alt: 'Tapa motriz (Transmisión) — 10 puntos perimetrales' },
    TAPA_CONDUCIDA: { src: '/static/images/thickness/tapa_conducida.png', alt: 'Tapa conducida (Descarga) — 10 puntos perimetrales' },
};

function refImageHTML(groupKey) {
    const m = REF_IMAGES[groupKey];
    if (!m) return '';
    const alt = (m.alt || '').replace(/'/g, '&#39;').replace(/"/g, '&quot;');
    return `<div class="ref-img-wrap"><img src="${m.src}" alt="${alt}" class="ref-img" title="Click para ampliar" onclick="openRefImage(this.src, this.alt)" onerror="this.parentElement.style.display='none'"></div>`;
}

function openRefImage(src, alt) {
    const existing = document.getElementById('refLightbox');
    if (existing) { existing.remove(); return; }
    const box = document.createElement('div');
    box.id = 'refLightbox';
    box.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.9);display:flex;flex-direction:column;align-items:center;justify-content:center;z-index:9999;cursor:zoom-out;padding:20px;gap:10px;';
    box.innerHTML = `
        <img src="${src}" alt="${(alt||'').replace(/"/g,'&quot;')}" style="max-width:95%;max-height:88%;border-radius:8px;box-shadow:0 20px 60px rgba(0,0,0,.6);background:#fff;" onclick="event.stopPropagation()">
        <div style="color:#bfd2ec;font-size:.85rem;">${alt || ''} — Click fuera para cerrar</div>
    `;
    box.onclick = () => box.remove();
    const escHandler = (e) => { if (e.key === 'Escape') { box.remove(); document.removeEventListener('keydown', escHandler); } };
    document.addEventListener('keydown', escHandler);
    document.body.appendChild(box);
}

function renderTripodeTable(title, points, positions, groupKey) {
    // Filas = posiciones (A,B,C o X,Y,Z), columnas = secciones 1..5
    const sections = [...new Set(points.map(p => p.section))].sort((a, b) => a - b);
    let html = `<div class="panel"><h4>${title}</h4>${refImageHTML(groupKey)}<table class="thk-table"><thead><tr><th></th>`;
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
    let html = `<div class="panel"><h4>${title}</h4>${refImageHTML('CHAQUETA')}<table class="thk-table"><thead><tr><th>LADO DE CHAQUETA</th>`;
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

function renderTapaTable(title, points, groupKey) {
    // 10 puntos perimetrales
    points.sort((a, b) => {
        const na = parseInt(a.position.replace(/\D/g, '')) || 0;
        const nb = parseInt(b.position.replace(/\D/g, '')) || 0;
        return na - nb;
    });
    let html = `<div class="panel"><h4>${title}</h4>${refImageHTML(groupKey)}<table class="thk-table"><thead><tr>`;
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

// ── Análisis Predictivo ──────────────────────────────────────

let _analysisChart = null;

async function openAnalysisFor(equipmentId) {
    const eq = _thkDashboard.find(e => e.equipment_id === equipmentId);
    _thkActiveEquipment = eq;
    try {
        // Cargar puntos para umbrales del gráfico
        const ptsRes = await fetch(`/api/thickness/points/${equipmentId}`);
        _thkPoints = await ptsRes.json();
        const res = await fetch(`/api/thickness/analysis/${equipmentId}`);
        if (!res.ok) { alert('Error al cargar análisis'); return; }
        const data = await res.json();

        document.getElementById('thkDashboard').classList.add('hidden');
        document.getElementById('thkCapture').classList.add('hidden');
        document.getElementById('thkHistory').classList.add('hidden');
        document.getElementById('thkAnalysis').classList.remove('hidden');
        document.getElementById('analysisTitle').textContent =
            `Análisis Predictivo — ${data.equipment_tag} ${data.equipment_name}`;
        document.getElementById('pointChartPanel').style.display = 'none';

        renderAlerts(data.alerts || []);
        renderGroupsSummary(data.groups_summary || []);
        renderAnalysisTable(data.points || []);
    } catch (e) { console.error('openAnalysisFor:', e); }
}

function renderAlerts(alerts) {
    const panel = document.getElementById('analysisAlerts');
    const list = document.getElementById('alertsList');
    if (!alerts.length) { panel.style.display = 'none'; return; }
    panel.style.display = 'block';
    const urgencyColors = { CRITICO: '#FF453A', URGENTE: '#FF9F0A', PLANIFICAR: '#5ac8fa' };
    const urgencyIcons = { CRITICO: 'fa-skull-crossbones', URGENTE: 'fa-exclamation-triangle', PLANIFICAR: 'fa-calendar-alt' };
    list.innerHTML = alerts.map(a => `
        <div style="padding:10px 14px;margin-bottom:8px;background:rgba(0,0,0,.2);border-left:4px solid ${urgencyColors[a.urgency]};border-radius:6px;">
            <div style="display:flex;justify-content:space-between;align-items:center;">
                <span style="color:${urgencyColors[a.urgency]};font-weight:700;">
                    <i class="fas ${urgencyIcons[a.urgency]}"></i> ${a.urgency}
                </span>
                <span style="color:#9ab0cb;font-size:.82rem;">${a.group_name} S${a.section || ''}-${a.position}</span>
            </div>
            <div style="color:#d5e2f5;font-size:.88rem;margin-top:6px;">
                Actual: <strong>${a.last_value} mm</strong> → Descarte: ${a.scrap} mm |
                Desgaste: <strong>${a.wear_mm_month} mm/mes</strong> |
                Vida: <strong style="color:${urgencyColors[a.urgency]};">${a.life_months} meses${a.life_weeks ? ` (${a.life_weeks} sem)` : ''}</strong>
                ${a.estimated_replacement ? ` → ${a.estimated_replacement}` : ''}
            </div>
            <div style="color:${urgencyColors[a.urgency]};font-size:.85rem;margin-top:4px;font-weight:600;">
                → ${a.recommendation}
            </div>
        </div>
    `).join('');
}

function renderGroupsSummary(groups) {
    const container = document.getElementById('groupsSummaryTable');
    if (!groups.length) { container.innerHTML = '<div class="empty">Sin datos suficientes para análisis. Se requieren al menos 2 inspecciones.</div>'; return; }
    const groupLabels = { PALETA: 'Paletas Trípode', REFUERZO: 'Refuerzo Trípode', EJE: 'Ejes Trípode', CHAQUETA: 'Chaqueta Interna', TAPA_MOTRIZ: 'Tapa Motriz', TAPA_CONDUCIDA: 'Tapa Conducida' };
    container.innerHTML = `
        <table class="thk-table" style="width:100%;">
            <thead><tr>
                <th>Componente</th><th>Puntos</th><th>Espesor mínimo (mm)</th>
                <th>Mayor desgaste (mm/mes)</th><th>Menor vida (meses)</th><th>Punto crítico</th><th>Estado</th>
            </tr></thead>
            <tbody>
                ${groups.map(g => {
                    const lifeColor = g.min_life_months <= 1 ? '#FF453A' : g.min_life_months <= 3 ? '#FF9F0A' : g.min_life_months <= 6 ? '#ffd966' : '#30D158';
                    const statusLabel = g.min_life_months <= 1 ? 'FABRICAR YA' : g.min_life_months <= 3 ? 'INICIAR FABRICACIÓN' : g.min_life_months <= 6 ? 'PROGRAMAR' : 'OK';
                    return `<tr>
                        <td style="font-weight:700;color:#d5e2f5;">${groupLabels[g.group_name] || g.group_name}</td>
                        <td>${g.total_points}</td>
                        <td>${g.min_value < 999 ? g.min_value : '-'}</td>
                        <td>${g.max_wear_rate > 0 ? g.max_wear_rate.toFixed(2) : '-'}</td>
                        <td style="color:${lifeColor};font-weight:700;">${g.min_life_months < 999 ? g.min_life_months : '-'}</td>
                        <td style="color:#FF9F0A;">${g.worst_point || '-'}</td>
                        <td><span style="color:${lifeColor};font-weight:700;">${g.min_life_months < 999 ? statusLabel : 'Sin datos'}</span></td>
                    </tr>`;
                }).join('')}
            </tbody>
        </table>`;
}

function renderAnalysisTable(points) {
    const tbody = document.getElementById('analysisTableBody');
    if (!points.length) { tbody.innerHTML = '<tr><td colspan="10" style="text-align:center;color:#666;">Sin datos de medición.</td></tr>'; return; }
    tbody.innerHTML = points.filter(p => p.readings_count > 0).map(p => {
        const wr = p.wear_rate;
        const lifeColor = p.life_months === null ? '#666' : p.life_months <= 1 ? '#FF453A' : p.life_months <= 3 ? '#FF9F0A' : p.life_months <= 6 ? '#ffd966' : '#30D158';
        return `<tr onclick="renderPointChart(${p.point_id}, '${p.group_name} S${p.section||''}-${p.position}')" style="cursor:pointer;">
            <td>${p.group_name}</td>
            <td>${p.section || '-'}</td>
            <td>${p.position}</td>
            <td style="font-weight:700;color:${p.status === 'CRITICO' ? '#FF453A' : p.status === 'ALERTA' ? '#FF9F0A' : '#30D158'};">${p.last_value}</td>
            <td>${wr ? wr.mm_per_month.toFixed(2) : '-'}</td>
            <td>${wr ? wr.mm_per_week.toFixed(3) : '-'}</td>
            <td>${p.remaining_mm}</td>
            <td style="color:${lifeColor};font-weight:700;">${p.life_months !== null ? p.life_months : '-'}</td>
            <td style="color:${lifeColor};">${p.life_weeks !== null ? p.life_weeks : '-'}</td>
            <td style="font-size:.8rem;">${p.estimated_replacement || '-'}</td>
        </tr>`;
    }).join('');
}

async function renderPointChart(pointId, label) {
    const panel = document.getElementById('pointChartPanel');
    panel.style.display = 'block';
    document.getElementById('pointChartTitle').innerHTML = `<i class="fas fa-chart-area"></i> Tendencia: ${label}`;
    try {
        const res = await fetch(`/api/thickness/history/${pointId}`);
        const data = await res.json();
        if (!data.length) return;

        const el = document.getElementById('pointChart');
        if (_analysisChart) _analysisChart.dispose();
        _analysisChart = echarts.init(el, 'dark');

        const dates = data.map(d => d.inspection_date);
        const values = data.map(d => d.value_mm);

        // Buscar el punto para obtener umbrales
        const pt = _thkPoints.find(p => p.id === pointId);
        const alarm = pt ? pt.alarm_thickness : 10;
        const scrap = pt ? pt.scrap_thickness : 8;

        // Proyección futura si hay >= 2 puntos
        let projDates = [];
        let projValues = [];
        if (values.length >= 2) {
            const d0 = new Date(dates[0]);
            const dLast = new Date(dates[dates.length - 1]);
            const vLast = values[values.length - 1];
            const totalDays = (dLast - d0) / 86400000;
            const totalDrop = values[0] - vLast;
            if (totalDays > 0 && totalDrop > 0) {
                const ratePerDay = totalDrop / totalDays;
                const daysToScrap = (vLast - scrap) / ratePerDay;
                const maxProjDays = Math.min(Math.max(daysToScrap, 30), 730);
                for (let d = 30; d <= maxProjDays; d += 30) {
                    const projDate = new Date(dLast);
                    projDate.setDate(projDate.getDate() + d);
                    projDates.push(projDate.toISOString().slice(0, 10));
                    projValues.push(Math.max(0, vLast - ratePerDay * d));
                }
            }
        }
        const allDates = [...dates, ...projDates];

        _analysisChart.setOption({
            backgroundColor: 'transparent',
            tooltip: { trigger: 'axis', formatter: params => params.map(p => `${p.seriesName}: ${p.value} mm`).join('<br/>') },
            legend: { data: ['Medición real', 'Proyección'], textStyle: { color: '#bfd2ec' } },
            grid: { top: 50, right: 20, bottom: 40, left: 60 },
            xAxis: { type: 'category', data: allDates, axisLabel: { color: '#9ab0cb', rotate: 30, fontSize: 10 } },
            yAxis: { type: 'value', name: 'mm', axisLabel: { color: '#9ab0cb' }, splitLine: { lineStyle: { color: 'rgba(255,255,255,.06)' } } },
            series: [
                {
                    name: 'Medición real', type: 'line', data: [...values, ...new Array(projDates.length).fill(null)],
                    lineStyle: { color: '#5ac8fa', width: 3 }, itemStyle: { color: '#5ac8fa' },
                    symbolSize: 8, areaStyle: { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: 'rgba(90,200,250,.3)' }, { offset: 1, color: 'rgba(90,200,250,0)' }] } },
                },
                {
                    name: 'Proyección', type: 'line', data: [...new Array(dates.length - 1).fill(null), values[values.length - 1], ...projValues],
                    lineStyle: { color: '#FF9F0A', width: 2, type: 'dashed' }, itemStyle: { color: '#FF9F0A' }, symbolSize: 4,
                },
                {
                    name: 'Alarma', type: 'line', data: allDates.map(() => alarm),
                    lineStyle: { color: '#ffd966', width: 1, type: 'dotted' }, itemStyle: { opacity: 0 }, symbol: 'none',
                },
                {
                    name: 'Descarte', type: 'line', data: allDates.map(() => scrap),
                    lineStyle: { color: '#FF453A', width: 2, type: 'dotted' }, itemStyle: { opacity: 0 }, symbol: 'none',
                    markArea: { data: [[{ yAxis: 0 }, { yAxis: scrap }]], itemStyle: { color: 'rgba(255,69,58,0.08)' } }
                }
            ]
        });
    } catch (e) { console.error('renderPointChart:', e); }
}

function backToDashboard() {
    document.getElementById('thkDashboard').classList.remove('hidden');
    document.getElementById('thkCapture').classList.add('hidden');
    document.getElementById('thkHistory').classList.add('hidden');
    document.getElementById('thkAnalysis').classList.add('hidden');
    reloadDashboard();
}

window.reloadDashboard = reloadDashboard;
window.openInspectionFor = openInspectionFor;
window.openHistoryFor = openHistoryFor;
window.backToDashboard = backToDashboard;
window.saveInspection = saveInspection;
window.attachPdfToInspection = attachPdfToInspection;
window.editInspection = editInspection;
window.deleteInspection = deleteInspection;
window.openAnalysisFor = openAnalysisFor;
window.renderPointChart = renderPointChart;
window.openRefImage = openRefImage;
