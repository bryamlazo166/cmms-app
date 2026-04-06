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
                <button class="btn-micro" onclick="openSpecModal(${a.id})">Ficha</button>
                <button class="btn-micro" onclick="openInstallModal(${a.id})">Instalar</button>
                <button class="btn-micro" onclick="removeAssetFromSite(${a.id})">Retirar</button>
                <button class="btn-micro" style="background:rgba(48,209,88,.15);color:#5cd870" onclick="openBomModal(${a.id})">Repuestos</button>
                ${a.status === 'Instalado' ? `<button class="btn-micro" style="background:rgba(255,159,10,.15);color:#FFB340" onclick="openSwapModal(${a.id})">Swap</button>` : ''}
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

function syncAreaLineEquip(areaIdEl, lineIdEl, equipIdEl, linePlaceholder, equipPlaceholder) {
    const areaEl = rQ(areaIdEl);
    const lineEl = rQ(lineIdEl);
    const equipEl = rQ(equipIdEl);

    const areaId = areaEl.value;
    const keepLine = lineEl.value;
    const keepEquip = equipEl.value;

    const lines = rotState.lines.filter(l => !areaId || String(l.area_id) === String(areaId));
    fillSelect(lineIdEl, lines, linePlaceholder);
    lineEl.value = lines.some(l => String(l.id) === String(keepLine)) ? String(keepLine) : '';

    const equips = rotState.equips.filter(e => !lineEl.value || String(e.line_id) === String(lineEl.value));
    fillSelect(equipIdEl, equips, equipPlaceholder);
    equipEl.value = equips.some(e => String(e.id) === String(keepEquip)) ? String(keepEquip) : '';
}

function setAreaLineEquip(areaIdEl, lineIdEl, equipIdEl, areaValue, lineValue, equipValue, linePlaceholder, equipPlaceholder) {
    rQ(areaIdEl).value = areaValue || '';
    syncAreaLineEquip(areaIdEl, lineIdEl, equipIdEl, linePlaceholder, equipPlaceholder);

    if (lineValue) {
        rQ(lineIdEl).value = String(lineValue);
        syncAreaLineEquip(areaIdEl, lineIdEl, equipIdEl, linePlaceholder, equipPlaceholder);
    }
    if (equipValue) {
        rQ(equipIdEl).value = String(equipValue);
    }
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
    rQ('aStatus').value = 'Disponible';

    setAreaLineEquip('aArea', 'aLine', 'aEquip', '', '', '', 'Selecciona linea', 'Selecciona equipo');

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

    setAreaLineEquip('aArea', 'aLine', 'aEquip', a.area_id, a.line_id, a.equipment_id, 'Selecciona linea', 'Selecciona equipo');

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

    setAreaLineEquip('insArea', 'insLine', 'insEquip', a.area_id, a.line_id, a.equipment_id, 'Selecciona linea', 'Selecciona equipo');

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
    const asset = rotState.assets.find(a => a.id === id);
    const title = document.getElementById('historyTitle');
    title.innerHTML = `<i class="fas fa-history" style="color:#5AC8FA;margin-right:8px"></i>Historial — ${asset ? (asset.code || '') + ' ' + (asset.name || '') : 'Activo'}`;

    const container = document.getElementById('historyTimeline');
    try {
        const data = await rFetch(`/api/rotative-assets/${id}/full-history`);
        const events = data.events || [];

        if (!events.length) {
            container.innerHTML = '<p style="color:rgba(255,255,255,.35);text-align:center;padding:20px">Sin historial registrado.</p>';
        } else {
            container.innerHTML = events.map(e => {
                const dotClass = `tl-dot-${e.category}`;
                const typeClass = `tl-type-${e.category}`;
                return `<div class="tl-item">
                    <div class="tl-dot ${dotClass}"></div>
                    <div class="tl-body">
                        <div><span class="tl-type ${typeClass}">${e.category} — ${e.type || ''}</span><span class="tl-date">${e.date || '-'}</span></div>
                        ${e.location ? `<div class="tl-location"><i class="fas fa-map-marker-alt" style="margin-right:4px"></i>${e.location}</div>` : ''}
                        ${e.description ? `<div class="tl-comment">${e.description}</div>` : ''}
                        ${e.status ? `<div style="margin-top:2px"><span style="font-size:.72rem;padding:1px 6px;border-radius:4px;background:rgba(255,255,255,.08);color:rgba(255,255,255,.50)">${e.status}</span></div>` : ''}
                    </div>
                </div>`;
            }).join('');
        }

        // Show BOM summary if available
        if (data.bom && data.bom.length) {
            container.innerHTML += `<div style="border-top:1px solid rgba(255,255,255,.08);padding-top:12px;margin-top:12px">
                <h4 style="color:rgba(255,255,255,.60);font-size:.85rem;margin:0 0 8px"><i class="fas fa-boxes" style="margin-right:5px"></i>Repuestos asociados (${data.bom.length})</h4>
                ${data.bom.map(b => `<div style="font-size:.82rem;color:rgba(255,255,255,.65);padding:3px 0">${b.item_code || '-'} ${b.item_name || '-'} <span style="color:rgba(255,255,255,.35)">(x${b.quantity} ${b.category})</span> <span style="color:${(b.item_stock||0)>0?'#30D158':'#FF453A'};font-size:.75rem">Stock: ${b.item_stock||0}</span></div>`).join('')}
            </div>`;
        }
    } catch (e) {
        container.innerHTML = `<p style="color:#FF6B61;text-align:center;padding:20px">Error: ${e.message}</p>`;
    }
    document.getElementById('historyModal').showModal();
}

