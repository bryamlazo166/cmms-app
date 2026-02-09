
// State
let allWorkOrders = [];
let allProviders = [];
let allTechnicians = [];
let allPendingNotices = [];
let allAreas = [], allLines = [], allEquips = [], allSystems = [], allComponents = [];
let currentTab = 'tab-planning';

async function handleProviderSubmit(e) {
    // This function needs to be bound to the form
    console.log("Submitting provider...");
}

document.addEventListener('DOMContentLoaded', () => {
    loadProviders();
    loadTechnicians();
    loadWorkOrders();
    loadPendingNotices();
    loadHierarchyData();

    // Provider Form Submit
    const provForm = document.getElementById('providerForm');
    if (provForm) {
        provForm.onsubmit = async (e) => {
            e.preventDefault();
            const id = provForm.dataset.editId;
            const data = {
                name: document.getElementById('provName').value,
                specialty: document.getElementById('provSpecialty').value,
                contact_info: document.getElementById('provContact').value
            };

            const url = id ? `/api/providers/${id}` : '/api/providers';
            const method = id ? 'PUT' : 'POST';

            try {
                const res = await fetch(url, {
                    method: method,
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(data)
                });
                if (res.ok) {
                    document.getElementById('providerModal').close();
                    delete provForm.dataset.editId; // Clear ID
                    provForm.reset(); // Clear Form
                    loadProviders();
                } else {
                    alert("Error saving provider");
                }
            } catch (err) { console.error(err); }
        };
    }

    // Form Listeners
    document.getElementById('otForm').addEventListener('submit', handleOTSubmit);
    document.getElementById('closeOTForm').addEventListener('submit', handleCloseOTSubmit);
});

async function loadHierarchyData() {
    try {
        const [areas, lines, equips] = await Promise.all([
            fetch('/api/areas').then(r => r.json()),
            fetch('/api/lines').then(r => r.json()),
            fetch('/api/equipments').then(r => r.json())
        ]);

        allAreas = areas.sort((a, b) => a.name.localeCompare(b.name));
        allLines = lines.sort((a, b) => a.name.localeCompare(b.name));
        allEquips = equips.sort((a, b) => a.name.localeCompare(b.name));

        // Populate modal dropdowns if needed (not filters)
    } catch (e) { console.error("Error loading hierarchy:", e); }
}

// Global state for filters
let activeFilters = {
    area: [],
    line: [],
    equip: [],
    status: []
};

function populateMultiSelectFilters() {
    // Extract unique values from allWorkOrders
    const areas = [...new Set(allWorkOrders.map(ot => ot.area_name || '(Sin Área)').filter(x => x))].sort();
    const lines = [...new Set(allWorkOrders.map(ot => ot.line_name || '(Sin Línea)').filter(x => x))].sort();
    const equips = [...new Set(allWorkOrders.map(ot => ot.equipment_name || '(Sin Equipo)').filter(x => x))].sort();
    const statuses = [...new Set(allWorkOrders.map(ot => ot.status).filter(x => x))].sort();

    renderCheckboxList('area', areas);
    renderCheckboxList('line', lines);
    renderCheckboxList('equip', equips);
    renderCheckboxList('status', statuses);

    // Initialize activeFilters based on all checkboxes being checked by default
    activeFilters.area = areas;
    activeFilters.line = lines;
    activeFilters.equip = equips;
    activeFilters.status = statuses;
}

function renderCheckboxList(type, items) {
    const container = document.getElementById(`list-${type}`);
    if (!container) return;

    // Add "Select All" option
    let html = `
        <label>
            <input type="checkbox" value="ALL" checked onchange="toggleSelectAll('${type}')"> Seleccionar Todo
        </label>
        <div class="filter-divider"></div>
    `;

    html += items.map(item => `
        <label>
            <input type="checkbox" value="${item}" checked onchange="applyFilters()"> ${item}
        </label>
    `).join('');
    container.innerHTML = html;
}

window.toggleFilter = (type) => {
    // Close others
    document.querySelectorAll('.filter-content').forEach(el => {
        if (el.id !== `dropdown-${type}`) el.classList.remove('show');
    });
    document.getElementById(`dropdown-${type}`).classList.toggle('show');
}

window.toggleSelectAll = (type) => {
    const parent = document.getElementById(`list-${type}`); // Use list-${type} for the container
    const selectAllCb = parent.querySelector('input[value="ALL"]');
    const checkboxes = parent.querySelectorAll('input:not([value="ALL"])');

    checkboxes.forEach(cb => cb.checked = selectAllCb.checked);
    applyFilters();
}

// Close dropdowns when clicking outside
window.onclick = function (event) {
    if (!event.target.matches('.filter-btn')) {
        var dropdowns = document.getElementsByClassName("filter-content");
        for (var i = 0; i < dropdowns.length; i++) {
            var openDropdown = dropdowns[i];
            if (openDropdown.classList.contains('show')) {
                // Determine if click was inside the dropdown
                if (!openDropdown.contains(event.target)) {
                    openDropdown.classList.remove('show');
                }
            }
        }
    }
}

/* --- TABS LOGIC --- */
function openTab(evt, tabName) {
    currentTab = tabName;
    const tabContent = document.getElementsByClassName("tab-content");
    for (let i = 0; i < tabContent.length; i++) {
        tabContent[i].style.display = "none";
        tabContent[i].classList.remove("active");
    }
    const tabLinks = document.getElementsByClassName("tab-link");
    for (let i = 0; i < tabLinks.length; i++) {
        tabLinks[i].className = tabLinks[i].className.replace(" active", "");
    }
    document.getElementById(tabName).style.display = "block";
    document.getElementById(tabName).classList.add("active");
    evt.currentTarget.className += " active";

    // Refresh data usually
    if (tabName === 'tab-planning') loadWorkOrders();
    if (tabName === 'tab-providers') loadProviders();
}

/* --- API CALLS --- */
async function loadProviders() {
    try {
        const res = await fetch('/api/providers');
        allProviders = await res.json();
        renderProviders();
        populateProviderSelect();
    } catch (e) { console.error(e); }
}

async function loadWorkOrders() {
    try {
        const res = await fetch('/api/work-orders');
        allWorkOrders = await res.json();

        // Initialize Multi-selects
        populateMultiSelectFilters();

        // Initially render all
        applyFilters();
    } catch (e) { console.error(e); }
}

/* --- RENDERING --- */
function renderProviders() {
    const container = document.getElementById('providersGrid');
    container.innerHTML = allProviders.map(p => `
        <div class="card provider-card">
            <h3>${p.name}</h3>
            <p><strong>Esp:</strong> ${p.specialty || '-'}</p>
            <p><i class="fas fa-phone"></i> ${p.contact_info || '-'}</p>
            <div style="margin-top:10px; border-top:1px solid #eee; padding-top:5px;">
                <button class="btn-icon" onclick="editProvider(${p.id})"><i class="fas fa-edit"></i></button>
                <button class="btn-icon" onclick="deleteProvider(${p.id})" style="color:red;"><i class="fas fa-trash"></i></button>
            </div>
        </div>
    `).join('');
}

function populateProviderSelect() {
    const sel = document.getElementById('otProvider');
    sel.innerHTML = '<option value="">- Interno -</option>' +
        allProviders.map(p => `<option value="${p.id}">${p.name}</option>`).join('');
}

/* --- PROVIDER ACTIONS --- */
window.editProvider = (id) => {
    const p = allProviders.find(x => x.id === id);
    if (!p) return;

    // We can reuse the same modal, just need to handle ID
    // Add hidden input to form if not exists, or just use a global var (simpler here)
    document.getElementById('provName').value = p.name;
    document.getElementById('provSpecialty').value = p.specialty || '';
    document.getElementById('provContact').value = p.contact_info || '';

    // Store ID on the form dataset
    document.getElementById('providerForm').dataset.editId = id;

    document.getElementById('providerModal').showModal();
}

window.deleteProvider = async (id) => {
    if (!confirm("¿Eliminar este proveedor?")) return;
    await fetch(`/api/providers/${id}`, { method: 'DELETE' });
    loadProviders();
}

function getCriticalityColor(crit) {
    if (!crit) return '#777';
    if (crit === 'Alta') return '#f44336'; // Red
    if (crit === 'Media') return '#ff9800'; // Orange
    if (crit === 'Baja') return '#4caf50'; // Green
    return '#777';
}

