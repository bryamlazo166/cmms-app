import os

path = r"d:\PROGRAMACION\CMMS_Industrial\static\js\work_orders.js"

try:
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()

    # Find the split point. searching for unique string in the middle
    split_marker = "function renderMaterialsTable() {"
    parts = content.split(split_marker)

    if len(parts) < 2:
        print("Error: Marker not found")
        exit(1)

    # Keep the first part (header + logic before materials table)
    # And discard ALL subsequent parts (dupes), replacing with clean logic.
    clean_head = parts[0]

    clean_tail = """function renderMaterialsTable() {
    const tbody = document.getElementById('materialsTableBody');
    const empty = document.getElementById('materialsEmpty');

    if (!tbody) return;

    tbody.innerHTML = '';

    if (currentOTMaterials.length === 0) {
        if (empty) empty.style.display = 'block';
        return;
    }

    if (empty) empty.style.display = 'none';

    currentOTMaterials.forEach((m) => {
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td><span class="badge" style="background: ${m.item_type === 'tool' ? '#ff9800' : '#4caf50'};">${m.item_type === 'tool' ? 'Herramienta' : 'Repuesto'}</span></td>
            <td>${m.code || '-'}</td>
            <td>${m.name || m.item_name || 'N/A'}</td>
            <td>${m.quantity || 1}</td>
            <td>
                <button type="button" class="btn-danger" onclick="removeMaterial(${m.id})" style="padding: 2px 8px;">
                    <i class="fas fa-trash"></i>
                </button>
            </td>
        `;
        tbody.appendChild(tr);
    });
}

window.removeMaterial = async function(id) {
    if (!confirm('¿Eliminar este material de la OT?')) return;
    const otId = document.getElementById('otId').value;
    try {
        await fetch(`/api/work_orders/${otId}/materials/${id}`, { method: 'DELETE' });
        loadOTMaterials(otId);
    } catch (e) {
        console.error(e);
    }
};

// ============= OT PERSONNEL MANAGEMENT =============
async function loadOTPersonnel(otId) {
    try {
        const res = await fetch(`/api/work_orders/${otId}/personnel`);
        if (res.ok) {
            currentOTPersonnel = await res.json();
        } else {
            currentOTPersonnel = [];
        }
        renderPersonnelTable();
    } catch (e) {
        console.error('Error loading personnel:', e);
        currentOTPersonnel = [];
        renderPersonnelTable();
    }
}

function renderPersonnelTable() {
    const tbody = document.getElementById('personnelTableBody');
    const empty = document.getElementById('personnelEmpty');
    if (!tbody) return;
    tbody.innerHTML = '';
    
    if (currentOTPersonnel.length === 0) {
        if (empty) empty.style.display = 'block';
        return;
    }
    if (empty) empty.style.display = 'none';

    currentOTPersonnel.forEach((p, idx) => {
        const tr = document.createElement('tr');
        const displayHours = p.hours_assigned !== undefined ? p.hours_assigned : (p.hours || 0);
        tr.innerHTML = `
            <td>${p.technician_name || p.name || 'N/A'}</td>
            <td>${p.specialty || '-'}</td>
            <td>${displayHours} hrs</td>
            <td>
                <button type="button" class="btn-danger" onclick="removePersonnel(${idx})" style="padding: 2px 8px;">
                    <i class="fas fa-trash"></i>
                </button>
            </td>
        `;
        tbody.appendChild(tr);
    });
}

window.addPersonnelRow = function () {
    const select = document.getElementById('personnelTechSelect');
    if (!select) return alert('Modal de personal no encontrado');
    select.innerHTML = '<option value="">- Seleccione Técnico -</option>';
    
    if(typeof allTechnicians !== 'undefined') {
        allTechnicians.forEach(tech => {
            const opt = document.createElement('option');
            opt.value = tech.id;
            opt.textContent = tech.name + (tech.specialty ? ` (${tech.specialty})` : '');
            opt.dataset.specialty = tech.specialty || 'GENERAL';
            select.appendChild(opt);
        });
    }

    select.onchange = function () {
        const selectedOpt = select.options[select.selectedIndex];
        if (selectedOpt && selectedOpt.dataset.specialty) {
            document.getElementById('personnelSpecialty').value = selectedOpt.dataset.specialty;
        }
    };
    document.getElementById('personnelHours').value = 8;
    document.getElementById('addPersonnelModal').showModal();
}

window.confirmAddPersonnel = function () {
    const techSelect = document.getElementById('personnelTechSelect');
    const techId = techSelect.value;
    const techName = techSelect.options[techSelect.selectedIndex]?.text || '';
    if (!techId) return alert('Seleccione un técnico');

    const specialty = document.getElementById('personnelSpecialty').value;
    const hours = parseFloat(document.getElementById('personnelHours').value) || 8;

    if (currentOTPersonnel.find(p => p.technician_id == techId)) {
        return alert('Este técnico ya está asignado a la OT');
    }

    currentOTPersonnel.push({
        technician_id: parseInt(techId),
        technician_name: techName,
        specialty: specialty,
        hours: hours
    });

    renderPersonnelTable();
    document.getElementById('addPersonnelModal').close();

    const otId = document.getElementById('otId').value;
    if (otId) saveOTPersonnel(otId);
}

window.removePersonnel = function (idx) {
    if (!confirm('¿Eliminar este personal de la OT?')) return;
    currentOTPersonnel.splice(idx, 1);
    renderPersonnelTable();
    const otId = document.getElementById('otId').value;
    if (otId) saveOTPersonnel(otId);
}

async function saveOTPersonnel(otId) {
    try {
        await fetch(`/api/work_orders/${otId}/personnel`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ personnel: currentOTPersonnel })
        });
    } catch (e) { console.error('Error saving personnel:', e); }
}

// ============= PURCHASING MODULE INTEGRATION =============
window.openPurchaseModal = function() {
    const otId = document.getElementById('otId').value;
    if(!otId) return alert("Error: ID OT no encontrado");
    
    document.getElementById('reqOtId').value = otId;
    document.getElementById('purchaseModal').showModal();
    loadSparesForReq();
}

window.toggleReqFields = function() {
    const type = document.getElementById('reqType').value;
    document.getElementById('fieldMaterial').style.display = type === 'MATERIAL' ? 'block' : 'none';
    document.getElementById('fieldService').style.display = type === 'SERVICIO' ? 'block' : 'none';
    
    document.getElementById('reqSpareId').required = (type === 'MATERIAL');
    document.getElementById('reqDesc').required = (type === 'SERVICIO');
}

async function loadSparesForReq() {
    const sel = document.getElementById('reqSpareId');
    if(sel.options.length > 1) return;
    
    try {
        const res = await fetch('/api/list-spare-parts');
        if(res.ok) {
            const list = await res.json();
            sel.innerHTML = '<option value="">-- Seleccionar Repuesto --</option>';
            list.forEach(item => {
                const opt = document.createElement('option');
                opt.value = item.id;
                opt.textContent = `${item.name} [${item.code || 'S/C'}]`;
                sel.appendChild(opt);
            });
        }
    } catch(e) { console.error(e); }
}

const pForm = document.getElementById('purchaseForm');
if(pForm) {
    pForm.onsubmit = async (e) => {
        e.preventDefault();
        
        const payload = {
            work_order_id: document.getElementById('reqOtId').value,
            item_type: document.getElementById('reqType').value,
            quantity: parseFloat(document.getElementById('reqQty').value)
        };
        
        if(payload.item_type === 'MATERIAL') {
            payload.spare_part_id = document.getElementById('reqSpareId').value;
        } else {
            payload.description = document.getElementById('reqDesc').value;
        }
        
        const btn = e.submitter;
        const originalText = btn.textContent;
        btn.textContent = "Enviando...";
        btn.disabled = true;
        
        try {
            const res = await fetch('/api/purchase-requests', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(payload)
            });
            
            if(res.ok) {
                alert("Solicitud Generada.");
                document.getElementById('purchaseModal').close();
            } else {
                const err = await res.json();
                alert("Error: " + err.error);
            }
        } catch(e) { alert("Error de red: " + e); }
        finally {
            btn.textContent = originalText;
            btn.disabled = false;
        }
    };
}
"""

    final_content = clean_head + clean_tail

    with open(path, 'w', encoding='utf-8') as f:
        f.write(final_content)

    print("Fixed work_orders.js successfully!")

except Exception as e:
    print(f"Error: {e}")