// ── BOM (Bill of Materials) ──────────────────────────────────────────────────

async function openBomModal(assetId) {
    const asset = rotState.assets.find(a => a.id === assetId);
    document.getElementById('bomTitle').innerHTML = `<i class="fas fa-boxes" style="color:#30D158;margin-right:8px"></i>Repuestos — ${asset ? (asset.code || '') + ' ' + (asset.name || '') : 'Activo'}`;
    document.getElementById('bomAssetId').value = assetId;

    // Load warehouse items for selector
    try {
        const items = await rFetch('/api/warehouse');
        const sel = document.getElementById('bomItem');
        sel.innerHTML = '<option value="">Seleccione repuesto</option>' +
            items.map(i => `<option value="${i.id}">${i.code} ${i.name}</option>`).join('');
    } catch (_) {}

    await loadBomItems(assetId);
    document.getElementById('bomModal').showModal();
}

async function loadBomItems(assetId) {
    const items = await rFetch(`/api/rotative-assets/${assetId}/bom`);
    const container = document.getElementById('bomList');
    if (!items.length) {
        container.innerHTML = '<p style="color:rgba(255,255,255,.35);text-align:center;padding:12px">Sin repuestos asignados. Agrega repuestos del almacen.</p>';
        return;
    }

    container.innerHTML = '<table style="width:100%;border-collapse:collapse"><thead><tr>' +
        '<th style="padding:6px 8px;font-size:.72rem;color:rgba(255,255,255,.40);text-align:left">Codigo</th>' +
        '<th style="padding:6px 8px;font-size:.72rem;color:rgba(255,255,255,.40);text-align:left">Repuesto</th>' +
        '<th style="padding:6px 8px;font-size:.72rem;color:rgba(255,255,255,.40);text-align:center">Cat.</th>' +
        '<th style="padding:6px 8px;font-size:.72rem;color:rgba(255,255,255,.40);text-align:center">Cant</th>' +
        '<th style="padding:6px 8px;font-size:.72rem;color:rgba(255,255,255,.40);text-align:center">Stock</th>' +
        '<th style="padding:6px 8px;font-size:.72rem;color:rgba(255,255,255,.40)">Nota</th>' +
        '<th></th></tr></thead><tbody>' +
        items.map(b => {
            const isLinked = b.is_linked;
            const stockColor = (b.item_stock || 0) > 0 ? '#30D158' : '#FF453A';
            const catColor = b.category === 'ELECTRICO' ? '#5AC8FA' : b.category === 'CONSUMIBLE' ? '#FF9F0A' : '#30D158';
            const codeDisplay = isLinked ? (b.item_code || '-') : '<span style="color:#FF9F0A;font-size:.70rem">LIBRE</span>';
            const stockDisplay = isLinked ? `<span style="color:${stockColor}">${b.item_stock || 0} ${b.item_unit || ''}</span>` : '<span style="color:rgba(255,255,255,.25)">-</span>';
            return `<tr style="border-bottom:1px solid rgba(255,255,255,.05)">
                <td style="padding:6px 8px;font-size:.82rem;color:#0A84FF">${codeDisplay}</td>
                <td style="padding:6px 8px;font-size:.82rem;color:rgba(255,255,255,.80)">${b.item_name || b.free_text || '-'}</td>
                <td style="padding:6px 8px;font-size:.72rem;text-align:center;color:${catColor}">${b.category}</td>
                <td style="padding:6px 8px;font-size:.82rem;text-align:center">${b.quantity}</td>
                <td style="padding:6px 8px;font-size:.82rem;text-align:center">${stockDisplay}</td>
                <td style="padding:6px 8px;font-size:.78rem;color:rgba(255,255,255,.45)">${b.notes || '-'}</td>
                <td><button onclick="removeBomItem(${b.id})" style="background:rgba(255,69,58,.12);border:none;border-radius:4px;color:#FF6B61;width:24px;height:24px;cursor:pointer;font-size:.72rem"><i class="fas fa-trash"></i></button></td>
            </tr>`;
        }).join('') + '</tbody></table>';
}