window.applyFilters = () => {
    // Helper to get selected values
    const getSelected = (type) => {
        const container = document.getElementById(`list-${type}`);
        if (!container) return [];
        const checkboxes = container.querySelectorAll('input:not([value="ALL"]):checked');
        return Array.from(checkboxes).map(cb => cb.value);
    };

    const selectedAreas = getSelected('area');
    const selectedLines = getSelected('line');
    const selectedEquips = getSelected('equip');
    const selectedStatuses = getSelected('status');
    const search = document.getElementById('searchPlanning')?.value.toLowerCase().trim();

    // Check "Select All" state to optimize
    // Actually, if "Select All" is checked, usually all sub-checkboxes are checked too.
    // If NO checkboxes are checked, typically that means "None", effectively hiding everything.
    // BUT user expects Excel behavior: if you uncheck all, you see nothing.

    const filtered = allWorkOrders.filter(ot => {
        // 1. Multi-select Filters
        // Match by Name because we populated lists with Names
        const otArea = ot.area_name || '(Sin Área)';
        const otLine = ot.line_name || '(Sin Línea)';
        const otEquip = ot.equipment_name || '(Sin Equipo)';
        const otStatus = ot.status;

        if (selectedAreas.length > 0 && !selectedAreas.includes(otArea)) return false;
        if (selectedLines.length > 0 && !selectedLines.includes(otLine)) return false;
        if (selectedEquips.length > 0 && !selectedEquips.includes(otEquip)) return false;
        if (selectedStatuses.length > 0 && !selectedStatuses.includes(otStatus)) return false;

        // 2. Search Text
        if (search) {
            const code = (ot.code || '').toLowerCase();
            const desc = (ot.description || '').toLowerCase();
            const equip = (ot.equipment_name || '').toLowerCase();
            const provider = (allProviders.find(p => p.id === ot.provider_id)?.name || '').toLowerCase();
            const tech = (ot.technician_id || '').toLowerCase();

            if (!code.includes(search) &&
                !desc.includes(search) &&
                !equip.includes(search) &&
                !provider.includes(search) &&
                !tech.includes(search)) {
                return false;
            }
        }
        return true;
    });

    renderPlanningTable(filtered);
}

function renderPlanningTable(data = null) {
    // If no data passed, use allWorkOrders (initial load)
    // BUT we should probably apply filters if they exist.
    // Better pattern: if data is null, call applyFilters() which calls this with data.
    // For now, to support direct calls, we'll default to allWorkOrders if null

    // However, calling applyFilters() indiscriminately might cause loops if not careful.
    // Let's rely on data passed in.

    const list = data || allWorkOrders;
    const tbody = document.querySelector('#planningTable tbody');

    if (list.length === 0) {
        tbody.innerHTML = '<tr><td colspan="15" style="text-align:center; padding:20px; color:#aaa;">No se encontraron órdenes de trabajo.</td></tr>';
        return;
    }

    tbody.innerHTML = list.map(ot => {
        let statusClass = 'status-open';
        if (ot.status === 'En Progreso') statusClass = 'status-progress';
        if (ot.status === 'Cerrada') statusClass = 'status-closed';

        return `
        <tr>
            <td><strong>${ot.code || ot.id}</strong></td>
            <td>${ot.notice_id ? 'AV-' + ot.notice_id : '-'}</td>
            <td>${ot.area_name || '-'}</td>
            <td>${ot.line_name || '-'}</td>
            <td>${ot.equipment_name || '-'}</td>
            <td>${ot.system_name || '-'}</td>
            <td>${ot.component_name || '-'}</td>
            <td><span class="badge" style="background:${getCriticalityColor(ot.criticality)}; color:white;">${ot.criticality || '-'}</span></td>
            <td>${ot.description || ''}</td>
            <td>${ot.maintenance_type || '-'}</td>
            <td><span class="badge ${statusClass}">${ot.status}</span></td>
            <td>${ot.priority || '-'}</td>
            <td>${ot.scheduled_date || '-'}</td>
            <td>${ot.technician_id || ot.provider_id || '-'}</td>
            <td>
                <button class="btn-icon" onclick="editOT(${ot.id})"><i class="fas fa-edit"></i></button>
            </td>
        </tr>
    `}).join('');
}

/* --- ACTIONS --- */
function openProviderModal() {
    document.getElementById('providerForm').reset();
    document.getElementById('providerModal').showModal();
}

async function handleProviderSubmit(e) {
    e.preventDefault();
    const data = {
        name: document.getElementById('provName').value,
        specialty: document.getElementById('provSpecialty').value,
        contact_info: document.getElementById('provContact').value
    };

    await fetch('/api/providers', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data)
    });

    document.getElementById('providerModal').close();
    loadProviders();
}

function openCreateOTModal() {
    document.getElementById('otForm').reset();
    document.getElementById('otId').value = '';

    // Reset sub-tabs to General
    document.querySelectorAll('.ot-tab-content').forEach(t => t.style.display = 'none');
    document.getElementById('ot-tab-general').style.display = 'block';
    document.querySelectorAll('.ot-subtab').forEach((btn, i) => {
        btn.style.background = i === 0 ? '#03dac6' : '#333';
        btn.style.color = i === 0 ? '#000' : '#aaa';
    });

    // Clear resource tables
    currentOTPersonnel = [];
    currentOTMaterials = [];
    renderPersonnelTable();
    renderMaterialsTable();

    // Reset Feedback
    document.getElementById('feedbackContainer').style.display = 'none';

    document.getElementById('otModal').showModal();
}

async function editOT(id) {
    const ot = allWorkOrders.find(x => x.id === id);
    if (!ot) return;

    document.getElementById('otId').value = ot.id;
    document.getElementById('otNoticeId').value = ot.notice_id || '';
    document.getElementById('otDescription').value = ot.description || '';
    document.getElementById('otType').value = ot.maintenance_type || 'Preventivo';
    document.getElementById('otPriority').value = ot.priority || 'Media';
    document.getElementById('otScheduledDate').value = ot.scheduled_date || '';
    document.getElementById('otTechnician').value = ot.technician_id || '';
    document.getElementById('otProvider').value = ot.provider_id || '';
    document.getElementById('otEstDuration').value = ot.estimated_duration || '';
    document.getElementById('otStatus').value = ot.status || 'Abierta';
    document.getElementById('otFailureMode').value = ot.failure_mode || '';

    // Load notice data if linked
    if (ot.notice_id) {
        try {
            const notices = await fetch('/api/notices').then(r => r.json());
            const notice = notices.find(n => n.id === ot.notice_id);
            if (notice) {
                document.getElementById('otReporterName').value = notice.reporter_name || '';
                document.getElementById('otSpecialty').value = notice.specialty || '';
                document.getElementById('otShift').value = notice.shift || 'Día';
                document.getElementById('otCriticality').value = notice.criticality || 'Baja';
            }
        } catch (e) { console.error(e); }
    } else {
        document.getElementById('otReporterName').value = '';
        document.getElementById('otSpecialty').value = '';
        document.getElementById('otShift').value = 'Día';
        document.getElementById('otCriticality').value = 'Baja';
    }

    // Reset sub-tabs to General and load resources
    document.querySelectorAll('.ot-tab-content').forEach(t => t.style.display = 'none');
    document.getElementById('ot-tab-general').style.display = 'block';
    document.querySelectorAll('.ot-subtab').forEach((btn, i) => {
        btn.style.background = i === 0 ? '#03dac6' : '#333';
        btn.style.color = i === 0 ? '#000' : '#aaa';
    });

    // Load personnel and materials for this OT
    currentEditingOT = ot; // Store for suggestions
    // These functions may not be fully implemented yet - using safe calls
    if (typeof loadOTPersonnel === 'function') loadOTPersonnel(ot.id);
    if (typeof loadOTMaterials === 'function') loadOTMaterials(ot.id);

    // Load Feedback (Lessons Learned)
    checkFeedback(ot.equipment_id);

    document.getElementById('otModal').showModal();
}

// Expose editOT to window for onclick handlers
window.editOT = editOT;

// Global to track what we are editing
let currentEditingOT = null;

