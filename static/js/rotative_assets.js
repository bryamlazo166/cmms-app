let rotState = {
    areas: [],
    lines: [],
    equips: [],
    systems: [],
    components: [],
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
    if (s === 'En Proveedor') return '<span class="pill status-proveedor">En Proveedor</span>';
    if (s === 'Baja') return '<span class="pill status-baja">Baja</span>';
    return '<span class="pill status-disponible">Disponible</span>';
}

function escHtml(v) {
    return String(v == null ? '' : v)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

// Un activo fuera de servicio no tiene ubicacion en planta: lo util ahi es
// saber donde esta fisicamente (taller, proveedor) y desde cuando.
function locationText(a) {
    if (a.status === 'En Taller' || a.status === 'En Proveedor') {
        const where = a.status === 'En Proveedor'
            ? (a.service_provider_name || 'Proveedor externo')
            : 'Taller interno';
        const since = a.out_since ? ` desde ${a.out_since}` : '';
        const back = a.expected_return_date
            ? ` <span style="color:#9ab0cb">· vuelve ${a.expected_return_date}</span>` : '';
        return `<span style="color:#ffd76f">${escHtml(where)}${since}</span>${back}`;
    }
    if (!a.area_name && !a.line_name && !a.equipment_name) return '-';
    return `${a.area_name || '-'} / ${a.line_name || '-'} / ${a.equipment_name || '-'}`;
}

function renderKPIs(rows) {
    const count = s => rows.filter(a => a.status === s).length;
    rQ('kpiTotal').textContent = rows.length;
    rQ('kpiInstalled').textContent = count('Instalado');
    rQ('kpiAvailable').textContent = count('Disponible');
    rQ('kpiWorkshop').textContent = count('En Taller');
    rQ('kpiProvider').textContent = count('En Proveedor');
    rQ('kpiOut').textContent = count('Baja');
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
        const installed = a.status === 'Instalado';
        const outForService = a.status === 'En Taller' || a.status === 'En Proveedor';
        // Cada estado admite acciones distintas: un activo instalado se cambia
        // o se retira; uno en taller se recibe de vuelta; uno disponible se instala.
        const actions = `
            <div class="actions-row">
                ${installed ? `<button class="btn-micro" style="background:rgba(255,159,10,.15);color:#FFB340;border-color:#FF9F0A" onclick="openSwapModal(${a.id})"><i class="fas fa-exchange-alt"></i> Cambiar</button>` : ''}
                ${installed ? `<button class="btn-micro" style="background:rgba(255,69,58,.12);color:#FF8078" onclick="openRemoveModal(${a.id})">Retirar</button>` : ''}
                ${outForService ? `<button class="btn-micro" style="background:rgba(48,209,88,.15);color:#5cd870;border-color:#30D158" onclick="openReturnModal(${a.id})"><i class="fas fa-truck-loading"></i> Recibir</button>` : ''}
                ${!installed && a.status !== 'Baja' ? `<button class="btn-micro" onclick="openInstallModal(${a.id})">Instalar</button>` : ''}
                <button class="btn-micro" onclick="openAssetModal(${a.id})">Editar</button>
                <button class="btn-micro" onclick="openSpecModal(${a.id})">Ficha</button>
                <button class="btn-micro" style="background:rgba(48,209,88,.15);color:#5cd870" onclick="openBomModal(${a.id})">Repuestos</button>
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
    const [areas, lines, equips, systems, components] = await Promise.all([
        rFetch('/api/areas'),
        rFetch('/api/lines'),
        rFetch('/api/equipments'),
        rFetch('/api/systems'),
        rFetch('/api/components')
    ]);
    rotState.areas = areas;
    rotState.lines = lines;
    rotState.equips = equips;
    rotState.systems = systems;
    rotState.components = components;

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

function fillSystemSelect(selectId, equipmentId, selectedId) {
    const sel = rQ(selectId);
    if (!sel) return;
    if (!equipmentId) {
        sel.innerHTML = '<option value="">- Selecciona equipo primero -</option>';
        return;
    }
    const systems = rotState.systems.filter(s => String(s.equipment_id) === String(equipmentId));
    sel.innerHTML = '<option value="">- Sin sistema -</option>'
        + systems.map(s => `<option value="${s.id}">${s.name}</option>`).join('');
    if (selectedId && systems.some(s => String(s.id) === String(selectedId))) {
        sel.value = String(selectedId);
    }
}

function fillComponentSelect(selectId, systemId, selectedId) {
    const sel = rQ(selectId);
    if (!sel) return;
    if (!systemId) {
        sel.innerHTML = '<option value="">- Selecciona sistema primero -</option>';
        return;
    }
    const components = rotState.components.filter(c => String(c.system_id) === String(systemId));
    sel.innerHTML = '<option value="">- Sin componente -</option>'
        + components.map(c => `<option value="${c.id}">${c.name}</option>`).join('');
    if (selectedId && components.some(c => String(c.id) === String(selectedId))) {
        sel.value = String(selectedId);
    }
}

async function reloadRotative() {
    try {
        const rows = await rFetch('/api/rotative-assets?' + gatherFilters().toString());
        rotState.assets = rows;
        renderKPIs(rows);
        renderAssets(rows);
        loadPredictiveTracking();
    } catch (e) {
        alert('Error cargando activos rotativos: ' + e.message);
    }
}

// ── Seguimiento Predictivo (motores, bombas, motorreductores, reductoras) ──
const PRED_ICON = { ROJO: '🔴', AMARILLO: '🟠', VERDE: '🟢', PENDIENTE: '⚪' };

async function loadPredictiveTracking() {
    const tbody = document.getElementById('predBody');
    if (!tbody) return;
    try {
        const data = await rFetch('/api/rotative-assets/predictive-tracking');
        const s = data.summary || {};
        const set = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };
        set('predRojo', s.rojo != null ? s.rojo : 0);
        set('predAmarillo', s.amarillo != null ? s.amarillo : 0);
        set('predVerde', s.verde != null ? s.verde : 0);
        set('predSinMedidas', s.sin_medidas != null ? s.sin_medidas : 0);

        const rows = data.assets || [];
        if (!rows.length) {
            tbody.innerHTML = '<tr><td colspan="5" style="color:#9ab0cb;">Sin activos de categorias predictivas (motor, bomba, motorreductor, caja reductora).</td></tr>';
            return;
        }
        tbody.innerHTML = rows.map(a => {
            const sem = a.overall
                ? `${PRED_ICON[a.overall] || '⚪'} ${a.overall}`
                : '<span style="color:#FF9F0A;">⚠ SIN MEDIDAS</span>';
            const medidas = (a.measures || []).map(m =>
                `<span style="display:inline-block;margin:1px 6px 1px 0;padding:2px 8px;border-radius:10px;font-size:.72rem;` +
                `background:${m.status === 'ROJO' ? 'rgba(255,69,58,.15)' : m.status === 'AMARILLO' ? 'rgba(255,159,10,.15)' : m.status === 'VERDE' ? 'rgba(48,209,88,.12)' : 'rgba(255,255,255,.06)'};` +
                `border:1px solid ${m.status === 'ROJO' ? '#FF453A' : m.status === 'AMARILLO' ? '#FF9F0A' : m.status === 'VERDE' ? '#30D158' : '#555'};">` +
                `${PRED_ICON[m.status] || '⚪'} ${m.tipo}${m.point_code ? ' ' + m.point_code : ''} · ult: ${m.last || '-'} · prox: ${m.next || '-'}</span>`
            ).join('') || '<span style="color:#9ab0cb;font-size:.78rem;">Configure megado (pagina Motores Electricos) o un punto de monitoreo vinculado a este activo</span>';
            return `<tr>
                <td>${sem}</td>
                <td style="font-weight:600;color:#5AC8FA;">${a.code || '-'}</td>
                <td>${a.name}</td>
                <td>${a.category}</td>
                <td>${medidas}</td>
            </tr>`;
        }).join('');
    } catch (e) {
        tbody.innerHTML = `<tr><td colspan="5" style="color:#FF453A;">Error cargando seguimiento: ${e.message}</td></tr>`;
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
    fillSystemSelect('aSystemId', null);
    fillComponentSelect('aComponentId', null);

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

    fillSystemSelect('aSystemId', a.equipment_id, a.system_id);
    fillComponentSelect('aComponentId', a.system_id, a.component_id);
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

    fillSystemSelect('insSystem', a.equipment_id, a.system_id);
    fillComponentSelect('insComp', a.system_id, a.component_id);
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

// ── Retiro con destino (taller / proveedor / baja / stand-by) ───────────────
// Un rotativo casi nunca sale "y ya": sale porque fallo y va al taller, se
// manda a un tercero, o se descarta. El destino decide su estado y si sigue
// contando como repuesto disponible.

let _providersCache = null;

async function loadProvidersInto(selectId) {
    const sel = rQ(selectId);
    if (!sel) return;
    if (!_providersCache) {
        try {
            const rows = await rFetch('/api/providers');
            _providersCache = (Array.isArray(rows) ? rows : []).filter(p => p.is_active !== false);
        } catch (e) { _providersCache = []; }
    }
    sel.innerHTML = '<option value="">Seleccione proveedor</option>' +
        _providersCache.map(p => `<option value="${p.id}">${escHtml(p.name)}${p.specialty ? ' — ' + escHtml(p.specialty) : ''}</option>`).join('');
}

const DEST_HINTS = {
    TALLER: 'Queda "En Taller". Sigue siendo tuyo y volvera al pool de repuestos cuando lo recibas reparado.',
    PROVEEDOR: 'Queda "En Proveedor". Registra a quien se envio para poder reclamar el servicio.',
    BAJA: 'Queda "Baja". No volvera a ofrecerse como reemplazo en ningun cambio.',
    STANDBY: 'Queda "Disponible": sale operativo y puede instalarse en otro equipo de inmediato.',
};

function _syncDestUI(dest, providerBoxId, returnBoxId, hintId) {
    const provBox = rQ(providerBoxId);
    const retBox = rQ(returnBoxId);
    if (provBox) provBox.style.display = dest === 'PROVEEDOR' ? '' : 'none';
    if (retBox) retBox.style.display = (dest === 'TALLER' || dest === 'PROVEEDOR') ? '' : 'none';
    const hint = hintId ? rQ(hintId) : null;
    if (hint) hint.textContent = DEST_HINTS[dest] || '';
}

function onRemoveDestChange() {
    const dest = document.querySelector('input[name="remDest"]:checked').value;
    _syncDestUI(dest, 'removeProviderBox', 'removeReturnBox', 'removeHint');
}

function onSwapDestChange() {
    const dest = document.querySelector('input[name="swapDest"]:checked').value;
    _syncDestUI(dest, 'swapProviderBox', 'swapReturnBox', null);
}

// Si el activo se va al taller, lo primero que se pregunta el tecnico es si
// tiene los repuestos internos (rodamientos, retenes) para repararlo ya.
async function renderBomSummary(assetId, containerId) {
    const box = rQ(containerId);
    if (!box) return;
    box.innerHTML = '';
    try {
        const items = await rFetch(`/api/rotative-assets/${assetId}/bom`);
        if (!items.length) {
            box.innerHTML = '<div style="font-size:.76rem;color:rgba(255,255,255,.35)">Sin repuestos cargados para este activo. Agregalos desde el boton "Repuestos".</div>';
            return;
        }
        const conStock = items.filter(i => i.is_linked && (i.item_stock || 0) >= (i.quantity || 1));
        box.innerHTML =
            `<div style="font-size:.72rem;color:rgba(255,255,255,.40);text-transform:uppercase;font-weight:700;margin-bottom:5px">
                Repuestos del activo — ${conStock.length}/${items.length} con stock suficiente
            </div>` +
            items.map(i => {
                const stock = i.item_stock || 0;
                const ok = i.is_linked && stock >= (i.quantity || 1);
                const color = !i.is_linked ? 'rgba(255,255,255,.35)' : (ok ? '#5cd870' : '#FF8078');
                const stockTxt = i.is_linked ? `stock ${stock} ${escHtml(i.item_unit || '')}` : 'sin vincular al almacen';
                return `<div style="font-size:.78rem;color:rgba(255,255,255,.65);padding:2px 0">
                    <i class="fas fa-${ok ? 'check' : 'exclamation'}-circle" style="color:${color};margin-right:5px"></i>
                    ${escHtml(i.item_name || i.free_text || '-')} <span style="color:rgba(255,255,255,.35)">x${i.quantity}</span>
                    <span style="color:${color};font-size:.74rem;margin-left:6px">${stockTxt}</span>
                </div>`;
            }).join('');
    } catch (e) {
        box.innerHTML = '';
    }
}

async function openRemoveModal(id) {
    const a = rotState.assets.find(x => x.id === id);
    if (!a) return;
    rQ('removeAssetId').value = id;
    rQ('removeLabel').innerHTML =
        `<b>${escHtml(a.code)}</b> ${escHtml(a.name)}<br>` +
        `<span style="color:rgba(255,255,255,.55);font-size:.80rem">Instalado en: ${locationText(a)}</span>`;
    rQ('removeDate').value = todayISO();
    rQ('removeExpectedReturn').value = '';
    rQ('removeReason').value = '';
    rQ('removeComments').value = '';
    document.querySelector('input[name="remDest"][value="TALLER"]').checked = true;
    await loadProvidersInto('removeProviderId');
    onRemoveDestChange();
    rQ('removeModal').showModal();
    renderBomSummary(id, 'removeBom');
}

async function executeRemove() {
    const id = rQ('removeAssetId').value;
    const dest = document.querySelector('input[name="remDest"]:checked').value;
    if (dest === 'PROVEEDOR' && !rQ('removeProviderId').value) {
        alert('Selecciona el proveedor externo al que se envia el activo.');
        return;
    }
    if (dest === 'BAJA' && !confirm('La baja es definitiva: el activo dejara de ofrecerse como reemplazo. Continuar?')) return;

    try {
        await rFetch(`/api/rotative-assets/${id}/remove`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                event_date: rQ('removeDate').value || todayISO(),
                destination: dest,
                provider_id: rNum(rQ('removeProviderId').value),
                expected_return_date: rQ('removeExpectedReturn').value || null,
                reason: rQ('removeReason').value || null,
                comments: rQ('removeComments').value || null,
            })
        });
        closeDialog('removeModal');
        await reloadRotative();
    } catch (e) { alert('Error: ' + e.message); }
}

