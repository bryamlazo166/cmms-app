
// State
let allWorkOrders = [];
let allProviders = [];
let allTechnicians = [];
let allPendingNotices = [];
let allAreas = [], allLines = [], allEquips = [], allSystems = [], allComponents = [];
let currentTab = 'tab-planning';
let _closePersonnelList = []; // personal en modal de cierre
let _currentUser = null;       // usuario logueado
let _myOTsMode = false;        // modo "Mis OTs"
let _myOTsIds = new Set();     // IDs de OTs del técnico logueado

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
    loadCurrentUser();
    loadUsersForTechLink();
    loadShutdownsForOT();

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

    // Toggle downtime hours field visibility
    const downtimeSelect = document.getElementById('closeCausedDowntime');
    if (downtimeSelect) {
        downtimeSelect.addEventListener('change', function() {
            document.getElementById('downtimeHoursGroup').style.display =
                this.value === '1' ? '' : 'none';
            checkDowntimeVsDuration();
        });
    }
    const dtHoursInput = document.getElementById('closeDowntimeHours');
    if (dtHoursInput) {
        dtHoursInput.addEventListener('input', checkDowntimeVsDuration);
    }
});

function checkDowntimeVsDuration() {
    const warn = document.getElementById('durationVsDowntimeWarning');
    const warnText = document.getElementById('durationVsDowntimeWarningText');
    if (!warn || !warnText) return;
    const caused = document.getElementById('closeCausedDowntime').value === '1';
    if (!caused) { warn.style.display = 'none'; return; }
    const start = document.getElementById('realStart').value;
    const end = document.getElementById('realEnd').value;
    const dt = parseFloat(document.getElementById('closeDowntimeHours').value);
    if (!start || !end || isNaN(dt)) { warn.style.display = 'none'; return; }
    const calHrs = (new Date(end) - new Date(start)) / 3600000;
    if (dt < calHrs - 0.1) {
        warnText.textContent = `Las horas de parada (${dt}h) son MENORES que el tiempo entre inicio y fin (${calHrs.toFixed(1)}h). Verifique: si el equipo estuvo parado todo ese tiempo, debe coincidir.`;
        warn.style.display = 'block';
    } else {
        warn.style.display = 'none';
    }
}

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
    const areas = [...new Set(allWorkOrders.map(ot => ot.area_name || '(Sin Area)').filter(x => x))].sort();
    const lines = [...new Set(allWorkOrders.map(ot => ot.line_name || '(Sin Linea)').filter(x => x))].sort();
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

let allShutdowns = [];
async function loadShutdownsForOT() {
    try {
        const res = await fetch('/api/shutdowns');
        allShutdowns = await res.json();
        const sel = document.getElementById('otShutdown');
        if (!sel) return;
        const active = allShutdowns.filter(s => s.status !== 'COMPLETADA' && s.status !== 'CANCELADA');
        sel.innerHTML = '<option value="">- Sin parada -</option>' +
            active.map(s => `<option value="${s.id}">${s.name} (${s.shutdown_date || '-'}) — ${s.status}</option>`).join('');
    } catch (e) { console.error('loadShutdowns OT:', e); }
}

async function loadCurrentUser() {
    try {
        const res = await fetch('/api/auth/me');
        if (!res.ok) return;
        _currentUser = await res.json();
        // Cargar IDs de mis OTs
        const mineRes = await fetch('/api/work-orders/mine');
        if (mineRes.ok) {
            const data = await mineRes.json();
            _myOTsIds = new Set((data.ot_ids || []).map(String));
            const badge = document.getElementById('myOTsCount');
            if (badge && _myOTsIds.size > 0) {
                badge.textContent = _myOTsIds.size;
                badge.style.display = 'inline';
            }
        }
        // Auto-activar 'Mis OTs' para tecnicos: solo ven sus OTs por defecto
        if (_currentUser && (_currentUser.role || '').toLowerCase() === 'tecnico') {
            _myOTsMode = true;
            const btn = document.getElementById('btnMisOTs');
            if (btn) {
                btn.style.background = 'rgba(10,132,255,0.35)';
                btn.style.borderColor = '#0A84FF';
            }
        }
    } catch (e) { console.error('loadCurrentUser:', e); }
}

function toggleMyOTs() {
    _myOTsMode = !_myOTsMode;
    const btn = document.getElementById('btnMisOTs');
    if (btn) {
        btn.style.background = _myOTsMode ? 'rgba(10,132,255,0.35)' : 'rgba(10,132,255,0.12)';
        btn.style.borderColor = _myOTsMode ? '#0A84FF' : '#0A84FF';
    }
    applyFilters();
}

async function createOrOpenDailyRound() {
    try {
        // Ver si ya existe
        const chk = await fetch('/api/work-orders/daily-round');
        const data = await chk.json();
        if (data.id) {
            // Ya existe — abrir en ejecución
            await loadWorkOrders();
            openOTInExecution(data.id);
            return;
        }
        // Crear nueva
        const res = await fetch('/api/work-orders/daily-round', { method: 'POST' });
        if (!res.ok) { alert('Error al crear Ronda del Día'); return; }
        const wo = await res.json();
        await loadWorkOrders();
        openOTInExecution(wo.id);
    } catch (e) { console.error('daily-round:', e); alert('Error al abrir Ronda del Día'); }
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
    if (crit === 'Media') return '#FF9F0A'; // Orange
    if (crit === 'Baja') return '#4caf50'; // Green
    return '#777';
}

