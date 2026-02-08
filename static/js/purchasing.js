
document.addEventListener('DOMContentLoaded', () => {
    loadRequests();
    loadOrders();
    loadProviders(); // If provider API exists
});

function openTab(evt, tabName) {
    const tabContents = document.getElementsByClassName("tab-content");
    for (let i = 0; i < tabContents.length; i++) {
        tabContents[i].style.display = "none";
    }
    const tabLinks = document.getElementsByClassName("tab-link");
    for (let i = 0; i < tabLinks.length; i++) {
        tabLinks[i].className = tabLinks[i].className.replace(" active", "");
    }
    document.getElementById(tabName).style.display = "block";
    evt.currentTarget.className += " active";
}

// --- REQUESTS LOGIC ---
let selectedRequests = new Set();

async function loadRequests() {
    try {
        const res = await fetch('/api/purchase-requests'); // Only pending by default
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

    if (list.length === 0) {
        container.innerHTML = '<p style="text-align:center; color:#888;">No hay solicitudes pendientes.</p>';
        return;
    }

    // Sort by ID desc
    list.sort((a, b) => b.id - a.id);

    list.forEach(req => {
        // Skip if already in order
        if (req.status !== 'PENDIENTE' && req.status !== 'APROBADO') return;

        const card = document.createElement('div');
        card.className = 'purchase-card';

        card.innerHTML = `
            <div style="display:flex; align-items:center; gap: 15px;">
                <input type="checkbox" value="${req.id}" onchange="toggleSelection(${req.id}, this)">
                <div>
                    <div style="color: #03dac6; font-weight: bold;">${req.req_code}</div>
                    <div style="color: #aaa; font-size: 0.9em;">OT: ${req.ot_code || 'N/A'}</div>
                </div>
            </div>
            <div style="flex: 2; margin: 0 20px;">
                <div style="font-weight: 500;">
                    ${req.item_type === 'MATERIAL' ?
                `📦 ${req.spare_part_name}` :
                `🔧 SERVICIO: ${req.description}`}
                </div>
                <div style="color: #bbb; font-size: 0.9em;">
                    Cant: <b style="color:white;">${req.quantity}</b>
                    ${req.item_type === 'MATERIAL' ? 'unidades' : ''}
                </div>
            </div>
            <div>
                <span class="status-pill status-${req.status.toLowerCase()}">${req.status}</span>
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

// --- CREATE PO ---

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
            body: JSON.stringify({
                provider_name: provider,
                request_ids: reqIds
            })
        });

        if (res.ok) {
            alert("Orden de Compra Generada Exitosamente");
            document.getElementById('poModal').close();
            selectedRequests.clear();
            loadRequests();
            loadOrders();
            // Switch tab
            document.querySelector('.tab-link:nth-child(2)').click();
        } else {
            const err = await res.json();
            alert("Error: " + err.error);
        }
    } catch (e) {
        alert("Error de red: " + e);
    }
}

// --- ORDERS LOGIC ---

async function loadOrders() {
    try {
        const res = await fetch('/api/purchase-orders');
        const list = await res.json();
        renderOrders(list);
    } catch (e) { console.error(e); }
}

function renderOrders(list) {
    const tbody = document.querySelector('#ordersTable tbody');
    tbody.innerHTML = '';

    list.forEach(po => {
        const tr = document.createElement('tr');

        let itemsHtml = '';
        if (po.requests) {
            po.requests.forEach(r => {
                const name = r.item_type === 'MATERIAL' ? r.spare_part_name : r.description;
                itemsHtml += `<div style="font-size:0.85em;">• ${name} (x${r.quantity})</div>`;
            });
        }

        tr.innerHTML = `
            <td><b style="color:#03dac6;">${po.po_code}</b></td>
            <td>${po.provider_name}</td>
            <td>${po.issue_date}</td>
            <td><span class="status-pill status-${po.status.toLowerCase()}">${po.status}</span></td>
            <td>${itemsHtml}</td>
            <td>
                ${po.status !== 'CERRADA' ?
                `<button class="btn-primary" style="font-size:0.8em; padding: 4px 8px;" onclick="closePO(${po.id})">
                        <i class="fas fa-check"></i> Recibir
                    </button>` :
                `<span style="color:#4caf50;"><i class="fas fa-check-circle"></i> Completado</span>`
            }
            </td>
        `;
        tbody.appendChild(tr);
    });
}

async function closePO(id) {
    if (!confirm("¿Confirmar recepción total de la Orden de Compra? Esto actualizará el stock (Simulado) y desbloqueará las OTs.")) return;

    try {
        const res = await fetch(`/api/purchase-orders/${id}/close`, { method: 'POST' });
        if (res.ok) {
            loadOrders();
            loadRequests(); // Refresh requests too
        } else {
            alert("Error al cerrar OC");
        }
    } catch (e) { alert(e); }
}

async function loadProviders() {
    // Mock or fetch
    // If we have provider API:
    try {
        const res = await fetch('/api/providers');
        if (res.ok) {
            const list = await res.json();
            const sel = document.getElementById('poProvider');
            sel.innerHTML = '';
            list.forEach(p => {
                const opt = document.createElement('option');
                opt.value = p.name;
                opt.textContent = p.name;
                sel.appendChild(opt);
            });
            // Fallback
            if (list.length === 0) sel.innerHTML = '<option value="Proveedor Genérico">Proveedor Genérico</option>';
        }
    } catch (e) { }
}