async function openReturnModal(id) {
    const a = rotState.assets.find(x => x.id === id);
    if (!a) return;
    rQ('returnAssetId').value = id;
    const where = a.status === 'En Proveedor'
        ? (a.service_provider_name || 'proveedor externo') : 'taller interno';
    rQ('returnLabel').innerHTML =
        `<b>${escHtml(a.code)}</b> ${escHtml(a.name)}<br>` +
        `<span style="color:rgba(255,255,255,.55);font-size:.80rem">En ${escHtml(where)}` +
        `${a.out_since ? ' desde ' + a.out_since : ''}` +
        `${a.out_reason ? ' · Motivo: ' + escHtml(a.out_reason) : ''}</span>`;
    rQ('returnDate').value = todayISO();
    rQ('returnStatus').value = 'Disponible';
    rQ('returnWork').value = '';
    rQ('returnModal').showModal();
}

async function executeReturn() {
    const id = rQ('returnAssetId').value;
    try {
        await rFetch(`/api/rotative-assets/${id}/return-to-service`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                event_date: rQ('returnDate').value || todayISO(),
                new_status: rQ('returnStatus').value,
                work_done: rQ('returnWork').value || null,
            })
        });
        closeDialog('returnModal');
        await reloadRotative();
    } catch (e) { alert('Error: ' + e.message); }
}