window.applyFilters = () => {
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
    const searchInput = document.getElementById('searchPlanning');
    const search = searchInput ? searchInput.value.toLowerCase().trim() : '';
    const logisticsSelect = document.getElementById('planningLogisticsFilter');
    const logisticsFilter = logisticsSelect ? logisticsSelect.value : 'all';
    const reportSelect = document.getElementById('planningReportFilter');
    const reportFilter = reportSelect ? reportSelect.value : 'all';
    const shutdownSelect = document.getElementById('planningShutdownFilter');
    const shutdownFilter = shutdownSelect ? shutdownSelect.value : 'all';

    const filtered = allWorkOrders.filter(ot => {
        // Filtro "Mis OTs"
        if (_myOTsMode && !_myOTsIds.has(String(ot.id))) return false;

        const otArea = ot.area_name || '(Sin Area)';
        const otLine = ot.line_name || '(Sin Linea)';
        const otEquip = ot.equipment_name || '(Sin Equipo)';
        const otStatus = ot.status || '';

        if (selectedAreas.length > 0 && !selectedAreas.includes(otArea)) return false;
        if (selectedLines.length > 0 && !selectedLines.includes(otLine)) return false;
        if (selectedEquips.length > 0 && !selectedEquips.includes(otEquip)) return false;
        if (selectedStatuses.length > 0 && !selectedStatuses.includes(otStatus)) return false;

        const pendingReq = Number(ot.purchase_requests_pending || 0);
        const totalReq = Number(ot.purchase_requests_total || 0);
        const hasBlock = !!ot.has_logistics_block || pendingReq > 0;
        const hasRequest = totalReq > 0 || pendingReq > 0 || !!ot.purchase_tracking;

        if (logisticsFilter === 'blocked' && !hasBlock) return false;
        if (logisticsFilter === 'released' && (hasBlock || !hasRequest)) return false;
        if (logisticsFilter === 'none' && hasRequest) return false;

        if (reportFilter === 'pending' && !(ot.report_required && ot.report_status !== 'RECIBIDO')) return false;
        if (reportFilter === 'received' && !(ot.report_required && ot.report_status === 'RECIBIDO')) return false;

        const hasShutdown = !!ot.shutdown_id;
        if (shutdownFilter === 'with' && !hasShutdown) return false;
        if (shutdownFilter === 'without' && hasShutdown) return false;

        if (search) {
            const code = (ot.code || '').toLowerCase();
            const desc = (ot.description || '').toLowerCase();
            const equip = (ot.equipment_name || '').toLowerCase();
            const area = (ot.area_name || '').toLowerCase();
            const line = (ot.line_name || '').toLowerCase();
            const providerMatch = allProviders.find(p => String(p.id) === String(ot.provider_id));
            const provider = ((providerMatch && providerMatch.name) || ot.provider_name || '').toLowerCase();
            const techMatch = allTechnicians.find(t => String(t.id) === String(ot.technician_id));
            const tech = ((techMatch && techMatch.name) || ot.technician_name || String(ot.technician_id || '')).toLowerCase();

            if (!code.includes(search) &&
                !desc.includes(search) &&
                !equip.includes(search) &&
                !area.includes(search) &&
                !line.includes(search) &&
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
    const list = data || allWorkOrders;
    const tbody = document.querySelector('#planningTable tbody');

    if (!tbody) return;

    if (list.length === 0) {
        tbody.innerHTML = '<tr><td colspan="18" style="text-align:center; padding:20px; color:#9fb6d6;">No se encontraron ordenes de trabajo.</td></tr>';
        return;
    }

    const sortedList = [...list].sort((a, b) => {
        const na = parseInt(String(a.code || '').replace(/\D/g, ''), 10) || Number(a.id || 0);
        const nb = parseInt(String(b.code || '').replace(/\D/g, ''), 10) || Number(b.id || 0);
        return nb - na;
    });

    tbody.innerHTML = sortedList.map(ot => {
        let statusClass = 'status-open';
        if (ot.status === 'En Progreso') statusClass = 'status-progress';
        if (ot.status === 'Cerrada') statusClass = 'status-closed';
        if (ot.status === 'No Ejecutada') statusClass = 'status-cancelled';

        let priorityClass = 'priority-medium';
        if (ot.priority === 'Alta' || ot.priority === 'Emergencia') priorityClass = 'priority-high';
        if (ot.priority === 'Baja') priorityClass = 'priority-low';

        const techMatch = allTechnicians.find(t => String(t.id) === String(ot.technician_id));
        const providerMatch = allProviders.find(p => String(p.id) === String(ot.provider_id));
        const assignedTo = (techMatch && techMatch.name)
            || ot.technician_name
            || (providerMatch && providerMatch.name)
            || ot.provider_name
            || ot.technician_id
            || ot.provider_id
            || '-';

        const logisticsClass = ot.has_logistics_block || Number(ot.purchase_requests_pending || 0) > 0
            ? 'logistics-blocked'
            : 'logistics-released';
        const logisticsLabel = ot.has_logistics_block || Number(ot.purchase_requests_pending || 0) > 0
            ? `Bloqueada (${ot.purchase_requests_pending || 0})`
            : (Number(ot.purchase_requests_total || 0) > 0 ? 'Liberada' : 'Sin Solicitud');
        const logisticsTrack = ot.purchase_tracking || '-';

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
            <td title="${ot.description || ''}">${ot.description || ''}</td>
            <td>${ot.maintenance_type || '-'}${ot.source_type ? ' <span style="font-size:.7rem;color:#30D158" title="' + ot.source_type + '">[PM]</span>' : ''}</td>
            <td><span class="badge ${statusClass}">${ot.status || '-'}</span></td>
            <td><span class="badge ${priorityClass}">${ot.priority || '-'}</span></td>
            <td>${ot.scheduled_date || '-'}</td>
            <td>${ot.real_end_date || '-'}</td>
            <td>${ot.shutdown_name ? `<a href="/paradas#${ot.shutdown_id}" style="color:#FF9F0A;text-decoration:underline;font-size:.78rem;" title="${ot.shutdown_name}">${ot.shutdown_name.substring(0, 22)}${ot.shutdown_name.length > 22 ? '…' : ''}</a>` : '<span style="color:rgba(255,255,255,.2);font-size:.78rem">-</span>'}</td>
            <td>${assignedTo}</td>
            <td>
                <span class="logistics-chip ${logisticsClass}">${logisticsLabel}</span>
                <span class="logistics-track" title="${logisticsTrack}">${logisticsTrack}</span>
            </td>
            <td>${ot.report_required ? (ot.report_status === 'RECIBIDO'
                ? '<span style="color:#30D158;font-size:.78rem"><i class="fas fa-check-circle"></i> Recibido</span>'
                : '<span style="color:#FF453A;font-size:.78rem"><i class="fas fa-clock"></i> Pendiente</span>')
                : '<span style="color:rgba(255,255,255,.20);font-size:.78rem">-</span>'}</td>
            <td>
                <div style="display:flex; align-items:center; gap:6px;">
                    <button class="btn-icon planning-action-btn" onclick="editOT(${ot.id})" title="Editar OT"><i class="fas fa-edit"></i></button>
                    <button class="btn-icon planning-action-btn" onclick="openOTInExecution(${ot.id})" title="Ir a Ejecucion y Cierre" style="border-color:#2d6a3d; background:#173528; color:#b8ffd0;"><i class="fas fa-play"></i></button>
                    <button class="btn-icon planning-action-btn" onclick="quickShareOT(${ot.id})" title="Compartir por WhatsApp" style="border-color:#25D366; background:rgba(37,211,102,.12); color:#25D366;"><i class="fab fa-whatsapp"></i></button>
                </div>
            </td>
        </tr>
    `;
    }).join('');
}

async function openOTInExecution(id) {
    const tabLinks = Array.from(document.getElementsByClassName('tab-link'));
    const execBtn = tabLinks.find(btn => (btn.getAttribute('onclick') || '').includes("tab-execution"));
    if (execBtn) openTab({ currentTarget: execBtn }, 'tab-execution');

    const selectedOT = allWorkOrders.find(o => Number(o.id) === Number(id));
    const searchInput = document.getElementById('executionSearch');
    if (searchInput) searchInput.value = selectedOT && selectedOT.code ? selectedOT.code : String(id);

    await searchForExecution();
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

async function loadRotativeAssets(equipmentId, selectedId) {
    const sel = document.getElementById('otRotativeAsset');
    sel.innerHTML = '<option value="">- Sin activo rotativo -</option>';
    if (!equipmentId) return;
    try {
        const assets = await fetch(`/api/rotative-assets?equipment_id=${equipmentId}`).then(r => r.json());
        const installed = Array.isArray(assets) ? assets.filter(a => a.status === 'Instalado') : [];
        installed.forEach(a => {
            const opt = document.createElement('option');
            opt.value = a.id;
            opt.textContent = `${a.code} ${a.name} (${a.category || '-'})`;
            sel.appendChild(opt);
        });
        if (selectedId) sel.value = selectedId;
    } catch (_) {}
}

function openCreateOTModal() {
    document.getElementById('otForm').reset();
    document.getElementById('otId').value = '';
    document.getElementById('otRotativeAsset').innerHTML = '<option value="">- Sin activo rotativo -</option>';

    // Reset sub-tabs to General
    document.querySelectorAll('.ot-tab-content').forEach(t => t.style.display = 'none');
    document.getElementById('ot-tab-general').style.display = 'block';
    document.querySelectorAll('.ot-subtab').forEach((btn, i) => {
        btn.style.background = i === 0 ? '#0A84FF' : '#333';
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

    // Preseleccionar parada vinculada (si existe)
    const otShutdown = document.getElementById('otShutdown');
    if (otShutdown) otShutdown.value = ot.shutdown_id || '';

    // Load rotative assets for this equipment
    if (ot.equipment_id) {
        await loadRotativeAssets(ot.equipment_id, ot.rotative_asset_id);
    }

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
        btn.style.background = i === 0 ? '#0A84FF' : '#333';
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
            const msg = `âœ¨ Historial Encontrado (OT: ${data.last_ot_code})\n\n` +
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


let _savingOT = false;
async function handleOTSubmit(e) {
    e.preventDefault();
    if (_savingOT) return;
    _savingOT = true;
    const btn = e.submitter || e.target.querySelector('button[type="submit"]');
    const origBtn = btn ? btn.innerHTML : '';
    if (btn) { btn.disabled = true; btn.innerHTML = '<i class="fas fa-circle-notch fa-spin"></i> Guardando...'; }
    try {
        const id = document.getElementById('otId').value;
        const noticeId = document.getElementById('otNoticeId').value;

        const raVal = document.getElementById('otRotativeAsset').value;
        const data = {
            description: document.getElementById('otDescription').value,
            maintenance_type: document.getElementById('otType').value,
            priority: document.getElementById('otPriority').value,
            scheduled_date: document.getElementById('otScheduledDate').value,
            technician_id: document.getElementById('otTechnician').value,
            provider_id: document.getElementById('otProvider').value ? parseInt(document.getElementById('otProvider').value) : null,
            estimated_duration: document.getElementById('otEstDuration').value,
            status: document.getElementById('otStatus').value,
            failure_mode: document.getElementById('otFailureMode').value,
            rotative_asset_id: raVal ? parseInt(raVal) : null,
            shutdown_id: (() => {
                const v = document.getElementById('otShutdown') ? document.getElementById('otShutdown').value : '';
                return v ? parseInt(v) : null;
            })(),
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
    } finally {
        _savingOT = false;
        if (btn) { btn.disabled = false; btn.innerHTML = origBtn; }
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
        btn.style.background = '#0A84FF'; // Unified primary color
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
        else if (ot.status === 'En Progreso') color = '#0A84FF'; // Teal
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
    ['Abierta', 'Programada', 'En Progreso', 'Cerrada', 'No Ejecutada'].forEach(status => {
        const colId = status === 'En Progreso' ? 'col-En Progreso' : `col-${status}`;
        const container = document.getElementById(colId);
        if (container) container.innerHTML = '';

        const countId = status === 'En Progreso' ? 'count-En_Progreso' : `count-${status.replace(' ', '_')}`;
        const badge = document.getElementById(countId);
        if (badge) badge.innerText = 0;
    });

    // Distribute OTs
    const counts = { 'Abierta': 0, 'Programada': 0, 'En Progreso': 0, 'Cerrada': 0, 'No Ejecutada': 0 };

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

    const ot = allWorkOrders.find(o => (o.code && o.code === val) || (String(o.id) === val));
    const panel = document.getElementById('execution-details');

    if (!ot) {
        alert("Orden de Trabajo no encontrada");
        panel.classList.add('hidden');
        return;
    }

    activeExecutionOT = ot;
    panel.classList.remove('hidden');

    document.getElementById('exec-ot-code').innerText = ot.code || `OT-${ot.id}`;
    document.getElementById('exec-desc').innerText = ot.description || 'Sin descripcion';

    const badge = document.getElementById('exec-status');
    badge.innerText = ot.status;
    badge.className = 'status-badge ' + (ot.status === 'En Progreso' ? 'status-progress' : ot.status === 'Cerrada' ? 'status-closed' : 'status-open');

    document.getElementById('exec-type').innerText = ot.maintenance_type || '-';
    document.getElementById('exec-priority').innerText = ot.priority || '-';
    document.getElementById('exec-scheduled').innerText = ot.scheduled_date || '-';
    document.getElementById('exec-duration').innerText = ot.estimated_duration ? `${ot.estimated_duration} hrs` : '-';

    const tech = allTechnicians.find(t => t.id === parseInt(ot.technician_id));
    document.getElementById('exec-technician').innerText = tech ? tech.name : (ot.technician_id || '-');

    const provider = allProviders.find(p => p.id === parseInt(ot.provider_id));
    document.getElementById('exec-provider').innerText = provider ? provider.name : '-';

    populateExecutionOperationalInfo(ot);
    loadExecutionSafetyState(ot.id);
    bindExecutionSafetyState(ot.id);

    let materials = [];
    let parts = [];

    try {
        const materialsRes = await fetch(`/api/work_orders/${ot.id}/materials`);
        materials = await materialsRes.json();

        const tools = materials.filter(m => m.item_type === 'tool');
        parts = materials.filter(m => m.item_type !== 'tool');

        const toolsContainer = document.getElementById('exec-tools-list');
        if (tools.length === 0) {
            toolsContainer.innerHTML = '<p style="color: #888; font-style: italic;">No hay herramientas asignadas</p>';
        } else {
            toolsContainer.innerHTML = `
                <table style="width: 100%; border-collapse: collapse;">
                    <thead>
                        <tr style="border-bottom: 1px solid #444;">
                            <th style="text-align: left; padding: 5px; color: #aaa;">Codigo</th>
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

        const partsContainer = document.getElementById('exec-parts-list');
        if (parts.length === 0) {
            partsContainer.innerHTML = '<p style="color: #888; font-style: italic;">No hay repuestos asignados</p>';
        } else {
            partsContainer.innerHTML = `
                <table style="width: 100%; border-collapse: collapse;">
                    <thead>
                        <tr style="border-bottom: 1px solid #444;">
                            <th style="text-align: left; padding: 5px; color: #aaa;">Codigo</th>
                            <th style="text-align: left; padding: 5px; color: #aaa;">Nombre</th>
                            <th style="text-align: center; padding: 5px; color: #aaa;">Req</th>
                            <th style="text-align: center; padding: 5px; color: #aaa;">Disponible</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${parts.map(m => {
                            const avail = (m.item_stock === null || m.item_stock === undefined) ? '-' : Number(m.item_stock);
                            const blocked = (avail !== '-' && avail < Number(m.quantity || 0));
                            return `
                            <tr style="border-bottom: 1px solid #333;">
                                <td style="padding: 8px;"><strong style="color: #4caf50;">${m.item_code || '-'}</strong></td>
                                <td style="padding: 8px;">${m.item_name || 'Desconocido'}</td>
                                <td style="text-align: center; padding: 8px;">${m.quantity || 0}</td>
                                <td style="text-align: center; padding: 8px; color:${blocked ? '#ff8a80' : '#a5d6a7'};">${avail}</td>
                            </tr>`;
                        }).join('')}
                    </tbody>
                </table>
            `;
        }
    } catch (e) {
        console.error('Error loading materials:', e);
        document.getElementById('exec-tools-list').innerHTML = '<p style="color: #f44336;">Error cargando herramientas</p>';
        document.getElementById('exec-parts-list').innerHTML = '<p style="color: #f44336;">Error cargando repuestos</p>';
    }

    let personnel = [];
    try {
        const pRes = await fetch(`/api/work_orders/${ot.id}/personnel`);
        personnel = pRes.ok ? await pRes.json() : [];
        renderExecutionPersonnel(personnel);
    } catch (e) {
        console.error('Error loading personnel:', e);
        const c = document.getElementById('exec-personnel-list');
        if (c) c.innerHTML = '<span style="color:#ff8a80;">Error cargando personal</span>';
    }

    let reqs = [];
    try {
        const prRes = await fetch('/api/purchase-requests?all=true');
        const allReq = prRes.ok ? await prRes.json() : [];
        reqs = allReq.filter(r => Number(r.work_order_id) === Number(ot.id));
        renderExecutionPurchaseRequests(reqs);
    } catch (e) {
        console.error('Error loading purchase requests:', e);
        const c = document.getElementById('exec-purchase-requests-list');
        if (c) c.innerHTML = '<span style="color:#ff8a80;">Error cargando requerimientos de compra</span>';
    }

    refreshExecutionLogisticsAlert(parts, reqs);

    const btnStart = document.getElementById('btn-start-job');
    const btnPause = document.getElementById('btn-pause-job');
    const btnEnd = document.getElementById('btn-finish-job');
    btnStart.classList.add('hidden');
    if (btnPause) btnPause.classList.add('hidden');
    btnEnd.classList.add('hidden');

    if (ot.status === 'Abierta' || ot.status === 'Programada') {
        btnStart.classList.remove('hidden');
    } else if (ot.status === 'En Progreso') {
        if (btnPause) btnPause.classList.remove('hidden');
        btnEnd.classList.remove('hidden');
    }

    // Load bitacora + report status + photos
    loadOTLog(ot.id);
    loadReportStatus(ot);
    loadOTPhotos(ot.id);
    loadNoticePhotosInExecution(ot.notice_id);
    document.getElementById('logDate').value = new Date().toISOString().slice(0, 10);
}

function populateExecutionOperationalInfo(ot) {
    const noticeText = ot.notice_id ? `AV-${String(ot.notice_id).padStart(4, '0')}` : '-';
    const area = ot.area_name || '-';
    const line = ot.line_name || '-';
    const equipment = ot.equipment_name || '-';
    const system = ot.system_name || '-';
    const component = ot.component_name || '-';
    const tag = ot.equipment_tag || ot.tag || equipment;
    const shift = ot.shift || '-';

    const setText = (id, value) => {
        const el = document.getElementById(id);
        if (el) el.innerText = value || '-';
    };

    setText('exec-notice', noticeText);
    setText('exec-criticality', ot.criticality || '-');
    setText('exec-area', area);
    setText('exec-line', line);
    setText('exec-equipment', equipment);
    setText('exec-system', system);
    setText('exec-component', component);
    setText('exec-tag', tag);
    setText('exec-shift', shift);
}

function renderExecutionPersonnel(personnel) {
    const container = document.getElementById('exec-personnel-list');
    if (!container) return;

    if (!Array.isArray(personnel) || personnel.length === 0) {
        container.innerHTML = '<em style="color:#aaa;">No hay personal asignado</em>';
        return;
    }

    container.innerHTML = personnel.map(p => {
        const name = p.technician_name || p.technician_id || 'Tecnico';
        const spec = p.specialty || 'GENERAL';
        const hPlan = p.hours_assigned || 0;
        const hReal = p.hours_worked;
        const hoursLabel = hReal != null
            ? `${hReal}h reales / ${hPlan}h plan`
            : `${hPlan}h plan`;
        const color = hReal != null && hReal > hPlan ? '#ff9f0a' : '#d9ecff';
        return `<span style="display:inline-block; margin:3px 6px 3px 0; padding:4px 8px; border-radius:999px; background:#1f3551; color:${color}; border:1px solid #365d85;">${name} | ${spec} | ${hoursLabel}</span>`;
    }).join('');
}

function getPurchaseRequestCode(r) {
    return r.req_code || r.code || `REQ-${r.id}`;
}

function getPurchaseRequestItemLabel(r) {
    const itemType = String(r.item_type || '').toUpperCase();
    const materialName = r.warehouse_item_name || r.spare_part_name || r.item_name || '';
    const serviceName = r.description || '';

    if (itemType === 'SERVICIO') {
        return serviceName || 'Servicio';
    }

    if (materialName) return materialName;
    if (serviceName) return serviceName;
    if (r.warehouse_item_id) return `Material ${r.warehouse_item_id}`;
    if (r.spare_part_id) return `Repuesto ${r.spare_part_id}`;
    return 'Item';
}

function renderExecutionPurchaseRequests(reqs) {
    const container = document.getElementById('exec-purchase-requests-list');
    if (!container) return;

    if (!Array.isArray(reqs) || reqs.length === 0) {
        container.innerHTML = '<em style="color:#aaa;">No hay requerimientos registrados</em>';
        return;
    }

    container.innerHTML = reqs.map(r => {
        const code = getPurchaseRequestCode(r);
        const status = r.status || 'Pendiente';
        const qty = Number(r.quantity || 0);
        const itemLabel = getPurchaseRequestItemLabel(r);
        const color = /cerrad|atendid|recibid/i.test(status) ? '#7ee08a' : '#ffb3ad';
        return `<div style="padding:6px 8px; border-bottom:1px solid #2c3f54;"><strong style="color:#6fb3ff;">${code}</strong> - ${itemLabel} (x${qty}) <span style="color:${color};">${status}</span></div>`;
    }).join('');
}

function refreshExecutionLogisticsAlert(parts, reqs) {
    const alertBox = document.getElementById('exec-logistics-alert');
    if (!alertBox) return;

    const blockedParts = (parts || []).filter(m => {
        const avail = (m.item_stock === null || m.item_stock === undefined) ? null : Number(m.item_stock);
        return avail !== null && !Number.isNaN(avail) && avail < Number(m.quantity || 0);
    });

    const pendingReqs = (reqs || []).filter(r => !/cerrad|atendid|recibid/i.test(String(r.status || '')));

    if (blockedParts.length === 0 && pendingReqs.length === 0) {
        alertBox.style.background = '#163b23';
        alertBox.style.color = '#9fe8a7';
        alertBox.style.border = '1px solid #2d6a3d';
        alertBox.innerText = 'Sin bloqueos detectados por recursos.';
        return;
    }

    const partText = blockedParts.map(m => `${m.item_code || 'REP'}: req ${m.quantity}, disp ${m.item_stock}`).join(' | ');
    const reqText = pendingReqs.map(r => getPurchaseRequestCode(r)).join(', ');

    alertBox.style.background = '#4a1717';
    alertBox.style.color = '#ffb3ad';
    alertBox.style.border = '1px solid #7a2525';

    if (blockedParts.length > 0 && pendingReqs.length > 0) {
        alertBox.innerText = `Bloqueo por recursos: Repuestos (${partText}) y compras pendientes (${reqText})`;
    } else if (blockedParts.length > 0) {
        alertBox.innerText = `Bloqueo por recursos: Repuestos ${partText}`;
    } else {
        alertBox.innerText = `Bloqueo por recursos: Compras pendientes ${reqText}`;
    }
}

function loadExecutionSafetyState(otId) {
    const raw = localStorage.getItem(`cmms.exec.safety.${otId}`);
    const data = raw ? JSON.parse(raw) : {};

    const setChecked = (id, value) => {
        const el = document.getElementById(id);
        if (el) el.checked = !!value;
    };

    setChecked('exec-loto', data.loto);
    setChecked('exec-hot-work', data.hot_work);
    setChecked('exec-confined-space', data.confined_space);
    setChecked('exec-epp-helmet', data.epp_helmet);
    setChecked('exec-epp-glasses', data.epp_glasses);
    setChecked('exec-epp-gloves', data.epp_gloves);
    setChecked('exec-epp-respirator', data.epp_respirator);
    setChecked('exec-epp-hearing', data.epp_hearing);

    const permit = document.getElementById('exec-permit');
    if (permit) permit.value = data.permit || '';
}

function bindExecutionSafetyState(otId) {
    const ids = [
        'exec-loto', 'exec-hot-work', 'exec-confined-space',
        'exec-epp-helmet', 'exec-epp-glasses', 'exec-epp-gloves',
        'exec-epp-respirator', 'exec-epp-hearing', 'exec-permit'
    ];

    const save = () => {
        const getChecked = (id) => {
            const el = document.getElementById(id);
            return !!(el && el.checked);
        };
        const permitEl = document.getElementById('exec-permit');

        const payload = {
            loto: getChecked('exec-loto'),
            hot_work: getChecked('exec-hot-work'),
            confined_space: getChecked('exec-confined-space'),
            epp_helmet: getChecked('exec-epp-helmet'),
            epp_glasses: getChecked('exec-epp-glasses'),
            epp_gloves: getChecked('exec-epp-gloves'),
            epp_respirator: getChecked('exec-epp-respirator'),
            epp_hearing: getChecked('exec-epp-hearing'),
            permit: permitEl ? permitEl.value : ''
        };

        localStorage.setItem(`cmms.exec.safety.${otId}`, JSON.stringify(payload));
    };

    ids.forEach(id => {
        const el = document.getElementById(id);
        if (!el) return;
        el.onchange = save;
        el.oninput = save;
    });
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

function openPauseModal() {
    if (!activeExecutionOT) return;
    document.getElementById('pauseOtId').value = activeExecutionOT.id;
    document.getElementById('pauseAvance').value = '';
    document.getElementById('pausePendiente').value = '';
    document.getElementById('pauseOTModal').showModal();
}

async function handlePauseSubmit() {
    const id = document.getElementById('pauseOtId').value;
    const avance = document.getElementById('pauseAvance').value.trim();
    const pendiente = document.getElementById('pausePendiente').value.trim();
    if (!avance) {
        alert('Debe describir el avance realizado.');
        return;
    }
    let comment = `[PAUSA] ${avance}`;
    if (pendiente) comment += `\nPendiente: ${pendiente}`;
    const today = new Date().toISOString().split('T')[0];
    try {
        const res = await fetch(`/api/work_orders/${id}/log`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ log_date: today, log_type: 'AVANCE', comment })
        });
        if (!res.ok) {
            alert('Error al registrar la pausa');
            return;
        }
        document.getElementById('pauseOTModal').close();
        await loadOTLog(id);
        alert('✅ Pausa registrada. La OT permanece En Progreso para continuar en el siguiente turno.');
    } catch (e) {
        console.error('pause:', e);
        alert('Error al registrar la pausa');
    }
}
window.openPauseModal = openPauseModal;
window.handlePauseSubmit = handlePauseSubmit;

function openCloseModal() {
    if (!activeExecutionOT) return;
    document.getElementById('closeOtId').value = activeExecutionOT.id;

    const now = getLocalISOString();
    const start = activeExecutionOT.real_start_date || now;

    const startInput = document.getElementById('realStart');
    const endInput = document.getElementById('realEnd');
    startInput.value = start;
    endInput.value = now;

    // Ambos campos editables: el valor se prellena con lo que tiene el sistema,
    // pero el tecnico/supervisor puede ajustar si la hora real no coincide
    // (ej: olvido cerrar la OT y la cierra al dia siguiente).
    startInput.readOnly = false;
    startInput.style.backgroundColor = "";
    endInput.readOnly = false;
    endInput.style.backgroundColor = "";

    // Pre-llenar horas de parada con la duración calendario como sugerencia
    try {
        const dt0 = new Date(start);
        const dt1 = new Date(now);
        const calHrs = Math.max(0, (dt1 - dt0) / 3600000);
        const dtInput = document.getElementById('closeDowntimeHours');
        if (dtInput) dtInput.value = calHrs.toFixed(2);
    } catch (e) { /* ignore */ }
    // Reset warning
    const warn = document.getElementById('durationVsDowntimeWarning');
    if (warn) warn.style.display = 'none';

    // Cargar personal planificado en la lista de cierre
    _closePersonnelList = (currentOTPersonnel || []).map(p => ({
        id: p.id,
        technician_id: p.technician_id,
        technician_name: p.technician_name || 'Sin nombre',
        specialty: p.specialty || '',
        hours_assigned: p.hours_assigned || 0,
        hours_worked: p.hours_worked != null ? p.hours_worked : (p.hours_assigned || 0),
        is_extra: false
    }));
    renderClosePersonnelTable();

    document.getElementById('closeOTModal').showModal();
}

function renderClosePersonnelTable() {
    const tbody = document.getElementById('closePersonnelBody');
    const empty = document.getElementById('closePersonnelEmpty');
    if (!tbody) return;
    tbody.innerHTML = '';
    if (_closePersonnelList.length === 0) {
        if (empty) empty.style.display = 'block';
        return;
    }
    if (empty) empty.style.display = 'none';
    const inputStyle = 'width:60px;background:rgba(255,255,255,.08);border:1px solid rgba(48,209,88,0.5);color:#fff;border-radius:4px;padding:2px 4px;text-align:center;';
    const selStyle = 'background:rgba(255,255,255,.08);border:1px solid rgba(255,255,255,.15);color:#fff;border-radius:4px;padding:2px 4px;width:100%;font-size:0.85em;';
    _closePersonnelList.forEach((p, idx) => {
        const tr = document.createElement('tr');
        tr.style.borderBottom = '1px solid rgba(255,255,255,0.05)';
        if (p.is_extra) {
            const opts = allTechnicians.filter(t => t.is_active).map(t =>
                `<option value="${t.id}" ${String(t.id) === String(p.technician_id) ? 'selected' : ''}>${t.name}</option>`
            ).join('');
            const specOpts = ['MECANICO','ELECTRICO','INSTRUMENTACION','GENERAL'].map(s =>
                `<option value="${s}" ${p.specialty === s ? 'selected' : ''}>${s}</option>`
            ).join('');
            tr.innerHTML = `
                <td style="padding:3px 5px;"><select onchange="updateClosePersonnel(${idx},'technician_id',this.value)" style="${selStyle}"><option value="">-- Técnico --</option>${opts}</select></td>
                <td style="padding:3px 5px;"><select onchange="updateClosePersonnel(${idx},'specialty',this.value)" style="${selStyle}">${specOpts}</select></td>
                <td style="padding:3px 5px;text-align:center;color:#666;">-</td>
                <td style="padding:3px 5px;text-align:center;"><input type="number" min="0" step="0.5" value="${p.hours_worked}" onchange="updateClosePersonnel(${idx},'hours_worked',parseFloat(this.value)||0)" style="${inputStyle}"></td>
                <td style="padding:3px 5px;text-align:center;"><button type="button" onclick="removeClosePersonnel(${idx})" style="background:none;border:none;color:#ff453a;cursor:pointer;"><i class="fas fa-times"></i></button></td>`;
        } else {
            tr.innerHTML = `
                <td style="padding:3px 5px;">${p.technician_name}</td>
                <td style="padding:3px 5px;color:#aaa;font-size:0.85em;">${p.specialty || '-'}</td>
                <td style="padding:3px 5px;text-align:center;color:#888;">${p.hours_assigned}h</td>
                <td style="padding:3px 5px;text-align:center;"><input type="number" min="0" step="0.5" value="${p.hours_worked}" onchange="updateClosePersonnel(${idx},'hours_worked',parseFloat(this.value)||0)" style="${inputStyle}"></td>
                <td></td>`;
        }
        tbody.appendChild(tr);
    });
}

function updateClosePersonnel(idx, field, value) {
    if (!_closePersonnelList[idx]) return;
    _closePersonnelList[idx][field] = value;
    if (field === 'technician_id') {
        const t = allTechnicians.find(x => String(x.id) === String(value));
        if (t) {
            _closePersonnelList[idx].technician_name = t.name;
            if (!_closePersonnelList[idx].specialty) _closePersonnelList[idx].specialty = t.specialty || 'GENERAL';
        }
    }
}

function addCloseExtraPersonnel() {
    _closePersonnelList.push({ id: null, technician_id: null, technician_name: '', specialty: 'MECANICO', hours_assigned: 0, hours_worked: 0, is_extra: true });
    renderClosePersonnelTable();
}

function removeClosePersonnel(idx) {
    _closePersonnelList.splice(idx, 1);
    renderClosePersonnelTable();
}

async function handleCloseOTSubmit(e) {
    e.preventDefault();
    const id = document.getElementById('closeOtId').value;
    const startVal = document.getElementById('realStart').value;
    const endVal = document.getElementById('realEnd').value;
    const comments = document.getElementById('closeComments').value.trim();

    // Validacion manual (reemplaza la del browser que falla en <dialog>)
    if (!comments) { alert('Debe ingresar el trabajo realizado.'); document.getElementById('closeComments').focus(); return; }
    if (!startVal) { alert('Debe ingresar la fecha/hora de inicio real.'); document.getElementById('realStart').focus(); return; }
    if (!endVal) { alert('Debe ingresar la fecha/hora de fin real.'); document.getElementById('realEnd').focus(); return; }

    // Calculate Duration
    const startDate = new Date(startVal);
    const endDate = new Date(endVal);
    const diffMs = endDate - startDate;
    const diffHrs = diffMs / (1000 * 60 * 60); // Hours float

    // Formatting for message
    const hours = Math.floor(diffMs / (1000 * 60 * 60));
    const minutes = Math.floor((diffMs % (1000 * 60 * 60)) / (1000 * 60));

    const causedDowntime = document.getElementById('closeCausedDowntime').value === '1';
    const downtimeHours = causedDowntime
        ? parseFloat(document.getElementById('closeDowntimeHours').value || diffHrs.toFixed(2))
        : 0;

    const data = {
        status: 'Cerrada',
        execution_comments: document.getElementById('closeComments').value,
        real_start_date: startVal,
        real_end_date: endVal,
        real_duration: parseFloat(diffHrs.toFixed(2)),
        caused_downtime: causedDowntime,
        downtime_hours: downtimeHours || null,
    };

    await fetch(`/api/work-orders/${id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data)
    });

    // Guardar horas reales por técnico
    for (const p of _closePersonnelList) {
        if (!p.technician_id) continue;
        if (p.id && !p.is_extra) {
            // Personal planificado: actualizar hours_worked
            await fetch(`/api/work_orders/${id}/personnel/${p.id}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ hours_worked: p.hours_worked })
            }).catch(() => {});
        } else if (p.is_extra) {
            // Técnico de apoyo extra: agregar nuevo registro
            await fetch(`/api/work_orders/${id}/personnel`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    technician_id: parseInt(p.technician_id),
                    specialty: p.specialty,
                    hours_assigned: p.hours_worked,
                    hours_worked: p.hours_worked
                })
            }).catch(() => {});
        }
    }

    // Save hallazgos as log entry if filled
    const findings = (document.getElementById('closeFindings').value || '').trim();
    if (findings) {
        const today = new Date().toISOString().split('T')[0];
        await fetch(`/api/work_orders/${id}/log`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ log_date: today, log_type: 'HALLAZGO', comment: findings })
        }).catch(() => {});
    }

    document.getElementById('closeOTModal').close();
    await loadWorkOrders();

    // Reset execution view
    document.getElementById('execution-details').classList.add('hidden');
    document.getElementById('executionSearch').value = '';

    const shareMsg = `✅ Orden Cerrada. Tiempo Total: ${hours}h ${minutes}m.\n\n¿Desea compartir por WhatsApp?`;
    if (confirm(shareMsg)) {
        shareOTWhatsApp(id, data.execution_comments, `${hours}h ${minutes}m`);
    }
}

