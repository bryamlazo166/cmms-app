let actState = { activities: [], equipments: [] };

function q(id) { return document.getElementById(id); }

async function jget(url, opts) {
    const r = await fetch(url, opts);
    const d = await r.json();
    if (!r.ok || d.error) throw new Error(d.error || `HTTP ${r.status}`);
    return d;
}

const TYPE_ICONS = {
    FABRICACION: 'fa-cogs', COMPRA: 'fa-shopping-cart', REUNION: 'fa-handshake',
    PROYECTO: 'fa-project-diagram', PARADA: 'fa-power-off', OTRO: 'fa-clipboard'
};
const PRIO_CLASS = { ALTA: 'badge-alta', MEDIA: 'badge-media', BAJA: 'badge-baja' };

function progressColor(p) {
    if (p >= 100) return '#30D158';
    if (p >= 50) return '#FF9F0A';
    return '#0A84FF';
}

// ── Render Activities ─────────────────────────────────────────────────────────

function renderActivities(items) {
    actState.activities = items;
    const list = q('actList');
    if (!items.length) {
        list.innerHTML = '<div class="empty">Sin actividades registradas.</div>';
        return;
    }
    list.innerHTML = items.map(a => {
        const icon = TYPE_ICONS[a.activity_type] || 'fa-clipboard';
        const prioClass = PRIO_CLASS[a.priority] || 'badge-media';
        const pc = progressColor(a.progress);
        const isClosed = a.status === 'COMPLETADA' || a.status === 'CANCELADA';
        const opacity = isClosed ? 'opacity:0.5' : '';

        return `<div class="act-card" id="act-${a.id}" style="${opacity}">
            <div class="act-header" onclick="toggleExpand(${a.id})">
                <i class="fas fa-chevron-right chevron"></i>
                <div class="act-body">
                    <div class="act-title"><i class="fas ${icon}" style="color:#5E5CE6;margin-right:6px"></i>${a.title}</div>
                    <div class="act-meta">
                        <span class="badge-type">${a.activity_type}</span>
                        <span class="${prioClass}">${a.priority}</span>
                        <span class="badge-status st-${a.status}">${a.status.replace('_',' ')}</span>
                        ${a.responsible ? `<span><i class="fas fa-user"></i> ${a.responsible}</span>` : ''}
                        ${a.target_date ? `<span><i class="fas fa-calendar"></i> ${a.target_date}</span>` : ''}
                        ${a.equipment_name ? `<span><i class="fas fa-cog"></i> ${a.equipment_name}</span>` : ''}
                    </div>
                    ${a.next_milestone ? `<div class="next-ms"><i class="fas fa-arrow-right"></i> ${a.next_milestone}${a.next_milestone_date ? ' (' + a.next_milestone_date + ')' : ''}</div>` : ''}
                </div>
                <div class="act-right">
                    <div class="progress-bar"><div class="progress-fill" style="width:${a.progress}%;background:${pc}"></div></div>
                    <div class="progress-text">${a.milestones_done}/${a.milestones_total} hitos (${a.progress}%)</div>
                </div>
            </div>
            <div class="ms-panel" id="ms-panel-${a.id}">
                <ul class="ms-list" id="ms-list-${a.id}"><li style="color:rgba(255,255,255,.30);padding:8px">Cargando hitos...</li></ul>
                <div class="ms-add">
                    <input id="ms-desc-${a.id}" placeholder="Nuevo hito..." style="flex:1;min-width:150px">
                    <input id="ms-date-${a.id}" type="date" style="width:140px">
                    <button class="btn btn-sm btn-primary" onclick="addMilestone(${a.id})"><i class="fas fa-plus"></i></button>
                </div>
                <div style="margin-top:10px;display:flex;gap:6px">
                    <button class="btn btn-sm btn-secondary" onclick="openEditModal(${a.id})"><i class="fas fa-pen"></i> Editar</button>
                    <button class="btn btn-sm btn-danger" onclick="cancelActivity(${a.id})"><i class="fas fa-ban"></i> Cancelar</button>
                </div>
            </div>
        </div>`;
    }).join('');
}

// ── Toggle expand / collapse ──────────────────────────────────────────────────

async function toggleExpand(id) {
    const card = q(`act-${id}`);
    const wasExpanded = card.classList.contains('expanded');

    // Collapse all
    document.querySelectorAll('.act-card.expanded').forEach(c => c.classList.remove('expanded'));

    if (!wasExpanded) {
        card.classList.add('expanded');
        await loadMilestones(id);
    }
}

async function loadMilestones(actId) {
    try {
        const milestones = await jget(`/api/activities/${actId}/milestones`);
        renderMilestones(actId, milestones);
    } catch (e) {
        q(`ms-list-${actId}`).innerHTML = `<li style="color:#FF6B61">Error: ${e.message}</li>`;
    }
}