function toggleBomMode() {
    const mode = document.querySelector('input[name="bomMode"]:checked').value;
    document.getElementById('bomItemContainer').style.display = mode === 'warehouse' ? '' : 'none';
    document.getElementById('bomFreeContainer').style.display = mode === 'free' ? '' : 'none';
}

async function addBomItem() {
    const assetId = document.getElementById('bomAssetId').value;
    const mode = document.querySelector('input[name="bomMode"]:checked').value;
    const payload = {
        category: document.getElementById('bomCat').value,
        quantity: Number(document.getElementById('bomQty').value || 1),
        notes: document.getElementById('bomNote').value || null,
    };

    if (mode === 'warehouse') {
        const wiId = document.getElementById('bomItem').value;
        if (!wiId) { alert('Seleccione un repuesto.'); return; }
        payload.warehouse_item_id = wiId;
    } else {
        const freeText = document.getElementById('bomFreeText').value.trim();
        if (!freeText) { alert('Escriba el nombre del repuesto.'); return; }
        payload.free_text = freeText;
    }

    try {
        await rFetch(`/api/rotative-assets/${assetId}/bom`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        document.getElementById('bomNote').value = '';
        document.getElementById('bomFreeText').value = '';
        await loadBomItems(assetId);
    } catch (e) { alert(e.message); }
}

async function removeBomItem(bomId) {
    if (!confirm('Quitar este repuesto de la lista?')) return;
    const assetId = document.getElementById('bomAssetId').value;
    await rFetch(`/api/rotative-assets/bom/${bomId}`, { method: 'DELETE' });
    await loadBomItems(assetId);
}

// ── Swap ─────────────────────────────────────────────────────────────────────

async function openSwapModal(assetId) {
    const asset = rotState.assets.find(a => a.id === assetId);
    if (!asset) return;
    document.getElementById('swapRemoveId').value = assetId;
    document.getElementById('swapRemoveLabel').textContent = `${asset.code} ${asset.name} — ${asset.equipment_name || ''}`;
    document.getElementById('swapReason').value = '';

    // Load available assets (Disponible status) for replacement
    const available = rotState.assets.filter(a => a.id !== assetId && a.status === 'Disponible' && a.is_active);
    const sel = document.getElementById('swapInstallId');
    sel.innerHTML = '<option value="">Seleccione reemplazo</option>' +
        available.map(a => `<option value="${a.id}">${a.code} ${a.name} (${a.category || '-'})</option>`).join('');

    document.getElementById('swapModal').showModal();
}

async function executeSwap() {
    const removeId = document.getElementById('swapRemoveId').value;
    const installId = document.getElementById('swapInstallId').value;
    if (!installId) { alert('Seleccione un activo de reemplazo.'); return; }

    try {
        await rFetch('/api/rotative-assets/swap', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                remove_asset_id: Number(removeId),
                install_asset_id: Number(installId),
                old_status: document.getElementById('swapOldStatus').value,
                reason: document.getElementById('swapReason').value || null,
            })
        });
        closeDialog('swapModal');
        alert('Swap realizado correctamente.');
        await reloadRotative();
    } catch (e) { alert('Error: ' + e.message); }
}

