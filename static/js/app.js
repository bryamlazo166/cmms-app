let state = {
    selectedAreaId: null,
    selectedLineId: null,
    selectedEquipId: null,
    selectedSysId: null,
    selectedCompId: null
};

document.addEventListener('DOMContentLoaded', () => {
    loadAreas();

    document.getElementById('resetDbBtn').onclick = resetDB;

    // Import Modal
    const modal = document.getElementById('importModal');
    document.getElementById('importBtn').onclick = () => modal.showModal();

    document.getElementById('uploadForm').onsubmit = async (e) => {
        e.preventDefault();
        const fileInput = document.getElementById('excelFile');
        const formData = new FormData();
        formData.append('file', fileInput.files[0]);

        const btn = e.submitter;
        btn.textContent = "Procesando...";
        btn.disabled = true;

        try {
            const res = await fetch('/api/upload-excel', {
                method: 'POST',
                body: formData
            });
            const result = await res.json();
            if (res.ok) {
                alert("¡Carga exitosa! " + result.message);
                modal.close();
                loadAreas();
                loadGlobalTree();
            } else {
                alert("Error: " + result.error);
            }
        } catch (err) {
            alert("Error de red: " + err);
        } finally {
            btn.textContent = "Subir y Procesar";
            btn.disabled = false;
        }
    };

    // Initialize hints
    updatePasteHint();
});

// --- IMPORT MODAL HELPERS ---

function toggleImportMode() {
    const mode = document.querySelector('input[name="importMode"]:checked').value;
    document.getElementById('modeFile').style.display = mode === 'file' ? 'block' : 'none';
    document.getElementById('modePaste').style.display = mode === 'paste' ? 'block' : 'none';
    document.getElementById('modeHierarchy').style.display = mode === 'hierarchy' ? 'block' : 'none';
}

const REQUIRED_COLS = {
    'Areas': 'Name, [Description]',
    'Lines': 'Name, AreaName, [Description]',
    'Equipments': 'Name, Tag, LineName, [AreaName], [Description]',
    'Systems': 'Name, EquipmentName, LineName, [AreaName]',
    'Components': 'Name, SystemName, EquipmentName, LineName, [AreaName], [Description]',
};

function updatePasteHint() {
    const type = document.getElementById('pasteEntityType').value;
    document.getElementById('pasteHint').textContent = "Columnas requeridas: " + REQUIRED_COLS[type];
}

async function processPaste() {
    const type = document.getElementById('pasteEntityType').value;
    const rawData = document.getElementById('pasteContent').value;

    if (!rawData.trim()) return alert("Por favor pega algo primero.");

    const btn = document.getElementById('btnProcessPaste');
    btn.textContent = "Procesando...";
    btn.disabled = true;

    try {
        const res = await fetch('/api/bulk-paste', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                entity_type: type,
                raw_data: rawData
            })
        });
        const result = await res.json();

        if (res.ok) {
            alert("¡Carga exitosa! " + result.message);
            document.getElementById('importModal').close();
            // Refresh simplified
            loadAreas();
            // Also refresh tree if open?
            // loadGlobalTree(); // Maybe too heavy to auto load every time
        } else {
            alert("Error: " + result.error);
        }

    } catch (err) {
        alert("Error de red: " + err);
    } finally {
        btn.textContent = "Procesar Pegado";
        btn.disabled = false;
    }
}

// --- GENERIC FORM HANDLERS ---

// 1. Area
const areaFormEl = document.getElementById('areaForm');
if (areaFormEl) areaFormEl.onsubmit = async (e) => {
    e.preventDefault();
    await postData('/api/areas', { name: document.getElementById('areaName').value });
    document.getElementById('areaName').value = '';
    loadAreas();
};

// 2. Line
const lineFormEl = document.getElementById('lineForm');
if (lineFormEl) lineFormEl.onsubmit = async (e) => {
    e.preventDefault();
    if (!state.selectedAreaId) return alert("Selecciona un Área primero");
    await postData('/api/lines', {
        name: document.getElementById('lineName').value,
        area_id: state.selectedAreaId
    });
    document.getElementById('lineName').value = '';
    loadLines(state.selectedAreaId);
};