async function toggleAsset(id) {
    if (!confirm('Deseas cambiar activo/inactivo?')) return;
    await rFetch(`/api/rotative-assets/${id}`, { method: 'DELETE' });
    await reloadRotative();
}

// Estado del historial del rotativo (para filtros y toggle vista)
// showEnv: incluir los eventos del equipo donde esta montado (chumaceras,
// fajas, rondas de inspeccion). Apagado por defecto — son del sistema de
// transmision, no del rotativo, y tapaban su historial real.
let _rotHistoryState = { events: [], bom: [], counts: {}, view: 'timeline', category: 'ALL', showEnv: false };

async function showAssetHistory(id) {
    const asset = rotState.assets.find(a => a.id === id);
    const title = document.getElementById('historyTitle');
    title.innerHTML = `<i class="fas fa-history" style="color:#5AC8FA;margin-right:8px"></i>Historial Completo — ${asset ? (asset.code || '') + ' ' + (asset.name || '') : 'Activo'}`;

    const container = document.getElementById('historyTimeline');
    container.innerHTML = '<p style="color:rgba(255,255,255,.35);text-align:center;padding:20px"><i class="fas fa-spinner fa-spin"></i> Cargando historial...</p>';

    try {
        const data = await rFetch(`/api/rotative-assets/${id}/full-history`);
        _rotHistoryState.events = data.events || [];
        _rotHistoryState.bom = data.bom || [];
        _rotHistoryState.counts = data.counts || {};
        _rotHistoryState.view = 'timeline';
        _rotHistoryState.category = 'ALL';
        _rotHistoryState.showEnv = false;
        renderRotHistoryControls();
        renderRotHistory();
    } catch (e) {
        container.innerHTML = `<p style="color:#FF6B61;text-align:center;padding:20px">Error: ${e.message}</p>`;
    }
    document.getElementById('historyModal').showModal();
}

function _rotVisibleEvents() {
    let events = _rotHistoryState.events;
    if (!_rotHistoryState.showEnv) {
        events = events.filter(e => e.scope !== 'EQUIPO');
    }
    return events;
}