async function shareOTWhatsApp(otId, comments, duration) {
    const ot = allWorkOrders.find(o => o.id === parseInt(otId));
    if (!ot) return;
    const techMatch = allTechnicians.find(t => String(t.id) === String(ot.technician_id));
    const techName = (techMatch && techMatch.name) || ot.technician_id || '-';
    const area = ot.area_name || '-';
    const equip = ot.equipment_name || '-';
    const tag = ot.equipment_tag || '';

    // Generar link seguro de foto
    let photoLink = '';
    try {
        const res = await fetch(`/api/photo-share/generate/work_order/${otId}`);
        if (res.ok) {
            const data = await res.json();
            if (data.url) photoLink = `${window.location.origin}${data.url}`;
        }
    } catch (_) {}

    let msg = '\u2705 *OT ' + (ot.code || 'OT-' + ot.id) + ' CERRADA*\n';
    msg += '\uD83D\uDCCD ' + area + ' > ' + equip + (tag ? ' [' + tag + ']' : '') + '\n';
    msg += '\n\uD83D\uDD27 *Trabajo realizado:*\n' + (comments || '-') + '\n';
    msg += '\n\u23F1 Duraci\u00f3n: ' + duration;
    msg += '\n\uD83D\uDC64 T\u00e9cnico: ' + techName;
    if (ot.caused_downtime) msg += '\n\u26A0\uFE0F Caus\u00f3 parada: ' + (ot.downtime_hours || '-') + ' horas';
    msg += '\n\uD83D\uDCC5 ' + new Date().toLocaleDateString('es-PE');
    if (photoLink) {
        msg += '\n\n\uD83D\uDCF7 Ver foto (v\u00e1lido 24h):\n' + photoLink;
    }
    msg += '\n\n_Equipo disponible para producci\u00f3n_';
    msg += '\n_Enviado desde CMMS Pro_';

    const waUrl = `https://wa.me/?text=${encodeURIComponent(msg)}`;
    if (navigator.share) {
        navigator.share({ text: msg }).catch(() => window.open(waUrl, '_blank'));
    } else {
        window.open(waUrl, '_blank');
    }
}
window.shareOTWhatsApp = shareOTWhatsApp;