// ============= PREDICTIVE SUGGESTIONS =============
async function checkSuggestions() {
    if (!currentEditingOT) return;

    const maintenanceType = document.getElementById('otType').value;

    // Build params
    const params = new URLSearchParams();
    params.append('maintenance_type', maintenanceType);
    if (currentEditingOT.component_id) params.append('component_id', currentEditingOT.component_id);
    else if (currentEditingOT.system_id) params.append('system_id', currentEditingOT.system_id);
    else if (currentEditingOT.equipment_id) params.append('equipment_id', currentEditingOT.equipment_id);
    else {
        alert("Esta OT no tiene activo asignado para buscar historial.");
        return;
    }

    try {
        const res = await fetch(`/api/predictive/ot-suggestions?${params.toString()}`);
        const data = await res.json();

        if (data.found) {
            const msg = `✨ Historial Encontrado (OT: ${data.last_ot_code})\n\n` +
                `Fecha: ${data.last_date}\n` +
                `Duración: ${data.duration} hrs\n` +
                `Herramientas: ${data.tools.length}\n` +
                `Repuestos: ${data.parts.length}\n\n` +
                `¿Desea aplicar estos valores?`;

            if (confirm(msg)) {
                applySuggestion(data);
            }
        } else {
            alert("No se encontró historial similar.");
        }
    } catch (e) {
        console.error(e);
        alert("Error consultando historial");
    }
}

async function applySuggestion(data) {
    if (!currentEditingOT) return;

    // 1. Update Duration
    if (data.duration) {
        document.getElementById('otEstDuration').value = data.duration;
    }

    // 2. Add Tools
    if (data.tools && data.tools.length > 0) {
        for (const t of data.tools) {
            await addMaterialToOT(currentEditingOT.id, t.item_type, t.item_id, t.quantity);
        }
    }

    // 3. Add Parts
    if (data.parts && data.parts.length > 0) {
        for (const p of data.parts) {
            await addMaterialToOT(currentEditingOT.id, p.item_type, p.item_id, p.quantity);
        }
    }

    // Refresh tables
    loadOTMaterials(currentEditingOT.id);
    alert("Sugerencias aplicadas exitosamente.");
}

// Helper to add material via API without modal
async function addMaterialToOT(otId, type, itemId, quantity) {
    try {
        await fetch(`/api/work_orders/${otId}/materials`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                item_type: type,
                item_id: itemId,
                quantity: quantity
            })
        });
    } catch (e) { console.error("Error auto-adding material:", e); }
}


async function handleOTSubmit(e) {
    e.preventDefault();
    try {
        const id = document.getElementById('otId').value;
        const noticeId = document.getElementById('otNoticeId').value;

        const data = {
            description: document.getElementById('otDescription').value,
            maintenance_type: document.getElementById('otType').value,
            priority: document.getElementById('otPriority').value,
            scheduled_date: document.getElementById('otScheduledDate').value,
            technician_id: document.getElementById('otTechnician').value,
            provider_id: document.getElementById('otProvider').value ? parseInt(document.getElementById('otProvider').value) : null,
            estimated_duration: document.getElementById('otEstDuration').value,
            status: document.getElementById('otStatus').value,
            failure_mode: document.getElementById('otFailureMode').value
        };

        let url = '/api/work-orders';
        let method = 'POST';

        if (id) {
            url += '/' + id;
            method = 'PUT';
        } else {
            data.status = data.status || 'Abierta';
        }

        const res = await fetch(url, {
            method: method,
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });

        if (!res.ok) {
            const err = await res.json();
            alert("Error guardando OT: " + (err.error || 'Desconocido'));
            return;
        }

        const savedOT = await res.json();

        // Sync notice data if linked
        if (noticeId) {
            const noticeData = {
                reporter_name: document.getElementById('otReporterName').value,
                specialty: document.getElementById('otSpecialty').value,
                shift: document.getElementById('otShift').value,
                criticality: document.getElementById('otCriticality').value,
                priority: document.getElementById('otPriority').value,
                description: document.getElementById('otDescription').value,
                maintenance_type: document.getElementById('otType').value,
                ot_number: savedOT.code || '',
                planning_date: document.getElementById('otScheduledDate').value,  // Sync planning date
                provider_id: document.getElementById('otProvider').value || null  // Sync provider
            };

            // Update notice status and dates based on OT status
            if (data.status === 'Cerrada') {
                noticeData.status = 'Cerrado';
            } else if (data.status === 'En Progreso') {
                noticeData.status = 'En Progreso';
                noticeData.treatment_date = new Date().toISOString().slice(0, 10);  // Today as treatment date
            } else if (data.status === 'Programada') {
                noticeData.status = 'Programado';
            }

            await fetch(`/api/notices/${noticeId}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(noticeData)
            });
        }

        document.getElementById('otModal').close();
        loadWorkOrders();
    } catch (error) {
        console.error("Error en handleOTSubmit:", error);
        alert("Error de red o de proceso: " + error.message);
    }
}


/* --- KANBAN LOGIC --- */


var calendarInstance = null;

function switchView(mode) {
    // Hide all
    document.getElementById('listView').style.display = 'none';
    document.getElementById('kanbanView').style.display = 'none';
    document.getElementById('calendarView').style.display = 'none';

    // Reset buttons
    const btns = ['viewListBtn', 'viewKanbanBtn', 'viewCalendarBtn'];
    btns.forEach(bid => {
        const btn = document.getElementById(bid);
        if (btn) {
            btn.classList.remove('active');
            btn.style.background = 'transparent';
            btn.style.color = '#aaa';
        }
    });

    if (mode === 'list') {
        document.getElementById('listView').style.display = 'block';
        setActiveBtn('viewListBtn');
    } else if (mode === 'kanban') {
        document.getElementById('kanbanView').style.display = 'flex';
        setActiveBtn('viewKanbanBtn');
        renderKanban();
    } else if (mode === 'calendar') {
        document.getElementById('calendarView').style.display = 'block';
        setActiveBtn('viewCalendarBtn');
        renderCalendar();
    }
}

function setActiveBtn(id) {
    const btn = document.getElementById(id);
    if (btn) {
        btn.classList.add('active');
        btn.style.background = '#03dac6'; // Unified primary color
        btn.style.color = 'black';
    }
}

function renderCalendar() {
    const calendarEl = document.getElementById('calendar');

    const events = getCalendarEvents();

    if (!calendarInstance) {
        calendarInstance = new FullCalendar.Calendar(calendarEl, {
            initialView: 'dayGridMonth',
            locale: 'es',
            headerToolbar: {
                left: 'prev,next today',
                center: 'title',
                right: 'dayGridMonth,timeGridWeek'
            },
            height: 700,
            editable: true,
            events: events,
            eventClick: function (info) {
                openEditOTModal(info.event.id);
            },
            eventDrop: function (info) {
                if (confirm("¿Reprogramar OT para " + info.event.start.toLocaleDateString() + "?")) {
                    updateOTDate(info.event.id, info.event.start);
                } else {
                    info.revert();
                }
            }
        });
        calendarInstance.render();
    } else {
        calendarInstance.removeAllEvents();
        calendarInstance.addEventSource(events);
        calendarInstance.render();
    }

    // Fix render issues when protected by display:none
    setTimeout(() => {
        calendarInstance.updateSize();
    }, 200);
}

function getCalendarEvents() {
    if (typeof allWorkOrders === 'undefined') return [];

    return allWorkOrders.map(ot => {
        if (!ot.scheduled_date) return null;

        // Color logic
        let color = '#3788d8'; // Default blue
        if (ot.status === 'Cerrada') color = '#4caf50'; // Green
        else if (ot.status === 'En Progreso') color = '#03dac6'; // Teal
        else if (ot.criticality === 'Alta' || ot.priority === 'Alta') color = '#f44336'; // Red programada alta

        return {
            id: ot.id,
            title: `${ot.code} - ${ot.equipment_name || 'Sin Eq.'}`,
            start: ot.scheduled_date,
            color: color,
            extendedProps: { description: ot.description }
        };
    }).filter(e => e !== null);
}

async function updateOTDate(id, newDate) {
    try {
        // Adjust timezone offset to get YYYY-MM-DD correctly
        const offset = newDate.getTimezoneOffset();
        const dateLocal = new Date(newDate.getTime() - (offset * 60 * 1000));
        const dateStr = dateLocal.toISOString().split('T')[0];

        const res = await fetch(`/api/work-orders/${id}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ scheduled_date: dateStr })
        });

        if (res.ok) {
            // Update local
            const ot = allWorkOrders.find(o => o.id == id);
            if (ot) ot.scheduled_date = dateStr;

            // Refresh other views
            loadWorkOrders(); // Refresh table (quietly)
        } else {
            alert("Error al actualizar fecha");
        }
    } catch (error) {
        console.error("Error updating date:", error);
        alert("Error de conexión");
    }
}

