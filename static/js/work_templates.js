// ============= TRABAJOS ESTANDAR =============
// OTs repetitivas (cambio de chumacera conducida de TH1..TH9, empaquetadura de
// la boca de llenado de cada digestor...): se elige el trabajo, se marcan los
// equipos y cada OT sale con descripcion, ubicacion, tipo, duracion, personal
// y materiales previstos. Usa el arbol cargado por work_orders.js
// (allAreas, allLines, allEquips, allSystems, allComponents).

let wtTemplates = [];
let wtMaterials = [];          // materiales del trabajo en edicion
let wtCatalog = { warehouse: null, tool: null };
let wtCurrent = null;          // trabajo que se esta aplicando
let wtTargets = [];            // equipos candidatos del trabajo actual
let wtSelected = new Set();
let wtDescEdits = {};          // key -> descripcion editada a mano
let wtPreviewTimer = null;

const WT_SUBTYPE_LABEL = { repuesto: 'Repuesto', consumible: 'Consumible', herramienta: 'Herramienta' };
const WT_SPECIALTY_LABEL = { MECANICO: 'mecánico', ELECTRICO: 'eléctrico', SOLDADOR: 'soldador', INSTRUMENTISTA: 'instrumentista' };
const wtSpecialty = s => WT_SPECIALTY_LABEL[s] || (s || '').toLowerCase();