window.quickShareOT = function(otId) {
    const ot = allWorkOrders.find(o => o.id === otId);
    if (!ot) return;
    const techMatch = allTechnicians.find(t => String(t.id) === String(ot.technician_id));
    const techName = (techMatch && techMatch.name) || ot.technician_id || '-';

    const statusIcon = ot.status === 'Cerrada' ? '\u2705' : ot.status === 'En Progreso' ? '\uD83D\uDD27' : '\uD83D\uDCCB';
    let msg = statusIcon + ' *' + (ot.code || 'OT-' + ot.id) + '* \u2014 ' + ot.status + '\n';
    msg += '\uD83D\uDCCD ' + (ot.area_name || '-') + ' > ' + (ot.equipment_name || '-') + (ot.equipment_tag ? ' [' + ot.equipment_tag + ']' : '') + '\n';
    msg += '\n\uD83D\uDCCB ' + (ot.description || '-') + '\n';
    msg += '\n\uD83D\uDD27 Tipo: ' + (ot.maintenance_type || '-');
    msg += '\n\uD83D\uDC64 T\u00e9cnico: ' + techName;
    msg += '\n\uD83D\uDCC5 Programada: ' + (ot.scheduled_date || '-');
    if (ot.status === 'Cerrada') {
        msg += '\n\u23F1 Duraci\u00f3n: ' + (ot.real_duration || '-') + ' h';
        if (ot.caused_downtime) msg += '\n\u26A0\uFE0F Parada: ' + (ot.downtime_hours || '-') + ' h';
        msg += '\n\n_Equipo disponible para producci\u00f3n_';
    }
    msg += '\n\n_Enviado desde CMMS Pro_';

    const waUrl = `https://wa.me/?text=${encodeURIComponent(msg)}`;
    if (navigator.share) {
        navigator.share({ text: msg }).catch(() => window.open(waUrl, '_blank'));
    } else {
        window.open(waUrl, '_blank');
    }
};