function renderKanban() {
    // Clear columns
    ['Abierta', 'Programada', 'En Progreso', 'Cerrada'].forEach(status => {
        const colId = status === 'En Progreso' ? 'col-En Progreso' : `col-${status}`;
        const container = document.getElementById(colId);
        if (container) container.innerHTML = '';

        const countId = status === 'En Progreso' ? 'count-En_Progreso' : `count-${status}`;
        const badge = document.getElementById(countId);
        if (badge) badge.innerText = 0;
    });

    // Distribute OTs
    const counts = { 'Abierta': 0, 'Programada': 0, 'En Progreso': 0, 'Cerrada': 0 };

    // We use global var "allWorkOrders" which should check if exists
    if (typeof allWorkOrders === 'undefined') return;

    allWorkOrders.forEach(ot => {
        let status = ot.status || 'Abierta';

        // Normalize status if needed (e.g. database has diferent strings)
        if (status === 'Pendiente') status = 'Abierta';

        const colId = status === 'En Progreso' ? 'col-En Progreso' : `col-${status}`;
        const container = document.getElementById(colId);

        if (!container) return; // Unknown status or filtered out

        counts[status] = (counts[status] || 0) + 1;

        const card = document.createElement('div');
        card.className = `kanban-card kanban-priority-${getPriorityClass(ot.criticality)}`;
        card.draggable = true;
        card.dataset.id = ot.id;
        card.ondragstart = drag;

        card.innerHTML = `
            <div class="kanban-card-header">
                <span>${ot.code}</span>
                <span style="font-size:0.8em; opacity:0.7;">${ot.scheduled_date || ''}</span>
            </div>
            <div class="kanban-card-title">${ot.description || 'Sin descripción'}</div>
            <div class="kanban-card-desc" style="font-size: 0.85em; color: #aaa;">
                ${ot.equipment_name || ot.component_name || 'Sin Equipo'}
            </div>
            <div class="kanban-card-footer">
                <span><i class="fas fa-hammer"></i> ${ot.failure_mode || '-'}</span>
                <span>${ot.technician_id || 'Sin Asig.'}</span>
            </div>
        `;

        // Double Click to Edit
        card.ondblclick = () => openEditOTModal(ot.id);

        container.appendChild(card);
    });

    // Update counts
    Object.keys(counts).forEach(status => {
        const countId = status === 'En Progreso' ? 'count-En_Progreso' : `count-${status}`;
        const badge = document.getElementById(countId);
        if (badge) badge.innerText = counts[status];
    });
}

function getPriorityClass(crit) {
    if (!crit) return 'low';
    const c = crit.toUpperCase();
    if (c === 'ALTA' || c === 'A') return 'high';
    if (c === 'MEDIA' || c === 'B') return 'med';
    return 'low';
}

// Drag & Drop
function drag(ev) {
    ev.dataTransfer.setData("text", ev.target.dataset.id);
}

function allowDrop(ev) {
    ev.preventDefault();
    ev.currentTarget.classList.add('drag-over');
}

function drop(ev, newStatus) {
    ev.preventDefault();
    document.querySelectorAll('.kanban-body').forEach(el => el.classList.remove('drag-over'));

    const id = ev.dataTransfer.getData("text");
    if (!id) return;

    // Optimistic UI Update
    // Find card and move it? Or just reload

    updateOTStatusKanban(id, newStatus);
}

async function updateOTStatusKanban(id, status) {
    try {
        const res = await fetch(`/api/work-orders/${id}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ status: status })
        });

        if (res.ok) {
            // Update local model
            const ot = allWorkOrders.find(o => o.id == id);
            if (ot) ot.status = status;
            renderKanban();   // Reloads kanban
            loadWorkOrders(); // Refresh table too
        } else {
            alert("Error al actualizar estado");
        }
    } catch (e) {
        console.error(e);
        alert("Error de conexión");
    }
}


/* --- EXECUTION MODULE --- */
let activeExecutionOT = null;

async function searchForExecution() {
    const val = document.getElementById('executionSearch').value.trim().toUpperCase();
    if (!val) return;

    // Try to find by code or ID
    const ot = allWorkOrders.find(o => (o.code && o.code === val) || (String(o.id) === val));

    const panel = document.getElementById('execution-details');
    if (ot) {
        activeExecutionOT = ot;
        panel.classList.remove('hidden');

        // Basic info
        document.getElementById('exec-ot-code').innerText = ot.code || `OT-${ot.id}`;
        document.getElementById('exec-desc').innerText = ot.description || 'Sin descripción';

        // Status badge
        const badge = document.getElementById('exec-status');
        badge.innerText = ot.status;
        badge.className = 'status-badge ' + (ot.status === 'En Progreso' ? 'status-progress' : ot.status === 'Cerrada' ? 'status-closed' : 'status-open');

        // Populate summary fields
        document.getElementById('exec-type').innerText = ot.maintenance_type || '-';
        document.getElementById('exec-priority').innerText = ot.priority || '-';
        document.getElementById('exec-scheduled').innerText = ot.scheduled_date || '-';
        document.getElementById('exec-duration').innerText = ot.estimated_duration ? `${ot.estimated_duration} hrs` : '-';

        // Get technician name
        const tech = allTechnicians.find(t => t.id === parseInt(ot.technician_id));
        document.getElementById('exec-technician').innerText = tech ? tech.name : (ot.technician_id || '-');

        // Get provider name
        const provider = allProviders.find(p => p.id === parseInt(ot.provider_id));
        document.getElementById('exec-provider').innerText = provider ? provider.name : '-';

        // Load materials for this OT
        try {
            const materialsRes = await fetch(`/api/work_orders/${ot.id}/materials`);
            const materials = await materialsRes.json();

            // Separate tools and parts
            const tools = materials.filter(m => m.item_type === 'tool');
            const parts = materials.filter(m => m.item_type !== 'tool');

            // Render tools list
            const toolsContainer = document.getElementById('exec-tools-list');
            if (tools.length === 0) {
                toolsContainer.innerHTML = '<p style="color: #888; font-style: italic;">No hay herramientas asignadas</p>';
            } else {
                toolsContainer.innerHTML = `
                    <table style="width: 100%; border-collapse: collapse;">
                        <thead>
                            <tr style="border-bottom: 1px solid #444;">
                                <th style="text-align: left; padding: 5px; color: #aaa;">Código</th>
                                <th style="text-align: left; padding: 5px; color: #aaa;">Nombre</th>
                                <th style="text-align: center; padding: 5px; color: #aaa;">Cantidad</th>
                            </tr>
                        </thead>
                        <tbody>
                            ${tools.map(t => `
                                <tr style="border-bottom: 1px solid #333;">
                                    <td style="padding: 8px;"><strong style="color: #2196f3;">${t.item_code || '-'}</strong></td>
                                    <td style="padding: 8px;">${t.item_name || 'Desconocido'}</td>
                                    <td style="text-align: center; padding: 8px;">${t.quantity}</td>
                                </tr>
                            `).join('')}
                        </tbody>
                    </table>
                `;
            }

            // Render parts list
            const partsContainer = document.getElementById('exec-parts-list');
            if (parts.length === 0) {
                partsContainer.innerHTML = '<p style="color: #888; font-style: italic;">No hay repuestos asignados</p>';
            } else {
                partsContainer.innerHTML = `
                    <table style="width: 100%; border-collapse: collapse;">
                        <thead>
                            <tr style="border-bottom: 1px solid #444;">
                                <th style="text-align: left; padding: 5px; color: #aaa;">Código</th>
                                <th style="text-align: left; padding: 5px; color: #aaa;">Nombre</th>
                                <th style="text-align: center; padding: 5px; color: #aaa;">Cantidad</th>
                            </tr>
                        </thead>
                        <tbody>
                            ${parts.map(p => `
                                <tr style="border-bottom: 1px solid #333;">
                                    <td style="padding: 8px;"><strong style="color: #4caf50;">${p.item_code || '-'}</strong></td>
                                    <td style="padding: 8px;">${p.item_name || 'Desconocido'}</td>
                                    <td style="text-align: center; padding: 8px;">${p.quantity}</td>
                                </tr>
                            `).join('')}
                        </tbody>
                    </table>
                `;
            }
        } catch (e) {
            console.error('Error loading materials:', e);
            document.getElementById('exec-tools-list').innerHTML = '<p style="color: #f44336;">Error cargando herramientas</p>';
            document.getElementById('exec-parts-list').innerHTML = '<p style="color: #f44336;">Error cargando repuestos</p>';
        }

        // Action buttons
        const btnStart = document.getElementById('btn-start-job');
        const btnEnd = document.getElementById('btn-finish-job');

        btnStart.classList.add('hidden');
        btnEnd.classList.add('hidden');

        if (ot.status === 'Abierta' || ot.status === 'Programada') {
            btnStart.classList.remove('hidden');
        } else if (ot.status === 'En Progreso') {
            btnEnd.classList.remove('hidden');
        } else {
            // Closed
            badge.innerText = "CERRADA";
            badge.classList.add('status-closed');
        }

    } else {
        alert("Orden de Trabajo no encontrada");
        panel.classList.add('hidden');
    }
}


// Helper for Local ISO String (YYYY-MM-DDTHH:mm)
function getLocalISOString() {
    const now = new Date();
    const tzOffset = now.getTimezoneOffset() * 60000; // offset in milliseconds
    const localISOTime = (new Date(now - tzOffset)).toISOString().slice(0, 16);
    return localISOTime;
}

async function startJob() {
    if (!activeExecutionOT) return;
    if (!confirm("¿Iniciar trabajo ahora? Se guardará fecha/hora según sistema.")) return;

    const now = getLocalISOString();
    const today = now.slice(0, 10);

    await fetch(`/api/work-orders/${activeExecutionOT.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            status: 'En Progreso',
            real_start_date: now
        })
    });

    // Sync notice status if linked
    if (activeExecutionOT.notice_id) {
        await fetch(`/api/notices/${activeExecutionOT.notice_id}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                status: 'En Progreso',
                treatment_date: today
            })
        });
    }

    // Refresh
    await loadWorkOrders();
    // Re-fetch to update activeExecutionOT with new status/date
    const res = await fetch('/api/work-orders');
    allWorkOrders = await res.json();
    const updatedOT = allWorkOrders.find(o => o.id === activeExecutionOT.id);
    if (updatedOT) {
        activeExecutionOT = updatedOT;
        searchForExecution();
    }
}

function openCloseModal() {
    if (!activeExecutionOT) return;
    document.getElementById('closeOtId').value = activeExecutionOT.id;

    const now = getLocalISOString();
    const start = activeExecutionOT.real_start_date || now;

    // Pre-fill
    const startInput = document.getElementById('realStart');
    const endInput = document.getElementById('realEnd');

    startInput.value = start;
    endInput.value = now;

    // Lock start date if it comes from server
    if (activeExecutionOT.real_start_date) {
        startInput.readOnly = true;
        startInput.style.backgroundColor = "#444";
    } else {
        startInput.readOnly = false;
        startInput.style.backgroundColor = "";
    }

    // Always lock end date as it should be system time
    endInput.readOnly = true;
    endInput.style.backgroundColor = "#444";

    document.getElementById('closeOTModal').showModal();
}

async function handleCloseOTSubmit(e) {
    e.preventDefault();
    const id = document.getElementById('closeOtId').value;
    const startVal = document.getElementById('realStart').value;
    const endVal = document.getElementById('realEnd').value;

    // Calculate Duration
    const startDate = new Date(startVal);
    const endDate = new Date(endVal);
    const diffMs = endDate - startDate;
    const diffHrs = diffMs / (1000 * 60 * 60); // Hours float

    // Formatting for message
    const hours = Math.floor(diffMs / (1000 * 60 * 60));
    const minutes = Math.floor((diffMs % (1000 * 60 * 60)) / (1000 * 60));

    const data = {
        status: 'Cerrada',
        execution_comments: document.getElementById('closeComments').value,
        real_start_date: startVal,
        real_end_date: endVal,
        real_duration: parseFloat(diffHrs.toFixed(2))
    };

    await fetch(`/api/work-orders/${id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data)
    });

    document.getElementById('closeOTModal').close();
    await loadWorkOrders();

    // Reset execution view
    document.getElementById('execution-details').classList.add('hidden');
    document.getElementById('executionSearch').value = '';

    alert(`✅ Orden Cerrada Correctamente.\n\nTiempo Total: ${hours} horas y ${minutes} minutos.`);
}