function wtEsc(s) {
    return String(s == null ? '' : s)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

async function wtFetchJson(url, opts) {
    const res = await fetch(url, opts);
    let body = null;
    try { body = await res.json(); } catch (_) { /* respuesta vacia */ }
    if (!res.ok) throw new Error((body && body.error) || `Error ${res.status}`);
    return body;
}

async function wtEnsureHierarchy() {
    if (allEquips.length && allSystems.length && allComponents.length) return;
    if (typeof loadHierarchyData === 'function') await loadHierarchyData();
}

// ── Lista ────────────────────────────────────────────────────────────────

async function openWorkTemplates() {
    document.getElementById('wtSearch').value = '';
    document.getElementById('wtListModal').showModal();
    await loadWorkTemplates();
}
window.openWorkTemplates = openWorkTemplates;

async function loadWorkTemplates() {
    const box = document.getElementById('wtList');
    box.innerHTML = '<div style="color:#888;padding:12px;">Cargando...</div>';
    try {
        wtTemplates = await wtFetchJson('/api/work-templates?only_active=0');
    } catch (e) {
        box.innerHTML = `<div style="color:#FF453A;padding:12px;">${wtEsc(e.message)}</div>`;
        return;
    }
    renderWorkTemplateList();
}

function wtWhereLabel(t) {
    const filters = [];
    if (t.area_name) filters.push(`área ${t.area_name}`);
    if (t.line_name) filters.push(`línea ${t.line_name}`);
    if (t.tag_filter) filters.push(`tag con "${t.tag_filter}"`);
    const suffix = filters.length ? ` · ${filters.join(' · ')}` : '';
    if (t.equipment_id) {
        const comp = t.component_fixed_name || t.component_name;
        return `Equipo ${t.equipment_tag || ''}${comp ? ' · ' + comp : ''}`;
    }
    if (t.component_name) return `Equipos con ${t.component_name}${suffix}`;
    return `Equipo completo${suffix || ' · todos los equipos'}`;
}

function renderWorkTemplateList() {
    const box = document.getElementById('wtList');
    const q = (document.getElementById('wtSearch').value || '').trim().toLowerCase();
    const rows = wtTemplates.filter(t => !q ||
        (t.name || '').toLowerCase().includes(q) ||
        (t.description_template || '').toLowerCase().includes(q) ||
        (t.component_name || '').toLowerCase().includes(q));
    if (!rows.length) {
        box.innerHTML = `<div style="text-align:center;color:#888;padding:24px;">
            ${wtTemplates.length ? 'Ningún trabajo coincide con la búsqueda.' :
            'Aún no hay trabajos estándar. Cree uno con "Nuevo trabajo estándar", o abra una orden de trabajo ya hecha y use "Guardar como trabajo estándar".'}
        </div>`;
        return;
    }
    box.innerHTML = rows.map(t => {
        const meta = [
            t.maintenance_type,
            t.estimated_duration ? `${t.estimated_duration} h` : null,
            t.tech_count ? `${t.tech_count} técnico${t.tech_count > 1 ? 's' : ''}` : null,
            t.specialty ? wtSpecialty(t.specialty).charAt(0).toUpperCase() + wtSpecialty(t.specialty).slice(1) : null,
            (t.materials || []).length ? `${t.materials.length} material${t.materials.length > 1 ? 'es' : ''}` : null,
            t.create_notice ? 'con aviso' : 'solo orden de trabajo',
        ].filter(Boolean).join(' · ');
        return `<div class="wt-card ${t.is_active ? '' : 'inactive'}">
            <div style="flex:1;min-width:260px;">
                <div style="font-weight:600;">${wtEsc(t.name)}${t.is_active ? '' : ' <span style="font-size:.75rem;color:#888;">(inactivo)</span>'}</div>
                <div style="font-size:.8rem;color:rgba(255,255,255,.6);margin-top:2px;">${wtEsc(wtWhereLabel(t))}</div>
                <div style="font-size:.76rem;color:rgba(255,255,255,.45);margin-top:2px;">${wtEsc(meta)}${t.use_count ? ` · usado ${t.use_count} ${t.use_count > 1 ? 'veces' : 'vez'}` : ''}</div>
            </div>
            <div class="wt-actions">
                <button type="button" class="wt-use" onclick="openApplyWorkTemplate(${t.id})" ${t.is_active ? '' : 'disabled'}>
                    <i class="fas fa-play"></i> Generar
                </button>
                <button type="button" onclick="openWorkTemplateEditor(${t.id})" title="Editar"><i class="fas fa-pen"></i></button>
                <button type="button" onclick="deleteWorkTemplate(${t.id})" title="Eliminar" style="color:#FF453A;"><i class="fas fa-trash"></i></button>
            </div>
        </div>`;
    }).join('');
}
window.renderWorkTemplateList = renderWorkTemplateList;

async function deleteWorkTemplate(id) {
    const t = wtTemplates.find(x => x.id === id);
    if (!confirm(`¿Eliminar el trabajo estándar "${t ? t.name : ''}"?\nLas órdenes de trabajo ya generadas no se tocan.`)) return;
    try {
        await wtFetchJson(`/api/work-templates/${id}`, { method: 'DELETE' });
        await loadWorkTemplates();
    } catch (e) { alert('No se pudo eliminar: ' + e.message); }
}
window.deleteWorkTemplate = deleteWorkTemplate;

// ── Editor ───────────────────────────────────────────────────────────────

function wtFillSelect(id, items, selectedId, labelFn, emptyLabel) {
    const sel = document.getElementById(id);
    sel.innerHTML = `<option value="">${wtEsc(emptyLabel)}</option>` + items.map(x =>
        `<option value="${x.id}" ${selectedId && x.id == selectedId ? 'selected' : ''}>${wtEsc(labelFn(x))}</option>`
    ).join('');
}

const wtNat = (a, b) => (a || '').localeCompare(b || '', 'es', { numeric: true, sensitivity: 'base' });
const wtEqLabel = e => (e.tag ? `[${e.tag}] ` : '') + (e.name || '');

function wtRenderFilterSelects(areaId, lineId) {
    wtFillSelect('wtArea', [...allAreas].sort((a, b) => wtNat(a.name, b.name)), areaId, x => x.name, '- Todas las áreas -');
    const lines = allLines.filter(l => !areaId || l.area_id == areaId).sort((a, b) => wtNat(a.name, b.name));
    wtFillSelect('wtLine', lines, lineId, x => x.name, '- Todas las líneas -');
}

function wtRenderFixedSelects(eqId, sysId, compId) {
    wtFillSelect('wtFixedEquip', [...allEquips].sort((a, b) => wtNat(a.tag || a.name, b.tag || b.name)), eqId, wtEqLabel, '- Elija el equipo -');
    const systems = eqId ? allSystems.filter(s => s.equipment_id == eqId).sort((a, b) => wtNat(a.name, b.name)) : [];
    wtFillSelect('wtFixedSystem', systems, sysId, x => x.name, eqId ? '- Cualquier sistema -' : '- Elija un equipo -');
    const comps = sysId ? allComponents.filter(c => c.system_id == sysId).sort((a, b) => wtNat(a.name, b.name)) : [];
    wtFillSelect('wtFixedComp', comps, compId, x => x.name, sysId ? '- Sin componente -' : '- Elija un sistema -');
}

function wtFillComponentNames() {
    const names = [...new Set(allComponents.map(c => (c.name || '').trim().toUpperCase()).filter(Boolean))].sort(wtNat);
    document.getElementById('wtComponentNames').innerHTML = names.map(n => `<option value="${wtEsc(n)}">`).join('');
}

function wtGetMode() {
    const r = document.querySelector('input[name="wtMode"]:checked');
    return r ? r.value : 'component';
}

function wtSetMode(mode) {
    document.querySelectorAll('input[name="wtMode"]').forEach(r => { r.checked = r.value === mode; });
    wtOnModeChange();
}

function wtOnModeChange() {
    const mode = wtGetMode();
    document.getElementById('wtModeComponent').style.display = mode === 'component' ? '' : 'none';
    document.getElementById('wtModeFixed').style.display = mode === 'fixed' ? '' : 'none';
    document.getElementById('wtFilters').style.display = mode === 'fixed' ? 'none' : '';
    wtSchedulePreview();
}
window.wtOnModeChange = wtOnModeChange;

function wtOnFixedChange(level) {
    const eqId = document.getElementById('wtFixedEquip').value;
    const sysId = level === 'equipment' ? '' : document.getElementById('wtFixedSystem').value;
    wtRenderFixedSelects(eqId, sysId, null);
    wtSchedulePreview();
}
window.wtOnFixedChange = wtOnFixedChange;

function wtOnFilterAreaChange() {
    wtRenderFilterSelects(document.getElementById('wtArea').value, null);
    wtSchedulePreview();
}
window.wtOnFilterAreaChange = wtOnFilterAreaChange;

function wtOnNoticeToggle() {
    document.getElementById('wtNoticeFields').style.display =
        document.getElementById('wtCreateNotice').checked ? '' : 'none';
}
window.wtOnNoticeToggle = wtOnNoticeToggle;

function wtInsertPlaceholder(ph) {
    const ta = document.getElementById('wtDescription');
    const start = ta.selectionStart ?? ta.value.length;
    const end = ta.selectionEnd ?? ta.value.length;
    ta.value = ta.value.slice(0, start) + ph + ta.value.slice(end);
    ta.focus();
    ta.selectionStart = ta.selectionEnd = start + ph.length;
}
window.wtInsertPlaceholder = wtInsertPlaceholder;

function wtCollectForm() {
    const mode = wtGetMode();
    const num = id => { const v = document.getElementById(id).value; return v === '' ? null : Number(v); };
    const data = {
        name: document.getElementById('wtName').value.trim(),
        description_template: document.getElementById('wtDescription').value.trim(),
        maintenance_type: document.getElementById('wtType').value,
        failure_mode: document.getElementById('wtFailureMode').value.trim(),
        specialty: document.getElementById('wtSpecialty').value,
        tech_count: num('wtTechCount') || 1,
        estimated_duration: num('wtDuration'),
        create_notice: document.getElementById('wtCreateNotice').checked,
        priority: document.getElementById('wtPriority').value,
        criticality: document.getElementById('wtCriticality').value,
        is_active: document.getElementById('wtActive').checked,
        materials: wtMaterials,
        component_name: '', equipment_id: null, system_id: null, component_id: null,
        area_id: null, line_id: null, tag_filter: '',
    };
    if (mode === 'fixed') {
        data.equipment_id = num('wtFixedEquip');
        data.system_id = num('wtFixedSystem');
        data.component_id = num('wtFixedComp');
    } else {
        if (mode === 'component') data.component_name = document.getElementById('wtComponentName').value.trim();
        data.area_id = num('wtArea');
        data.line_id = num('wtLine');
        data.tag_filter = document.getElementById('wtTagFilter').value.trim();
    }
    return data;
}

function wtSchedulePreview() {
    clearTimeout(wtPreviewTimer);
    wtPreviewTimer = setTimeout(wtRunPreview, 350);
}
window.wtSchedulePreview = wtSchedulePreview;

async function wtRunPreview() {
    const box = document.getElementById('wtPreview');
    const data = wtCollectForm();
    const mode = wtGetMode();
    if (mode === 'component' && !data.component_name) {
        box.innerHTML = 'Escriba el nombre del componente para ver en qué equipos aplica.';
        return;
    }
    if (mode === 'fixed' && !data.equipment_id) {
        box.innerHTML = 'Elija el equipo.';
        return;
    }
    try {
        const r = await wtFetchJson('/api/work-templates/preview-targets', {
            method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data),
        });
        if (!r.count) {
            box.innerHTML = '<span style="color:#FF9F0A;"><i class="fas fa-exclamation-triangle"></i> No aplica a ningún equipo. Revise el nombre del componente o los filtros.</span>';
            return;
        }
        const more = r.count > r.tags.length ? ` y ${r.count - r.tags.length} más` : '';
        box.innerHTML = `<i class="fas fa-check-circle" style="color:#30D158;"></i> Aplica a <b>${r.count}</b> ${r.count > 1 ? 'equipos' : 'equipo'}: ${wtEsc(r.tags.join(', '))}${more}`;
    } catch (e) {
        box.innerHTML = `<span style="color:#FF453A;">${wtEsc(e.message)}</span>`;
    }
}

