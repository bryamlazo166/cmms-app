let rotState = {
    areas: [],
    lines: [],
    equips: [],
    assets: []
};

function rQ(id) { return document.getElementById(id); }

function rNum(v) {
    if (v === '' || v === null || v === undefined) return null;
    const n = Number(v);
    return Number.isFinite(n) ? n : null;
}

function todayISO() {
    return new Date().toISOString().split('T')[0];
}

async function rFetch(url, opts) {
    const res = await fetch(url, opts);
    let data = {};
    try { data = await res.json(); } catch (e) { data = {}; }
    if (!res.ok || data.error) {
        throw new Error(data.error || `HTTP ${res.status}`);
    }
    return data;
}

function fillSelect(id, rows, placeholder) {
    rQ(id).innerHTML = `<option value="">${placeholder}</option>` + rows.map(r => `<option value="${r.id}">${r.name}</option>`).join('');
}

function setStatusPill(status) {
    const s = status || 'Disponible';
    if (s === 'Instalado') return '<span class="pill status-instalado">Instalado</span>';
    if (s === 'En Taller') return '<span class="pill status-taller">En Taller</span>';
    if (s === 'Baja') return '<span class="pill status-baja">Baja</span>';
    return '<span class="pill status-disponible">Disponible</span>';
}

function locationText(a) {
    if (!a.area_name && !a.line_name && !a.equipment_name) return '-';
    return `${a.area_name || '-'} / ${a.line_name || '-'} / ${a.equipment_name || '-'}`;
}

function renderKPIs(rows) {
    const total = rows.length;
    const installed = rows.filter(a => a.status === 'Instalado').length;
    const available = rows.filter(a => a.status === 'Disponible').length;
    const out = rows.filter(a => a.status === 'En Taller' || a.status === 'Baja').length;

    rQ('kpiTotal').textContent = total;
    rQ('kpiInstalled').textContent = installed;
    rQ('kpiAvailable').textContent = available;
    rQ('kpiOut').textContent = out;
}

function renderAssets(rows) {
    const search = (rQ('fSearch').value || '').trim().toLowerCase();
    const filtered = rows.filter(a => {
        if (!search) return true;
        const text = `${a.code || ''} ${a.name || ''} ${a.serial_number || ''}`.toLowerCase();
        return text.includes(search);
    });

    const tbody = rQ('assetsBody');
    if (!filtered.length) {
        tbody.innerHTML = '<tr><td colspan="8">No hay activos para mostrar.</td></tr>';
        return;
    }

    tbody.innerHTML = filtered.map(a => {
        const marcaModel = `${a.brand || '-'} / ${a.model || '-'}`;
        const actions = `
            <div class="actions-row">
                <button class="btn-micro" onclick="openAssetModal(${a.id})">Editar</button>
                <button class="btn-micro" onclick="openInstallModal(${a.id})">Instalar</button>
                <button class="btn-micro" onclick="removeAssetFromSite(${a.id})">Retirar</button>
                <button class="btn-micro" onclick="showAssetHistory(${a.id})">Historial</button>
                <button class="btn-micro" onclick="toggleAsset(${a.id})">Activo/Inactivo</button>
            </div>
        `;
        return `<tr>
            <td>${a.code || '-'}</td>
            <td>${a.name || '-'}</td>
            <td>${a.category || '-'}</td>
            <td>${marcaModel}</td>
            <td>${a.serial_number || '-'}</td>
            <td>${locationText(a)}</td>
            <td>${setStatusPill(a.status)}</td>
            <td>${actions}</td>
        </tr>`;
    }).join('');
}

function gatherFilters() {
    const p = new URLSearchParams();
    if (rQ('fArea').value) p.set('area_id', rQ('fArea').value);
    if (rQ('fLine').value) p.set('line_id', rQ('fLine').value);
    if (rQ('fEquip').value) p.set('equipment_id', rQ('fEquip').value);
    if (rQ('fStatus').value) p.set('status', rQ('fStatus').value);
    return p;
}

function syncFilterHierarchy() {
    const areaId = rQ('fArea').value;
    const lineId = rQ('fLine').value;

    const lines = rotState.lines.filter(l => !areaId || String(l.area_id) === String(areaId));
    fillSelect('fLine', lines, 'Linea: Todas');
    rQ('fLine').value = lines.some(l => String(l.id) === String(lineId)) ? lineId : '';

    const equips = rotState.equips.filter(e => !rQ('fLine').value || String(e.line_id) === String(rQ('fLine').value));
    fillSelect('fEquip', equips, 'Equipo: Todos');
}

async function loadHierarchy() {
    const [areas, lines, equips] = await Promise.all([
        rFetch('/api/areas'),
        rFetch('/api/lines'),
        rFetch('/api/equipments')
    ]);
    rotState.areas = areas;
    rotState.lines = lines;
    rotState.equips = equips;

    fillSelect('fArea', areas, 'Area: Todas');
    fillSelect('fLine', lines, 'Linea: Todas');
    fillSelect('fEquip', equips, 'Equipo: Todos');

    fillSelect('aArea', areas, 'Selecciona area');
    fillSelect('aLine', lines, 'Selecciona linea');
    fillSelect('aEquip', equips, 'Selecciona equipo');

    fillSelect('insArea', areas, 'Selecciona area');
    fillSelect('insLine', lines, 'Selecciona linea');
    fillSelect('insEquip', equips, 'Selecciona equipo');
}