function renderRotHistoryControls() {
    const container = document.getElementById('historyTimeline');
    const c = _rotHistoryState.counts;
    const visible = _rotVisibleEvents();
    const total = visible.length;
    const catChip = (key, label, color) => {
        const count = (key === 'ALL')
            ? total
            : visible.filter(e => e.category === key).length;
        const active = _rotHistoryState.category === key;
        return `<button onclick="setRotHistoryCategory('${key}')" style="background:${active ? color : 'rgba(255,255,255,.06)'};color:${active ? '#fff' : 'rgba(255,255,255,.75)'};border:1px solid ${active ? color : 'rgba(255,255,255,.12)'};padding:4px 10px;border-radius:16px;font-size:.78rem;cursor:pointer;margin-right:6px;margin-bottom:6px;">${label} <span style="background:rgba(0,0,0,.25);padding:0 6px;border-radius:8px;margin-left:4px;font-weight:700;">${count}</span></button>`;
    };

    const controlsHTML = `<div id="rotHistoryControls" style="padding:10px 0 12px 0;border-bottom:1px solid rgba(255,255,255,.08);margin-bottom:12px;">
        <div style="display:flex;flex-wrap:wrap;gap:4px;align-items:center;">
            ${catChip('ALL', 'Todo', '#5AC8FA')}
            ${catChip('MOVIMIENTO', 'Movimientos', '#BF5AF2')}
            ${catChip('OT', 'OTs', '#0A84FF')}
            ${catChip('AVISO', 'Avisos', '#FF9F0A')}
            ${catChip('ELECTRICA', 'Pruebas eléctricas', '#64D2FF')}
            ${catChip('LUBRICACION', 'Lubricación', '#FFD60A')}
            ${catChip('INSPECCION', 'Inspección', '#30D158')}
            ${catChip('MONITOREO', 'Monitoreo', '#FF453A')}
        </div>
        <label style="display:flex;align-items:center;gap:6px;margin-top:8px;font-size:.76rem;color:rgba(255,255,255,.55);cursor:pointer;">
            <input type="checkbox" ${_rotHistoryState.showEnv ? 'checked' : ''} onchange="toggleRotHistoryEnv(this.checked)">
            Incluir mantenimiento del equipo donde está montado (chumaceras, fajas, rondas de inspección) — ${c.entorno || 0} evento(s)
        </label>
        <div style="margin-top:8px;display:flex;gap:6px;align-items:center;">
            <span style="font-size:.75rem;color:rgba(255,255,255,.45);margin-right:4px;">Vista:</span>
            <button onclick="setRotHistoryView('timeline')" style="background:${_rotHistoryState.view === 'timeline' ? '#5AC8FA' : 'rgba(255,255,255,.06)'};color:${_rotHistoryState.view === 'timeline' ? '#000' : 'rgba(255,255,255,.75)'};border:1px solid rgba(255,255,255,.12);padding:4px 10px;border-radius:6px;font-size:.78rem;cursor:pointer;font-weight:600;"><i class="fas fa-stream"></i> Línea de tiempo</button>
            <button onclick="setRotHistoryView('grouped')" style="background:${_rotHistoryState.view === 'grouped' ? '#5AC8FA' : 'rgba(255,255,255,.06)'};color:${_rotHistoryState.view === 'grouped' ? '#000' : 'rgba(255,255,255,.75)'};border:1px solid rgba(255,255,255,.12);padding:4px 10px;border-radius:6px;font-size:.78rem;cursor:pointer;font-weight:600;"><i class="fas fa-layer-group"></i> Agrupado por categoría</button>
        </div>
    </div>`;
    container.innerHTML = controlsHTML + '<div id="rotHistoryBody"></div>';
}

function setRotHistoryCategory(cat) {
    _rotHistoryState.category = cat;
    renderRotHistoryControls();
    renderRotHistory();
}

function setRotHistoryView(view) {
    _rotHistoryState.view = view;
    renderRotHistoryControls();
    renderRotHistory();
}

function toggleRotHistoryEnv(checked) {
    _rotHistoryState.showEnv = !!checked;
    renderRotHistoryControls();
    renderRotHistory();
}

function renderRotHistory() {
    const body = document.getElementById('rotHistoryBody');
    if (!body) return;
    let events = _rotVisibleEvents();
    if (_rotHistoryState.category !== 'ALL') {
        events = events.filter(e => e.category === _rotHistoryState.category);
    }

    if (!events.length) {
        body.innerHTML = '<p style="color:rgba(255,255,255,.35);text-align:center;padding:20px">Sin eventos en esta categoría.</p>';
        renderRotHistoryBom();
        return;
    }

    if (_rotHistoryState.view === 'timeline') {
        body.innerHTML = events.map(e => _rotEventTimelineHTML(e)).join('');
    } else {
        // Agrupado por categoría
        const groups = {};
        events.forEach(e => { (groups[e.category] = groups[e.category] || []).push(e); });
        const catOrder = ['OT', 'AVISO', 'MOVIMIENTO', 'ELECTRICA', 'LUBRICACION', 'INSPECCION', 'MONITOREO'];
        const catColors = { OT: '#0A84FF', AVISO: '#FF9F0A', MOVIMIENTO: '#BF5AF2', ELECTRICA: '#64D2FF', LUBRICACION: '#FFD60A', INSPECCION: '#30D158', MONITOREO: '#FF453A' };
        body.innerHTML = catOrder.filter(c => groups[c]).map(cat => `
            <div style="margin-bottom:16px;">
                <h4 style="margin:0 0 8px 0;font-size:.9rem;color:${catColors[cat]};padding-bottom:4px;border-bottom:1px solid ${catColors[cat]}44;"><i class="fas fa-circle" style="font-size:.6rem;vertical-align:middle;margin-right:6px;"></i>${cat} <span style="color:rgba(255,255,255,.45);font-weight:400;font-size:.8rem;">(${groups[cat].length})</span></h4>
                ${groups[cat].map(e => _rotEventCardHTML(e)).join('')}
            </div>`).join('');
    }
    renderRotHistoryBom();
}

const ENV_BADGE = '<span style="font-size:.66rem;padding:1px 6px;border-radius:8px;background:rgba(255,255,255,.08);color:rgba(255,255,255,.50);margin-left:6px;border:1px solid rgba(255,255,255,.12)">DEL EQUIPO</span>';

