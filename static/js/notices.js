// Initial Listeners moved to bottom


// DATA CACHE
let allAreas = [], allLines = [], allEquips = [], allSys = [], allComps = [], allProviders = [];
let allNotices = [];
let currentScopeFilter = 'ALL';
let _treeSelectionCallback = null; // when set, tree node clicks call this instead of selectHierarchy
let _promotingNoticeId = null;

// ── Scope helpers ────────────────────────────────────────────────────────────
function scopeLabel(scope) {
    if (scope === 'FUERA_PLAN') return '🚧 Fuera de Plan';
    if (scope === 'GENERAL')    return '🛠️ General';
    return '🏭 Plan';
}
function scopeBadge(scope) {
    if (scope === 'FUERA_PLAN')
        return `<span class="scope-badge scope-badge-fuera_plan">🚧 F.Plan</span>`;
    if (scope === 'GENERAL')
        return `<span class="scope-badge scope-badge-general">🛠️ General</span>`;
    return `<span class="scope-badge scope-badge-plan">🏭 Plan</span>`;
}

function filterByScopeTab(scope) {
    currentScopeFilter = scope;
    document.querySelectorAll('.scope-tab').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.scope === scope);
    });
    renderNotices();
}

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
        allNotices = await res.json();
        renderNotices();
    } catch (e) { console.error(e); }
}