async function openSpecModal(id) {
    const a = rotState.assets.find(x => x.id === id);
    if (!a) return;

    rQ('specForm').reset();
    rQ('specAssetId').value = id;
    rQ('specId').value = '';
    rQ('specAssetLabel').textContent = `${a.code || ''} ${a.name || ''}`.trim();

    await Promise.all([loadSpecs(id), loadRADocLinks(id)]);
    rQ('specModal').showModal();
}

async function loadSpecs(assetId) {
    const rows = await rFetch(`/api/rotative-assets/${assetId}/specs`);
    const tbody = rQ('specBody');

    if (!rows.length) {
        tbody.innerHTML = '<tr><td colspan="4">Sin datos de ficha tecnica.</td></tr>';
        return;
    }

    tbody.innerHTML = rows.map(s => `
        <tr>
            <td>${s.key_name || '-'}</td>
            <td>${s.value_text || '-'}</td>
            <td>${s.unit || '-'}</td>
            <td>
                <button class="btn-micro" onclick="editSpec(${s.id}, '${String(s.key_name || '').replace(/'/g, "\\'")}', '${String(s.value_text || '').replace(/'/g, "\\'")}', '${String(s.unit || '').replace(/'/g, "\\'")}')">Editar</button>
                <button class="btn-micro" onclick="deleteSpec(${s.id})">Eliminar</button>
            </td>
        </tr>
    `).join('');
}

function editSpec(id, keyName, valueText, unit) {
    rQ('specId').value = id;
    rQ('specKey').value = keyName || '';
    rQ('specValue').value = valueText || '';
    rQ('specUnit').value = unit || '';
}

async function deleteSpec(specId) {
    if (!confirm('Deseas eliminar esta caracteristica?')) return;
    await rFetch(`/api/rotative-assets/specs/${specId}`, { method: 'DELETE' });
    await loadSpecs(rQ('specAssetId').value);
}

async function saveSpec(e) {
    e.preventDefault();

    const assetId = rQ('specAssetId').value;
    const payload = {
        id: rNum(rQ('specId').value),
        key_name: (rQ('specKey').value || '').trim(),
        value_text: (rQ('specValue').value || '').trim(),
        unit: (rQ('specUnit').value || '').trim() || null,
    };

    await rFetch(`/api/rotative-assets/${assetId}/specs`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    });

    rQ('specId').value = '';
    rQ('specKey').value = '';
    rQ('specValue').value = '';
    rQ('specUnit').value = '';
    await loadSpecs(assetId);
}

// ── Document Links for Rotative Assets ────────────────────────────────────