/* --- TECHNICIAN MANAGEMENT --- */
async function loadTechnicians() {
    try {
        const showInactiveEl = document.getElementById('showInactiveTechs');
        const showAll = showInactiveEl ? showInactiveEl.checked : false;
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

    container.innerHTML = allTechnicians.map(t => {
        const linkedUser = t.user_id ? _allUsers.find(u => u.id === t.user_id) : null;
        const userLabel = linkedUser ? `<span style="color:#30D158;font-size:.8rem;"><i class="fas fa-link"></i> ${linkedUser.full_name || linkedUser.username}</span>` : '<span style="color:#666;font-size:.8rem;">Sin vincular</span>';
        return `
        <div class="card provider-card" style="${t.is_active ? '' : 'opacity: 0.5; border: 1px dashed #888;'}">
            <h3>${t.name} ${t.is_active ? '' : '(INACTIVO)'}</h3>
            <p><strong>Esp:</strong> ${t.specialty || '-'}</p>
            <p><i class="fas fa-phone"></i> ${t.contact_info || '-'}</p>
            <p>${userLabel}</p>
            <div style="margin-top:10px; border-top:1px solid #eee; padding-top:5px;">
                <button class="btn-icon" onclick="editTechnician(${t.id})"><i class="fas fa-edit"></i></button>
                <button class="btn-icon" onclick="toggleTechnician(${t.id})" style="color:${t.is_active ? 'orange' : 'green'};" title="${t.is_active ? 'Dar de baja' : 'Dar de alta'}">
                    <i class="fas fa-${t.is_active ? 'user-slash' : 'user-check'}"></i>
                </button>
            </div>
        </div>
    `}).join('');
}

function populateTechnicianSelect() {
    const sel = document.getElementById('otTechnician');
    if (!sel) return;

    // Only show active technicians in dropdown
    const activeTechs = allTechnicians.filter(t => t.is_active);
    sel.innerHTML = '<option value="">- Seleccione -</option>' +
        activeTechs.map(t => `<option value="${t.id}">${t.name}</option>`).join('');
}

let _allUsers = [];
async function loadUsersForTechLink() {
    try {
        const res = await fetch('/api/auth/me');
        if (!res.ok) return;
        const me = await res.json();
        if (me.role === 'admin') {
            const uRes = await fetch('/api/auth/users');
            if (uRes.ok) _allUsers = await uRes.json();
        }
    } catch (_) {}
}

function populateTechUserSelect(selectedUserId) {
    const sel = document.getElementById('techUserId');
    if (!sel) return;
    const linkedIds = new Set(allTechnicians.filter(t => t.user_id).map(t => t.user_id));
    sel.innerHTML = '<option value="">— Sin vincular —</option>' +
        _allUsers.filter(u => u.active && (!linkedIds.has(u.id) || u.id === selectedUserId))
            .map(u => `<option value="${u.id}" ${u.id === selectedUserId ? 'selected' : ''}>${u.full_name || u.username} (${u.role})</option>`).join('');
}

function openTechnicianModal() {
    document.getElementById('techId').value = '';
    document.getElementById('techName').value = '';
    document.getElementById('techSpecialty').value = '';
    document.getElementById('techContact').value = '';
    document.getElementById('techModalTitle').textContent = 'Nuevo Técnico';
    populateTechUserSelect(null);
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
    populateTechUserSelect(t.user_id || null);
    document.getElementById('technicianModal').showModal();
}

window.toggleTechnician = async (id) => {
    const t = allTechnicians.find(x => x.id === id);
    const action = (t && t.is_active) ? 'dar de baja' : 'dar de alta';
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
            const userIdVal = document.getElementById('techUserId').value;
            const data = {
                name: document.getElementById('techName').value,
                specialty: document.getElementById('techSpecialty').value,
                contact_info: document.getElementById('techContact').value,
                user_id: userIdVal ? parseInt(userIdVal) : null,
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

        // Duplicados are shown (need review), Anulados hidden by default
        const showAnulados = document.getElementById('showAnulados')?.checked || false;
        const HIDDEN = ['Cerrado', 'Cancelado'];
        if (!showAnulados) HIDDEN.push('Anulado');
        allPendingNotices = notices.filter(n => !n.ot_number && !HIDDEN.includes(n.status));

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
            'Pendiente': '#FF9F0A',
            'En Tratamiento': '#0A84FF',
            'En Progreso': '#5AC8FA',
            'Duplicado': '#BF5AF2',
            'Anulado': '#666',
        };
        const statusColor = statusColors[n.status] || '#666';
        const isDuplicado = n.status === 'Duplicado';
        const isAnulado = n.status === 'Anulado';
        const rowOpacity = isAnulado ? 'opacity:0.45' : '';

        const tr = document.createElement('tr');
        tr.style.cssText = rowOpacity;
        tr.innerHTML = `
            <td>${n.code || n.id}</td>
            <td>${n.reporter_type || '-'}</td>
            <td>${equipName}</td>
            <td title="${(n.description||'').replace(/"/g,'&quot;')}">${n.description ? (n.description.length > 40 ? n.description.substring(0, 40) + '...' : n.description) : '-'}</td>
            <td>${n.criticality || '-'}</td>
            <td>${n.priority || '-'}</td>
            <td>${n.request_date || '-'}</td>
            <td>${n.reporter_name || '-'}</td>
            <td>${n.maintenance_type || '-'}</td>
            <td><span style="background: ${statusColor}; padding: 3px 8px; border-radius: 10px; font-size: 0.8em; color: white;">${n.status || 'Pendiente'}</span></td>
            <td>
                <div style="display: flex; gap: 5px;">
                    <button onclick="viewNoticeDetails(${n.id})" class="btn-info" style="padding: 5px 8px;" title="Ver Detalle">
                        <i class="fas fa-eye"></i>
                    </button>
                    ${isDuplicado ? `
                        <button onclick="acceptDuplicateNotice(${n.id})" class="btn-success" style="padding: 5px 8px;" title="Aceptar (convertir a Pendiente)">
                            <i class="fas fa-check"></i>
                        </button>
                        <button onclick="annulNotice(${n.id})" class="btn-danger" style="padding: 5px 8px;background:rgba(255,69,58,.2);color:#FF6B61;border:none;border-radius:4px;cursor:pointer" title="Anular">
                            <i class="fas fa-ban"></i>
                        </button>
                    ` : isAnulado ? '' : `
                        <button onclick="convertNoticeToOT(${n.id})" class="btn-success" style="padding: 5px 8px;" title="Crear OT">
                            <i class="fas fa-wrench"></i>
                        </button>
                    `}
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
                    list.innerHTML += `<li>âš ï¸ Aviso <strong>${d.code || d.id}</strong> (${d.status}): "${d.description}"</li>`;
                });

                // Add Work Orders
                data.work_orders.forEach(ot => {
                    list.innerHTML += `<li>âš ï¸ OT Activa <strong>${ot.code || ot.id}</strong> (${ot.status}): "${ot.description}"</li>`;
                });
            }
        }

        // Cargar fotos del aviso
        const photosSection  = document.getElementById('detail-photos-section');
        const photosGallery  = document.getElementById('detail-photos-gallery');
        photosSection.style.display = 'none';
        photosGallery.innerHTML = '';
        try {
            const photosRes = await fetch(`/api/photos/notice/${id}`);
            const photos = await photosRes.json();
            if (Array.isArray(photos) && photos.length > 0) {
                photosSection.style.display = '';
                photosGallery.innerHTML = photos.map(p => `
                    <div style="width:90px; height:90px; border-radius:8px; overflow:hidden; border:1px solid #444; cursor:pointer;"
                         onclick="window.open('${p.url}','_blank')" title="${p.caption || 'Ver foto'}">
                        <img src="${p.url}" style="width:100%; height:100%; object-fit:cover;">
                    </div>
                `).join('');
            }
        } catch (_) {}

        document.getElementById('noticeDetailModal').showModal();

    } catch (e) { console.error(e); alert("Error cargando detalles"); }
}

// Accept duplicate notice → change status to Pendiente
async function acceptDuplicateNotice(noticeId) {
    if (!confirm('Aceptar este aviso duplicado? Se cambiara a estado Pendiente.')) return;
    try {
        await fetch(`/api/notices/${noticeId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ status: 'Pendiente' })
        });
        loadPendingNotices();
    } catch (e) { alert('Error: ' + e.message); }
}