function renderNotices() {
    const filtered = currentScopeFilter === 'ALL'
        ? allNotices
        : allNotices.filter(n => (n.scope || 'PLAN') === currentScopeFilter);

    const tbody = document.querySelector('#noticesTable tbody');
    tbody.innerHTML = '';

    filtered.forEach(n => {
        const foundProvider = allProviders.find(p => p.id === n.provider_id);
        const provName = (foundProvider && foundProvider.name) ? foundProvider.name : '-';
        const scope = n.scope || 'PLAN';

        const tr = document.createElement('tr');

        if (n.status === 'Anulado') {
            tr.style.opacity = "0.6";
            tr.style.background = "#2a2a2a";
        }

        const canConvert = n.status !== 'Cerrado' && n.status !== 'Anulado' && !n.ot_number;
        const convertBtn = canConvert
            ? `<button onclick="convertToOT(${n.id})" style="padding:2px 5px; background: transparent; border: none; cursor: pointer;" title="Convertir a OT">🔧</button>`
            : '';

        const isLocked = n.status === 'Cerrado' || n.status === 'Anulado';
        const actionBtns = isLocked
            ? `<button style="padding:2px 5px; opacity:0.3; cursor:default;">🚫</button>`
            : `<button onclick="annulNotice(${n.id})" style="padding:2px 5px; background: transparent; border: none; cursor: pointer; color: #FF453A;" title="Anular Aviso">🚫</button>`;

        const editBtn = `<button onclick="editNotice(${n.id})" style="padding:2px 5px; background: transparent; border: none; cursor: pointer;" title="Editar">✏️</button>`;

        // Promover button for non-PLAN or for PLAN with missing equipment
        const canPromote = !isLocked;
        const promoteBtn = canPromote
            ? `<button onclick="openPromoteModal(${n.id})" style="padding:2px 5px; background: transparent; border: none; cursor: pointer;" title="Promover / Reclasificar alcance">📐</button>`
            : '';

        let statusColor = '#FF9F0A';
        if (n.status === 'En Tratamiento') statusColor = '#2196f3';
        if (n.status === 'En Progreso') statusColor = '#00bcd4';
        if (n.status === 'Cerrado') statusColor = '#4caf50';
        if (n.status === 'Anulado') statusColor = '#757575';
        if (n.status === 'Duplicado') statusColor = '#ff5722';

        const statusBadge = `<span style="background-color: ${statusColor}; color: white; padding: 2px 8px; border-radius: 4px; font-size: 0.85em;">${n.status || 'Pendiente'}</span>`;

        tr.innerHTML = `
            <td>${n.code || n.id}</td>
            <td>
                <span style="background-color: ${n.failure_count > 0 ? '#FF453A' : '#0A84FF'}; color: ${n.failure_count > 0 ? 'white' : 'black'}; padding: 2px 6px; border-radius: 12px; font-weight: bold; font-size: 0.9em;">
                    ${n.failure_count || 0}
                </span>
            </td>
            <td>${n.reporter_type || '-'}</td>
            <td>${provName}</td>
            <td>${n.specialty || '-'}</td>
            <td>${n.shift || '-'}</td>
            <td>${getName(allAreas, n.area_id)}</td>
            <td>${getName(allLines, n.line_id)}</td>
            <td>${n.equipment_id ? getName(allEquips, n.equipment_id) : (n.free_location ? `<span style="color:#888;font-style:italic">${n.free_location}</span>` : '-')}</td>
            <td>${getName(allSys, n.system_id)}</td>
            <td>${getName(allComps, n.component_id)}</td>
            <td style="max-width:320px;min-width:260px;">
                <div style="display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden;text-overflow:ellipsis;max-width:320px;line-height:1.3;white-space:normal;word-break:break-word;" title="${(n.description || '').replace(/"/g,'&quot;')}">${n.description || '-'}</div>
                ${n.cancellation_reason ? `<small style="color:#FF453A;">(Anulado: ${n.cancellation_reason})</small>` : ''}
            </td>
            <td>${n.criticality || '-'}</td>
            <td>${n.priority || '-'}</td>
            <td>${n.request_date || '-'}</td>
            <td>${n.treatment_date || '-'}</td>
            <td>${n.planning_date || '-'}</td>
            <td>${n.failure_mode || '-'}</td>
            <td>${n.maintenance_type || '-'}</td>
            <td>${n.ot_number || '-'}</td>
            <td>${scopeBadge(scope)}</td>
            <td>${statusBadge}</td>
            <td style="white-space:nowrap;">
                ${convertBtn}
                ${editBtn}
                ${promoteBtn}
                ${actionBtns}
                <button onclick="shareNoticeWhatsApp(${n.id})" style="padding:2px 5px; background:transparent; border:none; cursor:pointer; color:#25D366; font-size:1.1em;" title="Compartir por WhatsApp"><i class="fab fa-whatsapp"></i></button>
            </td>
        `;
        tbody.appendChild(tr);
    });

    // KPIs always based on full dataset
    updateKPIIndicators(allNotices);
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
        'Pendiente': { bg: '#FF9F0A', text: '#000' },
        'En Tratamiento': { bg: '#2196f3', text: '#fff' },
        'En Progreso': { bg: '#00bcd4', text: '#000' },
        'Cerrado': { bg: '#4caf50', text: '#fff' },
        'Duplicado': { bg: '#ff5722', text: '#fff' }
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

    const sortedReporterAreas = Object.entries(reporterAreaCounts).sort((a, b) => b[1] - a[1]);

    const areaEl = document.getElementById('kpiAreaBreakdown');
    if (areaEl) {
        areaEl.innerHTML = sortedReporterAreas.map(([area, count]) => `
            <div style="display: flex; align-items: center; gap: 6px; background: #3d3d3d; padding: 6px 12px; border-radius: 15px; border: 1px solid #555;">
                <span style="font-weight: bold; color: #BF5AF2;">${count}</span>
                <span style="color: #ccc; font-size: 0.85em;">${area}</span>
            </div>
        `).join('');
    }

    // Scope Breakdown
    const scopeCounts = { PLAN: 0, FUERA_PLAN: 0, GENERAL: 0 };
    notices.forEach(n => {
        const s = n.scope || 'PLAN';
        if (scopeCounts[s] !== undefined) scopeCounts[s]++;
        else scopeCounts['PLAN']++;
    });
    const total = notices.length || 1;

    const scopeEl = document.getElementById('kpiScopeBreakdown');
    if (scopeEl) {
        scopeEl.innerHTML = `
            <div onclick="filterByScopeTab('PLAN')" style="cursor:pointer; display:flex; align-items:center; gap:8px; background:#0A84FF18; padding:8px 14px; border-radius:20px; border:1px solid #0A84FF44;">
                <span style="font-size:1.2em; font-weight:bold; color:#5AC8FA">${scopeCounts.PLAN}</span>
                <div>
                    <div style="font-size:0.78em; color:#5AC8FA;">🏭 Plan</div>
                    <div style="font-size:0.72em; color:#3a7ab0">${Math.round(scopeCounts.PLAN/total*100)}%</div>
                </div>
            </div>
            <div onclick="filterByScopeTab('FUERA_PLAN')" style="cursor:pointer; display:flex; align-items:center; gap:8px; background:#FF9F0A18; padding:8px 14px; border-radius:20px; border:1px solid #FF9F0A44;">
                <span style="font-size:1.2em; font-weight:bold; color:#FF9F0A">${scopeCounts.FUERA_PLAN}</span>
                <div>
                    <div style="font-size:0.78em; color:#FF9F0A;">🚧 Fuera Plan</div>
                    <div style="font-size:0.72em; color:#8a6020">${Math.round(scopeCounts.FUERA_PLAN/total*100)}%</div>
                </div>
            </div>
            <div onclick="filterByScopeTab('GENERAL')" style="cursor:pointer; display:flex; align-items:center; gap:8px; background:#BF5AF218; padding:8px 14px; border-radius:20px; border:1px solid #BF5AF244;">
                <span style="font-size:1.2em; font-weight:bold; color:#BF5AF2">${scopeCounts.GENERAL}</span>
                <div>
                    <div style="font-size:0.78em; color:#BF5AF2;">🛠️ General</div>
                    <div style="font-size:0.72em; color:#7a3ab0">${Math.round(scopeCounts.GENERAL/total*100)}%</div>
                </div>
            </div>
        `;
    }
}

