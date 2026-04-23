document.addEventListener('DOMContentLoaded', () => {
    loadRequests();
    loadOrders();
    loadProviders();
});

function openTab(evt, tabName) {
    const tabContents = document.getElementsByClassName("tab-content");
    for (let i = 0; i < tabContents.length; i++) tabContents[i].style.display = "none";
    const tabLinks = document.getElementsByClassName("tab-link");
    for (let i = 0; i < tabLinks.length; i++) tabLinks[i].className = tabLinks[i].className.replace(" active", "");
    document.getElementById(tabName).style.display = "block";
    evt.currentTarget.className += " active";
}

let selectedRequests = new Set();
let allPurchaseOrders = [];
let activeReceivePO = null;
let selectedReceiveReqs = new Set();

function requestDisplayName(req) {
    if (req.item_type === 'MATERIAL') {
        return req.warehouse_item_name || req.spare_part_name || req.description || 'Material sin nombre';
    }
    return req.description || 'Servicio sin descripcion';
}

async function loadRequests() {
    try {
        const res = await fetch('/api/purchase-requests');
        const list = await res.json();
        renderRequests(list);
    } catch (e) {
        console.error(e);
        document.getElementById('requestsList').innerHTML = '<p style="color:red">Error cargando solicitudes</p>';
    }
}

function renderRequests(list) {
    const container = document.getElementById('requestsList');
    container.innerHTML = '';

    if (!list || list.length === 0) {
        container.innerHTML = '<p style="text-align:center; color:#888;">No hay solicitudes pendientes.</p>';
        return;
    }

    list.sort((a, b) => b.id - a.id);

    list.forEach(req => {
        if (req.status !== 'PENDIENTE' && req.status !== 'APROBADO') return;

        const card = document.createElement('div');
        card.className = 'purchase-card';
        const itemName = requestDisplayName(req);

        const otCode = req.ot_code || '';
        const otLink = otCode
            ? `<a href="javascript:void(0)" onclick="viewOTFromPurchase('${otCode}')" style="color:#5cd870;text-decoration:underline;cursor:pointer" title="Ver detalles de la OT">${otCode}</a>`
            : 'N/A';
        card.innerHTML = `
            <div style="display:flex; align-items:center; gap: 15px;">
                <input type="checkbox" value="${req.id}" onchange="toggleSelection(${req.id}, this)">
                <div>
                    <div style="color: #0A84FF; font-weight: bold;">${req.req_code}</div>
                    <div style="color: #aaa; font-size: 0.9em;">OT: ${otLink}</div>
                </div>
            </div>
            <div style="flex: 2; margin: 0 20px;">
                <div style="font-weight: 500;">${req.item_type === 'MATERIAL' ? '??' : '??'} ${itemName}</div>
                <div style="color: #bbb; font-size: 0.9em;">Cant: <b style="color:white;">${req.quantity}</b></div>
            </div>
            <div>
                <span class="status-pill status-${(req.status || '').toLowerCase()}">${req.status}</span>
                <div style="font-size: 0.8em; color: #666; margin-top: 5px;">${new Date(req.created_at).toLocaleDateString()}</div>
            </div>
        `;
        container.appendChild(card);
    });
}

function toggleSelection(id, checkbox) {
    if (checkbox.checked) selectedRequests.add(id);
    else selectedRequests.delete(id);
}

function createPurchaseOrder() {
    if (selectedRequests.size === 0) return alert("Selecciona al menos una solicitud.");

    document.getElementById('selectedCount').textContent = selectedRequests.size;
    document.getElementById('poModal').showModal();
}

document.getElementById('poForm').onsubmit = async (e) => {
    e.preventDefault();
    const provider = document.getElementById('poProvider').value;
    const reqIds = Array.from(selectedRequests);

    if (!provider) return alert("Selecciona Proveedor");

    try {
        const res = await fetch('/api/purchase-orders', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ provider_name: provider, request_ids: reqIds })
        });

        if (res.ok) {
            alert("Orden de Compra generada exitosamente");
            document.getElementById('poModal').close();
            selectedRequests.clear();
            loadRequests();
            loadOrders();
            document.querySelector('.tab-link:nth-child(2)').click();
        } else {
            const err = await res.json();
            alert("Error: " + err.error);
        }
    } catch (e2) {
        alert("Error de red: " + e2);
    }
};

async function loadOrders() {
    try {
        const res = await fetch('/api/purchase-orders');
        const list = await res.json();
        allPurchaseOrders = Array.isArray(list) ? list : [];
        renderOrders(allPurchaseOrders);
    } catch (e) {
        console.error(e);
    }
}