/* --- TECHNICIAN MANAGEMENT --- */
async function loadTechnicians() {
    try {
        const showAll = document.getElementById('showInactiveTechs')?.checked || false;
        const url = showAll ? '/api/technicians?all=true' : '/api/technicians';
        const res = await fetch(url);
        allTechnicians = await res.json();
        renderTechnicians();
        populateTechnicianSelect();
    } catch (e) { console.error(e); }
}

function renderTechnicians() {
    const container = document.getElementById('techniciansGrid');
    if (!container) return;

    container.innerHTML = allTechnicians.map(t => `
        <div class="card provider-card" style="${t.is_active ? '' : 'opacity: 0.5; border: 1px dashed #888;'}">
            <h3>${t.name} ${t.is_active ? '' : '(INACTIVO)'}</h3>
            <p><strong>Esp:</strong> ${t.specialty || '-'}</p>
            <p><i class="fas fa-phone"></i> ${t.contact_info || '-'}</p>
            <div style="margin-top:10px; border-top:1px solid #eee; padding-top:5px;">
                <button class="btn-icon" onclick="editTechnician(${t.id})"><i class="fas fa-edit"></i></button>
                <button class="btn-icon" onclick="toggleTechnician(${t.id})" style="color:${t.is_active ? 'orange' : 'green'};" title="${t.is_active ? 'Dar de baja' : 'Dar de alta'}">
                    <i class="fas fa-${t.is_active ? 'user-slash' : 'user-check'}"></i>
                </button>
            </div>
        </div>
    `).join('');
}

function populateTechnicianSelect() {
    const sel = document.getElementById('otTechnician');
    if (!sel) return;

    // Only show active technicians in dropdown
    const activeTechs = allTechnicians.filter(t => t.is_active);
    sel.innerHTML = '<option value="">- Seleccione -</option>' +
        activeTechs.map(t => `<option value="${t.id}">${t.name}</option>`).join('');
}

function openTechnicianModal() {
    document.getElementById('techId').value = '';
    document.getElementById('techName').value = '';
    document.getElementById('techSpecialty').value = '';
    document.getElementById('techContact').value = '';
    document.getElementById('techModalTitle').textContent = 'Nuevo Técnico';
    document.getElementById('technicianModal').showModal();
}

window.editTechnician = (id) => {
    const t = allTechnicians.find(x => x.id === id);
    if (!t) return;

    document.getElementById('techId').value = t.id;
    document.getElementById('techName').value = t.name;
    document.getElementById('techSpecialty').value = t.specialty || '';
    document.getElementById('techContact').value = t.contact_info || '';
    document.getElementById('techModalTitle').textContent = 'Editar Técnico';
    document.getElementById('technicianModal').showModal();
}

window.toggleTechnician = async (id) => {
    const t = allTechnicians.find(x => x.id === id);
    const action = t?.is_active ? 'dar de baja' : 'dar de alta';
    if (!confirm(`¿Desea ${action} a este técnico?`)) return;

    await fetch(`/api/technicians/${id}`, { method: 'DELETE' });
    loadTechnicians();
}

// Technician Form Submit
document.addEventListener('DOMContentLoaded', () => {
    const techForm = document.getElementById('technicianForm');
    if (techForm) {
        techForm.onsubmit = async (e) => {
            e.preventDefault();
            const id = document.getElementById('techId').value;
            const data = {
                name: document.getElementById('techName').value,
                specialty: document.getElementById('techSpecialty').value,
                contact_info: document.getElementById('techContact').value
            };

            const url = id ? `/api/technicians/${id}` : '/api/technicians';
            const method = id ? 'PUT' : 'POST';

            await fetch(url, {
                method: method,
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(data)
            });

            document.getElementById('technicianModal').close();
            loadTechnicians();
        };
    }
});

// Load Hierarchy Data for name lookups
async function loadHierarchyData() {
    try {
        const [areas, lines, equips, systems, comps] = await Promise.all([
            fetch('/api/areas').then(r => r.json()),
            fetch('/api/lines').then(r => r.json()),
            fetch('/api/equipments').then(r => r.json()),
            fetch('/api/systems').then(r => r.json()),
            fetch('/api/components').then(r => r.json())
        ]);
        allAreas = areas;
        allLines = lines;
        allEquips = equips;
        allSystems = systems;
        allComponents = comps;
    } catch (e) { console.error("Error loading hierarchy:", e); }
}

// Load Pending Notices (notices without OT)
async function loadPendingNotices() {
    try {
        const res = await fetch('/api/notices');
        const notices = await res.json();

        // Filter notices that don't have an OT yet and are not closed
        allPendingNotices = notices.filter(n => !n.ot_number && n.status !== 'Cerrado');

        renderPendingNotices();
    } catch (e) { console.error("Error loading notices:", e); }
}

