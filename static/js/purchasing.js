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

        card.innerHTML = `
            <div style="display:flex; align-items:center; gap: 15px;">
                <input type="checkbox" value="${req.id}" onchange="toggleSelection(${req.id}, this)">
                <div>
                    <div style="color: #03dac6; font-weight: bold;">${req.req_code}</div>
                    <div style="color: #aaa; font-size: 0.9em;">OT: ${req.ot_code || 'N/A'}</div>
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
            itemsHtml += `<div style="font-size:0.85em;">• ${name} (x${r.quantity}) - <span style="color:#9ad0ff">${r.status || '-'}</span></div>`;
        });

        tr.innerHTML = `
            <td><b style="color:#03dac6;">${po.po_code}</b></td>
            <td>${po.provider_name}</td>
            <td>${po.issue_date || '-'}</td>
            <td><span class="status-pill status-${(po.status || '').toLowerCase()}">${po.status}</span></td>
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

    tbody.innerHTML = pending.map(r => `
        <tr>
            <td><input type="checkbox" onchange="toggleReceiveReq(${r.id}, this)"></td>
            <td>${r.req_code}</td>
            <td>${requestDisplayName(r)}</td>
            <td>${r.quantity}</td>
            <td>${r.status || '-'}</td>
            <td>${r.ot_code || '-'}</td>
        </tr>
    `).join('');
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