// 3. Equipment
const equipFormEl = document.getElementById('equipForm');
if (equipFormEl) equipFormEl.onsubmit = async (e) => {
    e.preventDefault();
    if (!state.selectedLineId) return alert("Selecciona una Línea primero");
    await postData('/api/equipments', {
        name: document.getElementById('equipName').value,
        tag: document.getElementById('equipTag').value,
        line_id: state.selectedLineId
    });
    document.getElementById('equipName').value = '';
    document.getElementById('equipTag').value = '';
    loadEquipments(state.selectedLineId);
};

// 4. System
const sysFormEl = document.getElementById('sysForm');
if (sysFormEl) sysFormEl.onsubmit = async (e) => {
    e.preventDefault();
    if (!state.selectedEquipId) return alert("Selecciona un Equipo primero");
    await postData('/api/systems', {
        name: document.getElementById('sysName').value,
        equipment_id: state.selectedEquipId
    });
    document.getElementById('sysName').value = '';
    loadSystems(state.selectedEquipId);
};

// 5. Component
const compFormEl = document.getElementById('compForm');
if (compFormEl) compFormEl.onsubmit = async (e) => {
    e.preventDefault();
    if (!state.selectedSysId) return alert("Selecciona un Sistema primero");
    await postData('/api/components', {
        name: document.getElementById('compName').value,
        system_id: state.selectedSysId
    });
    document.getElementById('compName').value = '';
    loadComponents(state.selectedSysId);
};

// End of file


// --- API HELPERS ---

async function postData(url, data) {
    const res = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data)
    });
    if (!res.ok) {
        const err = await res.json();
        alert("Error: " + (err.error || 'Unknown'));
    }
}

async function fetchData(url) {
    const res = await fetch(url);
    return await res.json();
}

// --- LOADERS & RENDERERS ---

async function loadAreas() {
    const areas = await fetchData('/api/areas');
    renderList('areaList', areas, (id) => {
        state.selectedAreaId = id;
        state.selectedLineId = null; // reset child selection
        loadLines(id);
        clearColumnsFrom(2);
    }, 'Area');
}

async function loadLines(areaId) {
    const allLines = await fetchData('/api/lines');
    const lines = allLines.filter(l => l.area_id === areaId);
    renderList('lineList', lines, (id) => {
        state.selectedLineId = id;
        loadEquipments(id);
        clearColumnsFrom(3);
    }, 'Line');
}

async function loadEquipments(lineId) {
    const allEquips = await fetchData('/api/equipments');
    const equips = allEquips.filter(e => e.line_id === lineId);
    renderList('equipList', equips, (id) => {
        state.selectedEquipId = id;
        loadSystems(id);
        clearColumnsFrom(4);
    }, 'Equipment');
}

async function loadSystems(equipId) {
    const allSys = await fetchData('/api/systems');
    const systems = allSys.filter(s => s.equipment_id === equipId);
    renderList('sysList', systems, (id) => {
        state.selectedSysId = id;
        loadComponents(id);
        clearColumnsFrom(5);
    }, 'System');
}

async function loadComponents(sysId) {
    const allComps = await fetchData('/api/components');
    const comps = allComps.filter(c => c.system_id === sysId);
    renderList('compList', comps, (id) => {
        state.selectedCompId = id;
    }, 'Component');
}

// --- UTILS ---

function renderList(elementId, items, onClick, entityType) {
    const list = document.getElementById(elementId);
    list.innerHTML = '';
    items.forEach(item => {
        const div = document.createElement('div');
        div.className = 'item-row';
        div.style.display = 'flex';
        div.style.justifyContent = 'space-between';
        div.style.alignItems = 'center';

        const span = document.createElement('span');
        span.textContent = item.name + (item.tag ? ` (${item.tag})` : '');
        span.style.cursor = 'pointer';
        span.style.flexGrow = '1';
        span.onclick = () => {
            // Highlight selection
            Array.from(list.children).forEach(c => c.classList.remove('selected'));
            div.classList.add('selected');
            onClick(item.id);
        };

        const btn = document.createElement('button');
        btn.innerHTML = '📋';
        btn.title = "Crear Aviso para este item";
        btn.style.background = 'transparent';
        btn.style.border = 'none';
        btn.style.cursor = 'pointer';
        btn.onclick = (e) => {
            e.stopPropagation();
            window.location.href = `/avisos?create=true&type=${entityType}&id=${item.id}`;
        };

        div.appendChild(span);
        div.appendChild(btn);

        list.appendChild(div);
    });
}

