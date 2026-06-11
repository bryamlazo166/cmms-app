// ============================================================
// Requerimientos (Backlog Tecnico) — CMMS
// CRUD + conversion a OT / Requisicion / cierre manual
// ============================================================

const TYPE_LABELS = {
    COMPRA_ESPECIAL: 'Compra especial',
    FABRICACION: 'Fabricación',
    MEJORA: 'Mejora / Upgrade',
    REPUESTO_ESTRATEGICO: 'Repuesto estratégico',
};
const STATUS_LABELS = {
    REGISTRADO: 'Registrado',
    EN_EVALUACION: 'En evaluación',
    APROBADO: 'Aprobado',
    EN_GESTION: 'En gestión',
    CERRADO: 'Cerrado',
    RECHAZADO: 'Rechazado',
};

let _equipmentsCache = [];

document.addEventListener('DOMContentLoaded', () => {
    loadEquipments();
    loadRequirements();
});

function esc(s) {
    if (s === null || s === undefined) return '';
    return String(s).replace(/[&<>"']/g, c => (
        { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
    ));
}

async function loadEquipments() {
    try {
        const res = await fetch('/api/equipments');
        const data = await res.json();
        _equipmentsCache = Array.isArray(data) ? data : [];
        const sel = document.getElementById('reqEquipment');
        if (sel) {
            sel.innerHTML = '<option value="">— Sin equipo —</option>' +
                _equipmentsCache.map(e =>
                    `<option value="${e.id}">${esc(e.tag ? e.tag + ' · ' : '')}${esc(e.name)}</option>`
                ).join('');
        }
    } catch (e) {
        console.warn('No se pudieron cargar equipos', e);
    }
}

async function loadRequirements() {
    const body = document.getElementById('reqBody');
    body.innerHTML = '<tr><td colspan="10" style="text-align:center;padding:20px;">Cargando...</td></tr>';

    const params = new URLSearchParams();
    const st = document.getElementById('fStatus').value;
    const ty = document.getElementById('fType').value;
    const pr = document.getElementById('fPriority').value;
    if (st === '__all__') params.set('all', 'true');
    else if (st) params.set('status', st);
    if (ty) params.set('req_type', ty);
    if (pr) params.set('priority', pr);

    try {
        const res = await fetch('/api/requirements?' + params.toString());
        const items = await res.json();
        if (!Array.isArray(items) || items.length === 0) {
            body.innerHTML = '<tr><td colspan="10" style="text-align:center;padding:24px;color:#9ab0cb;">Sin requerimientos.</td></tr>';
            return;
        }
        body.innerHTML = items.map(rowHtml).join('');
    } catch (e) {
        body.innerHTML = `<tr><td colspan="10" style="text-align:center;padding:20px;color:#ff6b6b;">Error: ${esc(e.message)}</td></tr>`;
    }
}

function rowHtml(r) {
    const equip = r.equipment_name
        ? `${esc(r.equipment_tag ? r.equipment_tag + ' · ' : '')}${esc(r.equipment_name)}`
        : '<span style="color:#667;">—</span>';
    const cost = (r.estimated_cost != null && r.estimated_cost !== '')
        ? Number(r.estimated_cost).toLocaleString('es-PE', { minimumFractionDigits: 2 })
        : '—';
    let converted = '—';
    if (r.converted_to_type === 'OT' && r.ot_code) converted = `<span class="pill" style="background:#7e57c2;color:#fff;">${esc(r.ot_code)}</span>`;
    else if (r.converted_to_type === 'REQ' && r.req_code) converted = `<span class="pill" style="background:#2196f3;color:#fff;">${esc(r.req_code)}</span>`;
    else if (r.converted_to_type === 'MANUAL') converted = '<span style="color:#8bc34a;">Cierre manual</span>';

    const isTerminal = r.status === 'CERRADO' || r.status === 'RECHAZADO';
    const convertBtn = isTerminal ? '' :
        `<button class="b-convert" onclick='openConvert(${r.id})'><i class="fas fa-share"></i> Convertir</button>`;

    return `
    <tr>
        <td><b>${esc(r.code)}</b></td>
        <td>${esc(r.title)}</td>
        <td><span class="pill ty">${esc(TYPE_LABELS[r.req_type] || r.req_type)}</span></td>
        <td>${equip}</td>
        <td class="pr-${esc(r.priority)}">${esc(r.priority)}</td>
        <td>${cost}</td>
        <td>${esc(r.target_date || '—')}</td>
        <td><span class="pill st-${esc(r.status)}">${esc(STATUS_LABELS[r.status] || r.status)}</span></td>
        <td>${converted}</td>
        <td class="actions-cell">
            ${convertBtn}
            <button class="b-edit" onclick='openEdit(${r.id})'><i class="fas fa-pen"></i></button>
            <button class="b-del" onclick='deleteRequirement(${r.id}, ${JSON.stringify(r.code)})'><i class="fas fa-trash"></i></button>
        </td>
    </tr>`;
}

// ---------- Crear / Editar ----------

function _setField(id, val) {
    const el = document.getElementById(id);
    if (el) el.value = (val === null || val === undefined) ? '' : val;
}

function openNew() {
    document.getElementById('reqModalTitle').textContent = 'Nuevo Requerimiento';
    document.getElementById('reqId').value = '';
    ['reqTitle', 'reqDescription', 'reqQuantity', 'reqUnit', 'reqCost', 'reqTargetDate', 'reqRequestedBy', 'reqNotes']
        .forEach(id => _setField(id, ''));
    _setField('reqType', 'COMPRA_ESPECIAL');
    _setField('reqPriority', 'MEDIA');
    _setField('reqStatus', 'REGISTRADO');
    _setField('reqEquipment', '');
    document.getElementById('reqModal').showModal();
}

async function openEdit(id) {
    try {
        const res = await fetch('/api/requirements/' + id);
        const r = await res.json();
        if (r.error) { alert(r.error); return; }
        document.getElementById('reqModalTitle').textContent = 'Editar ' + r.code;
        _setField('reqId', r.id);
        _setField('reqTitle', r.title);
        _setField('reqType', r.req_type);
        _setField('reqPriority', r.priority);
        _setField('reqStatus', r.status);
        _setField('reqDescription', r.description);
        _setField('reqEquipment', r.equipment_id || '');
        _setField('reqQuantity', r.quantity);
        _setField('reqUnit', r.unit);
        _setField('reqCost', r.estimated_cost);
        _setField('reqTargetDate', r.target_date);
        _setField('reqRequestedBy', r.requested_by);
        _setField('reqNotes', r.notes);
        document.getElementById('reqModal').showModal();
    } catch (e) {
        alert('Error: ' + e.message);
    }
}

function _numOrNull(id) {
    const v = document.getElementById(id).value;
    return v === '' ? null : Number(v);
}

async function saveRequirement() {
    const title = document.getElementById('reqTitle').value.trim();
    if (!title) { alert('El título es obligatorio.'); return; }

    const payload = {
        title,
        req_type: document.getElementById('reqType').value,
        priority: document.getElementById('reqPriority').value,
        status: document.getElementById('reqStatus').value,
        description: document.getElementById('reqDescription').value || null,
        equipment_id: document.getElementById('reqEquipment').value || null,
        quantity: _numOrNull('reqQuantity'),
        unit: document.getElementById('reqUnit').value || null,
        estimated_cost: _numOrNull('reqCost'),
        target_date: document.getElementById('reqTargetDate').value || null,
        requested_by: document.getElementById('reqRequestedBy').value || null,
        notes: document.getElementById('reqNotes').value || null,
    };

    const id = document.getElementById('reqId').value;
    const url = id ? '/api/requirements/' + id : '/api/requirements';
    const method = id ? 'PUT' : 'POST';

    try {
        const res = await fetch(url, {
            method,
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        const data = await res.json();
        if (!res.ok) { alert(data.error || 'Error al guardar'); return; }
        document.getElementById('reqModal').close();
        loadRequirements();
    } catch (e) {
        alert('Error: ' + e.message);
    }
}

async function deleteRequirement(id, code) {
    if (!confirm(`¿Eliminar el requerimiento ${code}? Esta acción no se puede deshacer.`)) return;
    try {
        const res = await fetch('/api/requirements/' + id, { method: 'DELETE' });
        const data = await res.json();
        if (!res.ok) { alert(data.error || 'Error al eliminar'); return; }
        loadRequirements();
    } catch (e) {
        alert('Error: ' + e.message);
    }
}

// ---------- Conversion ----------

function openConvert(id) {
    document.getElementById('convReqId').value = id;
    // Buscar el codigo en la tabla para mostrarlo
    const row = document.querySelector(`button[onclick="openConvert(${id})"]`);
    document.getElementById('convReqCode').textContent = '';
    document.getElementById('convTarget').value = 'OT';
    document.getElementById('convItemType').value = 'SERVICIO';
    document.getElementById('convDescription').value = '';
    onConvTargetChange();
    // Cargar codigo via fetch para titulo fiable
    fetch('/api/requirements/' + id).then(r => r.json()).then(r => {
        if (r && r.code) document.getElementById('convReqCode').textContent = r.code;
    }).catch(() => {});
    document.getElementById('convertModal').showModal();
}

function onConvTargetChange() {
    const t = document.getElementById('convTarget').value;
    document.getElementById('convReqExtra').style.display = (t === 'REQ') ? 'block' : 'none';
}

async function doConvert() {
    const id = document.getElementById('convReqId').value;
    const target = document.getElementById('convTarget').value;
    const payload = {
        target,
        description: document.getElementById('convDescription').value || null,
    };
    if (target === 'REQ') {
        payload.item_type = document.getElementById('convItemType').value;
    }
    try {
        const res = await fetch(`/api/requirements/${id}/convert`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        const data = await res.json();
        if (!res.ok) { alert(data.error || 'Error al convertir'); return; }
        document.getElementById('convertModal').close();
        alert(data.msg || 'Conversión realizada.');
        loadRequirements();
    } catch (e) {
        alert('Error: ' + e.message);
    }
}