// Annul notice
async function annulNotice(noticeId) {
    const reason = prompt('Motivo de anulacion:');
    if (reason === null) return;
    try {
        await fetch(`/api/notices/${noticeId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ status: 'Anulado', cancellation_reason: reason || 'Anulado por usuario' })
        });
        loadPendingNotices();
    } catch (e) { alert('Error: ' + e.message); }
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
            component_id: notice.component_id,
            rotative_asset_id: notice.rotative_asset_id || null,
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
    evt.target.style.background = '#0A84FF';
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
        const hReal = p.hours_worked != null ? p.hours_worked : '-';
        const hPlan = p.hours_assigned || 0;
        const realColor = p.hours_worked != null && p.hours_worked > hPlan ? '#ff9f0a' : '#30D158';
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td>${p.technician_name || 'Sin asignar'}</td>
            <td>${p.specialty || '-'}</td>
            <td style="text-align:center;">${hPlan} h</td>
            <td style="text-align:center;color:${p.hours_worked != null ? realColor : '#666'};">${hReal !== '-' ? hReal + ' h' : '-'}</td>
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
}

// ── OT Activity Log (Bitacora) ──────────────────────────────────────────────

const LOG_TYPE_COLORS = {
    NOTA: '#888', AVANCE: '#30D158', MATERIAL: '#FF9F0A',
    PROVEEDOR: '#BF5AF2', INFORME: '#0A84FF', CIERRE: '#FF453A',
};

async function loadOTLog(otId) {
    const container = document.getElementById('exec-log-list');
    try {
        const res = await fetch(`/api/work_orders/${otId}/log`);
        const entries = await res.json();
        if (!entries.length) {
            container.innerHTML = '<p style="color:#888;font-style:italic;text-align:center;padding:8px">Sin registros en la bitacora.</p>';
            return;
        }
        container.innerHTML = entries.map(e => {
            const c = LOG_TYPE_COLORS[e.log_type] || '#888';
            return `<div style="display:flex;gap:8px;padding:6px 0;border-bottom:1px solid rgba(255,255,255,.06)">
                <div style="width:8px;height:8px;border-radius:50%;background:${c};margin-top:6px;flex-shrink:0"></div>
                <div style="flex:1;min-width:0">
                    <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
                        <span style="font-size:.75rem;color:${c};font-weight:700;text-transform:uppercase">${e.log_type}</span>
                        <span style="font-size:.75rem;color:rgba(255,255,255,.40)">${e.log_date}</span>
                        ${e.author ? `<span style="font-size:.72rem;color:rgba(255,255,255,.35)">por ${e.author}</span>` : ''}
                    </div>
                    <div style="font-size:.84rem;color:rgba(255,255,255,.78);margin-top:2px">${e.comment}</div>
                </div>
                <button onclick="deleteLogEntry(${e.id})" style="background:none;border:none;color:rgba(255,255,255,.20);cursor:pointer;font-size:.72rem;flex-shrink:0" title="Eliminar"><i class="fas fa-trash"></i></button>
            </div>`;
        }).join('');
    } catch (err) {
        container.innerHTML = `<p style="color:#FF6B61">${err.message}</p>`;
    }
}

async function addLogEntry() {
    if (!activeExecutionOT) return;
    const comment = document.getElementById('logComment').value.trim();
    if (!comment) { alert('Ingresa un comentario.'); return; }

    try {
        await fetch(`/api/work_orders/${activeExecutionOT.id}/log`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                log_date: document.getElementById('logDate').value || new Date().toISOString().slice(0, 10),
                log_type: document.getElementById('logType').value,
                comment,
            })
        });
        document.getElementById('logComment').value = '';
        loadOTLog(activeExecutionOT.id);
    } catch (e) { alert('Error: ' + e.message); }
}

async function deleteLogEntry(logId) {
    if (!activeExecutionOT || !confirm('Eliminar esta entrada?')) return;
    await fetch(`/api/work_orders/${activeExecutionOT.id}/log/${logId}`, { method: 'DELETE' });
    loadOTLog(activeExecutionOT.id);
}

// ── Report Tracking ─────────────────────────────────────────────────────────

function loadReportStatus(ot) {
    document.getElementById('reportRequired').checked = !!ot.report_required;
    document.getElementById('reportDueDate').value = ot.report_due_date || '';
    document.getElementById('reportReceivedDate').value = ot.report_received_date || '';
    updateReportBadge(ot);
}

function updateReportBadge(ot) {
    const badge = document.getElementById('reportStatusBadge');
    const req = document.getElementById('reportRequired').checked;
    const received = document.getElementById('reportReceivedDate').value;
    if (!req) {
        badge.textContent = '';
        badge.style.background = 'none';
    } else if (received) {
        badge.textContent = 'RECIBIDO';
        badge.style.background = 'rgba(48,209,88,.18)';
        badge.style.color = '#30D158';
    } else {
        badge.textContent = 'PENDIENTE';
        badge.style.background = 'rgba(255,69,58,.18)';
        badge.style.color = '#FF6B61';
    }
}

async function updateReport() {
    if (!activeExecutionOT) return;
    const required = document.getElementById('reportRequired').checked;
    const dueDate = document.getElementById('reportDueDate').value;
    const receivedDate = document.getElementById('reportReceivedDate').value;

    try {
        await fetch(`/api/work_orders/${activeExecutionOT.id}/report`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                report_required: required,
                report_status: receivedDate ? 'RECIBIDO' : (required ? 'PENDIENTE' : null),
                report_due_date: dueDate || null,
                report_received_date: receivedDate || null,
            })
        });
        updateReportBadge(activeExecutionOT);
    } catch (e) { console.error('Report update error:', e); }

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

// ── Add Material Modal ────────────────────────────────────────────────────────
let modalMaterialCatalog = [];
let currentMaterialSubtype = 'repuesto';

function renderMaterialSearchList(filterText = '') {
    const list = document.getElementById('materialSearchList');
    if (!list) return;
    const query = String(filterText || '').trim().toLowerCase();
    const filtered = modalMaterialCatalog.filter(item => {
        if (!query) return true;
        return `${item.code || ''} ${item.name || ''} ${item.category || ''}`.toLowerCase().includes(query);
    }).slice(0, 30);

    if (!filtered.length) {
        list.innerHTML = '<div style="padding:8px 12px;color:#888;font-size:.82rem;">Sin resultados en catálogo</div>';
        list.style.display = 'block';
        return;
    }
    list.innerHTML = filtered.map(i => {
        const detail = currentMaterialType === 'tool'
            ? `(${i.status || 'Disponible'})`
            : `Stock: ${i.stock ?? 'N/A'}`;
        return `<div onclick="selectMaterialItem(${i.id},'${(i.code||'').replace(/'/g,"\\'")}','${(i.name||'').replace(/'/g,"\\'")}',${i.stock ?? null})"
            style="padding:8px 12px;cursor:pointer;font-size:.83rem;border-bottom:1px solid #333;"
            onmouseover="this.style.background='#2a3a5a'" onmouseout="this.style.background=''">
            <strong>${i.code || '-'}</strong> — ${i.name}
            <span style="color:#888;font-size:.78rem;margin-left:6px;">${detail}</span>
        </div>`;
    }).join('');
    list.style.display = 'block';
}

window.selectMaterialItem = function(id, code, name, stock) {
    document.getElementById('materialItemId').value = id;
    document.getElementById('materialSelectedName').textContent = `${code} — ${name}${stock !== null ? ' (Stock: ' + stock + ')' : ''}`;
    document.getElementById('materialSelectedDisplay').style.display = 'block';
    document.getElementById('materialSearchInput').value = '';
    document.getElementById('materialSearchList').style.display = 'none';
};

window.clearMaterialSelection = function() {
    document.getElementById('materialItemId').value = '';
    document.getElementById('materialSelectedDisplay').style.display = 'none';
    document.getElementById('materialSearchInput').value = '';
    document.getElementById('materialSearchInput').focus();
};

async function loadMaterialCatalog(type) {
    try {
        const endpoint = type === 'tool' ? '/api/tools' : '/api/warehouse';
        const res = await fetch(endpoint);
        modalMaterialCatalog = await res.json() || [];
    } catch (e) {
        modalMaterialCatalog = [];
    }
}

window.openAddMaterialModal = async function (type, subtype) {
    const otId = document.getElementById('otId').value;
    if (!otId) { alert('Guarde la OT primero antes de agregar materiales'); return; }

    currentMaterialType = type;
    currentMaterialSubtype = subtype || (type === 'tool' ? 'herramienta' : 'repuesto');
    document.getElementById('materialType').value = type;
    document.getElementById('materialSubtype').value = currentMaterialSubtype;

    // Title + icon
    const cfg = {
        repuesto:    { icon: 'cog',    color: '#30D158', label: 'Agregar Repuesto' },
        consumible:  { icon: 'flask',  color: '#FF9F0A', label: 'Agregar Consumible' },
        herramienta: { icon: 'wrench', color: '#5AC8FA', label: 'Agregar Herramienta' },
    };
    const c = cfg[currentMaterialSubtype] || cfg.repuesto;
    document.getElementById('addMaterialTitle').innerHTML =
        `<i class="fas fa-${c.icon}" style="color:${c.color}"></i> ${c.label}`;

    // Reset fields
    document.getElementById('materialItemId').value = '';
    document.getElementById('materialSelectedDisplay').style.display = 'none';
    document.getElementById('materialSearchInput').value = '';
    document.getElementById('materialSearchList').style.display = 'none';
    document.getElementById('materialFreeText').value = '';
    document.getElementById('materialQuantity').value = 1;
    document.getElementById('materialUnit').value = '';
    document.getElementById('materialInstalled').value = '1';

    // Hide "Instalado?" for tools
    document.getElementById('materialInstalledGroup').style.display =
        currentMaterialSubtype === 'herramienta' ? 'none' : '';

    // Show/hide catalog section
    const hasCatalog = type !== 'free';
    document.getElementById('materialCatalogSection').style.display = hasCatalog ? '' : 'none';
    document.getElementById('materialFreeLabel').textContent =
        hasCatalog ? 'Nombre (si no está en catálogo)' : 'Nombre';

    // Load catalog
    if (hasCatalog) await loadMaterialCatalog(type);

    // Search handler
    const searchInput = document.getElementById('materialSearchInput');
    searchInput.oninput = function() {
        if (searchInput.value.trim()) renderMaterialSearchList(searchInput.value);
        else document.getElementById('materialSearchList').style.display = 'none';
    };
    searchInput.placeholder = type === 'tool' ? 'Buscar herramienta...' : 'Buscar por código o nombre...';

    document.getElementById('addMaterialModal').showModal();
    searchInput.focus();
};

// Close dropdown when clicking outside
document.addEventListener('click', function(e) {
    const list = document.getElementById('materialSearchList');
    if (list && !list.contains(e.target) && e.target.id !== 'materialSearchInput') {
        list.style.display = 'none';
    }
    const pList = document.getElementById('personnelSuggestions');
    if (pList && !pList.contains(e.target) && e.target.id !== 'personnelSearchInput') {
        pList.style.display = 'none';
    }
});

async function confirmAddMaterial() {
    const otId = document.getElementById('otId').value;
    const itemId = document.getElementById('materialItemId').value;
    const freeText = document.getElementById('materialFreeText').value.trim();
    const quantity = parseFloat(document.getElementById('materialQuantity').value) || 1;
    const unit = document.getElementById('materialUnit').value.trim();
    const isInstalled = document.getElementById('materialInstalled').value === '1';

    if (!itemId && !freeText) {
        alert('Seleccione del catálogo o escriba el nombre del item.');
        return;
    }

    const payload = {
        item_type: itemId ? currentMaterialType : 'free',
        subtype: currentMaterialSubtype,
        item_id: itemId ? parseInt(itemId, 10) : null,
        item_name_free: freeText || null,
        quantity: quantity,
        unit: unit || null,
        is_installed: isInstalled,
    };

    try {
        const res = await fetch(`/api/work_orders/${otId}/materials`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        if (res.ok) {
            document.getElementById('addMaterialModal').close();
            loadOTMaterials(otId);
        } else {
            const err = await res.json();
            alert('Error: ' + (err.error || 'Error desconocido'));
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
    const selectedOption = techSelect.options[techSelect.selectedIndex];
    const techName = selectedOption ? selectedOption.text : '';

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

    const subtypeCfg = {
        repuesto:    { bg: '#30D15822', color: '#30D158', icon: 'fa-cog',    label: 'Repuesto' },
        consumible:  { bg: '#FF9F0A22', color: '#FF9F0A', icon: 'fa-flask',  label: 'Consumible' },
        herramienta: { bg: '#5AC8FA22', color: '#5AC8FA', icon: 'fa-wrench', label: 'Herramienta' },
    };

    currentOTMaterials.forEach(m => {
        const sub = m.subtype || (m.item_type === 'tool' ? 'herramienta' : 'repuesto');
        const cfg = subtypeCfg[sub] || subtypeCfg.repuesto;
        const name = m.item_name_free || m.item_name || m.name || '-';
        const code = m.item_code || m.code || (m.item_type === 'free' ? '—' : '-');
        const installedBadge = sub !== 'herramienta'
            ? (m.is_installed !== false
                ? '<span style="color:#30D158;font-size:.8rem;"><i class="fas fa-check-circle"></i> Sí</span>'
                : '<span style="color:#FF453A;font-size:.8rem;"><i class="fas fa-times-circle"></i> No</span>')
            : '<span style="color:#888;font-size:.78rem;">N/A</span>';

        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td><span style="display:inline-flex;align-items:center;gap:4px;padding:2px 8px;border-radius:10px;font-size:.78rem;font-weight:600;background:${cfg.bg};color:${cfg.color};border:1px solid ${cfg.color}55;">
                <i class="fas ${cfg.icon}"></i> ${cfg.label}
            </span></td>
            <td style="font-family:monospace;font-size:.82rem;">${code}</td>
            <td style="font-weight:500;">${name}</td>
            <td style="text-align:center;">${m.quantity || 1}</td>
            <td style="text-align:center;color:#aaa;">${m.unit || '-'}</td>
            <td style="text-align:center;">${installedBadge}</td>
            <td>
                <button type="button" onclick="removeMaterial(${m.id})"
                    style="padding:2px 8px;background:#FF453A22;border:1px solid #FF453A55;border-radius:4px;color:#FF453A;cursor:pointer;">
                    <i class="fas fa-trash"></i>
                </button>
            </td>`;
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
        const planHours = p.hours_assigned !== undefined ? p.hours_assigned : (p.hours || 0);
        const realHours = (p.hours_worked !== null && p.hours_worked !== undefined) ? p.hours_worked : '';
        const isReplacement = !!p.replacement_for_id;
        const repName = p.replacement_for_name || '';

        // Estado asistencia
        let attBadge = '';
        if (p.attended === true) attBadge = '<span style="color:#30D158;font-weight:600">SI</span>';
        else if (p.attended === false) attBadge = '<span style="color:#FF453A;font-weight:600">NO</span>';
        else attBadge = '<span style="color:#888">—</span>';

        // Origen
        let origenLabel = isReplacement
            ? `<span style="color:#FF9F0A;font-size:.78rem">Reemplazo de ${repName || '?'}</span>`
            : `<span style="color:#0A84FF;font-size:.78rem">Planificado</span>`;

        // Si la persona no asistio, marcar fila en gris
        const rowStyle = (p.attended === false) ? 'opacity:.55;text-decoration:line-through;' : '';

        tr.style.cssText = rowStyle;
        tr.innerHTML = `
            <td>${p.technician_name || p.name || 'N/A'}</td>
            <td>${p.specialty || '-'}</td>
            <td style="text-align:center;">${planHours} h</td>
            <td style="text-align:center;">
                <input type="number" min="0" step="0.5" value="${realHours}" data-idx="${idx}"
                    onchange="updatePersonnelHoursWorked(${idx}, this.value)"
                    style="width:60px;padding:2px 4px;background:#1c1c1c;color:#fff;border:1px solid #333;border-radius:4px;text-align:center;" />
            </td>
            <td style="text-align:center;">${attBadge}</td>
            <td>${origenLabel}</td>
            <td>
                <div style="display:flex;gap:4px;flex-wrap:wrap;">
                    <button type="button" onclick="setAttended(${idx}, true)"
                        title="Marcar asistio" style="padding:2px 6px;background:#0d3a1a;color:#5cd870;border:1px solid #2d6a3d;border-radius:4px;font-size:.72rem;">
                        <i class="fas fa-check"></i>
                    </button>
                    <button type="button" onclick="setAttended(${idx}, false)"
                        title="Marcar NO asistio" style="padding:2px 6px;background:#3a1d1d;color:#ff8a8a;border:1px solid #6a2d2d;border-radius:4px;font-size:.72rem;">
                        <i class="fas fa-times"></i>
                    </button>
                    <button type="button" class="btn-danger" onclick="removePersonnel(${idx})"
                        title="Eliminar fila" style="padding:2px 6px;font-size:.72rem;">
                        <i class="fas fa-trash"></i>
                    </button>
                </div>
            </td>
        `;
        tbody.appendChild(tr);
    });
}