function clearColumnsFrom(stepIdx) {
    // Helper to clear downstream lists when a parent selection changes
    if (stepIdx <= 2) document.getElementById('lineList').innerHTML = '';
    if (stepIdx <= 3) document.getElementById('equipList').innerHTML = '';
    if (stepIdx <= 4) document.getElementById('sysList').innerHTML = '';
    if (stepIdx <= 5) document.getElementById('compList').innerHTML = '';
}

async function resetDB() {
    if (confirm("¿Estás seguro de borrar TODO?")) {
        await fetch('/api/initialize', { method: 'POST' });
        location.reload();
    }
}

// --- HIERARCHY PASTE ---

async function processHierarchyPaste() {
    const rawData = document.getElementById('hierarchyContent').value;
    if (!rawData.trim()) return alert("Por favor pega algo primero.");

    const btn = document.getElementById('btnProcessHierarchy');
    btn.textContent = "Procesando...";
    btn.disabled = true;

    try {
        const res = await fetch('/api/bulk-paste-hierarchy', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ raw_data: rawData })
        });
        const result = await res.json();

        if (res.ok) {
            alert("¡Carga Jerárquica Exitosa! " + result.message);
            document.getElementById('importModal').close();
            loadAreas();
            loadGlobalTree();
        } else {
            alert("Error: " + result.error);
        }

    } catch (err) {
        alert("Error de red: " + err);
    } finally {
        btn.textContent = "Procesar Jerarquía Completa";
        btn.disabled = false;
    }
}

// --- IMPORT MODAL HELPERS ---



// ... existing code ...

