// Initial Listeners moved to bottom


// DATA CACHE
// DATA CACHE
let allAreas = [], allLines = [], allEquips = [], allSys = [], allComps = [], allProviders = [];

async function loadDropdowns() {
    try {
        const [areas, lines, equips, systems, comps, providers] = await Promise.all([
            fetch('/api/areas').then(r => r.json()),
            fetch('/api/lines').then(r => r.json()),
            fetch('/api/equipments').then(r => r.json()),
            fetch('/api/systems').then(r => r.json()),
            fetch('/api/components').then(r => r.json()),
            fetch('/api/providers').then(r => r.json())
        ]);

        // Sort alphabetically
        const sortFn = (a, b) => a.name.localeCompare(b.name);
        allAreas = areas.sort(sortFn);
        allLines = lines.sort(sortFn);
        allEquips = equips.sort(sortFn);
        allSys = systems.sort(sortFn);
        allComps = comps.sort(sortFn);
        allProviders = providers.sort(sortFn);

        // Populate Provider Select
        const pSel = document.getElementById('provider');
        if (pSel) {
            pSel.innerHTML = '<option value="">- Seleccione -</option>' +
                allProviders.map(p => `<option value="${p.id}">${p.name}</option>`).join('');
        }

        console.log(`Loaded: Areas=${allAreas.length}, Lines=${allLines.length}, Equips=${allEquips.length}, Sys=${allSys.length}, Comps=${allComps.length}`);
    } catch (e) {
        console.error("Error loading data", e);
    }
}

// ... Tree Logic remains same ...

// CRUD Logic
async function loadNotices() {
    try {
        const res = await fetch('/api/notices');
        const notices = await res.json();
        const tbody = document.querySelector('#noticesTable tbody');
        tbody.innerHTML = '';

        notices.forEach(n => {
            // Helper to find provider name
            const provName = allProviders.find(p => p.id === n.provider_id)?.name || '-';

            const tr = document.createElement('tr');

            // Visual check for Anulado
            if (n.status === 'Anulado') {
                tr.style.opacity = "0.6";
                tr.style.background = "#2a2a2a"; // Slightly darker
            }

            // Show convert to OT button only if status is not Cerrado/Anulado and no OT yet
            const canConvert = n.status !== 'Cerrado' && n.status !== 'Anulado' && !n.ot_number;
            const convertBtn = canConvert
                ? `<button onclick="convertToOT(${n.id})" style="padding:2px 5px; background: transparent; border: none; cursor: pointer;" title="Convertir a OT">🔧</button>`
                : '';

            // Anulled/Locked logic
            const isLocked = n.status === 'Cerrado' || n.status === 'Anulado';
            const actionBtns = isLocked
                ? `<button style="padding:2px 5px; opacity:0.3; cursor:default;">🚫</button>` // Placeholder for alignment
                : `<button onclick="annulNotice(${n.id})" style="padding:2px 5px; background: transparent; border: none; cursor: pointer; color: #cf6679;" title="Anular Aviso">🚫</button>`;

            const editBtn = `<button onclick="editNotice(${n.id})" style="padding:2px 5px; background: transparent; border: none; cursor: pointer;" title="Editar">✏️</button>`;

            // Status Badge
            let statusColor = '#ff9800'; // Default Pendiente
            if (n.status === 'En Tratamiento') statusColor = '#2196f3';
            if (n.status === 'En Progreso') statusColor = '#00bcd4';
            if (n.status === 'Cerrado') statusColor = '#4caf50';
            if (n.status === 'Anulado') statusColor = '#757575';

            const statusBadge = `<span style="background-color: ${statusColor}; color: white; padding: 2px 8px; border-radius: 4px; font-size: 0.85em;">${n.status || 'Pendiente'}</span>`;

            // Match all columns from HTML header
            tr.innerHTML = `
                <td>${n.code || n.id}</td>
                <td>
                    <span style="background-color: ${n.failure_count > 0 ? '#cf6679' : '#03dac6'}; color: ${n.failure_count > 0 ? 'white' : 'black'}; padding: 2px 6px; border-radius: 12px; font-weight: bold; font-size: 0.9em;">
                        ${n.failure_count || 0}
                    </span>
                </td>
                <td>${n.reporter_type || '-'}</td>
                <td>${provName}</td>
                <td>${n.specialty || '-'}</td>
                <td>${n.shift || '-'}</td>
                <td>${getName(allAreas, n.area_id)}</td>
                <td>${getName(allLines, n.line_id)}</td>
                <td>${getName(allEquips, n.equipment_id)}</td>
                <td>${getName(allSys, n.system_id)}</td>
                <td>${getName(allComps, n.component_id)}</td>
                <td>${n.description || '-'} <br> <small style="color:#cf6679;">${n.cancellation_reason ? '(Anulado: ' + n.cancellation_reason + ')' : ''}</small></td>
                <td>${n.criticality || '-'}</td>
                <td>${n.priority || '-'}</td>
                <td>${n.request_date || '-'}</td>
                <td>${n.treatment_date || '-'}</td>
                <td>${n.planning_date || '-'}</td>
                <td>${n.failure_mode || '-'}</td>
                <td>${n.maintenance_type || '-'}</td>
                <td>-</td>
                <td>${n.ot_number || '-'}</td>
                <td>-</td>
                <td>-</td>
                <td>${statusBadge}</td>
                <td>-</td>
                <td>-</td>
                <td>
                    ${convertBtn}
                    ${editBtn}
                    ${actionBtns}
                </td>
            `;
            tbody.appendChild(tr);
        });

        // Update KPI Indicators
        updateKPIIndicators(notices);
    } catch (e) { console.error(e); }
}

