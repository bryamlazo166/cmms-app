const lubState = { points: [], areas: [], lines: [], systems: [], components: [], equipments: [], showInactive: false };

function q(id) { return document.getElementById(id); }
function fnum(v, d = 0) { return Number(v || 0).toLocaleString("es-PE", { minimumFractionDigits: d, maximumFractionDigits: d }); }

async function jget(url, opts) {
    const r = await fetch(url, opts);
    const d = await r.json();
    if (!r.ok || d.error) throw new Error(d.error || `HTTP ${r.status}`);
    return d;
}

function fillSelect(select, rows, valueKey, textFn, first = "Seleccione") {
    select.innerHTML = `<option value="">${first}</option>` + rows.map(r => `<option value="${r[valueKey]}">${textFn(r)}</option>`).join("");
}

async function loadCatalogs() {
    const [areas, lines, equipments, systems, components] = await Promise.all([
        jget('/api/areas'),
        jget('/api/lines'),
        jget('/api/equipments'),
        jget('/api/systems'),
        jget('/api/components')
    ]);
    lubState.areas = areas || [];
    lubState.lines = lines || [];
    lubState.equipments = equipments || [];
    lubState.systems = systems || [];
    lubState.components = components || [];

    fillSelect(q('fArea'), lubState.areas, 'id', a => a.name);
    fillSelect(q('fLine'), [], 'id', l => l.name);
    fillSelect(q('fEquipment'), [], 'id', e => `${e.tag ? e.tag + ' - ' : ''}${e.name}`);
    fillSelect(q('fSystem'), [], 'id', s => s.name);
    fillSelect(q('fComponent'), [], 'id', c => c.name);
}

function onAreaChange() {
    const areaId = Number(q('fArea').value || 0);
    const lines = lubState.lines.filter(l => Number(l.area_id) === areaId);
    fillSelect(q('fLine'), lines, 'id', l => l.name);
    fillSelect(q('fEquipment'), [], 'id', e => `${e.tag ? e.tag + ' - ' : ''}${e.name}`);
    fillSelect(q('fSystem'), [], 'id', s => s.name);
    fillSelect(q('fComponent'), [], 'id', c => c.name);
}

function onLineChange() {
    const lineId = Number(q('fLine').value || 0);
    const equips = lubState.equipments.filter(e => Number(e.line_id) === lineId);
    fillSelect(q('fEquipment'), equips, 'id', e => `${e.tag ? e.tag + ' - ' : ''}${e.name}`);
    fillSelect(q('fSystem'), [], 'id', s => s.name);
    fillSelect(q('fComponent'), [], 'id', c => c.name);
}

function onEquipmentChange() {
    const eqId = Number(q('fEquipment').value || 0);
    const systems = lubState.systems.filter(s => Number(s.equipment_id) === eqId);
    fillSelect(q('fSystem'), systems, 'id', s => s.name);
    fillSelect(q('fComponent'), [], 'id', c => c.name);
    refreshPointSelect();
}