async function loadGlobalTree() {
    // Simple implementation for fetching full tree
    const [areas, lines, equips, systems, comps] = await Promise.all([
        fetchData('/api/areas'),
        fetchData('/api/lines'),
        fetchData('/api/equipments'),
        fetchData('/api/systems'),
        fetchData('/api/components')
    ]);

    // SORTING HELPERS
    const sortByName = (a, b) => a.name.localeCompare(b.name);

    areas.sort(sortByName);
    lines.sort(sortByName);
    equips.sort(sortByName);
    systems.sort(sortByName);
    comps.sort(sortByName);

    const tree = document.getElementById('globalTree');
    tree.innerHTML = '';

    // Stats
    const totalEquips = equips.length;
    const totalSys = systems.length;
    const totalComps = comps.length;

    // Expand/Collapse All Buttons
    const controls = document.createElement('div');
    controls.className = 'tree-controls';
    controls.innerHTML = `
        <button onclick="expandAll()"><i class="fas fa-expand-alt"></i> Expandir Todo</button>
        <button onclick="collapseAll()"><i class="fas fa-compress-alt"></i> Colapsar Todo</button>
        <span class="tree-stats">${areas.length} areas · ${lines.length} lineas · ${totalEquips} equipos · ${totalSys} sistemas · ${totalComps} componentes</span>
    `;
    tree.appendChild(controls);

    const ulRoot = document.createElement('ul');

    const LEVEL_CONFIG = {
        Area:      { icon: 'fa-industry',    css: 'area',   badge: 'Area' },
        Line:      { icon: 'fa-grip-lines',  css: 'line',   badge: 'Linea' },
        Equipment: { icon: 'fa-cog',         css: 'equip',  badge: 'Equipo' },
        System:    { icon: 'fa-project-diagram', css: 'system', badge: 'Sistema' },
        Component: { icon: 'fa-puzzle-piece', css: 'comp',  badge: 'Componente' },
    };

    function buildTreeNode(label, type, data, childCount) {
        const cfg = LEVEL_CONFIG[type];
        const li = document.createElement('li');
        const node = createNode(label, type, data, cfg, childCount);
        return { li, node };
    }

    areas.forEach(area => {
        const areaLines = lines.filter(l => l.area_id === area.id);
        const { li: liArea, node: nodeArea } = buildTreeNode(area.name, 'Area', area, areaLines.length);

        if (areaLines.length > 0) {
            addCaret(liArea);
            liArea.appendChild(nodeArea);
            const ulLines = document.createElement('ul');
            ulLines.className = 'nested';

            areaLines.forEach(line => {
                const lineEquips = equips.filter(e => e.line_id === line.id);
                const { li: liLine, node: nodeLine } = buildTreeNode(line.name, 'Line', line, lineEquips.length);

                if (lineEquips.length > 0) {
                    addCaret(liLine);
                    liLine.appendChild(nodeLine);
                    const ulEquips = document.createElement('ul');
                    ulEquips.className = 'nested';

                    lineEquips.forEach(eq => {
                        const equipSys = systems.filter(s => s.equipment_id === eq.id);
                        const eqLabel = eq.tag ? `${eq.name} [${eq.tag}]` : eq.name;
                        const { li: liEquip, node: nodeEquip } = buildTreeNode(eqLabel, 'Equipment', eq, equipSys.length);

                        if (equipSys.length > 0) {
                            addCaret(liEquip);
                            liEquip.appendChild(nodeEquip);
                            const ulSys = document.createElement('ul');
                            ulSys.className = 'nested';

                            equipSys.forEach(sys => {
                                const sysComps = comps.filter(c => c.system_id === sys.id);
                                const { li: liSys, node: nodeSys } = buildTreeNode(sys.name, 'System', sys, sysComps.length);

                                if (sysComps.length > 0) {
                                    addCaret(liSys);
                                    liSys.appendChild(nodeSys);
                                    const ulComps = document.createElement('ul');
                                    ulComps.className = 'nested';

                                    sysComps.forEach(comp => {
                                        const { li: liComp, node: nodeComp } = buildTreeNode(comp.name, 'Component', comp, 0);
                                        liComp.appendChild(nodeComp);
                                        ulComps.appendChild(liComp);
                                    });
                                    liSys.appendChild(ulComps);
                                } else {
                                    liSys.appendChild(nodeSys);
                                }
                                ulSys.appendChild(liSys);
                            });
                            liEquip.appendChild(ulSys);
                        } else {
                            liEquip.appendChild(nodeEquip);
                        }
                        ulEquips.appendChild(liEquip);
                    });
                    liLine.appendChild(ulEquips);
                } else {
                    liLine.appendChild(nodeLine);
                }
                ulLines.appendChild(liLine);
            });
            liArea.appendChild(ulLines);
        } else {
            liArea.appendChild(nodeArea);
        }
        ulRoot.appendChild(liArea);
    });
    tree.appendChild(ulRoot);
}

// Helper to add Toggle Caret
function addCaret(liElement) {
    const span = document.createElement('span');
    span.className = 'caret';
    span.onclick = function () {
        this.parentElement.querySelector('.nested').classList.toggle('active');
        this.classList.toggle('caret-down');
    };
    liElement.appendChild(span);
}

// Helpers for buttons
window.expandAll = function () {
    document.querySelectorAll('.nested').forEach(el => el.classList.add('active'));
    document.querySelectorAll('.caret').forEach(el => el.classList.add('caret-down'));
};

window.collapseAll = function () {
    document.querySelectorAll('.nested').forEach(el => el.classList.remove('active'));
    document.querySelectorAll('.caret').forEach(el => el.classList.remove('caret-down'));
};

// --- EDIT & DELETE LOGIC ---

async function deleteItem(type, id, name) {
    if (!confirm(`¿Estás seguro de eliminar "${name}"? Esta acción borrará también todos sus hijos.`)) return;

    try {
        const endpointMap = {
            'Area': '/api/areas',
            'Line': '/api/lines',
            'Equipment': '/api/equipments',
            'System': '/api/systems',
            'Component': '/api/components'
        };

        const res = await fetch(`${endpointMap[type]}/${id}`, { method: 'DELETE' });
        if (res.ok) {
            // Determine what to reload based on type
            // Simple approach: Reload everything relevant or just Global Tree + Active Lists
            // For simplicity/safety: Reload Area list (if area) or just parent list
            // But since we have a split view (Pipeline vs Tree), improving UX is key.

            // Refresh all
            loadAreas(); // Pipeline
            loadGlobalTree(); // Tree
        } else {
            try {
                const err = await res.json();
                alert("Error al eliminar: " + err.error);
            } catch (parseErr) {
                console.error(parseErr);
                alert("Error crítico del servidor al eliminar (posible 404/500).");
            }
        }
    } catch (e) {
        alert("Error de red: " + e);
    }
}