function renderOrders(list) {
    const tbody = document.querySelector('#ordersTable tbody');
    tbody.innerHTML = '';

    (list || []).forEach(po => {
        const tr = document.createElement('tr');

        let itemsHtml = '';
        (po.requests || []).forEach(r => {
            const name = requestDisplayName(r);
            itemsHtml += `<div style="font-size:0.85em;">� ${name} (x${r.quantity}) - <span style="color:#9ad0ff">${r.status || '-'}</span></div>`;
        });

        // Chips de OTs asociadas (clickeables → modal de detalle)
        const otChips = (po.work_orders || []).map(w => {
            const title = (w.description || '').replace(/"/g,'&quot;').replace(/'/g,"&#39;");
            return `<button onclick="viewOTFromPurchase('${w.code}')"
                style="background:rgba(10,132,255,.15);color:#5ac8fa;border:1px solid rgba(10,132,255,.4);
                       border-radius:10px;padding:2px 8px;font-size:.75rem;cursor:pointer;margin:2px;
                       font-weight:600;" title="${title} — click para ver detalle">
                <i class="fas fa-tools" style="font-size:.68rem;"></i> ${w.code}
            </button>`;
        }).join('') || '<span style="color:rgba(255,255,255,.25);font-size:.8em;">-</span>';

        tr.innerHTML = `
            <td><b style="color:#0A84FF;">${po.po_code}</b></td>
            <td>${po.provider_name}</td>
            <td>${po.issue_date || '-'}</td>
            <td><span class="status-pill status-${(po.status || '').toLowerCase()}">${po.status}</span></td>
            <td>${otChips}</td>
            <td>${itemsHtml || '-'}</td>
            <td>
                ${po.status !== 'CERRADA'
                    ? `<button class="btn-primary" style="font-size:0.8em; padding: 4px 8px;" onclick="openReceiveModal(${po.id})"><i class="fas fa-box-open"></i> Recibir</button>`
                    : `<span style="color:#4caf50;"><i class="fas fa-check-circle"></i> Completado</span>`}
            </td>
        `;
        tbody.appendChild(tr);
    });
}

window.openReceiveModal = function (poId) {
    activeReceivePO = allPurchaseOrders.find(x => x.id === poId);
    if (!activeReceivePO) return alert('No se encontro la OC');

    selectedReceiveReqs = new Set();
    document.getElementById('receivePoTitle').textContent = `Recepcion de ${activeReceivePO.po_code}`;
    renderReceiveRows();
    document.getElementById('receiveModal').showModal();
};

function renderReceiveRows() {
    const tbody = document.getElementById('receiveItemsBody');
    const pending = (activeReceivePO.requests || []).filter(r => !['RECIBIDO', 'CANCELADO', 'ANULADO'].includes((r.status || '').toUpperCase()));

    if (pending.length === 0) {
        tbody.innerHTML = '<tr><td colspan="6" style="text-align:center; color:#888;">No hay items pendientes por recibir</td></tr>';
        return;
    }

    tbody.innerHTML = pending.map(r => {
        const otLink = r.ot_code
            ? `<a href="javascript:void(0)" onclick="viewOTFromPurchase('${r.ot_code}')" style="color:#5cd870;text-decoration:underline;cursor:pointer">${r.ot_code}</a>`
            : '-';
        return `
        <tr>
            <td><input type="checkbox" onchange="toggleReceiveReq(${r.id}, this)"></td>
            <td>${r.req_code}</td>
            <td>${requestDisplayName(r)}</td>
            <td>${r.quantity}</td>
            <td>${r.status || '-'}</td>
            <td>${otLink}</td>
        </tr>`;
    }).join('');
}

window.toggleReceiveReq = function (id, cb) {
    if (cb.checked) selectedReceiveReqs.add(id);
    else selectedReceiveReqs.delete(id);
};

window.selectAllReceive = function () {
    const checkboxes = document.querySelectorAll('#receiveItemsBody input[type="checkbox"]');
    selectedReceiveReqs.clear();
    checkboxes.forEach(ch => {
        ch.checked = true;
        const tr = ch.closest('tr');
        const reqCode = tr && tr.children[1] ? tr.children[1].textContent : null;
        const req = (activeReceivePO.requests || []).find(x => x.req_code === reqCode);
        if (req) selectedReceiveReqs.add(req.id);
    });
};

window.confirmReceiveSelection = async function () {
    if (!activeReceivePO) return;
    if (selectedReceiveReqs.size === 0) {
        return alert('Seleccione al menos un item a recibir.');
    }

    try {
        const res = await fetch(`/api/purchase-orders/${activeReceivePO.id}/receive`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ request_ids: Array.from(selectedReceiveReqs) })
        });
        if (!res.ok) {
            const err = await res.json();
            return alert('Error al recibir: ' + (err.error || 'desconocido'));
        }

        alert('Recepcion registrada. Se actualizo stock y estado de la OC.');
        document.getElementById('receiveModal').close();
        loadOrders();
        loadRequests();
    } catch (e) {
        alert('Error de red: ' + e);
    }
};