// KPI Indicators Function
function updateKPIIndicators(notices) {
    // Total Notices
    const totalEl = document.getElementById('kpiTotalNotices');
    if (totalEl) {
        totalEl.textContent = notices.length;
    }

    // Status Breakdown with color coding
    const statusColors = {
        'Pendiente': { bg: '#ff9800', text: '#000' },
        'En Tratamiento': { bg: '#2196f3', text: '#fff' },
        'En Progreso': { bg: '#00bcd4', text: '#000' },
        'Cerrado': { bg: '#4caf50', text: '#fff' }
    };

    const statusCounts = {};
    notices.forEach(n => {
        const status = n.status || 'Pendiente';
        statusCounts[status] = (statusCounts[status] || 0) + 1;
    });

    const statusEl = document.getElementById('kpiStatusBreakdown');
    if (statusEl) {
        statusEl.innerHTML = Object.entries(statusCounts).map(([status, count]) => {
            const colors = statusColors[status] || { bg: '#666', text: '#fff' };
            return `
                <div style="display: flex; align-items: center; gap: 8px; background: ${colors.bg}; color: ${colors.text}; padding: 8px 14px; border-radius: 20px; font-weight: 600;">
                    <span style="font-size: 1.2em;">${count}</span>
                    <span style="font-size: 0.85em;">${status}</span>
                </div>
            `;
        }).join('');
    }

    // Reporter Area Breakdown (Department that creates the notice)
    const reporterAreaCounts = {};
    notices.forEach(n => {
        const reporterArea = n.reporter_type || 'Sin Asignar';
        reporterAreaCounts[reporterArea] = (reporterAreaCounts[reporterArea] || 0) + 1;
    });

    // Sort by count descending
    const sortedReporterAreas = Object.entries(reporterAreaCounts).sort((a, b) => b[1] - a[1]);

    const areaEl = document.getElementById('kpiAreaBreakdown');
    if (areaEl) {
        areaEl.innerHTML = sortedReporterAreas.map(([area, count]) => `
            <div style="display: flex; align-items: center; gap: 6px; background: #3d3d3d; padding: 6px 12px; border-radius: 15px; border: 1px solid #555;">
                <span style="font-weight: bold; color: #bb86fc;">${count}</span>
                <span style="color: #ccc; font-size: 0.85em;">${area}</span>
            </div>
        `).join('');
    }
}