// Helper to get name from list
function getNameFromList(list, id) {
    if (!id) return '-';
    const item = list.find(x => x.id === parseInt(id));
    return item ? item.name : '-';
}

// Render Pending Notices Table
// Render Pending Notices Table
function renderPendingNotices() {
    const tbody = document.querySelector('#pendingNoticesTable tbody');
    if (!tbody) return;

    tbody.innerHTML = '';

    allPendingNotices.forEach(n => {
        // Get equipment name
        let equipName = getNameFromList(allEquips, n.equipment_id);
        if (equipName === '-') equipName = getNameFromList(allSystems, n.system_id);
        if (equipName === '-') equipName = getNameFromList(allComponents, n.component_id);

        // Status badge color
        const statusColors = {
            'Pendiente': '#ff9800',
            'En Tratamiento': '#2196f3',
            'En Progreso': '#00bcd4'
        };
        const statusColor = statusColors[n.status] || '#666';

        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td>${n.code || n.id}</td>
            <td>${n.reporter_type || '-'}</td>
            <td>${equipName}</td>
            <td>${n.description ? (n.description.length > 30 ? n.description.substring(0, 30) + '...' : n.description) : '-'}</td>
            <td>${n.criticality || '-'}</td>
            <td>${n.priority || '-'}</td>
            <td>${n.request_date || '-'}</td>
            <td>${n.reporter_name || '-'}</td>
            <td>${n.maintenance_type || '-'}</td>
            <td><span style="background: ${statusColor}; padding: 3px 8px; border-radius: 10px; font-size: 0.8em; color: white;">${n.status || 'Pendiente'}</span></td>
            <td>
                <div style="display: flex; gap: 5px;">
                    <button onclick="viewNoticeDetails(${n.id})" class="btn-info" style="padding: 5px 8px;" title="Ver Detalle y Duplicados">
                        <i class="fas fa-eye"></i>
                    </button>
                    <button onclick="convertNoticeToOT(${n.id})" class="btn-success" style="padding: 5px 8px;" title="Crear OT">
                        <i class="fas fa-wrench"></i>
                    </button>
                </div>
            </td>
        `;
        tbody.appendChild(tr);
    });

    // Show message if no pending notices
    if (allPendingNotices.length === 0) {
        tbody.innerHTML = '<tr><td colspan="11" style="text-align: center; color: #888; padding: 20px;">No hay avisos pendientes para convertir en OT</td></tr>';
    }
}

// View Notice Details & Check Duplicates
window.viewNoticeDetails = async function (id) {
    try {
        const n = allPendingNotices.find(x => x.id === id);
        if (!n) return;

        document.getElementById('detail-code').textContent = n.code || n.id;
        document.getElementById('detail-status').textContent = n.status || '-';
        document.getElementById('detail-reporter-type').textContent = n.reporter_type || '-';
        document.getElementById('detail-reporter-name').textContent = n.reporter_name || '-';
        document.getElementById('detail-request-date').textContent = n.request_date || '-';
        document.getElementById('detail-maint-type').textContent = n.maintenance_type || '-';
        document.getElementById('detail-description').textContent = n.description || '-';

        // Hierarchy
        let hText = `Area: ${getNameFromList(allAreas, n.area_id)} | Línea: ${getNameFromList(allLines, n.line_id)} | Equipo: ${getNameFromList(allEquips, n.equipment_id)}`;
        document.getElementById('detail-hierarchy').textContent = hText;

        // Reset & Actions
        document.getElementById('detail-actions').innerHTML = `
            <button class="btn-primary" onclick="convertNoticeToOT(${n.id}); document.getElementById('noticeDetailModal').close();">
                <i class="fas fa-wrench"></i> Crear OT Ahora
            </button>
        `;

        // Check Duplicates
        const warningSection = document.getElementById('duplicate-warning-section');
        const list = document.getElementById('duplicate-list');
        warningSection.style.display = 'none';
        list.innerHTML = '';

        if (n.equipment_id) {
            const res = await fetch(`/api/predictive/check-duplicates?equipment_id=${n.equipment_id}&exclude_notice_id=${n.id}`);
            const data = await res.json();

            if ((data.notices && data.notices.length > 0) || (data.work_orders && data.work_orders.length > 0)) {
                warningSection.style.display = 'block';

                // Add Notices
                data.notices.forEach(d => {
                    list.innerHTML += `<li>⚠️ Aviso <strong>${d.code || d.id}</strong> (${d.status}): "${d.description}"</li>`;
                });

                // Add Work Orders
                data.work_orders.forEach(ot => {
                    list.innerHTML += `<li>⚠️ OT Activa <strong>${ot.code || ot.id}</strong> (${ot.status}): "${ot.description}"</li>`;
                });
            }
        }

        document.getElementById('noticeDetailModal').showModal();

    } catch (e) { console.error(e); alert("Error cargando detalles"); }
}

// Convert Notice to OT
async function convertNoticeToOT(noticeId) {
    if (!confirm('¿Desea crear una Orden de Trabajo a partir de este aviso?')) return;

    try {
        // Get the notice data
        const noticeRes = await fetch(`/api/notices/${noticeId}`);
        const notice = await noticeRes.json();

        // Create OT with notice data
        const newOT = {
            notice_id: noticeId,
            description: notice.description,
            scheduled_date: new Date().toISOString().split('T')[0],
            maintenance_type: notice.maintenance_type || 'Correctivo',
            status: 'Pendiente',
            area_id: notice.area_id,
            line_id: notice.line_id,
            equipment_id: notice.equipment_id,
            system_id: notice.system_id,
            component_id: notice.component_id
        };

        const res = await fetch('/api/work-orders', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(newOT)
        });

        if (res.ok) {
            const createdOT = await res.json();
            alert(`OT creada exitosamente: ${createdOT.code}`);
            loadWorkOrders();
            loadPendingNotices();

            // Switch to planning tab
            document.querySelector('[onclick*="tab-planning"]').click();
        } else {
            const err = await res.json();
            alert('Error al crear la OT: ' + (err.error || 'Desconocido'));
        }
    } catch (e) {
        console.error(e);
        alert('Error de red al crear la OT');
    }
}

// ============= OT SUB-TABS FUNCTIONS =============

// State for OT resources
let currentOTPersonnel = [];
let currentOTMaterials = [];
let allToolsList = [];
let allWarehouseList = [];

// Open OT Sub-tab
window.openOTSubTab = function (evt, tabId) {
    // Hide all tab content
    document.querySelectorAll('.ot-tab-content').forEach(tab => {
        tab.style.display = 'none';
    });

    // Remove active class from all buttons
    document.querySelectorAll('.ot-subtab').forEach(btn => {
        btn.style.background = '#333';
        btn.style.color = '#aaa';
    });

    // Show selected tab
    document.getElementById(tabId).style.display = 'block';

    // Activate clicked button
    evt.target.style.background = '#03dac6';
    evt.target.style.color = '#000';
}

// Load OT Personnel
async function loadOTPersonnel(otId) {
    if (!otId) {
        currentOTPersonnel = [];
        renderPersonnelTable();
        return;
    }

    try {
        const res = await fetch(`/api/work_orders/${otId}/personnel`);
        currentOTPersonnel = await res.json();
        renderPersonnelTable();
    } catch (e) { console.error(e); }
}

// Render Personnel Table
function renderPersonnelTable() {
    const tbody = document.getElementById('personnelTableBody');
    const emptyMsg = document.getElementById('personnelEmpty');

    if (!tbody) return;

    tbody.innerHTML = '';

    if (currentOTPersonnel.length === 0) {
        emptyMsg.style.display = 'block';
        return;
    }

    emptyMsg.style.display = 'none';

    currentOTPersonnel.forEach(p => {
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td>${p.technician_name || 'Sin asignar'}</td>
            <td>${p.specialty || '-'}</td>
            <td>${p.hours_assigned || 0} hrs</td>
            <td>
                <button type="button" onclick="removePersonnel(${p.id})" style="padding: 3px 8px; background: #f44336; border: none; color: white; border-radius: 3px;">
                    <i class="fas fa-trash"></i>
                </button>
            </td>
        `;
        tbody.appendChild(tr);
    });
}