window.updatePersonnelHoursWorked = function (idx, value) {
    const v = parseFloat(value);
    currentOTPersonnel[idx].hours_worked = isNaN(v) ? null : v;
    const otId = document.getElementById('otId').value;
    if (otId) saveOTPersonnel(otId);
};

window.setAttended = function (idx, val) {
    currentOTPersonnel[idx].attended = val;
    // Si marca como NO asistio, ofrecer agregar un reemplazo
    if (val === false) {
        if (confirm('Marcado como NO asistio. ¿Quieres agregar un reemplazo ahora?')) {
            const original = currentOTPersonnel[idx];
            // ID temporal: usamos el id real si ya existe en BD, si no usamos negativo basado en idx
            _pendingReplacementFor = { idx, id: original.id || null, name: original.technician_name };
            addPersonnelRow(true);
        }
    }
    renderPersonnelTable();
    const otId = document.getElementById('otId').value;
    if (otId) saveOTPersonnel(otId);
};

let _pendingReplacementFor = null;

window.addPersonnelRow = function (isReplacement) {
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

    // Marcar si esta agregando un reemplazo
    if (!isReplacement) _pendingReplacementFor = null;
    const titleEl = document.querySelector('#addPersonnelModal h3');
    if (titleEl) {
        if (isReplacement && _pendingReplacementFor) {
            titleEl.innerHTML = `<i class="fas fa-user-plus"></i> Reemplazo para ${_pendingReplacementFor.name || '?'}`;
        } else if (isReplacement) {
            titleEl.innerHTML = `<i class="fas fa-user-plus"></i> Agregar Reemplazo`;
        } else {
            titleEl.innerHTML = `<i class="fas fa-user-plus"></i> Agregar Personal Planificado`;
        }
    }
    document.getElementById('addPersonnelModal').showModal();
}