const _STOP_TOK = new Set(['el','la','los','las','del','de','al','un','una','lo','que']);
function _tokenize(s) {
    if (!s) return [];
    return String(s).toLowerCase().split(/[\s,;/#-]+/)
        .filter(t => t && !_STOP_TOK.has(t) && (t.length >= 2 || /^\d+$/.test(t)));
}
function _pointBlob(p) {
    return [p.code, p.name, p.equipment_name, p.equipment_tag, p.system_name, p.component_name]
        .filter(Boolean).join(' ').toLowerCase();
}
function getFilteredPoints() {
    let pts = lubState.points || [];
    const eqId = Number(q('fEquipment').value || 0);
    if (eqId) pts = pts.filter(p => Number(p.equipment_id) === eqId);
    const tokens = _tokenize(q('fPointSearch') ? q('fPointSearch').value : '');
    if (tokens.length) {
        pts = pts.filter(p => {
            const blob = _pointBlob(p);
            return tokens.every(t => blob.includes(t));
        });
    }
    return pts;
}
const _SEMA_ICON = { VERDE: '🟢', AMARILLO: '🟡', ROJO: '🔴', PENDIENTE: '⚪' };
function _esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, c => (
        { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
    ));
}
function _shortName(name, max = 38) {
    if (!name) return '';
    const s = String(name).replace(/\s+/g, ' ').trim();
    return s.length > max ? s.slice(0, max - 1) + '…' : s;
}
function _groupKey(p) {
    const area = p.area_name || 'Sin area';
    const tag = p.equipment_tag || '';
    const eqName = p.equipment_name || '';
    return `[${area}] ${tag}${tag && eqName ? ' — ' : ''}${eqName}`;
}
function _optionText(p) {
    const ico = _SEMA_ICON[p.semaphore_status] || '⚪';
    // Preferimos componente · sistema; si faltan, caemos al nombre del punto.
    const comp = p.component_name ? _shortName(p.component_name, 32) : '';
    const sys = p.system_name ? _shortName(p.system_name, 28) : '';
    let body;
    if (comp && sys) body = `${comp} · ${sys}`;
    else if (comp) body = comp;
    else body = _shortName(p.name || p.code || '(sin nombre)', 60);
    const freq = p.frequency_days ? ` (${p.frequency_days}d)` : '';
    return `${ico} ${body}${freq}`;
}
function renderPointSelect() {
    const sel = q('fPoint');
    if (!sel) return;
    const filtered = getFilteredPoints();
    const total = (lubState.points || []).length;
    const countEl = q('fPointCount');
    if (countEl) countEl.textContent = filtered.length === total
        ? `(${total})`
        : `(${filtered.length}/${total})`;
    if (!filtered.length) {
        sel.innerHTML = '<option value="">Sin coincidencias — ajusta el filtro</option>';
        return;
    }

    // Agrupa por equipo (orden: area → tag → equipo)
    const groups = new Map();
    filtered.forEach(p => {
        const k = _groupKey(p);
        if (!groups.has(k)) groups.set(k, []);
        groups.get(k).push(p);
    });
    const sortedGroups = [...groups.entries()].sort((a, b) =>
        a[0].localeCompare(b[0], 'es', { numeric: true, sensitivity: 'base' })
    );
    const renderOpt = p => {
        const tip = [p.code, p.lubricant_name, p.last_service_date ? `Ult: ${p.last_service_date}` : null,
                     p.next_due_date ? `Prox: ${p.next_due_date}` : null]
                    .filter(Boolean).join(' · ');
        return `<option value="${p.id}" title="${_esc(tip)}">${_esc(_optionText(p))}</option>`;
    };
    let html = '<option value="">Seleccione punto</option>';
    if (sortedGroups.length === 1) {
        // Si todo el filtro cae en un solo equipo, omitimos el header (ruido)
        const [, points] = sortedGroups[0];
        points.sort((a, b) => (a.component_name || a.name || '').localeCompare(
            b.component_name || b.name || '', 'es', { sensitivity: 'base' }));
        html += points.map(renderOpt).join('');
    } else {
        for (const [label, points] of sortedGroups) {
            points.sort((a, b) => (a.component_name || a.name || '').localeCompare(
                b.component_name || b.name || '', 'es', { numeric: true, sensitivity: 'base' }));
            html += `<optgroup label="${_esc(label)}">${points.map(renderOpt).join('')}</optgroup>`;
        }
    }
    sel.innerHTML = html;
    if (filtered.length === 1) sel.value = String(filtered[0].id);
}
function refreshPointSelect() { renderPointSelect(); }

function onSystemChange() {
    const sysId = Number(q('fSystem').value || 0);
    const comps = lubState.components.filter(c => Number(c.system_id) === sysId);
    fillSelect(q('fComponent'), comps, 'id', c => c.name);
}

function updateKPIs(d) {
    q('kpiTotal').textContent = fnum(d.total);
    q('kpiGreen').textContent = fnum(d.green);
    q('kpiYellow').textContent = fnum(d.yellow);
    q('kpiRed').textContent = fnum(d.red);
    q('kpiPending').textContent = fnum(d.pending);
    q('kpiCompliance').textContent = `${fnum(d.compliance_percent, 1)}%`;
}

function renderPoints(points) {
    lubState.points = points || [];
    renderPointsView();
    renderPointSelect();
    updateHistFilterOptions();
}

// ── Filtros de la lista de puntos (tabla + arbol) ────────────────────────────
// Cada select se llena con los valores distintos presentes en los puntos que
// pasan los DEMAS filtros, para que las opciones siempre sean alcanzables.
const _TABLE_FILTERS = [
    { id: 'tfArea',      key: p => p.area_name || '' },
    { id: 'tfEquipment', key: p => p.equipment_name || '' },
    { id: 'tfSystem',    key: p => p.system_name || '' },
    { id: 'tfComponent', key: p => p.component_name || '' },
    { id: 'tfLubricant', key: p => p.lubricant_name || '' },
    { id: 'tfFreq',      key: p => (p.frequency_days ? `${p.frequency_days}` : ''),
                         label: v => `${v} dias` },
];

function _daysUntilDue(p) {
    if (!p.next_due_date) return null;
    const due = new Date(p.next_due_date + 'T00:00:00');
    if (isNaN(due)) return null;
    const today = new Date(); today.setHours(0, 0, 0, 0);
    return Math.round((due - today) / 86400000);
}

// skipId permite ignorar un filtro (para calcular las opciones de su select).
function _pointPassesFilters(p, skipId) {
    for (const f of _TABLE_FILTERS) {
        if (f.id === skipId) continue;
        const el = q(f.id);
        const v = el ? el.value : '';
        if (v && f.key(p) !== v) return false;
    }
    if (skipId !== 'tfSema') {
        const sema = (q('tfSema') || {}).value || '';
        if (sema && (p.semaphore_status || 'PENDIENTE') !== sema) return false;
    }
    if (skipId !== 'tfDue') {
        const due = (q('tfDue') || {}).value || '';
        if (due) {
            const days = _daysUntilDue(p);
            if (days === null) return false;
            if (due === 'vencido' ? days >= 0 : days > Number(due)) return false;
        }
    }
    if (skipId !== 'tfSearch') {
        const tokens = _tokenize((q('tfSearch') || {}).value || '');
        if (tokens.length) {
            const blob = [_pointBlob(p), p.lubricant_name, p.area_name, p.line_name]
                .filter(Boolean).join(' ').toLowerCase();
            if (!tokens.every(t => blob.includes(t))) return false;
        }
    }
    return true;
}

// Lista de puntos que comparten tabla y arbol: aplica el filtro de responsable
// y los filtros de la barra para que ambas vistas muestren exactamente el
// mismo subconjunto. El filtro de inactivos ya viene resuelto desde el
// backend (show_inactive).
function getDisplayPoints() {
    const respFilter = (q('fResponsible') || {}).value || '';
    let points = lubState.points || [];
    if (respFilter) {
        points = points.filter(p => (p.effective_responsible_party || 'INTERNO') === respFilter);
    }
    points = points.filter(p => _pointPassesFilters(p, null));
    return points;
}

// Reconstruye las opciones de cada select de filtro con los valores distintos
// de los puntos que pasan los demas filtros, conservando la seleccion actual.
function updateTableFilterOptions() {
    const respFilter = (q('fResponsible') || {}).value || '';
    let base = lubState.points || [];
    if (respFilter) {
        base = base.filter(p => (p.effective_responsible_party || 'INTERNO') === respFilter);
    }
    _TABLE_FILTERS.forEach(f => {
        const sel = q(f.id);
        if (!sel) return;
        const current = sel.value;
        const candidates = base.filter(p => _pointPassesFilters(p, f.id));
        const values = [...new Set(candidates.map(f.key).filter(Boolean))]
            .sort((a, b) => f.id === 'tfFreq'
                ? Number(a) - Number(b)
                : String(a).localeCompare(String(b), 'es', { numeric: true, sensitivity: 'base' }));
        const firstLabel = sel.options[0] ? sel.options[0].textContent : 'Todos';
        sel.innerHTML = `<option value="">${firstLabel}</option>` +
            values.map(v => `<option value="${_esc(v)}">${_esc(f.label ? f.label(v) : v)}</option>`).join('');
        // Mantener la seleccion aunque haya quedado sin coincidencias, para
        // que el usuario vea el filtro activo y pueda quitarlo.
        if (current && !values.includes(current)) {
            sel.insertAdjacentHTML('beforeend', `<option value="${_esc(current)}">${_esc(f.label ? f.label(current) : current)}</option>`);
        }
        sel.value = current;
    });
}

function clearTableFilters() {
    ['tfSearch', 'tfArea', 'tfEquipment', 'tfSystem', 'tfComponent',
     'tfLubricant', 'tfFreq', 'tfSema', 'tfDue'].forEach(id => {
        const el = q(id);
        if (el) el.value = '';
    });
    renderPointsView();
}
window.clearTableFilters = clearTableFilters;

// Re-renderiza ambas vistas (tabla + arbol) con los filtros actuales.
function renderPointsView() {
    renderPointsTable();
    renderLubTree();
    updateTableFilterOptions();
    const countEl = q('tfCount');
    if (countEl) {
        const shown = getDisplayPoints().length;
        const total = (lubState.points || []).length;
        countEl.textContent = shown === total ? `(${total})` : `(${shown}/${total})`;
    }
}
window.renderPointsView = renderPointsView;

// Render con filtro de responsable aplicado (separado para poder re-renderizar
// solo al cambiar el filtro sin re-fetchear).
function renderPointsTable() {
    const tbody = q('tbodyPoints');
    if (!tbody) return;
    const points = getDisplayPoints();
    if (!points.length) {
        tbody.innerHTML = '<tr><td colspan="12">Sin puntos para el filtro actual.</td></tr>';
        return;
    }
    const respBadge = (party) => {
        if (party === 'PROVEEDOR') return '<span style="background:rgba(48,209,88,.15);color:#30D158;border:1px solid rgba(48,209,88,.4);padding:1px 6px;border-radius:8px;font-size:.7rem;font-weight:700;" title="Proveedor">PROV</span>';
        return '<span style="background:rgba(10,132,255,.15);color:#5AC8FA;border:1px solid rgba(10,132,255,.4);padding:1px 6px;border-radius:8px;font-size:.7rem;font-weight:700;" title="Mantenimiento interno">INT</span>';
    };
    tbody.innerHTML = points.map(p => {
        const inactive = p.is_active === false;
        const rowStyle = inactive ? 'opacity:0.45;' : '';
        const semaphore = inactive ? 'INACTIVO' : (p.semaphore_status || 'PENDIENTE');
        const pillClass = inactive ? 'INACTIVO' : (p.semaphore_status || '');
        const toggleIcon = inactive ? 'fa-rotate-left' : 'fa-ban';
        const toggleTitle = inactive ? 'Reactivar' : 'Desactivar';
        const toggleClass = inactive ? 'btn-reactivate' : 'btn-del';
        const party = p.effective_responsible_party || 'INTERNO';
        return `<tr style="${rowStyle}">
            <td>${p.code || '-'}</td>
            <td>${p.name || '-'}</td>
            <td>${p.equipment_name || '-'}</td>
            <td>${p.system_name || '-'}</td>
            <td>${p.component_name || '-'}</td>
            <td>${p.lubricant_name || '-'}</td>
            <td>${p.frequency_days || '-'} d</td>
            <td>${p.last_service_date || '-'}</td>
            <td>${p.next_due_date || '-'}</td>
            <td><span class="pill ${pillClass}">${semaphore}</span></td>
            <td>${respBadge(party)}</td>
            <td>
                ${inactive ? '' : `<button class="btn-icon btn-edit" title="Editar" onclick="openEditModal(${p.id})"><i class="fas fa-pen"></i></button>`}
                <button class="btn-icon ${toggleClass}" title="${toggleTitle}" onclick="togglePoint(${p.id}, ${inactive})"><i class="fas ${toggleIcon}"></i></button>
            </td>
        </tr>`;
    }).join('');
}
window.renderPointsTable = renderPointsTable;

/* ──────────────────────────────────────────────────────────────
   VISTA DE ARBOL DE PLANTA (Area → Linea → Equipo → Sistema →
   Componente → punto). Construida en el cliente a partir de la
   misma lista filtrada que la tabla, reutilizando el patron de
   carets/.nested/.active del arbol de activos (static/js/app.js).
   ────────────────────────────────────────────────────────────── */
const _LUB_TREE_LEVELS = [
    { icon: 'fa-industry',        color: '#7aa7d6', key: p => p.area_name || '(sin area)' },
    { icon: 'fa-grip-lines',      color: '#7aa7d6', key: p => p.line_name || '(sin linea)' },
    { icon: 'fa-cog',             color: '#5AC8FA', key: p => {
        const tag = p.equipment_tag || ''; const name = p.equipment_name || '';
        if (!tag && !name) return '(sin equipo)';
        return name ? `${name}${tag ? ' [' + tag + ']' : ''}` : `[${tag}]`;
    } },
    { icon: 'fa-project-diagram', color: '#9b8cff', key: p => p.system_name || '(sin sistema)' },
    { icon: 'fa-puzzle-piece',    color: '#FF9F0A', key: p => p.component_name || '(sin componente)' },
];

const _lubTreeSort = (a, b) => String(a).localeCompare(String(b), 'es', { numeric: true, sensitivity: 'base' });

function _lubAddCaret(li, expanded) {
    const span = document.createElement('span');
    span.className = 'caret' + (expanded ? ' caret-down' : '');
    span.onclick = function () {
        const nested = this.parentElement.querySelector(':scope > .nested');
        if (nested) nested.classList.toggle('active');
        this.classList.toggle('caret-down');
    };
    li.appendChild(span);
}

function _lubCountBadge(points) {
    const red = points.filter(p => (p.semaphore_status || '') === 'ROJO' && p.is_active !== false).length;
    const cls = red > 0 ? 'node-count has-red' : 'node-count';
    const txt = red > 0 ? `${points.length} · ${red}🔴` : `${points.length}`;
    return `<span class="${cls}">${txt}</span>`;
}

function _lubBuildLevel(points, depth) {
    const ul = document.createElement('ul');
    if (depth > 0) ul.className = 'nested';

    const cfg = _LUB_TREE_LEVELS[depth];
    const groups = new Map();
    points.forEach(p => {
        const k = cfg.key(p);
        if (!groups.has(k)) groups.set(k, []);
        groups.get(k).push(p);
    });

    [...groups.entries()].sort((a, b) => _lubTreeSort(a[0], b[0])).forEach(([label, grp]) => {
        const li = document.createElement('li');
        const node = document.createElement('span');
        node.className = 'tree-node';
        node.innerHTML = `<i class="fas ${cfg.icon}" style="margin-right:6px;color:${cfg.color}"></i>${_esc(label)} ${_lubCountBadge(grp)}`;
        _lubAddCaret(li, false);
        li.appendChild(node);

        const childUl = (depth < _LUB_TREE_LEVELS.length - 1)
            ? _lubBuildLevel(grp, depth + 1)
            : _lubBuildLeaves(grp);
        li.appendChild(childUl);
        ul.appendChild(li);
    });
    return ul;
}

function _lubBuildLeaves(points) {
    const ul = document.createElement('ul');
    ul.className = 'nested';
    points.slice().sort((a, b) => _lubTreeSort(a.name || a.code || '', b.name || b.code || '')).forEach(p => {
        const li = document.createElement('li');
        const inactive = p.is_active === false;
        const pill = inactive ? 'INACTIVO' : (p.semaphore_status || 'PENDIENTE');
        const due = p.next_due_date
            ? `<span style="color:#9ab0cb;font-size:.74rem;margin-left:8px;">vence ${_esc(p.next_due_date)}</span>` : '';
        const lub = p.lubricant_name
            ? `<span style="color:#7f93ad;font-size:.74rem;margin-left:8px;">· ${_esc(p.lubricant_name)}</span>` : '';
        const reg = inactive ? '' :
            `<button class="btn-reg" title="Registrar ejecucion en este punto" onclick="lubQuickRegister(${p.id})"><i class="fas fa-oil-can"></i> Registrar</button>`;
        const node = document.createElement('span');
        node.className = 'tree-node lub-leaf';
        node.innerHTML =
            `<i class="fas fa-oil-can" style="margin-right:6px;color:#d6a44a"></i>` +
            `<span style="${inactive ? 'opacity:.5' : ''}">${_esc(p.name || p.code || '(sin nombre)')}</span>` +
            `<span class="pill ${pill}" style="margin-left:8px;font-size:.68rem;padding:1px 7px;">${pill}</span>` +
            `${due}${lub}${reg}`;
        li.appendChild(node);
        ul.appendChild(li);
    });
    return ul;
}

function renderLubTree() {
    const cont = q('lubTree');
    if (!cont) return;
    const points = getDisplayPoints();
    cont.innerHTML = '';

    const controls = document.createElement('div');
    controls.className = 'lub-tree-controls';
    controls.innerHTML =
        `<button class="btn secondary" onclick="lubExpandAll()"><i class="fas fa-expand-alt"></i> Expandir</button>` +
        `<button class="btn secondary" onclick="lubCollapseAll()"><i class="fas fa-compress-alt"></i> Colapsar</button>`;
    cont.appendChild(controls);

    if (!points.length) {
        const empty = document.createElement('p');
        empty.style.cssText = 'color:#9ab0cb;padding:10px;';
        empty.textContent = 'Sin puntos para el filtro actual.';
        cont.appendChild(empty);
        return;
    }
    cont.appendChild(_lubBuildLevel(points, 0));
}
window.renderLubTree = renderLubTree;

function lubExpandAll() {
    const cont = q('lubTree');
    if (!cont) return;
    cont.querySelectorAll('.nested').forEach(el => el.classList.add('active'));
    cont.querySelectorAll('.caret').forEach(el => el.classList.add('caret-down'));
}
window.lubExpandAll = lubExpandAll;

function lubCollapseAll() {
    const cont = q('lubTree');
    if (!cont) return;
    cont.querySelectorAll('.nested').forEach(el => el.classList.remove('active'));
    cont.querySelectorAll('.caret').forEach(el => el.classList.remove('caret-down'));
}
window.lubCollapseAll = lubCollapseAll;

// Preselecciona un punto en el formulario de ejecucion y hace scroll al boton
// de registro. Inserta la opcion directamente para no depender de los filtros
// del buscador (#fEquipment / #fPointSearch).
function lubQuickRegister(pointId) {
    const p = (lubState.points || []).find(x => x.id === pointId);
    const sel = q('fPoint');
    if (sel) {
        if (!sel.querySelector(`option[value="${pointId}"]`)) {
            const opt = document.createElement('option');
            opt.value = String(pointId);
            opt.textContent = p ? _optionText(p) : `Punto ${pointId}`;
            sel.appendChild(opt);
        }
        sel.value = String(pointId);
        sel.style.outline = '2px solid #5ac8fa';
        setTimeout(() => { sel.style.outline = ''; }, 1600);
    }
    if (q('fExecDate') && !q('fExecDate').value) {
        q('fExecDate').value = new Date().toISOString().slice(0, 10);
    }
    const anchor = q('btnExec');
    if (anchor) anchor.scrollIntoView({ behavior: 'smooth', block: 'center' });
}
window.lubQuickRegister = lubQuickRegister;

// Toggle Tabla / Arbol, persiste la preferencia.
function setLubView(view) {
    const isTree = view === 'tree';
    const tableWrap = q('lubTableWrap');
    const tree = q('lubTree');
    if (tableWrap) tableWrap.style.display = isTree ? 'none' : '';
    if (tree) tree.style.display = isTree ? '' : 'none';
    const btnT = q('btnViewTable'), btnR = q('btnViewTree');
    if (btnT) btnT.classList.toggle('active', !isTree);
    if (btnR) btnR.classList.toggle('active', isTree);
    try { localStorage.setItem('cmms.lub.view', view); } catch (e) { /* ignore */ }
}
window.setLubView = setLubView;

function renderExecutions(rows) {
    const tbody = q('tbodyExec');
    if (!rows || !rows.length) {
        tbody.innerHTML = '<tr><td colspan="12">Sin historial para el filtro actual.</td></tr>';
        return;
    }
    const ACTION_LABEL = {
        CAMBIO_TOTAL: '<span class="pill" style="background:rgba(48,209,88,.18);color:#30D158">Cambio total</span>',
        SERVICIO:     '<span class="pill" style="background:rgba(48,209,88,.18);color:#30D158">Cambio total</span>',
        RELLENO:      '<span class="pill" style="background:rgba(10,132,255,.18);color:#5AC8FA">Relleno</span>',
    };
    tbody.innerHTML = rows.map(r => `
        <tr>
            <td>${r.execution_date || '-'}</td>
            <td>${r.point_name || '-'}</td>
            <td>${r.equipment_name || '-'}</td>
            <td>${r.component_name || '-'}</td>
            <td>${ACTION_LABEL[r.action_type] || (r.action_type || '-')}</td>
            <td>${r.interval_days != null ? r.interval_days + ' d' : '-'}</td>
            <td>${r.quantity_used ? fnum(r.quantity_used, 2) : '-'} ${r.quantity_unit || ''}</td>
            <td>${r.executed_by || '-'}</td>
            <td>${r.anomaly_detected || r.leak_detected ? 'Si' : 'No'}</td>
            <td>${r.created_notice_code || '-'}</td>
            <td>${r.comments || '-'}</td>
            <td><button class="btn-icon btn-del" title="Eliminar ejecucion" onclick="deleteExecution(${r.id})"><i class="fas fa-trash"></i></button></td>
        </tr>
    `).join('');
}

/* ──────────────────────────────────────────────────────────────
   FILTROS DEL HISTORIAL (Area → Equipo → Sistema → Componente,
   por nombre, en cascada) + resumen de intervalos reales.
   ────────────────────────────────────────────────────────────── */
const _HIST_LEVELS = [
    { id: 'hArea',      key: p => p.area_name || '' },
    { id: 'hEquipment', key: p => p.equipment_name || '' },
    { id: 'hSystem',    key: p => p.system_name || '' },
    { id: 'hComponent', key: p => p.component_name || '' },
];

// Un punto pasa los filtros de los niveles ANTERIORES a uptoId (cascada).
function _histPointPasses(p, uptoId) {
    for (const lvl of _HIST_LEVELS) {
        if (lvl.id === uptoId) return true;
        const v = (q(lvl.id) || {}).value || '';
        if (v && lvl.key(p) !== v) return false;
    }
    return true;
}

function updateHistFilterOptions() {
    _HIST_LEVELS.forEach(lvl => {
        const sel = q(lvl.id);
        if (!sel) return;
        const current = sel.value;
        const candidates = (lubState.points || []).filter(p => _histPointPasses(p, lvl.id));
        const values = [...new Set(candidates.map(lvl.key).filter(Boolean))]
            .sort((a, b) => String(a).localeCompare(String(b), 'es', { numeric: true, sensitivity: 'base' }));
        const firstLabel = sel.options[0] ? sel.options[0].textContent : 'Todos';
        sel.innerHTML = `<option value="">${firstLabel}</option>` +
            values.map(v => `<option value="${_esc(v)}">${_esc(v)}</option>`).join('');
        if (current && !values.includes(current)) {
            sel.insertAdjacentHTML('beforeend', `<option value="${_esc(current)}">${_esc(current)}</option>`);
        }
        sel.value = current;
    });
}

function _histQueryParams() {
    const params = new URLSearchParams();
    const map = { hArea: 'area', hEquipment: 'equipment', hSystem: 'system', hComponent: 'component' };
    Object.entries(map).forEach(([id, key]) => {
        const v = (q(id) || {}).value || '';
        if (v) params.set(key, v);
    });
    const from = (q('hFrom') || {}).value || '';
    const to = (q('hTo') || {}).value || '';
    if (from) params.set('date_from', from);
    if (to) params.set('date_to', to);
    return params;
}

// Resumen: cuantas lubricaciones, cada cuantos dias en promedio (real) y la
// frecuencia teorica cuando el filtro cae en un solo punto.
function renderHistSummary(rows, hasFilters) {
    const countEl = q('hfCount');
    if (countEl) countEl.textContent = rows.length ? `(${rows.length})` : '';
    const el = q('histSummary');
    if (!el) return;
    if (!hasFilters || !rows.length) { el.style.display = 'none'; return; }
    const ivals = rows.map(r => r.interval_days).filter(v => v != null);
    const changes = rows.filter(r => r.action_type === 'CAMBIO_TOTAL' || r.action_type === 'SERVICIO').length;
    const pointIds = new Set(rows.map(r => r.point_id));
    let txt = `<b>${rows.length}</b> lubricaciones (${changes} cambio(s) total(es), ${rows.length - changes} relleno(s)) en <b>${pointIds.size}</b> punto(s)`;
    if (ivals.length) {
        const avg = ivals.reduce((a, b) => a + b, 0) / ivals.length;
        txt += ` &middot; se ha lubricado cada <b>${avg.toFixed(1)} d&iacute;as</b> en promedio (m&iacute;n ${Math.min(...ivals)}, m&aacute;x ${Math.max(...ivals)})`;
    }
    if (pointIds.size === 1 && rows[0].frequency_days) {
        txt += ` &middot; frecuencia te&oacute;rica <b>${rows[0].frequency_days} d&iacute;as</b>`;
    }
    el.innerHTML = txt;
    el.style.display = '';
}

function clearHistFilters() {
    ['hArea', 'hEquipment', 'hSystem', 'hComponent', 'hFrom', 'hTo'].forEach(id => {
        const el = q(id);
        if (el) el.value = '';
    });
    updateHistFilterOptions();
    loadExecutions();
}
window.clearHistFilters = clearHistFilters;

async function deleteExecution(execId) {
    if (!confirm('¿Eliminar esta ejecucion? El semaforo del punto se recalculara con la ultima ejecucion restante.')) return;
    try {
        await jget(`/api/lubrication/executions/${execId}`, { method: 'DELETE' });
        await refreshAll();
    } catch (e) {
        alert(`Error al eliminar: ${e.message}`);
    }
}
window.deleteExecution = deleteExecution;

async function loadDashboard() {
    const url = lubState.showInactive
        ? '/api/lubrication/dashboard?show_inactive=true'
        : '/api/lubrication/dashboard';
    const data = await jget(url);
    updateKPIs(data.kpi || {});
    renderPoints(data.items || []);
}

async function loadExecutions() {
    const params = _histQueryParams();
    const qs = params.toString();
    const data = await jget('/api/lubrication/executions' + (qs ? `?${qs}` : ''));
    renderExecutions(data || []);
    renderHistSummary(data || [], qs.length > 0);
}

/* ──────────────────────────────────────────────────────────────
   EXPORTACION A EXCEL
   ────────────────────────────────────────────────────────────── */
// Excel de pendientes: respeta los filtros activos de la tabla de puntos.
function exportPendingExcel() {
    const params = new URLSearchParams({ scope: 'pending' });
    const map = {
        tfArea: 'area', tfEquipment: 'equipment', tfSystem: 'system',
        tfComponent: 'component', tfLubricant: 'lubricant', tfFreq: 'freq',
        tfSema: 'sema', tfDue: 'due', tfSearch: 'search', fResponsible: 'responsible',
    };
    Object.entries(map).forEach(([id, key]) => {
        const v = ((q(id) || {}).value || '').trim();
        if (v) params.set(key, v);
    });
    window.location = '/api/lubrication/export?' + params.toString();
}
window.exportPendingExcel = exportPendingExcel;

// Excel de historial: respeta los filtros del panel de historial.
function exportHistoryExcel() {
    const params = _histQueryParams();
    params.set('scope', 'history');
    window.location = '/api/lubrication/export?' + params.toString();
}
window.exportHistoryExcel = exportHistoryExcel;

async function createPoint() {
    const payload = {
        name: (q('fName').value || '').trim(),
        area_id: q('fArea').value || null,
        line_id: q('fLine').value || null,
        equipment_id: q('fEquipment').value || null,
        system_id: q('fSystem').value || null,
        component_id: q('fComponent').value || null,
        lubricant_name: (q('fLub').value || '').trim() || null,
        frequency_days: Number(q('fFreq').value || 30),
        warning_days: Number(q('fWarn').value || 3)
    };
    if (!payload.name) {
        alert('Ingresa nombre del punto.');
        return;
    }
    await jget('/api/lubrication/points', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    });
    q('fName').value = '';
    q('fLub').value = '';
    await refreshAll();
}