function renderMilestones(actId, milestones) {
    const list = q(`ms-list-${actId}`);
    if (!milestones.length) {
        list.innerHTML = '<li style="color:rgba(255,255,255,.30);padding:8px;text-align:center">Sin hitos. Agrega el primer hito.</li>';
        return;
    }
    list.innerHTML = milestones.map(m => {
        const isDone = m.status === 'COMPLETADO';
        const isProgress = m.status === 'EN_PROGRESO';
        const iconClass = isDone ? 'ms-done' : isProgress ? 'ms-progress' : 'ms-pending';
        const iconChar = isDone ? '<i class="fas fa-check"></i>' : isProgress ? '<i class="fas fa-spinner"></i>' : '<i class="fas fa-circle"></i>';
        const descClass = isDone ? 'ms-desc done' : 'ms-desc';

        let dateInfo = '';
        if (m.target_date) dateInfo += `Obj: ${m.target_date}`;
        if (m.completion_date) dateInfo += ` | Real: ${m.completion_date}`;

        return `<li class="ms-item" style="flex-wrap:wrap">
            <div class="ms-icon ${iconClass}">${iconChar}</div>
            <div class="ms-body">
                <div class="${descClass}">${m.description}</div>
                ${dateInfo ? `<div class="ms-dates">${dateInfo}</div>` : ''}
                ${m.comment ? `<div class="ms-comment"><i class="fas fa-comment" style="margin-right:3px"></i>${m.comment}</div>` : ''}
            </div>
            <div class="ms-actions">
                ${!isDone ? `<button class="ms-btn-complete" title="Completar" onclick="completeMilestone(${m.id}, ${actId})"><i class="fas fa-check"></i></button>` : ''}
                <button class="ms-btn-del" title="Eliminar" onclick="deleteMilestone(${m.id}, ${actId})"><i class="fas fa-trash"></i></button>
            </div>
            <div style="width:100%;padding-left:32px;margin-top:4px">
                <input id="ms-cmt-${m.id}" value="${(m.comment || '').replace(/"/g, '&quot;')}" placeholder="Agregar comentario..."
                    style="width:100%;height:26px;background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.06);border-radius:5px;color:rgba(255,255,255,.55);padding:0 8px;font-size:.75rem"
                    onblur="saveComment(${m.id}, ${actId}, this.value)">
            </div>
        </li>`;
    }).join('');
}

// ── Milestone actions ─────────────────────────────────────────────────────────

async function addMilestone(actId) {
    const desc = q(`ms-desc-${actId}`).value.trim();
    if (!desc) return;
    const targetDate = q(`ms-date-${actId}`).value || null;
    await jget(`/api/activities/${actId}/milestones`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ description: desc, target_date: targetDate })
    });
    q(`ms-desc-${actId}`).value = '';
    q(`ms-date-${actId}`).value = '';
    await loadMilestones(actId);
    await loadActivities(true);
}

async function saveComment(msId, actId, comment) {
    try {
        await jget(`/api/milestones/${msId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ comment: comment.trim() || null })
        });
    } catch (_) {}
}

async function completeMilestone(msId, actId) {
    // Use existing comment from input if available
    const commentEl = document.getElementById(`ms-cmt-${msId}`);
    const comment = commentEl ? commentEl.value.trim() : '';
    await jget(`/api/milestones/${msId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: 'COMPLETADO', comment: comment || null })
    });
    await loadMilestones(actId);
    await loadActivities(true);
}

async function deleteMilestone(msId, actId) {
    if (!confirm('Eliminar este hito?')) return;
    await jget(`/api/milestones/${msId}`, { method: 'DELETE' });
    await loadMilestones(actId);
    await loadActivities(true);
}

// ── Activity CRUD ─────────────────────────────────────────────────────────────

async function loadActivities(keepExpand) {
    const statusFilter = q('filterStatus').value;
    const typeFilter = q('filterType').value;

    // Always load all to separate active vs closed
    let url = '/api/activities?all=true';
    if (typeFilter) url += `&type=${typeFilter}`;

    const allItems = await jget(url);

    // Split into active and closed
    let active, closed;
    if (statusFilter === 'all') {
        active = allItems.filter(a => !['COMPLETADA', 'CANCELADA'].includes(a.status));
        closed = allItems.filter(a => ['COMPLETADA', 'CANCELADA'].includes(a.status));
    } else if (statusFilter === 'COMPLETADA' || statusFilter === 'CANCELADA') {
        active = [];
        closed = allItems.filter(a => !statusFilter || a.status === statusFilter);
    } else {
        active = allItems.filter(a => {
            if (statusFilter) return a.status === statusFilter;
            return !['COMPLETADA', 'CANCELADA'].includes(a.status);
        });
        closed = allItems.filter(a => ['COMPLETADA', 'CANCELADA'].includes(a.status));
    }

    const expandedId = keepExpand ? document.querySelector('.act-card.expanded')?.id?.replace('act-', '') : null;
    renderActivities(active);
    renderClosedActivities(closed);

    if (expandedId) {
        const card = q(`act-${expandedId}`);
        if (card) { card.classList.add('expanded'); await loadMilestones(Number(expandedId)); }
    }
}