let _savingNotice = false;
async function saveNotice(e) {
    e.preventDefault();
    if (_savingNotice) return;
    _savingNotice = true;
    const btn = e.submitter || e.target.querySelector('button[type="submit"]');
    const origBtn = btn ? btn.innerHTML : '';
    if (btn) { btn.disabled = true; btn.innerHTML = '<i class="fas fa-circle-notch fa-spin"></i> Guardando...'; }
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
        rotative_asset_id: document.getElementById('noticeRotativeAsset')?.value || null,
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
            const respJson = await res.json();
            document.getElementById('noticeModal').close();
            loadNotices();

            if (respJson.is_duplicate) {
                alert(`⚠️ ATENCIÓN: El aviso fue creado pero marcado como DUPLICADO.\nMotivo: ${respJson.duplicate_reason}`);
            }
        } else {
            alert("Error guardando aviso");
        }
    } catch (err) {
        alert("Error de red: " + err);
    } finally {
        _savingNotice = false;
        if (btn) { btn.disabled = false; btn.innerHTML = origBtn; }
    }
}

document.addEventListener('DOMContentLoaded', async () => {
    await loadDropdowns();
    loadNotices();

    document.getElementById('newNoticeBtn').onclick = () => {
        document.getElementById('noticeForm').reset();
        document.getElementById('noticeId').value = '';
        document.getElementById('photoSection').style.display = 'none';

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
        const n = allNotices.find(x => x.id === id) ||
                  await fetch(`/api/notices/${id}`).then(r => r.json());
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
        // Show photo section for existing notices
        document.getElementById('photoSection').style.display = '';
        loadNoticePhotos(n.id);
        document.getElementById('noticeModal').showModal();

    } catch (e) { console.error(e); }
}


// TREE SELECTION LOGIC
window.openTreeSelection = (callback = null) => {
    _treeSelectionCallback = callback || null;
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
    const typeClass = `node-${String(type || '').toLowerCase()}`;

    span.className = `node-label ${typeClass}`;
    span.textContent = `${type}: ${item.name} ${item.tag ? '[' + item.tag + ']' : ''}`;
    span.setAttribute('tabindex', '0');

    const selectNode = (e) => {
        e.stopPropagation();
        if (_treeSelectionCallback) {
            const cb = _treeSelectionCallback;
            _treeSelectionCallback = null;
            cb(item, type, parents);
        } else {
            selectHierarchy(item, type, parents);
        }
        document.getElementById('treeModal').close();
    };

    span.onclick = selectNode;
    span.onkeydown = (e) => {
        if (e.key === 'Enter' || e.key === ' ') {
            selectNode(e);
        }
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
        <strong style="color:#0A84FF">Area:</strong> ${safeName(allAreas, areaId)} |
        <strong style="color:#0A84FF">Línea:</strong> ${safeName(allLines, lineId)} |
        <strong style="color:#0A84FF">Equipo:</strong> ${safeName(allEquips, eqId)} <br>
        <strong style="color:#0A84FF">Sistema:</strong> ${safeName(allSys, sysId)} |
        <strong style="color:#0A84FF">Comp.:</strong> ${safeName(allComps, compId)}
    `;

    // Load rotative assets for selected equipment
    loadNoticeRotativeAssets(eqId);
}

async function loadNoticeRotativeAssets(equipmentId) {
    const sel = document.getElementById('noticeRotativeAsset');
    if (!sel) return;
    sel.innerHTML = '<option value="">- Sin activo rotativo -</option>';
    if (!equipmentId) return;
    try {
        const res = await fetch(`/api/rotative-assets?equipment_id=${equipmentId}`);
        const assets = await res.json();
        if (!Array.isArray(assets)) return;
        assets.filter(a => a.status === 'Instalado').forEach(a => {
            const opt = document.createElement('option');
            opt.value = a.id;
            opt.textContent = `${a.code} ${a.name} (${a.category || '-'})`;
            sel.appendChild(opt);
        });
    } catch (_) {}
}

// Helper function to get name from list by id
function getName(list, id) {
    if (!id) return '-';
    const numId = parseInt(id);
    const item = list.find(x => x.id === numId);
    return item ? item.name : id;
}

// ── Promote / Reclassify Modal ───────────────────────────────────────────────

window.openPromoteModal = (id) => {
    _promotingNoticeId = id;
    const notice = allNotices.find(n => n.id === id);
    if (!notice) return;

    document.getElementById('promoteNoticeCode').textContent = notice.code || `AV-${id}`;
    document.getElementById('promoteCurrentScope').textContent = scopeLabel(notice.scope || 'PLAN');
    document.getElementById('promoteCurrentScope').style.color =
        notice.scope === 'FUERA_PLAN' ? '#FF9F0A' :
        notice.scope === 'GENERAL'    ? '#BF5AF2' : '#5AC8FA';

    document.getElementById('promoteNewScope').value = notice.scope || 'PLAN';
    document.getElementById('promoteFreeLocation').value = notice.free_location || '';

    // Reset hierarchy
    ['promoteAreaId','promoteLineId','promoteEquipId','promoteSysId','promoteCompId'].forEach(f => {
        document.getElementById(f).value = notice[f.replace('promote','').replace(/Id$/,'_id').toLowerCase()] || '';
    });
    _updatePromoteHierarchyDisplay();
    onPromoteScopeChange();
    document.getElementById('promoteModal').showModal();
};

function onPromoteScopeChange() {
    const scope = document.getElementById('promoteNewScope').value;
    const planSec = document.getElementById('promotePlanSection');
    const genSec  = document.getElementById('promoteGeneralSection');
    if (scope === 'PLAN') {
        planSec.style.display = '';
        genSec.style.display = 'none';
    } else {
        planSec.style.display = 'none';
        genSec.style.display = '';
    }
}

window.openTreeForPromotion = () => {
    openTreeSelection((item, type, parents) => {
        // Set hidden promote hierarchy fields
        document.getElementById('promoteAreaId').value  = '';
        document.getElementById('promoteLineId').value  = '';
        document.getElementById('promoteEquipId').value = '';
        document.getElementById('promoteSysId').value   = '';
        document.getElementById('promoteCompId').value  = '';

        if (type === 'Area') {
            document.getElementById('promoteAreaId').value = item.id;
        } else if (type === 'Line') {
            document.getElementById('promoteAreaId').value = parents.area?.id || '';
            document.getElementById('promoteLineId').value = item.id;
        } else if (type === 'Equipment') {
            document.getElementById('promoteAreaId').value  = parents.area?.id || '';
            document.getElementById('promoteLineId').value  = parents.line?.id || '';
            document.getElementById('promoteEquipId').value = item.id;
        } else if (type === 'System') {
            document.getElementById('promoteAreaId').value  = parents.area?.id || '';
            document.getElementById('promoteLineId').value  = parents.line?.id || '';
            document.getElementById('promoteEquipId').value = parents.equipment?.id || '';
            document.getElementById('promoteSysId').value   = item.id;
        } else if (type === 'Component') {
            document.getElementById('promoteAreaId').value  = parents.area?.id || '';
            document.getElementById('promoteLineId').value  = parents.line?.id || '';
            document.getElementById('promoteEquipId').value = parents.equipment?.id || '';
            document.getElementById('promoteSysId').value   = parents.system?.id || '';
            document.getElementById('promoteCompId').value  = item.id;
        }
        _updatePromoteHierarchyDisplay();
        // Re-open promote modal (tree modal closed it)
        document.getElementById('promoteModal').showModal();
    });
};

function _updatePromoteHierarchyDisplay() {
    const aId = parseInt(document.getElementById('promoteAreaId').value);
    const lId = parseInt(document.getElementById('promoteLineId').value);
    const eId = parseInt(document.getElementById('promoteEquipId').value);
    const sId = parseInt(document.getElementById('promoteSysId').value);
    const cId = parseInt(document.getElementById('promoteCompId').value);

    const safeName = (list, id) => { const i = list.find(x => x.id === id); return i ? i.name : '—'; };

    const parts = [];
    if (aId) parts.push(`Área: ${safeName(allAreas, aId)}`);
    if (lId) parts.push(`Línea: ${safeName(allLines, lId)}`);
    if (eId) parts.push(`Equipo: ${safeName(allEquips, eId)}`);
    if (sId) parts.push(`Sistema: ${safeName(allSys, sId)}`);
    if (cId) parts.push(`Comp.: ${safeName(allComps, cId)}`);

    document.getElementById('promoteHierarchyDisplay').textContent =
        parts.length ? parts.join(' | ') : 'No seleccionado';
}

window.savePromotion = async () => {
    const id = _promotingNoticeId;
    if (!id) return;

    const newScope = document.getElementById('promoteNewScope').value;
    const data = { scope: newScope };

    if (newScope === 'PLAN') {
        const aId = document.getElementById('promoteAreaId').value;
        const lId = document.getElementById('promoteLineId').value;
        const eId = document.getElementById('promoteEquipId').value;
        const sId = document.getElementById('promoteSysId').value;
        const cId = document.getElementById('promoteCompId').value;
        if (aId) data.area_id       = aId;
        if (lId) data.line_id       = lId;
        if (eId) data.equipment_id  = eId;
        if (sId) data.system_id     = sId;
        if (cId) data.component_id  = cId;
        data.free_location = null;
    } else {
        const fl = document.getElementById('promoteFreeLocation').value.trim();
        if (fl) data.free_location = fl;
    }

    try {
        const res = await fetch(`/api/notices/${id}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
        if (res.ok) {
            document.getElementById('promoteModal').close();
            await loadNotices();
        } else {
            const err = await res.json().catch(() => ({}));
            alert('Error al promover: ' + (err.error || res.status));
        }
    } catch (e) {
        alert('Error de red: ' + e);
    }
};

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
        const notice = allNotices.find(n => n.id === noticeId) ||
                       await fetch(`/api/notices/${noticeId}`).then(r => r.json());
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

// ── Photo Functions ──────────────────────────────────────────────────────────

async function loadNoticePhotos(noticeId) {
    const gallery = document.getElementById('photoGallery');
    try {
        const res = await fetch(`/api/photos/notice/${noticeId}`);
        const photos = await res.json();
        if (!photos.length) {
            gallery.innerHTML = '<span style="color:rgba(255,255,255,.30);font-size:.80rem">Sin fotos adjuntas.</span>';
            return;
        }
        gallery.innerHTML = photos.map(p => `
            <div style="position:relative;width:100px;height:100px;border-radius:8px;overflow:hidden;border:1px solid rgba(255,255,255,.10)">
                <img src="${p.url}" style="width:100%;height:100%;object-fit:cover;cursor:pointer" onclick="window.open('${p.url}','_blank')" title="${p.caption || ''}">
                <button onclick="deleteNoticePhoto(${p.id}, ${noticeId})" style="position:absolute;top:2px;right:2px;width:20px;height:20px;background:rgba(0,0,0,.7);border:none;border-radius:50%;color:#FF453A;font-size:.65rem;cursor:pointer"><i class="fas fa-times"></i></button>
                ${p.caption ? `<div style="position:absolute;bottom:0;left:0;right:0;background:rgba(0,0,0,.7);padding:2px 4px;font-size:.65rem;color:#ddd;overflow:hidden;white-space:nowrap;text-overflow:ellipsis">${p.caption}</div>` : ''}
            </div>
        `).join('');
    } catch (_) {
        gallery.innerHTML = '<span style="color:#FF6B61;font-size:.80rem">Error cargando fotos.</span>';
    }
}

async function uploadNoticePhoto() {
    const noticeId = document.getElementById('noticeId').value;
    if (!noticeId) { alert('Guarda el aviso primero antes de adjuntar fotos.'); return; }

    const fileInput = document.getElementById('photoFile');
    if (!fileInput.files.length) { alert('Selecciona una foto.'); return; }

    const gallery = document.getElementById('photoGallery');
    gallery.innerHTML = '<span style="color:#5AC8FA;font-size:.82rem"><i class="fas fa-circle-notch fa-spin"></i> Subiendo y comprimiendo foto...</span>';

    const formData = new FormData();
    formData.append('photo', fileInput.files[0]);
    formData.append('caption', document.getElementById('photoCaption').value || '');

    try {
        const res = await fetch(`/api/photos/notice/${noticeId}`, {
            method: 'POST',
            body: formData,
        });
        const data = await res.json();
        if (!res.ok) {
            alert(data.error || 'Error subiendo foto.');
            loadNoticePhotos(noticeId);
            return;
        }
        fileInput.value = '';
        document.getElementById('photoCaption').value = '';
        alert(`Foto subida correctamente.\nOriginal: ${data.original_size_kb || '?'}KB → Comprimida: ${data.compressed_size_kb || '?'}KB`);
        loadNoticePhotos(noticeId);
    } catch (e) {
        alert('Error: ' + e.message);
        loadNoticePhotos(noticeId);
    }
}

async function deleteNoticePhoto(photoId, noticeId) {
    if (!confirm('Eliminar esta foto?')) return;
    await fetch(`/api/photos/${photoId}`, { method: 'DELETE' });
    loadNoticePhotos(noticeId);
}

// ── Compartir por WhatsApp ──────────────────────────────
window.shareNoticeWhatsApp = async function(noticeId) {
    const n = allNotices.find(x => x.id === noticeId);
    if (!n) return;
    const area = getName(allAreas, n.area_id);
    const equip = n.equipment_id ? getName(allEquips, n.equipment_id) : (n.free_location || '-');
    const sys = getName(allSys, n.system_id);
    const comp = getName(allComps, n.component_id);

    // Generar link seguro temporal para la foto
    let photoLink = '';
    try {
        const res = await fetch(`/api/photo-share/generate/notice/${noticeId}`);
        if (res.ok) {
            const data = await res.json();
            if (data.url) {
                photoLink = `${window.location.origin}${data.url}`;
            }
        }
    } catch (_) {}

    let msg = `🔔 *AVISO ${n.code || 'AV-' + n.id}*\n`;
    msg += `📍 ${area}`;
    if (equip !== '-') msg += ` > ${equip}`;
    if (sys !== '-') msg += ` > ${sys}`;
    if (comp !== '-') msg += ` > ${comp}`;
    msg += `\n\n📋 ${n.description || '-'}`;
    msg += `\n\n⚠️ Criticidad: ${n.criticality || '-'} | Prioridad: ${n.priority || '-'}`;
    msg += `\n🔧 Tipo: ${n.maintenance_type || '-'}`;
    if (n.failure_mode) msg += ` | Modo: ${n.failure_mode}`;
    if (n.blockage_object) msg += `\n🪨 Objeto extraño: ${n.blockage_object}`;
    msg += `\n📅 Fecha: ${n.request_date || '-'}`;
    msg += `\n👤 Reportado por: ${n.reporter_name || '-'}`;
    if (photoLink) msg += `\n\n📷 Ver foto (válido 24h):\n${photoLink}`;
    msg += `\n\n_Enviado desde CMMS Pro_`;

    const encoded = encodeURIComponent(msg);
    window.open(`https://wa.me/?text=${encoded}`, '_blank');
};