async function saveNotice(e) {
    e.preventDefault();
    const id = document.getElementById('noticeId').value;
    const method = id ? 'PUT' : 'POST';
    const url = id ? `/api/notices/${id}` : '/api/notices';

    const val = (id) => document.getElementById(id).value || null;

    const data = {
        provider_id: val('provider'), // Now sending ID
        specialty: val('specialty'),
        shift: val('shift'),
        reporter_name: val('reporterName'),
        reporter_type: val('reporterArea'),
        area_id: val('areaId'),
        line_id: val('lineId'),
        equipment_id: val('equipmentId'),
        system_id: val('systemId'),
        component_id: val('componentId'),
        description: val('description'),
        criticality: val('criticality'),
        priority: val('priority'),
        request_date: val('requestDate'),
        planning_date: val('planningDate'),
        maintenance_type: val('maintType'),
        ot_number: val('otNumber'),
        status: val('status') || 'Pendiente'
    };

    try {
        const res = await fetch(url, {
            method: method,
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
        if (res.ok) {
            document.getElementById('noticeModal').close();
            loadNotices();
        } else {
            alert("Error guardando aviso");
        }
    } catch (err) {
        alert("Error de red: " + err);
    }
}

document.addEventListener('DOMContentLoaded', () => {
    loadNotices();
    loadDropdowns();

    document.getElementById('newNoticeBtn').onclick = () => {
        document.getElementById('noticeForm').reset();
        document.getElementById('noticeId').value = '';

        // Default Date: Today
        const today = new Date().toISOString().split('T')[0];
        document.getElementById('requestDate').value = today;

        // Default Status
        document.getElementById('status').value = 'Pendiente';

        // Show advanced by default as requested
        document.getElementById('advancedFields').style.display = 'block';

        updateHierarchyDisplay();
        document.getElementById('noticeModal').showModal();
    };

    document.getElementById('noticeForm').onsubmit = saveNotice;

    // Check for URL Params (Create from Tree)
    const params = new URLSearchParams(window.location.search);
    if (params.get('create') === 'true') {
        const type = params.get('type');
        const id = parseInt(params.get('id')); // IDs are ints

        // Timeout to ensure data loaded
        setTimeout(() => {
            document.getElementById('newNoticeBtn').click();
            prefillFromTree(type, id);
        }, 500);
    }
});

function prefillFromTree(type, id) {
    if (!type || !id) return;

    // Helper to find parent
    const get = (list, id) => list.find(x => x.id === id);

    if (type === 'Area') {
        document.getElementById('areaId').value = id;
    }
    else if (type === 'Line') {
        const l = get(allLines, id);
        if (l) {
            document.getElementById('lineId').value = id;
            document.getElementById('areaId').value = l.area_id;
        }
    }
    else if (type === 'Equipment') {
        const e = get(allEquips, id);
        if (e) {
            document.getElementById('equipmentId').value = id;

            const l = get(allLines, e.line_id);
            if (l) {
                document.getElementById('lineId').value = l.id;
                document.getElementById('areaId').value = l.area_id;
            }
        }
    }
    else if (type === 'System') {
        const s = get(allSys, id);
        if (s) {
            document.getElementById('systemId').value = id;

            const e = get(allEquips, s.equipment_id);
            if (e) {
                document.getElementById('equipmentId').value = e.id;
                const l = get(allLines, e.line_id);
                if (l) {
                    document.getElementById('lineId').value = l.id;
                    document.getElementById('areaId').value = l.area_id;
                }
            }
        }
    }
    else if (type === 'Component') {
        const c = get(allComps, id);
        if (c) {
            document.getElementById('componentId').value = id;

            const s = get(allSys, c.system_id);
            if (s) {
                document.getElementById('systemId').value = s.id;
                const e = get(allEquips, s.equipment_id);
                if (e) {
                    document.getElementById('equipmentId').value = e.id;
                    const l = get(allLines, e.line_id);
                    if (l) {
                        document.getElementById('lineId').value = l.id;
                        document.getElementById('areaId').value = l.area_id;
                    }
                }
            }
        }
    }
    updateHierarchyDisplay();
}


window.editNotice = async (id) => {
    try {
        const notices = await fetch('/api/notices').then(r => r.json());
        const n = notices.find(x => x.id === id);
        if (!n) return;

        document.getElementById('noticeId').value = n.id;
        document.getElementById('provider').value = n.provider_id || '';
        document.getElementById('specialty').value = n.specialty || '';
        document.getElementById('shift').value = n.shift || 'Día';
        document.getElementById('reporterName').value = n.reporter_name || '';
        document.getElementById('reporterArea').value = n.reporter_type || '';
        document.getElementById('description').value = n.description || '';
        document.getElementById('criticality').value = n.criticality || 'Baja';
        document.getElementById('priority').value = n.priority || 'Baja';
        document.getElementById('requestDate').value = n.request_date || '';
        document.getElementById('status').value = n.status || 'Pendiente';

        // Advanced
        document.getElementById('advancedFields').style.display = 'block';
        document.getElementById('maintType').value = n.maintenance_type || '';
        document.getElementById('otNumber').value = n.ot_number ? 'OT-' + n.ot_number : ''; // Assuming we might want to show formatted

        // Hierarchy
        document.getElementById('areaId').value = n.area_id || '';
        document.getElementById('lineId').value = n.line_id || '';
        document.getElementById('equipmentId').value = n.equipment_id || '';
        document.getElementById('systemId').value = n.system_id || '';
        document.getElementById('componentId').value = n.component_id || '';

        updateHierarchyDisplay();
        document.getElementById('noticeModal').showModal();

    } catch (e) { console.error(e); }
}


// TREE SELECTION LOGIC
window.openTreeSelection = () => {
    console.log("Opening Tree Selection with Expansion Logic");
    const treeContainer = document.getElementById('selectionTree');
    treeContainer.innerHTML = ''; // Clear

    if (allAreas.length === 0) {
        treeContainer.innerHTML = '<li style="color: grey;">No se encontraron activos cargados.</li>';
        document.getElementById('treeModal').showModal();
        return;
    }

    // Helper to add caret if children exist
    const addCaret = (li, ul) => {
        if (ul.children.length > 0) {
            const caret = document.createElement('span');
            caret.className = 'caret';
            caret.onclick = (e) => {
                e.stopPropagation(); // Don't trigger selection
                ul.classList.toggle('active');
                caret.classList.toggle('caret-down');
            };
            li.insertBefore(caret, li.firstChild); // Prepend
            li.appendChild(ul);
        }
    };

    // Sort Areas
    allAreas.forEach(area => {
        const liArea = createTreeNode(area, 'Area');
        const ulLines = document.createElement('ul');
        ulLines.className = 'nested';

        // Use == for loose equality (string vs int safety)
        const areaLines = allLines.filter(x => x.area_id == area.id);

        areaLines.forEach(line => {
            const liLine = createTreeNode(line, 'Line', { area });
            const ulEquips = document.createElement('ul');
            ulEquips.className = 'nested';

            const lineEquips = allEquips.filter(x => x.line_id == line.id);
            lineEquips.forEach(eq => {
                const liEq = createTreeNode(eq, 'Equipment', { area, line });
                const ulSys = document.createElement('ul');
                ulSys.className = 'nested';

                const eqSystems = allSys.filter(x => x.equipment_id == eq.id);
                eqSystems.forEach(sys => {
                    const liSys = createTreeNode(sys, 'System', { area, line, equipment: eq });
                    const ulComps = document.createElement('ul');
                    ulComps.className = 'nested';

                    const sysComps = allComps.filter(x => x.system_id == sys.id);
                    sysComps.forEach(comp => {
                        const liComp = createTreeNode(comp, 'Component', { area, line, equipment: eq, system: sys });
                        ulComps.appendChild(liComp);
                    });

                    addCaret(liSys, ulComps);
                    ulSys.appendChild(liSys);
                });

                addCaret(liEq, ulSys);
                ulEquips.appendChild(liEq);
            });

            addCaret(liLine, ulEquips);
            ulLines.appendChild(liLine);
        });

        addCaret(liArea, ulLines);
        treeContainer.appendChild(liArea);
    });

    document.getElementById('treeModal').showModal();
}

function createTreeNode(item, type, parents = {}) {
    const li = document.createElement('li');
    const span = document.createElement('span');
    span.className = 'node-label';
    span.textContent = `${type}: ${item.name} ${item.tag ? '[' + item.tag + ']' : ''}`;

    span.onclick = (e) => {
        e.stopPropagation();
        selectHierarchy(item, type, parents);
        document.getElementById('treeModal').close();
    };

    li.appendChild(span);
    return li;
}

function selectHierarchy(item, type, parents = {}) {
    // Clear all
    document.getElementById('areaId').value = '';
    document.getElementById('lineId').value = '';
    document.getElementById('equipmentId').value = '';
    document.getElementById('systemId').value = '';
    document.getElementById('componentId').value = '';

    const critField = document.getElementById('criticality');

    // Set based on depth
    if (type === 'Area') {
        document.getElementById('areaId').value = item.id;
        critField.value = '';
        critField.disabled = false; // Allow manual if no component
    }
    else if (type === 'Line') {
        document.getElementById('areaId').value = parents.area.id;
        document.getElementById('lineId').value = item.id;
        critField.value = '';
        critField.disabled = false;
    }
    else if (type === 'Equipment') {
        document.getElementById('areaId').value = parents.area.id;
        document.getElementById('lineId').value = parents.line.id;
        document.getElementById('equipmentId').value = item.id;
        critField.value = '';
        critField.disabled = false;
    }
    else if (type === 'System') {
        document.getElementById('areaId').value = parents.area.id;
        document.getElementById('lineId').value = parents.line.id;
        document.getElementById('equipmentId').value = parents.equipment.id;
        document.getElementById('systemId').value = item.id;
        critField.value = '';
        critField.disabled = false;
    }
    else if (type === 'Component') {
        document.getElementById('areaId').value = parents.area.id;
        document.getElementById('lineId').value = parents.line.id;
        document.getElementById('equipmentId').value = parents.equipment.id;
        document.getElementById('systemId').value = parents.system.id;
        document.getElementById('componentId').value = item.id;
        // Auto-fill criticality from Component and LOCK it
        critField.value = item.criticality || 'Media';
        critField.disabled = true; // LOCK - Not editable in Notices
    }

    updateHierarchyDisplay();
}

function updateHierarchyDisplay() {
    const areaId = parseInt(document.getElementById('areaId').value);
    const lineId = parseInt(document.getElementById('lineId').value);
    const eqId = parseInt(document.getElementById('equipmentId').value);
    const sysId = parseInt(document.getElementById('systemId').value);
    const compId = parseInt(document.getElementById('componentId').value);

    const div = document.getElementById('hierarchyDisplay');

    const safeName = (list, id) => {
        const i = list.find(x => x.id === id);
        return i ? i.name : '-';
    };

    div.innerHTML = `
        <strong style="color:#03dac6">Area:</strong> ${safeName(allAreas, areaId)} | 
        <strong style="color:#03dac6">Línea:</strong> ${safeName(allLines, lineId)} | 
        <strong style="color:#03dac6">Equipo:</strong> ${safeName(allEquips, eqId)} <br>
        <strong style="color:#03dac6">Sistema:</strong> ${safeName(allSys, sysId)} | 
        <strong style="color:#03dac6">Comp.:</strong> ${safeName(allComps, compId)}
    `;
}

// Helper function to get name from list by id
function getName(list, id) {
    if (!id) return '-';
    const numId = parseInt(id);
    const item = list.find(x => x.id === numId);
    return item ? item.name : id;
}

window.annulNotice = async (id) => {
    const reason = prompt("Motivo de la anulación (Requerido):");
    if (reason === null) return; // Cancelled
    if (!reason.trim()) {
        alert("Debes ingresar un motivo para anular.");
        return;
    }

    if (!confirm("¿Estás seguro de ANULAR este aviso? No se podrá procesar después.")) return;

    try {
        const res = await fetch(`/api/notices/${id}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                status: 'Anulado',
                cancellation_reason: reason.trim()
            })
        });

        if (res.ok) {
            alert("Aviso anulado correctamente.");
            loadNotices();
        } else {
            const err = await res.json();
            alert("Error al anular: " + (err.error || 'Unknown'));
        }
    } catch (e) {
        alert("Error de red: " + e);
    }
}

// Convert notice to Work Order
window.convertToOT = async (noticeId) => {
    if (!confirm("¿Crear Orden de Trabajo a partir de este aviso?")) return;

    try {
        // Get notice data
        const notices = await fetch('/api/notices').then(r => r.json());
        const notice = notices.find(n => n.id === noticeId);
        if (!notice) {
            alert("Aviso no encontrado");
            return;
        }

        // Create work order with notice data
        const woData = {
            notice_id: noticeId,
            provider_id: notice.provider_id,
            area_id: notice.area_id,
            line_id: notice.line_id,
            equipment_id: notice.equipment_id,
            system_id: notice.system_id,
            component_id: notice.component_id,
            description: notice.description,
            maintenance_type: notice.maintenance_type || 'Correctivo'
        };

        const res = await fetch('/api/work-orders', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(woData)
        });

        if (res.ok) {
            const newOT = await res.json();
            alert(`Orden de Trabajo ${newOT.code} creada exitosamente`);
            // Redirect to work orders page
            window.location.href = '/ordenes';
        } else {
            const err = await res.json();
            alert("Error creando OT: " + (err.error || 'Unknown'));
        }
    } catch (e) {
        alert("Error de red: " + e);
    }
}