async function openWorkTemplateEditor(id, draft) {
    await wtEnsureHierarchy();
    if (typeof loadFailureModeSuggestions === 'function') loadFailureModeSuggestions();
    wtFillComponentNames();
    const t = id ? wtTemplates.find(x => x.id === id) : (draft || {});

    document.getElementById('wtId').value = id || '';
    document.getElementById('wtEditTitle').textContent = id ? 'Editar trabajo estándar' : 'Nuevo trabajo estándar';
    const note = document.getElementById('wtSourceNote');
    if (draft && draft.source_ot_code) {
        note.style.display = '';
        note.innerHTML = `<i class="fas fa-info-circle"></i> Basado en la ${wtEsc(draft.source_ot_code)}${draft.source_equipment_tag ? ` (${wtEsc(draft.source_equipment_tag)})` : ''}. Revise la descripción: el tag del equipo se cambió por el dato de cada equipo.`;
    } else {
        note.style.display = 'none';
    }

    document.getElementById('wtName').value = t.name || '';
    document.getElementById('wtDescription').value = t.description_template || '';
    document.getElementById('wtType').value = t.maintenance_type || 'Correctivo';
    document.getElementById('wtFailureMode').value = t.failure_mode || '';
    document.getElementById('wtSpecialty').value = t.specialty || '';
    document.getElementById('wtTechCount').value = t.tech_count || 1;
    document.getElementById('wtDuration').value = t.estimated_duration ?? '';
    document.getElementById('wtCreateNotice').checked = !!t.create_notice;
    document.getElementById('wtPriority').value = t.priority || 'Media';
    document.getElementById('wtCriticality').value = t.criticality || '';
    document.getElementById('wtActive').checked = t.is_active !== false;
    document.getElementById('wtComponentName').value = t.component_name || '';
    document.getElementById('wtTagFilter').value = t.tag_filter || '';
    wtRenderFilterSelects(t.area_id, t.line_id);
    wtRenderFixedSelects(t.equipment_id, t.system_id, t.component_id);
    wtOnNoticeToggle();

    wtMaterials = (t.materials || []).map(m => ({ ...m }));
    wtRenderMaterials();
    document.getElementById('wtMatSubtype').value = 'repuesto';
    document.getElementById('wtMatName').value = '';
    document.getElementById('wtMatQty').value = 1;
    document.getElementById('wtMatUnit').value = '';
    wtLoadMaterialOptions();

    wtSetMode(t.equipment_id ? 'fixed' : (t.component_name || (!id && !draft) ? 'component' : 'equipment'));
    document.getElementById('wtEditModal').showModal();
}
window.openWorkTemplateEditor = openWorkTemplateEditor;