async function loadProviders() {
    try {
        const res = await fetch('/api/providers');
        if (!res.ok) return;
        const list = await res.json();
        const sel = document.getElementById('poProvider');
        sel.innerHTML = '';
        list.forEach(p => {
            const opt = document.createElement('option');
            opt.value = p.name;
            opt.textContent = p.name;
            sel.appendChild(opt);
        });
        if (list.length === 0) sel.innerHTML = '<option value="Proveedor Generico">Proveedor Generico</option>';
    } catch (_) {}
}

// ── Ver detalles de OT desde un RQ (para logistica) ──────────────────────
async function viewOTFromPurchase(otCode) {
    if (!otCode) return;
    const modal = document.getElementById('otDetailModal');
    const body = document.getElementById('otDetailBody');
    if (!modal || !body) return;
    body.innerHTML = '<p style="color:#888;text-align:center;padding:20px;">Cargando...</p>';
    modal.showModal();
    try {
        const res = await fetch(`/api/work-orders/by-code/${encodeURIComponent(otCode)}`);
        if (!res.ok) {
            body.innerHTML = `<p style="color:#FF453A">Error: no se pudo cargar ${otCode}</p>`;
            return;
        }
        const ot = await res.json();
        const equip = ot.equipment_name ? `[${ot.equipment_tag || '-'}] ${ot.equipment_name}` : '-';
        const fmtDate = (d) => d || '-';
        const noticeBlock = ot.notice_code
            ? `<div style="margin-top:14px;padding:10px;background:#1c2330;border-left:3px solid #FF9F0A;border-radius:6px">
                 <div style="color:#FF9F0A;font-weight:600;margin-bottom:6px">Aviso vinculado: ${ot.notice_code}</div>
                 <div style="color:#ddd;font-size:.9em;white-space:pre-wrap">${ot.notice_description || '-'}</div>
                 ${ot.notice_failure_mode ? `<div style="color:#aaa;font-size:.85em;margin-top:6px">Modo falla: <b>${ot.notice_failure_mode}</b>${ot.notice_blockage_object ? ' | Bloqueo: <b>' + ot.notice_blockage_object + '</b>' : ''}</div>` : ''}
               </div>`
            : '';
        body.innerHTML = `
            <div style="display:grid;grid-template-columns:140px 1fr;gap:8px 14px;color:#ddd;font-size:.92em">
                <div style="color:#888">Codigo:</div>            <div style="color:#0A84FF;font-weight:600">${ot.code || '-'}</div>
                <div style="color:#888">Estado:</div>            <div>${ot.status || '-'}</div>
                <div style="color:#888">Tipo:</div>               <div>${ot.maintenance_type || '-'}</div>
                <div style="color:#888">Area:</div>               <div>${ot.area_name || '-'}</div>
                <div style="color:#888">Linea:</div>              <div>${ot.line_name || '-'}</div>
                <div style="color:#888">Equipo:</div>             <div>${equip}</div>
                <div style="color:#888">Sistema:</div>            <div>${ot.system_name || '-'}</div>
                <div style="color:#888">Componente:</div>         <div>${ot.component_name || '-'}</div>
                <div style="color:#888">Tecnico:</div>            <div>${ot.technician_name || '-'}</div>
                <div style="color:#888">Fecha programada:</div>   <div>${fmtDate(ot.scheduled_date)}</div>
                <div style="color:#888">Inicio real:</div>        <div>${fmtDate(ot.real_start_date)}</div>
                <div style="color:#888">Fin real:</div>           <div>${fmtDate(ot.real_end_date)}</div>
            </div>
            <div style="margin-top:14px">
                <div style="color:#888;margin-bottom:4px;font-size:.88em">Descripcion del trabajo:</div>
                <div style="color:#ddd;white-space:pre-wrap;background:#1a1a1a;padding:10px;border-radius:6px;font-size:.92em">${ot.description || '-'}</div>
            </div>
            ${noticeBlock}
        `;
    } catch (e) {
        body.innerHTML = `<p style="color:#FF453A">Error: ${e.message}</p>`;
    }
}

window.viewOTFromPurchase = viewOTFromPurchase;