// Open Add Personnel Modal (click-based selection)
window.openAddPersonnelModal = function () {
    const otId = document.getElementById('otId').value;
    if (!otId) {
        alert('Guarde la OT primero antes de agregar personal');
        return;
    }

    // Filter active technicians
    const techSelect = allTechnicians.filter(t => t.is_active);
    if (techSelect.length === 0) {
        alert('No hay técnicos disponibles. Agregue técnicos primero.');
        return;
    }

    // Populate technician dropdown
    const select = document.getElementById('personnelTechSelect');
    select.innerHTML = techSelect.map(t =>
        `<option value="${t.id}" data-specialty="${t.specialty || 'GENERAL'}">${t.name} (${t.specialty || 'N/A'})</option>`
    ).join('');

    // Set default specialty from first technician
    const firstTech = techSelect[0];
    if (firstTech && firstTech.specialty) {
        document.getElementById('personnelSpecialty').value = firstTech.specialty;
    }

    // Reset hours
    document.getElementById('personnelHours').value = '8';

    // Open modal
    document.getElementById('addPersonnelModal').showModal();
}

// Update specialty when technician changes
document.addEventListener('DOMContentLoaded', () => {
    // ... existing listeners ...

    // Add Listener for Equipment Change to load Feedback
    // Note: Since we don't have a direct equipment select in OT modal (it comes from Notice usually), 
    // we need to handle when otEquipment or similar is set.
    // However, the OT modal currently only shows "Datos del Aviso". 
    // If we want to support direct OT creation without notice, we might need an equipment selector.
    // Assuming for now we check feedback when opening modal or when notice data loads.
});

// Explicit function to check feedback
async function checkFeedback(equipmentId) {
    const container = document.getElementById('feedbackContainer');
    const list = document.getElementById('feedbackList');

    if (!equipmentId) {
        container.style.display = 'none';
        return;
    }

    try {
        const res = await fetch(`/api/work-orders/feedback?equipment_id=${equipmentId}`);
        const data = await res.json();

        if (data.length > 0) {
            list.innerHTML = data.map(item => `
                <div style="border-bottom: 1px solid #666; padding: 5px 0; margin-bottom: 5px;">
                    <div style="font-weight: bold; color: #ffd700;">${item.date.split('T')[0]} - ${item.ot_code} (${item.maintenance_type})</div>
                    <div style="color: #eee;">"${item.comments}"</div>
                    <div style="font-size: 0.8em; color: #aaa;">Téc: ${item.tech_name}</div>
                </div>
            `).join('');
            container.style.display = 'block';
        } else {
            container.style.display = 'none';
        }
    } catch (e) {
        console.error("Error loading feedback", e);
        container.style.display = 'none';
    }
}

// ... existing code ...

// Open Add Material Modal
window.openAddMaterialModal = async function (type) {
    const otId = document.getElementById('otId').value;
    if (!otId) {
        alert('Guarde la OT primero antes de agregar materiales');
        return;
    }

    document.getElementById('materialType').value = type;
    currentMaterialType = type;
    document.getElementById('materialQuantity').value = 1;

    // Update Title
    const title = type === 'tool' ? 'Agregar Herramienta (Catálogo)' : 'Agregar Repuesto / Material';
    const icon = type === 'tool' ? 'wrench' : 'box';
    document.getElementById('addMaterialTitle').innerHTML = `<i class="fas fa-${icon}"></i> ${title}`;

    // Load Items
    await loadWarehouseItemsForSelect();

    document.getElementById('addMaterialModal').showModal();
}

async function loadWarehouseItemsForSelect() {
    const select = document.getElementById('materialItemSelect');
    select.innerHTML = '<option>Cargando...</option>';

    try {
        const res = await fetch('/api/warehouse');
        const items = await res.json();

        select.innerHTML = items.map(i => {
            const stock = (i.stock !== undefined) ? i.stock : 'N/A';
            return `<option value="${i.id}" data-stock="${stock}">${i.code} - ${i.name} (Stock: ${stock})</option>`;
        }).join('');
    } catch (e) {
        select.innerHTML = '<option>Error cargando items</option>';
        console.error(e);
    }
}

async function confirmAddMaterial() {
    const otId = document.getElementById('otId').value;
    const itemId = document.getElementById('materialItemSelect').value;
    const quantity = document.getElementById('materialQuantity').value;

    if (!itemId) {
        alert("Por favor seleccione un ítem.");
        return;
    }
    if (!quantity || parseInt(quantity) <= 0) {
        alert("Por favor ingrese una cantidad válida mayor a 0.");
        return;
    }

    try {
        const res = await fetch(`/api/work_orders/${otId}/materials`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                item_type: currentMaterialType, // 'warehouse' or 'tool'
                item_id: parseInt(itemId),
                quantity: parseInt(quantity)
            })
        });

        if (res.ok) {
            document.getElementById('addMaterialModal').close();
            loadOTMaterials(otId);
        } else {
            const err = await res.json();
            alert("Error: " + (err.error || "Error desconocido"));
        }
    } catch (e) { console.error(e); }
}

// Remove Material
window.removeMaterial = async function (id) {
    if (!confirm('¿Eliminar este material de la OT?')) return;

    const otId = document.getElementById('otId').value;
    try {
        await fetch(`/api/work_orders/${otId}/materials/${id}`, { method: 'DELETE' });
        loadOTMaterials(otId);
    } catch (e) { console.error(e); }
}

// ============= OT PERSONNEL MANAGEMENT =============
// Note: currentOTPersonnel is declared at line 883

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
        // Handle both new items (hours) and loaded items (hours_assigned)
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
    // Populate technician dropdown from allTechnicians
    const select = document.getElementById('personnelTechSelect');
    if (!select) return alert('Modal de personal no encontrado');

    select.innerHTML = '<option value="">- Seleccione Técnico -</option>';
    allTechnicians.forEach(tech => {
        const opt = document.createElement('option');
        opt.value = tech.id;
        opt.textContent = tech.name + (tech.specialty ? ` (${tech.specialty})` : '');
        opt.dataset.specialty = tech.specialty || 'GENERAL';
        select.appendChild(opt);
    });

    // Auto-select specialty when technician is selected
    select.onchange = function () {
        const selectedOpt = select.options[select.selectedIndex];
        if (selectedOpt && selectedOpt.dataset.specialty) {
            document.getElementById('personnelSpecialty').value = selectedOpt.dataset.specialty;
        }
    };

    // Reset hours
    document.getElementById('personnelHours').value = 8;

    // Open modal
    document.getElementById('addPersonnelModal').showModal();
}

window.confirmAddPersonnel = function () {
    const techSelect = document.getElementById('personnelTechSelect');
    const techId = techSelect.value;
    const techName = techSelect.options[techSelect.selectedIndex]?.text || '';

    if (!techId) {
        return alert('Seleccione un técnico');
    }

    const specialty = document.getElementById('personnelSpecialty').value;
    const hours = parseFloat(document.getElementById('personnelHours').value) || 8;

    // Check if already added
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

    // Save to backend if OT exists
    const otId = document.getElementById('otId').value;
    if (otId) {
        saveOTPersonnel(otId);
    }
}

window.removePersonnel = function (idx) {
    if (!confirm('¿Eliminar este personal de la OT?')) return;

    currentOTPersonnel.splice(idx, 1);
    renderPersonnelTable();

    const otId = document.getElementById('otId').value;
    if (otId) {
        saveOTPersonnel(otId);
    }
}

async function saveOTPersonnel(otId) {
    try {
        await fetch(`/api/work_orders/${otId}/personnel`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ personnel: currentOTPersonnel })
        });
    } catch (e) {
        console.error('Error saving personnel:', e);
    }
}

// ============= OT MATERIALS MANAGEMENT =============
// Note: currentOTMaterials is declared at line 884

async function loadOTMaterials(otId) {
    try {
        const res = await fetch(`/api/work_orders/${otId}/materials`);
        if (res.ok) {
            currentOTMaterials = await res.json();
        } else {
            currentOTMaterials = [];
        }
        renderMaterialsTable();
    } catch (e) {
        console.error('Error loading materials:', e);
        currentOTMaterials = [];
        renderMaterialsTable();
    }
}