async function reloadRotative() {
    try {
        const rows = await rFetch('/api/rotative-assets?' + gatherFilters().toString());
        rotState.assets = rows;
        renderKPIs(rows);
        renderAssets(rows);
    } catch (e) {
        alert('Error cargando activos rotativos: ' + e.message);
    }
}

function closeDialog(id) {
    rQ(id).close();
}

function openAssetModal(id) {
    rQ('assetForm').reset();
    rQ('assetId').value = '';
    rQ('assetModalTitle').innerHTML = '<i class="fas fa-plus"></i> Nuevo Activo Rotativo';

    if (!id) {
        rQ('assetModal').showModal();
        return;
    }

    const a = rotState.assets.find(x => x.id === id);
    if (!a) return;

    rQ('assetModalTitle').innerHTML = '<i class="fas fa-edit"></i> Editar Activo Rotativo';
    rQ('assetId').value = a.id;
    rQ('aName').value = a.name || '';
    rQ('aCategory').value = a.category || '';
    rQ('aBrand').value = a.brand || '';
    rQ('aModel').value = a.model || '';
    rQ('aSerial').value = a.serial_number || '';
    rQ('aStatus').value = a.status || 'Disponible';
    rQ('aArea').value = a.area_id || '';
    rQ('aLine').value = a.line_id || '';
    rQ('aEquip').value = a.equipment_id || '';
    rQ('aSystemId').value = a.system_id || '';
    rQ('aComponentId').value = a.component_id || '';
    rQ('aInstallDate').value = a.install_date || '';
    rQ('aNotes').value = a.notes || '';
    rQ('assetModal').showModal();
}

function openInstallModal(id) {
    const a = rotState.assets.find(x => x.id === id);
    if (!a) return;

    rQ('installForm').reset();
    rQ('installAssetId').value = id;
    rQ('insDate').value = todayISO();
    rQ('insArea').value = a.area_id || '';
    rQ('insLine').value = a.line_id || '';
    rQ('insEquip').value = a.equipment_id || '';
    rQ('insSystem').value = a.system_id || '';
    rQ('insComp').value = a.component_id || '';
    rQ('installModal').showModal();
}

async function saveAsset(e) {
    e.preventDefault();

    const id = rQ('assetId').value;
    const payload = {
        name: rQ('aName').value,
        category: rQ('aCategory').value || null,
        brand: rQ('aBrand').value || null,
        model: rQ('aModel').value || null,
        serial_number: rQ('aSerial').value || null,
        status: rQ('aStatus').value,
        area_id: rNum(rQ('aArea').value),
        line_id: rNum(rQ('aLine').value),
        equipment_id: rNum(rQ('aEquip').value),
        system_id: rNum(rQ('aSystemId').value),
        component_id: rNum(rQ('aComponentId').value),
        install_date: rQ('aInstallDate').value || null,
        notes: rQ('aNotes').value || null,
    };

    const url = id ? `/api/rotative-assets/${id}` : '/api/rotative-assets';
    const method = id ? 'PUT' : 'POST';

    await rFetch(url, {
        method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    });

    closeDialog('assetModal');
    await reloadRotative();
}

async function saveInstall(e) {
    e.preventDefault();

    const id = rQ('installAssetId').value;
    const payload = {
        event_date: rQ('insDate').value || todayISO(),
        area_id: rNum(rQ('insArea').value),
        line_id: rNum(rQ('insLine').value),
        equipment_id: rNum(rQ('insEquip').value),
        system_id: rNum(rQ('insSystem').value),
        component_id: rNum(rQ('insComp').value),
        comments: rQ('insComments').value || null,
    };

    await rFetch(`/api/rotative-assets/${id}/install`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    });

    closeDialog('installModal');
    await reloadRotative();
}

async function removeAssetFromSite(id) {
    if (!confirm('Deseas retirar este activo y dejarlo disponible?')) return;
    await rFetch(`/api/rotative-assets/${id}/remove`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ event_date: todayISO(), new_status: 'Disponible' })
    });
    await reloadRotative();
}

async function toggleAsset(id) {
    if (!confirm('Deseas cambiar activo/inactivo?')) return;
    await rFetch(`/api/rotative-assets/${id}`, { method: 'DELETE' });
    await reloadRotative();
}

async function showAssetHistory(id) {
    const rows = await rFetch(`/api/rotative-assets/${id}/history`);
    if (!rows.length) {
        alert('Sin historial.');
        return;
    }
    const txt = rows.slice(0, 12).map(h => `${h.event_date} | ${h.event_type} | ${h.area_name || '-'} / ${h.line_name || '-'} / ${h.equipment_name || '-'}${h.comments ? ' | ' + h.comments : ''}`).join('\n');
    alert(txt);
}

async function initRotative() {
    await loadHierarchy();
    await reloadRotative();

    rQ('assetForm').addEventListener('submit', saveAsset);
    rQ('installForm').addEventListener('submit', saveInstall);

    rQ('fArea').addEventListener('change', () => {
        syncFilterHierarchy();
        reloadRotative();
    });
    rQ('fLine').addEventListener('change', reloadRotative);
    rQ('fEquip').addEventListener('change', reloadRotative);
    rQ('fStatus').addEventListener('change', reloadRotative);
    rQ('fSearch').addEventListener('input', () => renderAssets(rotState.assets));
}

document.addEventListener('DOMContentLoaded', () => {
    initRotative().catch(e => alert('No se pudo inicializar activos rotativos: ' + e.message));
});