async function saveWorkTemplate(e) {
    e.preventDefault();
    const id = document.getElementById('wtId').value;
    const data = wtCollectForm();
    if (!data.name) { alert('Escriba el nombre del trabajo.'); return; }
    if (!data.description_template) { alert('Escriba la descripción que tendrá cada orden de trabajo.'); return; }
    const mode = wtGetMode();
    if (mode === 'component' && !data.component_name) { alert('Escriba el nombre del componente.'); return; }
    if (mode === 'fixed' && !data.equipment_id) { alert('Elija el equipo.'); return; }
    try {
        await wtFetchJson(id ? `/api/work-templates/${id}` : '/api/work-templates', {
            method: id ? 'PUT' : 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
        });
    } catch (err) {
        alert('No se pudo guardar: ' + err.message);
        return;
    }
    document.getElementById('wtEditModal').close();
    if (!document.getElementById('wtListModal').open) document.getElementById('wtListModal').showModal();
    await loadWorkTemplates();
}
window.saveWorkTemplate = saveWorkTemplate;

// Materiales previstos
async function wtLoadMaterialOptions() {
    const sub = document.getElementById('wtMatSubtype').value;
    const kind = sub === 'herramienta' ? 'tool' : 'warehouse';
    if (!wtCatalog[kind]) {
        try {
            wtCatalog[kind] = await wtFetchJson(kind === 'tool' ? '/api/tools' : '/api/warehouse') || [];
        } catch (_) { wtCatalog[kind] = []; }
    }
    document.getElementById('wtMatOptions').innerHTML = wtCatalog[kind]
        .filter(x => kind !== 'tool' || x.is_active !== false)
        .map(x => `<option value="${wtEsc(x.code)} — ${wtEsc(x.name)}">`).join('');
}
window.wtLoadMaterialOptions = wtLoadMaterialOptions;