function _rotEventTimelineHTML(e) {
    const dotClass = `tl-dot-${e.category}`;
    const typeClass = `tl-type-${e.category}`;
    const envBadge = e.scope === 'EQUIPO' ? ENV_BADGE : '';
    return `<div class="tl-item"${e.scope === 'EQUIPO' ? ' style="opacity:.72"' : ''}>
        <div class="tl-dot ${dotClass}"></div>
        <div class="tl-body">
            <div><span class="tl-type ${typeClass}">${e.category}${e.code ? ' · ' + e.code : ''}${e.type ? ' — ' + e.type : ''}</span>${envBadge}<span class="tl-date">${e.date || '-'}</span></div>
            ${e.location ? `<div class="tl-location"><i class="fas fa-map-marker-alt" style="margin-right:4px"></i>${e.location}</div>` : ''}
            ${e.description ? `<div class="tl-comment">${e.description}</div>` : ''}
            ${e.failure_mode ? `<div style="margin-top:3px;font-size:.75rem;color:#FF9F0A;"><i class="fas fa-exclamation-circle"></i> ${e.failure_mode}</div>` : ''}
            ${e.status ? `<div style="margin-top:2px"><span style="font-size:.72rem;padding:1px 6px;border-radius:4px;background:rgba(255,255,255,.08);color:rgba(255,255,255,.70)">${e.status}</span>${e.duration_h ? ` <span style="font-size:.72rem;color:rgba(255,255,255,.5);margin-left:6px;"><i class="far fa-clock"></i> ${e.duration_h}h</span>` : ''}</div>` : ''}
        </div>
    </div>`;
}

function _rotEventCardHTML(e) {
    return `<div style="padding:8px 12px;margin-bottom:6px;background:rgba(255,255,255,.03);border-left:3px solid rgba(255,255,255,.15);border-radius:4px;font-size:.85rem;${e.scope === 'EQUIPO' ? 'opacity:.72;' : ''}">
        <div style="display:flex;justify-content:space-between;gap:12px;color:rgba(255,255,255,.85);">
            <div><b>${e.code || e.type || '-'}</b> ${e.type && e.code ? `<span style="color:rgba(255,255,255,.5);">· ${e.type}</span>` : ''}${e.scope === 'EQUIPO' ? ENV_BADGE : ''}</div>
            <div style="color:rgba(255,255,255,.45);font-size:.78rem;">${e.date || '-'}</div>
        </div>
        ${e.description ? `<div style="color:rgba(255,255,255,.65);margin-top:3px;font-size:.82rem;">${e.description}</div>` : ''}
        <div style="margin-top:4px;display:flex;gap:8px;font-size:.72rem;color:rgba(255,255,255,.5);flex-wrap:wrap;">
            ${e.status ? `<span>Estado: <b style="color:rgba(255,255,255,.75);">${e.status}</b></span>` : ''}
            ${e.failure_mode ? `<span>Falla: <b style="color:#FF9F0A;">${e.failure_mode}</b></span>` : ''}
            ${e.duration_h ? `<span><i class="far fa-clock"></i> ${e.duration_h}h</span>` : ''}
            ${e.location ? `<span><i class="fas fa-map-marker-alt"></i> ${e.location}</span>` : ''}
        </div>
    </div>`;
}

function renderRotHistoryBom() {
    const body = document.getElementById('rotHistoryBody');
    if (!body || !_rotHistoryState.bom.length) return;
    // Solo mostrar BOM al ver "Todo" para no ensuciar filtros
    if (_rotHistoryState.category !== 'ALL') return;
    body.insertAdjacentHTML('beforeend', `<div style="border-top:1px solid rgba(255,255,255,.08);padding-top:12px;margin-top:16px">
        <h4 style="color:rgba(255,255,255,.60);font-size:.85rem;margin:0 0 8px"><i class="fas fa-boxes" style="margin-right:5px"></i>Repuestos asociados (${_rotHistoryState.bom.length})</h4>
        ${_rotHistoryState.bom.map(b => `<div style="font-size:.82rem;color:rgba(255,255,255,.65);padding:3px 0">${b.item_code || '-'} ${b.item_name || '-'} <span style="color:rgba(255,255,255,.35)">(x${b.quantity} ${b.category})</span> <span style="color:${(b.item_stock||0)>0?'#30D158':'#FF453A'};font-size:.75rem">Stock: ${b.item_stock||0}</span></div>`).join('')}
    </div>`);
}

window.setRotHistoryCategory = setRotHistoryCategory;
window.setRotHistoryView = setRotHistoryView;
window.toggleRotHistoryEnv = toggleRotHistoryEnv;

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

// ── Cambio de activo (swap) ─────────────────────────────────────────────────
// Los candidatos se piden al servidor, NO se filtran de rotState.assets: la
// tabla de pantalla ya viene filtrada por area/linea/equipo y un repuesto
// disponible no tiene ubicacion, asi que desaparecia justo cuando el usuario
// filtraba por el equipo que fallo — y la lista salia vacia.

function _candidateCardHTML(c, selectable) {
    const reasons = (c.reasons || []).slice(0, 4).map(escHtml).join(' · ');
    const warns = (c.warnings || []).slice(0, 3).map(escHtml).join(' · ');
    const specs = [c.brand, c.model].filter(Boolean).map(escHtml).join(' ');
    const input = selectable
        ? `<input type="radio" name="swapCandidate" value="${c.id}">`
        : '';
    const extra = !selectable
        ? `<div class="cand-reason">${escHtml(c.status)}${c.service_provider_name ? ' — ' + escHtml(c.service_provider_name) : ''}` +
          `${c.out_since ? ' · desde ' + escHtml(c.out_since) : ''}` +
          `${c.expected_return_date ? ' · retorno estimado ' + escHtml(c.expected_return_date) : ''}</div>`
        : '';
    return `<label class="cand-card" style="${selectable ? '' : 'cursor:default;opacity:.75'}">
        <div class="cand-head">
            ${input}
            <span class="cand-code">${escHtml(c.code)}</span>
            <span class="cand-name">${escHtml(c.name)}</span>
            <span class="match-badge match-${c.match_level}">${c.match_level === 'ALTA' ? 'Compatible' : c.match_level === 'MEDIA' ? 'Revisar' : 'Poco compatible'}</span>
            <span style="margin-left:auto;font-size:.72rem;color:rgba(255,255,255,.35)">${escHtml(c.category || 'sin categoria')}${specs ? ' · ' + specs : ''}</span>
        </div>
        ${reasons ? `<div class="cand-reason"><i class="fas fa-check" style="color:#30D158;margin-right:4px"></i>${reasons}</div>` : ''}
        ${warns ? `<div class="cand-warn"><i class="fas fa-exclamation-triangle" style="margin-right:4px"></i>${warns}</div>` : ''}
        ${extra}
    </label>`;
}