function renderClosedActivities(items) {
    const section = q('closedSection');
    const list = q('closedList');
    const count = q('closedCount');

    if (!items.length) {
        section.style.display = 'none';
        return;
    }
    section.style.display = '';
    count.textContent = items.length;

    list.innerHTML = items.map(a => {
        const icon = TYPE_ICONS[a.activity_type] || 'fa-clipboard';
        const isCompleted = a.status === 'COMPLETADA';
        return `<div class="act-card" id="act-${a.id}" style="opacity:0.55">
            <div class="act-header" onclick="toggleExpand(${a.id})">
                <i class="fas fa-chevron-right chevron"></i>
                <div class="act-body">
                    <div class="act-title"><i class="fas ${icon}" style="color:#5E5CE6;margin-right:6px"></i>${a.title}</div>
                    <div class="act-meta">
                        <span class="badge-type">${a.activity_type}</span>
                        <span class="badge-status st-${a.status}">${a.status.replace('_',' ')}</span>
                        ${a.responsible ? `<span><i class="fas fa-user"></i> ${a.responsible}</span>` : ''}
                        ${a.completion_date ? `<span><i class="fas fa-check-circle" style="color:#30D158"></i> ${a.completion_date}</span>` : ''}
                    </div>
                </div>
                <div class="act-right">
                    <div class="progress-bar"><div class="progress-fill" style="width:${a.progress}%;background:#30D158"></div></div>
                    <div class="progress-text">${a.milestones_done}/${a.milestones_total} (${a.progress}%)</div>
                </div>
            </div>
            <div class="ms-panel" id="ms-panel-${a.id}">
                <ul class="ms-list" id="ms-list-${a.id}"><li style="color:rgba(255,255,255,.30);padding:8px">Cargando...</li></ul>
                <div style="margin-top:10px;display:flex;gap:6px">
                    <button class="btn btn-sm btn-success" onclick="reopenActivity(${a.id})"><i class="fas fa-redo"></i> Reabrir</button>
                    <button class="btn btn-sm btn-secondary" onclick="openEditModal(${a.id})"><i class="fas fa-pen"></i> Editar</button>
                </div>
            </div>
        </div>`;
    }).join('');
}

function toggleClosedSection() {
    const list = q('closedList');
    const chevron = q('closedChevron');
    const isVisible = list.style.display !== 'none';
    list.style.display = isVisible ? 'none' : '';
    chevron.style.transform = isVisible ? '' : 'rotate(180deg)';
}

async function reopenActivity(id) {
    if (!confirm('Reabrir esta actividad?')) return;
    await jget(`/api/activities/${id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: 'EN_PROGRESO', completion_date: null })
    });
    await loadActivities();
}

async function loadEquipments() {
    try {
        const equips = await jget('/api/equipments');
        actState.equipments = equips;
        const sel = q('aEquipment');
        sel.innerHTML = '<option value="">Ninguno</option>' +
            equips.map(e => `<option value="${e.id}">${e.tag ? e.tag + ' - ' : ''}${e.name}</option>`).join('');
    } catch (_) {}
}

function openCreateModal() {
    q('aId').value = '';
    q('modalTitle').innerHTML = '<i class="fas fa-plus-circle"></i> Nueva Actividad';
    q('aTitle').value = '';
    q('aType').value = 'OTRO';
    q('aPriority').value = 'MEDIA';
    q('aResponsible').value = '';
    q('aEquipment').value = '';
    q('aStart').value = new Date().toISOString().slice(0, 10);
    q('aTarget').value = '';
    q('aDesc').value = '';
    q('actModal').classList.add('open');
}

function openEditModal(id) {
    const a = actState.activities.find(x => x.id === id);
    if (!a) return;
    q('aId').value = a.id;
    q('modalTitle').innerHTML = '<i class="fas fa-pen"></i> Editar Actividad';
    q('aTitle').value = a.title || '';
    q('aType').value = a.activity_type || 'OTRO';
    q('aPriority').value = a.priority || 'MEDIA';
    q('aResponsible').value = a.responsible || '';
    q('aEquipment').value = a.equipment_id || '';
    q('aStart').value = a.start_date || '';
    q('aTarget').value = a.target_date || '';
    q('aDesc').value = a.description || '';
    q('actModal').classList.add('open');
}

function closeModal() { q('actModal').classList.remove('open'); }

async function saveActivity() {
    const id = q('aId').value;
    const payload = {
        title: q('aTitle').value.trim(),
        activity_type: q('aType').value,
        priority: q('aPriority').value,
        responsible: q('aResponsible').value.trim() || null,
        equipment_id: q('aEquipment').value || null,
        start_date: q('aStart').value || null,
        target_date: q('aTarget').value || null,
        description: q('aDesc').value.trim() || null,
    };
    if (!payload.title) { alert('El titulo es obligatorio.'); return; }

    const url = id ? `/api/activities/${id}` : '/api/activities';
    const method = id ? 'PUT' : 'POST';
    await jget(url, { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
    closeModal();
    await loadActivities();
}

async function cancelActivity(id) {
    if (!confirm('Cancelar esta actividad?')) return;
    await jget(`/api/activities/${id}`, { method: 'DELETE' });
    await loadActivities();
}

// ── Boot ──────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', async () => {
    await loadEquipments();
    await loadActivities();
});