function wtAddMaterial() {
    const sub = document.getElementById('wtMatSubtype').value;
    const kind = sub === 'herramienta' ? 'tool' : 'warehouse';
    const raw = document.getElementById('wtMatName').value.trim();
    if (!raw) { alert('Escriba o elija el material.'); return; }
    const item = (wtCatalog[kind] || []).find(x => `${x.code} — ${x.name}` === raw || x.code === raw);
    const qty = Number(document.getElementById('wtMatQty').value) || 1;
    const unit = document.getElementById('wtMatUnit').value.trim();
    wtMaterials.push(item
        ? { item_type: kind, item_id: item.id, code: item.code, name: item.name, quantity: qty, unit: unit || item.unit || null, subtype: sub }
        : { item_type: 'free', item_id: null, code: null, name: raw, quantity: qty, unit: unit || null, subtype: sub });
    document.getElementById('wtMatName').value = '';
    document.getElementById('wtMatQty').value = 1;
    document.getElementById('wtMatUnit').value = '';
    wtRenderMaterials();
}
window.wtAddMaterial = wtAddMaterial;

function wtRemoveMaterial(idx) {
    wtMaterials.splice(idx, 1);
    wtRenderMaterials();
}
window.wtRemoveMaterial = wtRemoveMaterial;

function wtRenderMaterials() {
    const tbody = document.getElementById('wtMaterialsBody');
    if (!wtMaterials.length) {
        tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:#888;">Sin materiales previstos.</td></tr>';
        return;
    }
    tbody.innerHTML = wtMaterials.map((m, i) => `<tr>
        <td>${WT_SUBTYPE_LABEL[m.subtype] || 'Repuesto'}</td>
        <td style="font-family:monospace;font-size:.82rem;">${wtEsc(m.code || '—')}</td>
        <td>${wtEsc(m.name)}</td>
        <td style="text-align:center;">${wtEsc(m.quantity)}</td>
        <td style="text-align:center;">${wtEsc(m.unit || '-')}</td>
        <td><button type="button" onclick="wtRemoveMaterial(${i})" style="padding:2px 8px;background:#FF453A22;border:1px solid #FF453A55;border-radius:4px;color:#FF453A;cursor:pointer;"><i class="fas fa-trash"></i></button></td>
    </tr>`).join('');
}

// Desde una OT abierta en el modal de edicion
async function saveOTAsWorkTemplate() {
    const otId = document.getElementById('otId').value;
    if (!otId) return;
    try {
        const draft = await wtFetchJson(`/api/work-templates/draft-from-ot/${otId}`);
        if (!wtTemplates.length) {
            try { wtTemplates = await wtFetchJson('/api/work-templates?only_active=0'); } catch (_) { /* lista opcional */ }
        }
        document.getElementById('otModal').close();
        await openWorkTemplateEditor(null, draft);
    } catch (e) {
        alert('No se pudo preparar el trabajo estándar: ' + e.message);
    }
}
window.saveOTAsWorkTemplate = saveOTAsWorkTemplate;