async function openSwapModal(assetId) {
    const asset = rotState.assets.find(a => a.id === assetId);
    if (!asset) return;
    rQ('swapRemoveId').value = assetId;
    rQ('swapRemoveLabel').innerHTML =
        `<b>${escHtml(asset.code)}</b> ${escHtml(asset.name)}` +
        `${asset.category ? ` <span style="color:rgba(255,255,255,.5)">(${escHtml(asset.category)})</span>` : ''}<br>` +
        `<span style="font-size:.80rem;color:rgba(255,255,255,.55)">${locationText(asset)}</span>`;
    rQ('swapReason').value = '';
    rQ('swapDate').value = todayISO();
    rQ('swapExpectedReturn').value = '';
    document.querySelector('input[name="swapDest"][value="TALLER"]').checked = true;

    const box = rQ('swapCandidates');
    box.innerHTML = '<p style="color:rgba(255,255,255,.35);font-size:.84rem;padding:12px 0"><i class="fas fa-spinner fa-spin"></i> Buscando activos disponibles...</p>';
    rQ('swapModal').showModal();
    await loadProvidersInto('swapProviderId');
    onSwapDestChange();

    try {
        const data = await rFetch(`/api/rotative-assets/${assetId}/swap-candidates`);
        const s = data.summary || {};
        let html = '';

        if (!(data.candidates || []).length) {
            html += `<div style="padding:12px;border:1px solid rgba(255,159,10,.4);background:rgba(255,159,10,.08);border-radius:8px;color:#FFB340;font-size:.84rem">
                <b>No hay ningun activo Disponible para instalar.</b><br>
                <span style="color:rgba(255,255,255,.6)">Retira el que fallo indicando su destino, y cuando llegue el repuesto nuevo dalo de alta e instalalo.</span>
                <div style="display:flex;gap:8px;margin-top:10px">
                    <button type="button" onclick="closeDialog('swapModal');openRemoveModal(${assetId})" style="height:30px;padding:0 12px;background:rgba(255,69,58,.15);border:1px solid #FF453A;border-radius:6px;color:#FF8078;font-size:.78rem;cursor:pointer">Solo retirar</button>
                    <button type="button" onclick="closeDialog('swapModal');openAssetModal()" style="height:30px;padding:0 12px;background:rgba(90,200,250,.15);border:1px solid #5AC8FA;border-radius:6px;color:#5AC8FA;font-size:.78rem;cursor:pointer">Registrar activo nuevo</button>
                </div>
            </div>`;
        } else {
            const compat = data.candidates.filter(c => c.match_level !== 'BAJA');
            const rest = data.candidates.filter(c => c.match_level === 'BAJA');
            html += `<div style="font-size:.78rem;color:rgba(255,255,255,.45);margin-bottom:8px">
                ${s.disponibles} disponible(s) · ${s.compatibles} del mismo tipo que ${escHtml(asset.category || 'este activo')}
            </div>`;
            if (compat.length) {
                html += compat.map(c => _candidateCardHTML(c, true)).join('');
            }
            if (rest.length) {
                html += `<details style="margin-top:6px"><summary style="cursor:pointer;font-size:.78rem;color:rgba(255,255,255,.45);padding:6px 0">
                    Ver ${rest.length} activo(s) disponible(s) de otro tipo</summary>
                    ${rest.map(c => _candidateCardHTML(c, true)).join('')}</details>`;
            }
        }

        if ((data.in_service || []).length) {
            html += `<details style="margin-top:10px"><summary style="cursor:pointer;font-size:.78rem;color:#ffd76f;padding:6px 0">
                <i class="fas fa-tools"></i> ${data.in_service.length} activo(s) en taller o proveedor — todavia no se pueden instalar</summary>
                ${data.in_service.map(c => _candidateCardHTML(c, false)).join('')}</details>`;
        }
        box.innerHTML = html;
    } catch (e) {
        box.innerHTML = `<p style="color:#FF6B61;font-size:.84rem">Error cargando candidatos: ${escHtml(e.message)}</p>`;
    }
}

async function executeSwap() {
    const removeId = rQ('swapRemoveId').value;
    const picked = document.querySelector('input[name="swapCandidate"]:checked');
    if (!picked) { alert('Selecciona el activo que va a entrar en su lugar.'); return; }

    const dest = document.querySelector('input[name="swapDest"]:checked').value;
    if (dest === 'PROVEEDOR' && !rQ('swapProviderId').value) {
        alert('Selecciona el proveedor externo al que se envia el activo retirado.');
        return;
    }

    try {
        const res = await rFetch('/api/rotative-assets/swap', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                remove_asset_id: Number(removeId),
                install_asset_id: Number(picked.value),
                date: rQ('swapDate').value || todayISO(),
                destination: dest,
                provider_id: rNum(rQ('swapProviderId').value),
                expected_return_date: rQ('swapExpectedReturn').value || null,
                reason: rQ('swapReason').value || null,
            })
        });
        closeDialog('swapModal');
        alert(res.message || 'Cambio realizado correctamente.');
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