async function registerExecution() {
    const userComment = (q('fComments') ? q('fComments').value : '').trim();
    const payload = {
        point_id: Number(q('fPoint').value || 0),
        execution_date: q('fExecDate').value || new Date().toISOString().slice(0, 10),
        action_type: (q('fActionType') && q('fActionType').value) || 'CAMBIO_TOTAL',
        quantity_used: q('fQty').value ? Number(q('fQty').value) : null,
        executed_by: (q('fBy').value || '').trim() || null,
        leak_detected: q('fLeak') ? q('fLeak').value === '1' : false,
        anomaly_detected: q('fAnom').value === '1',
        create_notice: true,
        // Solo enviamos el comentario del usuario; el backend decide si crear
        // aviso OBSERVADO cuando hay texto sin fuga ni anomalia.
        comments: userComment || null,
    };
    if (!payload.point_id) {
        alert('Selecciona un punto para registrar ejecucion.');
        return;
    }
    const result = await jget('/api/lubrication/executions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    });
    // Limpiar inputs (fBy vuelve al default FAPMETAL, responsable habitual)
    q('fQty').value = '';
    q('fBy').value = 'FAPMETAL';
    if (q('fComments')) q('fComments').value = '';
    if (q('fLeak')) q('fLeak').value = '0';
    q('fAnom').value = '0';
    if (result && result.created_notice_id) {
        const code = 'AV-' + String(result.created_notice_id).padStart(4, '0');
        alert(`Lubricacion registrada. Se creo aviso ${code} para programar la atencion.`);
    }
    await refreshAll();
}

async function togglePoint(id, isCurrentlyInactive) {
    const action = isCurrentlyInactive ? 'Reactivar' : 'Desactivar';
    if (!confirm(`${action} este punto?`)) return;
    await jget(`/api/lubrication/points/${id}`, { method: 'DELETE' });
    await refreshAll();
}
window.togglePoint = togglePoint;

function toggleInactiveFilter() {
    lubState.showInactive = !lubState.showInactive;
    const btn = q('btnToggleInactive');
    if (btn) {
        btn.classList.toggle('active', lubState.showInactive);
        btn.innerHTML = lubState.showInactive
            ? '<i class="fas fa-eye-slash"></i> Ocultar Inactivos'
            : '<i class="fas fa-eye"></i> Mostrar Inactivos';
    }
    refreshAll();
}
window.toggleInactiveFilter = toggleInactiveFilter;

function openEditModal(id) {
    const p = lubState.points.find(x => x.id === id);
    if (!p) return;

    q('eId').value = p.id;
    q('eName').value = p.name || '';
    q('eLub').value = p.lubricant_name || '';
    q('eFreq').value = p.frequency_days || 30;
    q('eWarn').value = p.warning_days || 3;
    q('eLastDate').value = p.last_service_date || '';

    // Populate equipment select
    fillSelect(q('eEquipment'), lubState.equipments, 'id', e => `${e.tag ? e.tag + ' - ' : ''}${e.name}`);
    q('eEquipment').value = p.equipment_id || '';

    const systems = lubState.systems.filter(s => Number(s.equipment_id) === Number(p.equipment_id || 0));
    fillSelect(q('eSystem'), systems, 'id', s => s.name);
    q('eSystem').value = p.system_id || '';

    const comps = lubState.components.filter(c => Number(c.system_id) === Number(p.system_id || 0));
    fillSelect(q('eComponent'), comps, 'id', c => c.name);
    q('eComponent').value = p.component_id || '';

    q('eEquipment').onchange = () => {
        const eqId = Number(q('eEquipment').value || 0);
        fillSelect(q('eSystem'), lubState.systems.filter(s => Number(s.equipment_id) === eqId), 'id', s => s.name);
        fillSelect(q('eComponent'), [], 'id', c => c.name);
    };
    q('eSystem').onchange = () => {
        const sysId = Number(q('eSystem').value || 0);
        fillSelect(q('eComponent'), lubState.components.filter(c => Number(c.system_id) === sysId), 'id', c => c.name);
    };

    q('editModal').classList.add('open');
}
window.openEditModal = openEditModal;

function closeEditModal() {
    q('editModal').classList.remove('open');
}
window.closeEditModal = closeEditModal;

async function saveEdit() {
    const id = q('eId').value;
    const payload = {
        name: q('eName').value.trim(),
        equipment_id: q('eEquipment').value || null,
        system_id: q('eSystem').value || null,
        component_id: q('eComponent').value || null,
        lubricant_name: q('eLub').value.trim() || null,
        frequency_days: Number(q('eFreq').value || 30),
        warning_days: Number(q('eWarn').value || 3),
        last_service_date: q('eLastDate').value || null
    };
    if (!payload.name) { alert('El nombre es obligatorio.'); return; }
    try {
        await jget(`/api/lubrication/points/${id}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        closeEditModal();
        await refreshAll();
    } catch (e) {
        alert(`Error al guardar: ${e.message}`);
    }
}
window.saveEdit = saveEdit;

async function refreshAll() {
    await loadDashboard();
    await loadExecutions();
}

async function boot() {
    try {
        q('fExecDate').value = new Date().toISOString().slice(0, 10);
        await loadCatalogs();
        await refreshAll();
        q('fArea').addEventListener('change', onAreaChange);
        q('fLine').addEventListener('change', onLineChange);
        q('fEquipment').addEventListener('change', onEquipmentChange);
        q('fSystem').addEventListener('change', onSystemChange);
        q('btnCreate').addEventListener('click', createPoint);
        q('btnExec').addEventListener('click', registerExecution);
        if (q('fPointSearch')) q('fPointSearch').addEventListener('input', renderPointSelect);
        // Filtros de la lista de puntos
        ['tfArea', 'tfEquipment', 'tfSystem', 'tfComponent', 'tfLubricant',
         'tfFreq', 'tfSema', 'tfDue'].forEach(id => {
            if (q(id)) q(id).addEventListener('change', renderPointsView);
        });
        if (q('tfSearch')) {
            let _tfTimer = null;
            q('tfSearch').addEventListener('input', () => {
                clearTimeout(_tfTimer);
                _tfTimer = setTimeout(renderPointsView, 200);
            });
        }
        if (q('btnClearFilters')) q('btnClearFilters').addEventListener('click', clearTableFilters);
        // Filtros del historial (cascada: al cambiar un nivel se limpian los hijos)
        _HIST_LEVELS.forEach((lvl, idx) => {
            const sel = q(lvl.id);
            if (!sel) return;
            sel.addEventListener('change', () => {
                for (let j = idx + 1; j < _HIST_LEVELS.length; j++) {
                    const child = q(_HIST_LEVELS[j].id);
                    if (child) child.value = '';
                }
                updateHistFilterOptions();
                loadExecutions().catch(e => alert(`Error cargando historial: ${e.message}`));
            });
        });
        ['hFrom', 'hTo'].forEach(id => {
            if (q(id)) q(id).addEventListener('change', () => {
                loadExecutions().catch(e => alert(`Error cargando historial: ${e.message}`));
            });
        });
        if (q('btnHistClear')) q('btnHistClear').addEventListener('click', clearHistFilters);
        if (q('btnExportPending')) q('btnExportPending').addEventListener('click', exportPendingExcel);
        if (q('btnExportHistory')) q('btnExportHistory').addEventListener('click', exportHistoryExcel);
        // Restaurar vista preferida (tabla por defecto)
        let savedView = 'table';
        try { savedView = localStorage.getItem('cmms.lub.view') || 'table'; } catch (e) { /* ignore */ }
        setLubView(savedView);
    } catch (e) {
        alert(`Error inicializando lubricacion: ${e.message}`);
    }
}

document.addEventListener('DOMContentLoaded', boot);