// ── Generar OTs ──────────────────────────────────────────────────────────

async function openApplyWorkTemplate(id) {
    wtCurrent = wtTemplates.find(x => x.id === id);
    if (!wtCurrent) return;
    wtSelected = new Set();
    wtDescEdits = {};
    wtTargets = [];
    document.getElementById('wtApplyTitle').textContent = `Generar órdenes de trabajo: ${wtCurrent.name}`;
    const parts = [
        wtCurrent.maintenance_type,
        wtCurrent.estimated_duration ? `${wtCurrent.estimated_duration} h estimadas` : null,
        wtCurrent.specialty ? `${wtCurrent.tech_count || 1} × ${wtSpecialty(wtCurrent.specialty)}` : `${wtCurrent.tech_count || 1} técnico(s)`,
        (wtCurrent.materials || []).length ? `materiales previstos: ${wtCurrent.materials.map(m => `${m.quantity} ${m.name}`).join(', ')}` : null,
    ].filter(Boolean);
    document.getElementById('wtApplySummary').textContent = parts.join(' · ');
    document.getElementById('wtApplyDate').value = '';
    document.getElementById('wtApplyNotice').checked = !!wtCurrent.create_notice;
    document.getElementById('wtApplySearch').value = '';
    document.getElementById('wtApplyResult').style.display = 'none';
    document.getElementById('wtTargetsBody').innerHTML = '<tr><td colspan="5" style="color:#888;padding:14px;">Buscando equipos...</td></tr>';
    document.getElementById('wtTargetsEmpty').style.display = 'none';
    wtUpdateApplyButton();
    document.getElementById('wtApplyModal').showModal();

    try {
        const r = await wtFetchJson(`/api/work-templates/${id}/targets`);
        wtTargets = r.targets || [];
    } catch (e) {
        document.getElementById('wtTargetsBody').innerHTML = `<tr><td colspan="5" style="color:#FF453A;padding:14px;">${wtEsc(e.message)}</td></tr>`;
        return;
    }
    // Un solo equipo posible: ya marcado
    if (wtTargets.length === 1 && !wtTargets[0].open_ot_code) wtSelected.add(wtTargets[0].key);
    renderWorkTemplateTargets();
}
window.openApplyWorkTemplate = openApplyWorkTemplate;

function wtVisibleTargets() {
    const q = (document.getElementById('wtApplySearch').value || '').trim().toLowerCase();
    if (!q) return wtTargets;
    return wtTargets.filter(t => [t.equipment_tag, t.equipment_name, t.area_name, t.line_name, t.system_name, t.component_name]
        .some(v => (v || '').toLowerCase().includes(q)));
}

function renderWorkTemplateTargets() {
    const tbody = document.getElementById('wtTargetsBody');
    const empty = document.getElementById('wtTargetsEmpty');
    const rows = wtVisibleTargets();
    if (!wtTargets.length) {
        tbody.innerHTML = '';
        empty.style.display = '';
        empty.textContent = 'Este trabajo no aplica a ningún equipo. Edítelo y revise el componente o los filtros.';
        wtUpdateApplyButton();
        return;
    }
    empty.style.display = rows.length ? 'none' : '';
    empty.textContent = 'Ningún equipo coincide con el filtro.';
    tbody.innerHTML = rows.map(t => {
        const checked = wtSelected.has(t.key) ? 'checked' : '';
        const desc = wtDescEdits[t.key] ?? t.description;
        const warn = t.open_ot_code
            ? `<div style="color:#FF9F0A;font-size:.74rem;margin-top:3px;"><i class="fas fa-exclamation-triangle"></i> Ya tiene la ${wtEsc(t.open_ot_code)} (${wtEsc(t.open_ot_status)})</div>`
            : '';
        const comp = t.component_name
            ? `${wtEsc(t.system_name || '')}<br><b>${wtEsc(t.component_name)}</b>`
            : (t.system_name ? wtEsc(t.system_name) : '<span style="color:#888;">Equipo completo</span>');
        return `<tr class="${t.open_ot_code ? 'wt-has-open' : ''}">
            <td><input type="checkbox" data-key="${wtEsc(t.key)}" ${checked} onchange="wtToggleTarget(this)"></td>
            <td><b>${wtEsc(t.equipment_tag)}</b><div style="font-size:.76rem;color:rgba(255,255,255,.55);">${wtEsc(t.equipment_name)}</div>${warn}</td>
            <td style="font-size:.8rem;">${wtEsc(t.area_name || '-')}<div style="color:rgba(255,255,255,.5);">${wtEsc(t.line_name || '')}</div></td>
            <td style="font-size:.8rem;">${comp}</td>
            <td><input type="text" data-key="${wtEsc(t.key)}" value="${wtEsc(desc)}" oninput="wtEditDesc(this)"></td>
        </tr>`;
    }).join('');
    wtUpdateApplyButton();
}
window.renderWorkTemplateTargets = renderWorkTemplateTargets;