// ── Plantillas de specs estandar por categoria ──────────────────────────────
// Cada plantilla genera una lista de filas vacias (key_name + unit, sin valor)
// que el usuario completa luego. Sirve para homogeneizar la ficha tecnica
// entre activos del mismo tipo (ej: todas las chumaceras tienen los mismos
// campos: marca, modelo, diametro interior, sello, lubricante, etc.).
const SPEC_TEMPLATES = {
    chumacera: [
        { key: 'Marca', unit: '' },
        { key: 'Modelo', unit: '' },
        { key: 'Tipo de chumacera', unit: '' },         // SY, SYJ, SYK / brida / pared
        { key: 'Tipo de rodamiento', unit: '' },        // bolas, rodillos, autoalineante
        { key: 'Diametro interior (eje)', unit: 'mm' },
        { key: 'Diametro exterior carcasa', unit: 'mm' },
        { key: 'Ancho carcasa', unit: 'mm' },
        { key: 'Tipo de sello', unit: '' },             // LL, ZZ, RS, 2RS, taconite
        { key: 'Tornilleria de fijacion', unit: '' },   // espárragos M16, etc.
        { key: 'Lubricante recomendado', unit: '' },    // grasa NLGI 2 mineral / litio
        { key: 'Cantidad de lubricante', unit: 'g' },
        { key: 'Frecuencia de relubricacion', unit: 'dias' },
        { key: 'Carga dinamica (C)', unit: 'kN' },
        { key: 'Carga estatica (Co)', unit: 'kN' },
        { key: 'Velocidad nominal', unit: 'rpm' },
        { key: 'Posicion (motriz/conducida)', unit: '' },
    ],
    cadena: [
        { key: 'Marca', unit: '' },
        { key: 'Norma', unit: '' },                     // ANSI, BS, DIN, ISO
        { key: 'Designacion', unit: '' },               // ej: ANSI 80, ISO 16B
        { key: 'Paso', unit: 'mm o pulg' },
        { key: 'Tipo de cadena', unit: '' },            // simple, doble, triple, silente, transportadora
        { key: 'Numero de eslabones', unit: 'eslabones' },
        { key: 'Longitud total', unit: 'm' },
        { key: 'Diametro del rodillo', unit: 'mm' },
        { key: 'Ancho interior eslabon', unit: 'mm' },
        { key: 'Material', unit: '' },                  // acero al carbono, inox, galvanizada
        { key: 'Resistencia a la traccion', unit: 'kN' },
        { key: 'Lubricante recomendado', unit: '' },
        { key: 'Frecuencia de lubricacion', unit: 'dias' },
        { key: 'Tipo de eslabon de cierre', unit: '' }, // clip, pasador chaveta
    ],
    motor_electrico: [
        { key: 'Marca', unit: '' },
        { key: 'Modelo', unit: '' },
        { key: 'Numero de serie', unit: '' },
        { key: 'Potencia nominal', unit: 'HP / kW' },
        { key: 'Voltaje nominal', unit: 'V' },
        { key: 'Conexion', unit: '' },                  // estrella, triangulo, dual
        { key: 'Frecuencia', unit: 'Hz' },
        { key: 'Corriente nominal', unit: 'A' },
        { key: 'Corriente de arranque', unit: 'A' },
        { key: 'Velocidad sincrona', unit: 'rpm' },
        { key: 'Velocidad nominal', unit: 'rpm' },
        { key: 'Numero de polos', unit: '' },
        { key: 'Factor de potencia (cos φ)', unit: '' },
        { key: 'Eficiencia (clase)', unit: '' },        // IE2, IE3, IE4
        { key: 'Tipo de rotor', unit: '' },             // jaula de ardilla, bobinado
        { key: 'Frame / Carcasa', unit: '' },           // 184T, 132M, etc.
        { key: 'Norma carcasa', unit: '' },             // NEMA / IEC
        { key: 'Grado de proteccion', unit: '' },       // IP55, IP65
        { key: 'Clase de aislamiento', unit: '' },      // F, H
        { key: 'Tipo de servicio', unit: '' },          // S1 continuo
        { key: 'Rodamiento lado acople', unit: '' },    // 6308-2RS / 2Z
        { key: 'Rodamiento lado libre', unit: '' },     // 6206-2RS
        { key: 'Tipo de arranque', unit: '' },          // DOL, soft starter, variador
        { key: 'Forma de montaje', unit: '' },          // B3, B5, B14
        { key: 'Peso', unit: 'kg' },
    ],
    motorreductor: [
        { key: 'Marca', unit: '' },                     // SEW, Sumitomo, Nord, Siemens
        { key: 'Modelo motor', unit: '' },
        { key: 'Modelo reductor', unit: '' },
        { key: 'Numero de serie', unit: '' },
        { key: 'Tipo de reductor', unit: '' },          // sinfin-corona, helicoidal, planetario, ortogonal
        { key: 'Potencia entrada', unit: 'HP / kW' },
        { key: 'Voltaje motor', unit: 'V' },
        { key: 'Corriente motor', unit: 'A' },
        { key: 'RPM entrada', unit: 'rpm' },
        { key: 'RPM salida', unit: 'rpm' },
        { key: 'Relacion de reduccion (i)', unit: '' },
        { key: 'Torque salida nominal', unit: 'Nm' },
        { key: 'Factor de servicio (fS)', unit: '' },
        { key: 'Eficiencia del reductor', unit: '%' },
        { key: 'Forma de montaje', unit: '' },          // M1, M2, B3, B5
        { key: 'Tipo de eje salida', unit: '' },        // macizo, hueco, brida
        { key: 'Diametro eje salida', unit: 'mm' },
        { key: 'Lubricante reductor', unit: '' },       // ISO VG 220, sintetico
        { key: 'Volumen lubricante', unit: 'L' },
        { key: 'Frecuencia cambio aceite', unit: 'h o dias' },
        { key: 'Rodamientos reductor', unit: '' },      // lista
        { key: 'Tipo de retenes', unit: '' },           // CR, NAK, dim/dim/ancho
        { key: 'Grado proteccion', unit: '' },          // IP55, IP65
        { key: 'Peso total', unit: 'kg' },
    ],
    caja_reductora: [
        { key: 'Marca', unit: '' },
        { key: 'Modelo', unit: '' },
        { key: 'Numero de serie', unit: '' },
        { key: 'Tipo de reductor', unit: '' },          // sinfin-corona, helicoidal, planetario
        { key: 'Potencia que admite', unit: 'HP / kW' },
        { key: 'RPM entrada maxima', unit: 'rpm' },
        { key: 'Relacion de reduccion (i)', unit: '' },
        { key: 'Torque salida nominal', unit: 'Nm' },
        { key: 'Factor de servicio (fS)', unit: '' },
        { key: 'Diametro eje entrada', unit: 'mm' },
        { key: 'Diametro eje salida', unit: 'mm' },
        { key: 'Tipo eje salida', unit: '' },           // macizo, hueco, brida
        { key: 'Forma de montaje', unit: '' },
        { key: 'Lubricante recomendado', unit: '' },    // ISO VG 220
        { key: 'Volumen lubricante', unit: 'L' },
        { key: 'Frecuencia cambio aceite', unit: 'h o dias' },
        { key: 'Rodamientos (lista)', unit: '' },
        { key: 'Retenes (entrada/salida)', unit: '' },
        { key: 'Grado proteccion', unit: '' },
        { key: 'Peso', unit: 'kg' },
    ],
};