async function loadRADocLinks(assetId) {
    try {
        const res = await rFetch(`/api/doc-links/rotative_asset/${assetId}`);
        const docs = Array.isArray(res) ? res : [];
        const container = rQ('raDocsList');
        if (!docs.length) {
            container.innerHTML = '<span style="color:#666;font-size:.80rem">Sin documentos.</span>';
            return;
        }
        const typeIcons = { plano: 'fa-drafting-compass', manual: 'fa-book', informe: 'fa-file-alt', otro: 'fa-link' };
        container.innerHTML = docs.map(d => `
            <div style="display:flex;align-items:center;gap:8px;padding:5px 8px;background:#252526;border-radius:5px;margin-bottom:4px;font-size:.82rem">
                <i class="fas ${typeIcons[d.doc_type] || 'fa-link'}" style="color:#30D158;width:16px"></i>
                <a href="${d.url}" target="_blank" style="color:#5AC8FA;text-decoration:none;flex:1">${d.title}</a>
                <span style="color:#666;font-size:.70rem;text-transform:uppercase">${d.doc_type || ''}</span>
                <span onclick="deleteRADocLink(${d.id})" style="cursor:pointer;color:#FF453A;font-size:.70rem"><i class="fas fa-times"></i></span>
            </div>
        `).join('');
    } catch (_) {
        rQ('raDocsList').innerHTML = '<span style="color:#FF6B61;font-size:.80rem">Error.</span>';
    }
}

async function addRADocLink() {
    const assetId = rQ('specAssetId').value;
    const title = (rQ('raDocTitle').value || '').trim();
    const url = (rQ('raDocUrl').value || '').trim();
    const docType = rQ('raDocType').value;
    if (!title || !url) { alert('Ingresa titulo y URL.'); return; }
    await rFetch(`/api/doc-links/rotative_asset/${assetId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title, url, doc_type: docType })
    });
    rQ('raDocTitle').value = '';
    rQ('raDocUrl').value = '';
    await loadRADocLinks(assetId);
}

async function deleteRADocLink(docId) {
    if (!confirm('Eliminar este documento?')) return;
    const assetId = rQ('specAssetId').value;
    await rFetch(`/api/doc-links/${docId}`, { method: 'DELETE' });
    await loadRADocLinks(assetId);
}

async function initRotative() {
    await loadHierarchy();
    await reloadRotative();

    rQ('assetForm').addEventListener('submit', saveAsset);
    rQ('installForm').addEventListener('submit', saveInstall);
    rQ('specForm').addEventListener('submit', saveSpec);

    rQ('fArea').addEventListener('change', () => {
        syncAreaLineEquip('fArea', 'fLine', 'fEquip', 'Linea: Todas', 'Equipo: Todos');
        reloadRotative();
    });
    rQ('fLine').addEventListener('change', () => {
        syncAreaLineEquip('fArea', 'fLine', 'fEquip', 'Linea: Todas', 'Equipo: Todos');
        reloadRotative();
    });
    rQ('fEquip').addEventListener('change', reloadRotative);
    rQ('fStatus').addEventListener('change', reloadRotative);
    rQ('fSearch').addEventListener('input', () => renderAssets(rotState.assets));

    rQ('aArea').addEventListener('change', () => syncAreaLineEquip('aArea', 'aLine', 'aEquip', 'Selecciona linea', 'Selecciona equipo'));
    rQ('aLine').addEventListener('change', () => syncAreaLineEquip('aArea', 'aLine', 'aEquip', 'Selecciona linea', 'Selecciona equipo'));

    rQ('insArea').addEventListener('change', () => syncAreaLineEquip('insArea', 'insLine', 'insEquip', 'Selecciona linea', 'Selecciona equipo'));
    rQ('insLine').addEventListener('change', () => syncAreaLineEquip('insArea', 'insLine', 'insEquip', 'Selecciona linea', 'Selecciona equipo'));
}

document.addEventListener('DOMContentLoaded', () => {
    initRotative().catch(e => alert('No se pudo inicializar activos rotativos: ' + e.message));
});