function wtToggleTarget(cb) {
    if (cb.checked) wtSelected.add(cb.dataset.key);
    else wtSelected.delete(cb.dataset.key);
    wtUpdateApplyButton();
}
window.wtToggleTarget = wtToggleTarget;

function wtEditDesc(input) {
    wtDescEdits[input.dataset.key] = input.value;
}
window.wtEditDesc = wtEditDesc;

function wtSelectAllTargets(on) {
    if (on) {
        // Los que ya tienen una OT abierta del mismo trabajo se marcan a mano
        wtVisibleTargets().filter(t => !t.open_ot_code).forEach(t => wtSelected.add(t.key));
    } else {
        wtSelected.clear();
    }
    renderWorkTemplateTargets();
}
window.wtSelectAllTargets = wtSelectAllTargets;

function wtUpdateApplyButton() {
    const btn = document.getElementById('wtApplyBtn');
    const n = wtSelected.size;
    btn.disabled = n === 0;
    btn.innerHTML = n ? `<i class="fas fa-check"></i> Crear ${n} ${n > 1 ? 'órdenes de trabajo' : 'orden de trabajo'}` : 'Marque los equipos';
}

let _wtGenerating = false;
async function generateFromWorkTemplate() {
    if (_wtGenerating || !wtCurrent || !wtSelected.size) return;
    const chosen = wtTargets.filter(t => wtSelected.has(t.key));
    const withOpen = chosen.filter(t => t.open_ot_code);
    if (withOpen.length && !confirm(`${withOpen.map(t => `${t.equipment_tag} ya tiene la ${t.open_ot_code}`).join('\n')}\n\n¿Crear de todos modos?`)) return;

    const createNotice = document.getElementById('wtApplyNotice').checked;
    _wtGenerating = true;
    const btn = document.getElementById('wtApplyBtn');
    btn.disabled = true;
    btn.innerHTML = '<i class="fas fa-circle-notch fa-spin"></i> Creando...';
    try {
        const r = await wtFetchJson(`/api/work-templates/${wtCurrent.id}/generate`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                scheduled_date: document.getElementById('wtApplyDate').value || null,
                create_notice: createNotice,
                targets: chosen.map(t => ({
                    equipment_id: t.equipment_id,
                    system_id: t.system_id,
                    component_id: t.component_id,
                    description: (wtDescEdits[t.key] ?? t.description).trim(),
                })),
            }),
        });
        const box = document.getElementById('wtApplyResult');
        box.style.display = '';
        box.innerHTML = `<b><i class="fas fa-check-circle"></i> Se crearon ${r.created_count} ${r.created_count > 1 ? 'órdenes de trabajo' : 'orden de trabajo'}:</b><br>` +
            r.created.map(c => `${wtEsc(c.code)}${c.notice_code ? ` (aviso ${wtEsc(c.notice_code)})` : ''} — ${wtEsc(c.description)}`).join('<br>');
        // Reabrir con el estado nuevo (avisa de las OTs recien creadas)
        wtSelected.clear();
        try {
            const t = await wtFetchJson(`/api/work-templates/${wtCurrent.id}/targets`);
            wtTargets = t.targets || [];
        } catch (_) { /* la lista anterior sigue sirviendo */ }
        renderWorkTemplateTargets();
        if (typeof loadWorkOrders === 'function') loadWorkOrders();
        loadWorkTemplates();
    } catch (e) {
        alert('No se pudieron crear las órdenes de trabajo: ' + e.message);
        wtUpdateApplyButton();
    } finally {
        _wtGenerating = false;
    }
}
window.generateFromWorkTemplate = generateFromWorkTemplate;