window.applySpecTemplate = async function(category) {
    const tpl = SPEC_TEMPLATES[category];
    if (!tpl) return alert('Plantilla no encontrada.');
    const assetId = rQ('specAssetId').value;
    if (!assetId) return alert('Selecciona un activo primero.');

    if (!confirm(`Aplicar plantilla "${category.replace('_',' ')}"?\nSe agregaran ${tpl.length} caracteristicas vacias para que las completes.\nLas que ya tengas no se duplicaran.`)) return;

    // Cargar specs existentes para no duplicar
    let existing = [];
    try {
        existing = await rFetch(`/api/rotative-assets/${assetId}/specs`);
    } catch (e) { existing = []; }
    const existingKeys = new Set((existing || []).map(s => (s.key_name || '').toLowerCase().trim()));

    let added = 0, skipped = 0;
    for (const row of tpl) {
        if (existingKeys.has(row.key.toLowerCase().trim())) {
            skipped++;
            continue;
        }
        try {
            await rFetch(`/api/rotative-assets/${assetId}/specs`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    key_name: row.key,
                    value_text: '—',  // placeholder, el usuario lo edita despues
                    unit: row.unit || null,
                })
            });
            added++;
        } catch (e) {
            console.warn('Error agregando spec:', row.key, e);
        }
    }
    await loadSpecs(assetId);
    alert(`✓ Plantilla aplicada: ${added} caracteristicas agregadas${skipped ? `, ${skipped} ya existian (omitidas)` : ''}.\nAhora completa los valores haciendo click en "Editar" en cada fila.`);
};

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

    rQ('aArea').addEventListener('change', () => {
        syncAreaLineEquip('aArea', 'aLine', 'aEquip', 'Selecciona linea', 'Selecciona equipo');
        fillSystemSelect('aSystemId', rQ('aEquip').value);
        fillComponentSelect('aComponentId', null);
    });
    rQ('aLine').addEventListener('change', () => {
        syncAreaLineEquip('aArea', 'aLine', 'aEquip', 'Selecciona linea', 'Selecciona equipo');
        fillSystemSelect('aSystemId', rQ('aEquip').value);
        fillComponentSelect('aComponentId', null);
    });
    rQ('aEquip').addEventListener('change', () => {
        fillSystemSelect('aSystemId', rQ('aEquip').value);
        fillComponentSelect('aComponentId', null);
    });
    rQ('aSystemId').addEventListener('change', () => {
        fillComponentSelect('aComponentId', rQ('aSystemId').value);
    });

    rQ('insArea').addEventListener('change', () => {
        syncAreaLineEquip('insArea', 'insLine', 'insEquip', 'Selecciona linea', 'Selecciona equipo');
        fillSystemSelect('insSystem', rQ('insEquip').value);
        fillComponentSelect('insComp', null);
    });
    rQ('insLine').addEventListener('change', () => {
        syncAreaLineEquip('insArea', 'insLine', 'insEquip', 'Selecciona linea', 'Selecciona equipo');
        fillSystemSelect('insSystem', rQ('insEquip').value);
        fillComponentSelect('insComp', null);
    });
    rQ('insEquip').addEventListener('change', () => {
        fillSystemSelect('insSystem', rQ('insEquip').value);
        fillComponentSelect('insComp', null);
    });
    rQ('insSystem').addEventListener('change', () => {
        fillComponentSelect('insComp', rQ('insSystem').value);
    });

    // ── Soporte para URL params: prefill desde /configuracion ───────────────
    // Cuando el usuario hace clic en "+ asignar activo" en el arbol, se pasa
    // prefill_component_id (y equipment/system) para abrir directamente el
    // modal "Nuevo Activo" con el componente ya seleccionado.
    try {
        const params = new URLSearchParams(window.location.search);
        const prefillComp = params.get('prefill_component_id');
        const focusAsset = params.get('focus_asset_id');
        if (prefillComp) {
            // Abrir el modal de nuevo activo con el componente preseleccionado
            const eqId = params.get('prefill_equipment_id');
            const sysId = params.get('prefill_system_id');
            openAssetModal();
            // Esperar un tick para que el modal se monte y populeo los selects
            setTimeout(() => {
                if (eqId) {
                    // Buscar area/line del equipo
                    const eq = rotState.equips.find(e => String(e.id) === String(eqId));
                    if (eq) {
                        const line = rotState.lines.find(l => String(l.id) === String(eq.line_id));
                        if (line) {
                            setAreaLineEquip('aArea', 'aLine', 'aEquip',
                                line.area_id, line.id, eq.id,
                                'Selecciona linea', 'Selecciona equipo');
                        }
                    }
                    fillSystemSelect('aSystemId', eqId, sysId);
                    fillComponentSelect('aComponentId', sysId, prefillComp);
                }
                rQ('aName').focus();
            }, 100);
            // Limpiar URL para evitar re-disparar al refrescar
            window.history.replaceState({}, '', '/activos-rotativos');
        } else if (focusAsset) {
            const id = parseInt(focusAsset, 10);
            if (Number.isFinite(id)) {
                setTimeout(() => openAssetModal(id), 100);
            }
            window.history.replaceState({}, '', '/activos-rotativos');
        }
    } catch (_) {
        // Ignorar fallos de URL parsing
    }
}

document.addEventListener('DOMContentLoaded', () => {
    initRotative().catch(e => alert('No se pudo inicializar activos rotativos: ' + e.message));
});