function renderMaterialsTable() {
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

window.removeMaterial = async function (id) {
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

    if (typeof allTechnicians !== 'undefined') {
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
/* GLOBAL VARS FOR PURCHASING */
let allSparesList = [];

window.openPurchaseModal = function () {
    const otId = document.getElementById('otId').value;

    // Validar si la OT existe (tiene ID)
    if (!otId) {
        alert("⚠️ ATENCIÓN: Para solicitar una compra, primero debe GUARDAR la Orden de Trabajo.\n\nPor favor, guarde los cambios y vuelva a intentar.");
        return;
    }

    document.getElementById('reqOtId').value = otId;

    // Reset Form
    document.getElementById('reqType').value = "MATERIAL";
    toggleReqFields();
    clearSpareSelection();

    document.getElementById('purchaseModal').showModal();
    loadSparesForReq();
}

window.toggleReqFields = function () {
    const type = document.getElementById('reqType').value;
    document.getElementById('fieldMaterial').style.display = type === 'MATERIAL' ? 'block' : 'none';
    document.getElementById('fieldService').style.display = type === 'SERVICIO' ? 'block' : 'none';

    // Toggle requirements logic is handled by validation in submit
    // But we can reset search if switching
    if (type !== 'MATERIAL') {
        clearSpareSelection();
    }
}

async function loadSparesForReq(force = false) {
    // Only load if empty or force refresh needed.
    // For "TREMENDA LISTA", better to load once.
    if (!force && allSparesList.length > 0) return;

    // Visual feedback for refresh
    const searchInput = document.getElementById('reqSpareSearch');
    if (force && searchInput) {
        searchInput.placeholder = "🔄 Cargando catálogo...";
        searchInput.disabled = true;
    }

    try {
        const res = await fetch('/api/list-spare-parts');
        if (res.ok) {
            allSparesList = await res.json();
            console.log("Spares loaded:", allSparesList.length);
            if (force) alert("Catálogo actualizado: " + allSparesList.length + " items.");
        }
    } catch (e) {
        console.error("Error loading spares:", e);
        if (force) alert("Error al actualizar catálogo");
    } finally {
        if (force && searchInput) {
            searchInput.placeholder = "🔍 Escriba para buscar repuesto...";
            searchInput.disabled = false;
            searchInput.focus();
        }
    }
}

// FILTER FUNCTION (Triggered on keyup/focus)
window.filterSpares = function () {
    const input = document.getElementById('reqSpareSearch');
    const filter = input.value.toUpperCase();
    const listDiv = document.getElementById('reqSpareList');

    if (!filter && document.activeElement !== input) {
        listDiv.style.display = "none";
        return;
    }

    listDiv.innerHTML = "";
    listDiv.style.display = "block";

    // Filter logic
    const matches = allSparesList.filter(item => {
        const text = `${item.name} ${item.code || ''}`.toUpperCase();
        return text.includes(filter);
    });

    if (matches.length === 0) {
        listDiv.innerHTML = '<div style="padding:10px; color:#aaa;">No se encontraron resultados</div>';
        return;
    }

    // Render results
    // Limit to 20 to avoid lag if empty query
    const limit = filter ? 50 : 20;

    matches.slice(0, limit).forEach(item => {
        const div = document.createElement("div");
        div.style.padding = "8px";
        div.style.cursor = "pointer";
        div.style.borderBottom = "1px solid #333";
        div.style.color = "#eee";
        div.onmouseover = function () { this.style.backgroundColor = "#03dac6"; this.style.color = "black"; };
        div.onmouseout = function () { this.style.backgroundColor = "transparent"; this.style.color = "#eee"; };

        div.innerHTML = `
            <strong>${item.name}</strong> 
            <span style="font-size:0.8em; color:#aaa;">(${item.code || 'S/C'})</span>
            <span style="float:right; font-size:0.8em;">Stock: ${item.stock}</span>
        `;

        div.onclick = function () {
            selectSpare(item.id, item.name, item.code);
        };

        listDiv.appendChild(div);
    });
}

// SELECT ITEM
window.selectSpare = function (id, name, code) {
    document.getElementById('reqSpareId').value = id;
    document.getElementById('reqSpareSearch').value = ""; // Clear search or keep it? user usage. Clear is cleaner.
    document.getElementById('reqSpareList').style.display = "none";

    // Show Selection
    document.getElementById('reqSpareSearch').style.display = 'none'; // Hide input
    document.getElementById('selectedSpareDisplay').style.display = 'block';
    document.getElementById('selectedSpareName').textContent = `${name} [${code || 'S/C'}]`;
}

// CLEAR SELECTION
window.clearSpareSelection = function () {
    document.getElementById('reqSpareId').value = "";
    document.getElementById('selectedSpareDisplay').style.display = 'none';
    document.getElementById('reqSpareSearch').style.display = 'block';
    document.getElementById('reqSpareSearch').value = "";
    document.getElementById('reqSpareList').style.display = "none";
    document.getElementById('reqSpareSearch').focus();
}

// Close list if clicking outside
document.addEventListener('click', function (e) {
    const list = document.getElementById('reqSpareList');
    const input = document.getElementById('reqSpareSearch');
    if (!list.contains(e.target) && e.target !== input) {
        list.style.display = 'none';
    }
});


/* CART LOGIC */
let purchaseCart = [];

window.addToPurchaseCart = function () {
    const type = document.getElementById('reqType').value;
    const qty = parseFloat(document.getElementById('reqQty').value);

    if (!qty || qty <= 0) return alert("Cantidad inválida");

    let item = {
        item_type: type,
        quantity: qty
    };

    if (type === 'MATERIAL') {
        const spareId = document.getElementById('reqSpareId').value;
        // Text is in selectedSpareName span
        const spareText = document.getElementById('selectedSpareName').textContent;

        if (!spareId) return alert("Seleccione un repuesto");
        item.spare_part_id = spareId;
        item.detail = spareText; // For display
    } else {
        const desc = document.getElementById('reqDesc').value;
        if (!desc.trim()) return alert("Ingrese descripción del servicio");
        item.description = desc;
        item.detail = desc;
    }

    purchaseCart.push(item);
    renderPurchaseCart();

    // Reset fields for next entry
    document.getElementById('reqQty').value = 1;
    if (type === 'MATERIAL') {
        clearSpareSelection();
    } else {
        document.getElementById('reqDesc').value = '';
    }
}

window.renderPurchaseCart = function () {
    const tbody = document.getElementById('purchaseCartBody');
    const btn = document.getElementById('btnSubmitPurchase');

    if (purchaseCart.length === 0) {
        tbody.innerHTML = '<tr><td colspan="4" style="text-align:center; padding:10px; color:#666;">Lista vacía</td></tr>';
        if (btn) btn.disabled = true;
        return;
    }

    if (btn) btn.disabled = false;
    tbody.innerHTML = '';

    purchaseCart.forEach((item, idx) => {
        const tr = document.createElement('tr');
        tr.style.borderBottom = '1px solid #333';
        tr.innerHTML = `
            <td style="padding:5px;">${item.item_type === 'MATERIAL' ? '<span style="color:#03dac6">REP</span>' : '<span style="color:#ffb74d">SERV</span>'}</td>
            <td style="padding:5px;">${item.detail}</td>
            <td style="padding:5px;">${item.quantity}</td>
            <td style="padding:5px;">
                <button type="button" class="btn-danger" style="padding:2px 6px;" onclick="removeFromPurchaseCart(${idx})">
                    <i class="fas fa-trash"></i>
                </button>
            </td>
        `;
        tbody.appendChild(tr);
    });
}

window.removeFromPurchaseCart = function (idx) {
    purchaseCart.splice(idx, 1);
    renderPurchaseCart();
}

const pForm = document.getElementById('purchaseForm');
if (pForm) {
    pForm.onsubmit = async (e) => {
        e.preventDefault();

        if (purchaseCart.length === 0) return alert("La lista está vacía");

        const otId = document.getElementById('reqOtId').value;
        const btn = e.submitter;
        const originalText = btn.textContent;
        btn.textContent = "Procesando...";
        btn.disabled = true;

        let errors = 0;

        // Process sequentially to be safe, or parallel? Parallel is fine.
        for (const item of purchaseCart) {
            const payload = {
                work_order_id: otId,
                item_type: item.item_type,
                quantity: item.quantity,
                warehouse_item_id: item.spare_part_id, // ID from dropdown (now WarehouseItem)
                description: item.description
            };

            try {
                const res = await fetch('/api/purchase-requests', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                if (!res.ok) errors++;
            } catch (x) { errors++; }
        }

        btn.textContent = originalText;
        btn.disabled = false;

        if (errors === 0) {
            alert("Todas las solicitudes fueron enviadas correctamente.");
            purchaseCart = []; // Clear
            renderPurchaseCart();
            document.getElementById('purchaseModal').close();
        } else {
            alert(`Se procesaron las solicitudes pero ${errors} fallaron. Revise el historial.`);
            document.getElementById('purchaseModal').close(); // Close anyway?
        }
    };
}