window.confirmAddPersonnel = function () {
    const techSelect = document.getElementById('personnelTechSelect');
    const techId = techSelect.value;
    const selectedOption = techSelect.options[techSelect.selectedIndex];
    const techName = selectedOption ? selectedOption.text : '';
    if (!techId) return alert('Seleccione un técnico');

    const specialty = document.getElementById('personnelSpecialty').value;
    const hours = parseFloat(document.getElementById('personnelHours').value) || 8;

    // Validar duplicado solo para planificados (un reemplazo puede repetir si eligen al mismo)
    if (!_pendingReplacementFor && currentOTPersonnel.find(p => p.technician_id == techId && !p.replacement_for_id)) {
        return alert('Este técnico ya está asignado en planificado');
    }

    const newRow = {
        technician_id: parseInt(techId),
        technician_name: techName,
        specialty: specialty,
        hours: hours,
        attended: _pendingReplacementFor ? true : null,
    };
    if (_pendingReplacementFor) {
        newRow.replacement_for_id = _pendingReplacementFor.id;
        newRow.replacement_for_name = _pendingReplacementFor.name;
    }
    currentOTPersonnel.push(newRow);
    _pendingReplacementFor = null;

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
        alert("âš ï¸ ATENCIÃ“N: Para solicitar una compra, primero debe GUARDAR la Orden de Trabajo.\n\nPor favor, guarde los cambios y vuelva a intentar.");
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
        searchInput.placeholder = "ðŸ”„ Cargando catálogo...";
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
            searchInput.placeholder = "ðŸ” Escriba para buscar repuesto...";
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
        div.onmouseover = function () { this.style.backgroundColor = "#0A84FF"; this.style.color = "black"; };
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
            <td style="padding:5px;">${item.item_type === 'MATERIAL' ? '<span style="color:#0A84FF">REP</span>' : '<span style="color:#ffb74d">SERV</span>'}</td>
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
                description: item.description || item.detail
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

// ── Personnel Typeahead ───────────────────────────────────────────────────────
let _selectedPersonnelId   = null;
let _selectedPersonnelName = null;

function renderPersonnelSuggestions(query) {
    const list = document.getElementById('personnelSuggestions');
    if (!list) return;
    const q = (query || '').trim().toLowerCase();
    const filtered = (Array.isArray(allTechnicians) ? allTechnicians : [])
        .filter(t => {
            if (!q) return true;
            return `${t.name || ''} ${t.specialty || ''}`.toLowerCase().includes(q);
        }).slice(0, 15);

    if (!filtered.length) {
        list.innerHTML = '<div style="padding:8px 12px;color:#888;font-size:.82rem;">Sin resultados</div>';
        list.style.display = 'block';
        return;
    }
    list.innerHTML = filtered.map(t => `
        <div onclick="selectPersonnelItem(${t.id},'${(t.name||'').replace(/'/g,"\\'")}','${(t.specialty||'GENERAL').replace(/'/g,"\\'")}') "
            style="padding:8px 12px;cursor:pointer;font-size:.83rem;border-bottom:1px solid #333;display:flex;align-items:center;gap:8px;"
            onmouseover="this.style.background='#2a3a5a'" onmouseout="this.style.background=''">
            <i class="fas fa-user" style="color:#5AC8FA;font-size:.75rem;"></i>
            <span><strong>${t.name}</strong><span style="color:#888;font-size:.78rem;margin-left:6px;">${t.specialty||''}</span></span>
        </div>`).join('');
    list.style.display = 'block';
}

window.selectPersonnelItem = function(id, name, specialty) {
    _selectedPersonnelId   = id;
    _selectedPersonnelName = name;
    document.getElementById('personnelTechId').value = id;
    document.getElementById('personnelSelectedName').textContent = name;
    document.getElementById('personnelSelectedDisplay').style.display = 'block';
    document.getElementById('personnelSearchInput').value = '';
    document.getElementById('personnelSuggestions').style.display = 'none';
    // Auto-fill specialty
    const specSelect = document.getElementById('personnelSpecialty');
    if (specSelect && specialty) specSelect.value = specialty;
};

window.clearPersonnelSelection = function() {
    _selectedPersonnelId   = null;
    _selectedPersonnelName = null;
    document.getElementById('personnelTechId').value = '';
    document.getElementById('personnelSelectedDisplay').style.display = 'none';
    document.getElementById('personnelSearchInput').value = '';
    document.getElementById('personnelSearchInput').focus();
};

window.addPersonnelRow = function (isReplacement) {
    _selectedPersonnelId   = null;
    _selectedPersonnelName = null;
    document.getElementById('personnelTechId').value = '';
    document.getElementById('personnelSelectedDisplay').style.display = 'none';
    document.getElementById('personnelSearchInput').value = '';
    document.getElementById('personnelSuggestions').style.display = 'none';
    document.getElementById('personnelHours').value = 8;

    const searchInput = document.getElementById('personnelSearchInput');
    searchInput.oninput = function() {
        if (searchInput.value.trim()) renderPersonnelSuggestions(searchInput.value);
        else document.getElementById('personnelSuggestions').style.display = 'none';
    };

    if (!isReplacement) _pendingReplacementFor = null;
    const titleEl = document.querySelector('#addPersonnelModal h3');
    if (titleEl) {
        if (isReplacement && _pendingReplacementFor) {
            titleEl.innerHTML = `<i class="fas fa-user-plus"></i> Reemplazo para ${_pendingReplacementFor.name || '?'}`;
        } else if (isReplacement) {
            titleEl.innerHTML = `<i class="fas fa-user-plus"></i> Agregar Reemplazo`;
        } else {
            titleEl.innerHTML = `<i class="fas fa-user-plus"></i> Agregar Personal Planificado`;
        }
    }

    document.getElementById('addPersonnelModal').showModal();
    searchInput.focus();
};

window.confirmAddPersonnel = function () {
    const techId   = document.getElementById('personnelTechId').value || _selectedPersonnelId;
    const techName = _selectedPersonnelName || document.getElementById('personnelSelectedName').textContent;

    if (!techId) return alert('Seleccione un técnico de la lista');

    const specialty = document.getElementById('personnelSpecialty').value;
    const hours     = parseFloat(document.getElementById('personnelHours').value) || 8;

    // Validar duplicado solo entre planificados (un reemplazo puede repetir)
    if (!_pendingReplacementFor && currentOTPersonnel.find(p => Number(p.technician_id) === Number(techId) && !p.replacement_for_id)) {
        return alert('Este técnico ya está asignado en planificado');
    }

    const newRow = {
        technician_id: parseInt(techId, 10),
        technician_name: techName,
        specialty: specialty,
        hours: hours,
        attended: _pendingReplacementFor ? true : null,
    };
    if (_pendingReplacementFor) {
        newRow.replacement_for_id = _pendingReplacementFor.id;
        newRow.replacement_for_name = _pendingReplacementFor.name;
    }
    currentOTPersonnel.push(newRow);
    _pendingReplacementFor = null;

    renderPersonnelTable();
    document.getElementById('addPersonnelModal').close();

    const otId = document.getElementById('otId').value;
    if (otId) saveOTPersonnel(otId);
};







// ── OT Photo Functions ──────────────────────────────────────────────────────

async function loadOTPhotos(otId) {
    const gallery = document.getElementById('exec-photo-gallery');
    if (!gallery) return;
    try {
        const res = await fetch(`/api/photos/work_order/${otId}`);
        const photos = await res.json();
        if (!photos.length) {
            gallery.innerHTML = '<span style="color:rgba(255,255,255,.30);font-size:.80rem">Sin fotos.</span>';
            return;
        }
        gallery.innerHTML = photos.map(p => `
            <div style="position:relative;width:100px;height:100px;border-radius:8px;overflow:hidden;border:1px solid rgba(255,255,255,.10)">
                <img src="${p.url}" style="width:100%;height:100%;object-fit:cover;cursor:pointer" onclick="window.open('${p.url}','_blank')" title="${p.caption || ''}">
                <button onclick="deleteOTPhoto(${p.id})" style="position:absolute;top:2px;right:2px;width:20px;height:20px;background:rgba(0,0,0,.7);border:none;border-radius:50%;color:#FF453A;font-size:.65rem;cursor:pointer"><i class="fas fa-times"></i></button>
                ${p.caption ? '<div style="position:absolute;bottom:0;left:0;right:0;background:rgba(0,0,0,.7);padding:2px 4px;font-size:.65rem;color:#ddd;overflow:hidden;white-space:nowrap;text-overflow:ellipsis">' + p.caption + '</div>' : ''}
            </div>
        `).join('');
    } catch (_) {
        gallery.innerHTML = '<span style="color:#FF6B61;font-size:.80rem">Error cargando fotos.</span>';
    }
}

async function uploadOTPhoto() {
    if (!activeExecutionOT) return;
    const fileInput = document.getElementById('execPhotoFile');
    if (!fileInput.files.length) { alert('Selecciona una foto.'); return; }

    const gallery = document.getElementById('exec-photo-gallery');
    gallery.innerHTML = '<span style="color:#5AC8FA;font-size:.82rem"><i class="fas fa-circle-notch fa-spin"></i> Subiendo y comprimiendo foto...</span>';

    const formData = new FormData();
    formData.append('photo', fileInput.files[0]);
    formData.append('caption', document.getElementById('execPhotoCaption').value || '');

    try {
        const res = await fetch(`/api/photos/work_order/${activeExecutionOT.id}`, {
            method: 'POST',
            body: formData,
        });
        const data = await res.json();
        if (!res.ok) {
            alert(data.error || 'Error subiendo foto.');
            loadOTPhotos(activeExecutionOT.id);
            return;
        }
        fileInput.value = '';
        document.getElementById('execPhotoCaption').value = '';
        alert(`Foto subida correctamente.\nOriginal: ${data.original_size_kb || '?'}KB → Comprimida: ${data.compressed_size_kb || '?'}KB`);
        loadOTPhotos(activeExecutionOT.id);
    } catch (e) {
        alert('Error: ' + e.message);
        loadOTPhotos(activeExecutionOT.id);
    }
}

async function deleteOTPhoto(photoId) {
    if (!activeExecutionOT || !confirm('Eliminar foto?')) return;
    await fetch(`/api/photos/${photoId}`, { method: 'DELETE' });
    loadOTPhotos(activeExecutionOT.id);
}

// ── Notice Photos in Execution Panel ────────────────────────────────────────

async function loadNoticePhotosInExecution(noticeId) {
    const section = document.getElementById('exec-notice-photos');
    const gallery = document.getElementById('exec-notice-photo-gallery');
    if (!section || !gallery) return;

    if (!noticeId) {
        section.style.display = 'none';
        return;
    }

    try {
        const res = await fetch(`/api/photos/notice/${noticeId}`);
        const photos = await res.json();
        if (!photos.length) {
            section.style.display = 'none';
            return;
        }
        section.style.display = '';
        gallery.innerHTML = photos.map(p => `
            <div style="position:relative;width:120px;height:120px;border-radius:8px;overflow:hidden;border:1px solid rgba(255,255,255,.10)">
                <img src="${p.url}" style="width:100%;height:100%;object-fit:cover;cursor:pointer" onclick="window.open('${p.url}','_blank')" title="${p.caption || 'Foto del aviso'}">
                ${p.caption ? '<div style="position:absolute;bottom:0;left:0;right:0;background:rgba(0,0,0,.7);padding:3px 6px;font-size:.70rem;color:#ddd;overflow:hidden;white-space:nowrap;text-overflow:ellipsis">' + p.caption + '</div>' : ''}
            </div>
        `).join('');
    } catch (_) {
        section.style.display = 'none';
    }
}