function openEditModal(type, id, data) {
    const modal = document.getElementById('editModal');
    document.getElementById('editEntityId').value = id;
    document.getElementById('editEntityType').value = type;
    document.getElementById('editName').value = data.name;

    const extraDiv = document.getElementById('editExtraFields');
    extraDiv.innerHTML = '';

    if (type === 'Equipment') {
        extraDiv.innerHTML = `
                <label>TAG</label>
                <input type="text" id="editTag" value="${data.tag || ''}" required>
            `;
    }

    modal.showModal();
}

document.getElementById('editForm').onsubmit = async (e) => {
    e.preventDefault();
    const id = document.getElementById('editEntityId').value;
    const type = document.getElementById('editEntityType').value;
    const name = document.getElementById('editName').value;

    if (!id || id === 'undefined') {
        alert("Error: ID no válido. Recarga la página.");
        return;
    }

    const payload = { name };

    if (type === 'Equipment') {
        payload.tag = document.getElementById('editTag').value;
    }

    try {
        const endpointMap = {
            'Area': '/api/areas',
            'Line': '/api/lines',
            'Equipment': '/api/equipments',
            'System': '/api/systems',
            'Component': '/api/components'
        };

        const res = await fetch(`${endpointMap[type]}/${id}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });

        if (res.ok) {
            document.getElementById('editModal').close();
            loadAreas();
            loadGlobalTree();
        } else {
            // Try to get JSON, if fails, it's a server/network error
            try {
                const err = await res.json();
                alert("Error al editar: " + err.error);
            } catch (parseErr) {
                alert("Error crítico del servidor (posible error 500/404).");
            }
        }
    } catch (err) {
        alert("Error de red: " + err);
    }
};

function createNode(text, type, data, cfg, childCount) {
    cfg = cfg || { icon: 'fa-circle', css: 'comp', badge: type };

    const node = document.createElement('div');
    node.className = `tree-node level-${cfg.css}`;

    // Icon
    const icon = document.createElement('span');
    icon.className = `node-icon icon-${cfg.css}`;
    icon.innerHTML = `<i class="fas ${cfg.icon}"></i>`;

    // Label
    const label = document.createElement('span');
    label.className = 'node-label';
    label.textContent = text;

    // Badge
    const badge = document.createElement('span');
    badge.className = `node-badge badge-${cfg.css}`;
    badge.textContent = cfg.badge;

    // Child count
    const countEl = childCount > 0 ? (() => {
        const s = document.createElement('span');
        s.style.cssText = 'font-size:.7rem;color:#666;margin-left:6px;';
        s.textContent = `(${childCount})`;
        return s;
    })() : null;

    // Actions
    const actions = document.createElement('div');
    actions.className = 'node-actions';

    const btnNotice = document.createElement('span');
    btnNotice.innerHTML = '<i class="fas fa-clipboard-list"></i>';
    btnNotice.title = 'Crear Aviso';
    btnNotice.onclick = (e) => { e.stopPropagation(); if (data && data.id) window.location.href = `/avisos?create=true&type=${type}&id=${data.id}`; };

    const btnEdit = document.createElement('span');
    btnEdit.innerHTML = '<i class="fas fa-pen"></i>';
    btnEdit.title = 'Editar';
    btnEdit.onclick = (e) => { e.stopPropagation(); if (data && data.id) openEditModal(type, data.id, data); };

    const btnDel = document.createElement('span');
    btnDel.innerHTML = '<i class="fas fa-trash-alt"></i>';
    btnDel.title = 'Eliminar';
    btnDel.onclick = (e) => { e.stopPropagation(); if (data && data.id) deleteItem(type, data.id, data.name); };

    actions.appendChild(btnNotice);
    actions.appendChild(btnEdit);
    actions.appendChild(btnDel);

    node.appendChild(icon);
    node.appendChild(label);
    node.appendChild(badge);
    if (countEl) node.appendChild(countEl);
    node.appendChild(actions);

    return node;
}
