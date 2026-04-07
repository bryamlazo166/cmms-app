let chartBreakdown = null;
let chartTrend = null;
let chartCauses = null;
let chartWeeklyLoad = null;
let chartWeeklySpecialty = null;

const state = { areas: [], lines: [], equipments: [] };

function num(v, d = 0) {
    return Number(v || 0).toLocaleString("es-PE", {
        minimumFractionDigits: d,
        maximumFractionDigits: d
    });
}

function qs(params) {
    const p = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => {
        if (v !== null && v !== undefined && String(v).trim() !== "") p.set(k, v);
    });
    return p.toString();
}

async function getJson(url) {
    const r = await fetch(url);
    const data = await r.json();
    if (!r.ok || data.error) throw new Error(data.error || `HTTP ${r.status}`);
    return data;
}

function setText(id, value) {
    const el = document.getElementById(id);
    if (el) el.textContent = value;
}

function fillAreas() {
    const sel = document.getElementById("filterArea");
    sel.innerHTML = '<option value="">Todas las areas</option>' + state.areas
        .sort((a, b) => (a.name || "").localeCompare(b.name || ""))
        .map(a => `<option value="${a.id}">${a.name}</option>`).join("");
}

function fillLines() {
    const areaId = Number(document.getElementById("filterArea").value || 0);
    const sel = document.getElementById("filterLine");
    sel.innerHTML = '<option value="">Todas las lineas</option>' + state.lines
        .filter(l => !areaId || Number(l.area_id) === areaId)
        .sort((a, b) => (a.name || "").localeCompare(b.name || ""))
        .map(l => `<option value="${l.id}">${l.name}</option>`).join("");
}

function fillEquipments() {
    const areaId = Number(document.getElementById("filterArea").value || 0);
    const lineId = Number(document.getElementById("filterLine").value || 0);
    const areaLineSet = new Set(state.lines.filter(l => !areaId || Number(l.area_id) === areaId).map(l => Number(l.id)));
    const sel = document.getElementById("filterEquipment");
    sel.innerHTML = '<option value="">Todos los equipos</option>' + state.equipments
        .filter(e => {
            const lid = Number(e.line_id || 0);
            if (lineId) return lid === lineId;
            if (areaId) return areaLineSet.has(lid);
            return true;
        })
        .sort((a, b) => (a.name || "").localeCompare(b.name || ""))
        .map(e => `<option value="${e.id}">${e.tag ? `${e.tag} - ` : ""}${e.name}</option>`).join("");
}

function currentExecutiveFilters() {
    return {
        start_date: document.getElementById("startDate").value,
        end_date: document.getElementById("endDate").value,
        area_id: document.getElementById("filterArea").value || null,
        line_id: document.getElementById("filterLine").value || null,
        equipment_id: document.getElementById("filterEquipment").value || null
    };
}

function currentWeeklyFilters() {
    // Construir param scope como lista separada por comas
    const scopes = [];
    if (document.getElementById("scopePlan")?.checked)      scopes.push("PLAN");
    if (document.getElementById("scopeFueraPlan")?.checked) scopes.push("FUERA_PLAN");
    if (document.getElementById("scopeGeneral")?.checked)   scopes.push("GENERAL");

    return {
        window: document.getElementById("weeklyWindow").value || "current_week",
        start_date: document.getElementById("weeklyStartDate").value || null,
        end_date: document.getElementById("weeklyEndDate").value || null,
        specialty: document.getElementById("weeklySpecialty").value || null,
        maintenance_type: document.getElementById("weeklyType").value || null,
        status: document.getElementById("weeklyStatus").value || null,
        area_id: document.getElementById("filterArea").value || null,
        line_id: document.getElementById("filterLine").value || null,
        equipment_id: document.getElementById("filterEquipment").value || null,
        scope: scopes.length ? scopes.join(",") : "PLAN",
    };
}

function toInputDate(dateObj) {
    const y = dateObj.getFullYear();
    const m = String(dateObj.getMonth() + 1).padStart(2, "0");
    const d = String(dateObj.getDate()).padStart(2, "0");
    return `${y}-${m}-${d}`;
}

function computeWeekWindow(windowKey) {
    const now = new Date();
    const jsDay = now.getDay();
    const mondayOffset = jsDay === 0 ? -6 : 1 - jsDay;
    const monday = new Date(now);
    monday.setDate(now.getDate() + mondayOffset);
    monday.setHours(0, 0, 0, 0);

    let start = new Date(monday);
    let end = new Date(monday);

    if (windowKey === "next_week") {
        start.setDate(start.getDate() + 7);
        end = new Date(start);
        end.setDate(end.getDate() + 6);
    } else if (windowKey === "weekend") {
        start.setDate(start.getDate() + 5);
        end = new Date(start);
        end.setDate(end.getDate() + 1);
        if (now > end) {
            start.setDate(start.getDate() + 7);
            end.setDate(end.getDate() + 7);
        }
    } else {
        end.setDate(end.getDate() + 6);
    }

    return { start: toInputDate(start), end: toInputDate(end) };
}

function setWeeklyWindowDates(windowKey) {
    if (windowKey === "custom") return;
    const range = computeWeekWindow(windowKey);
    document.getElementById("weeklyStartDate").value = range.start;
    document.getElementById("weeklyEndDate").value = range.end;
}

function renderSummary(s, m) {
    setText("reportPeriod", `${m.start_date} a ${m.end_date} | ${m.window_days} dias`);
    setText("kpiCompliance", `${num(s.compliance_percent, 1)}%`);
    setText("kpiPreventive", num(s.preventive_count));
    setText("kpiCorrective", num(s.corrective_count));
    setText("kpiAvailability", `${num(s.availability, 2)}%`);
    setText("kpiDowntime", `${num(s.downtime_hours, 1)} h`);
    setText("kpiCost", `S/ ${num(s.cost, 2)}`);
    setText("kpiMtbf", `${num(s.mtbf, 1)} h`);
    setText("kpiMttr", `${num(s.mttr, 1)} h`);
}

function renderBreakdown(rows, key) {
    const tbody = document.getElementById("tableBreakdownBody");
    const titleMap = { areas: "Area", lines: "Linea", equipments: "Equipo" };
    setText("breakdownTitle", `Desglose por ${titleMap[key] || "Nivel"}`);
    if (!rows || rows.length === 0) {
        tbody.innerHTML = '<tr><td colspan="11" class="muted-cell">Sin datos para el filtro actual.</td></tr>';
        return;
    }
    tbody.innerHTML = rows.map(r => `
        <tr>
            <td>${r.name || "-"}</td>
            <td>${num(r.planned_total)}</td>
            <td>${num(r.planned_closed)}</td>
            <td><span class="pill pill-cyan">${num(r.compliance_percent, 1)}%</span></td>
            <td>${num(r.preventive_count)}</td>
            <td>${num(r.corrective_count)}</td>
            <td><span class="pill ${r.availability >= 95 ? "pill-green" : r.availability >= 90 ? "pill-yellow" : "pill-red"}">${num(r.availability, 2)}%</span></td>
            <td>${num(r.downtime_hours, 1)}</td>
            <td>${num(r.mtbf, 1)}</td>
            <td>${num(r.mttr, 1)}</td>
            <td>S/ ${num(r.cost, 2)}</td>
        </tr>`).join("");
}

function drawBreakdown(rows, key) {
    if (chartBreakdown) chartBreakdown.destroy();
    const ctx = document.getElementById("chartBreakdown").getContext("2d");
    const top = (rows || []).slice(0, 12);
    chartBreakdown = new Chart(ctx, {
        type: "bar",
        data: {
            labels: top.map(r => r.name),
            datasets: [
                { label: "Preventivo", data: top.map(r => Number(r.preventive_count || 0)), backgroundColor: "rgba(76,175,80,.8)" },
                { label: "Correctivo", data: top.map(r => Number(r.corrective_count || 0)), backgroundColor: "rgba(244,67,54,.82)" }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { title: { display: true, text: `Preventivo vs Correctivo (${key})`, color: "#d8ebff" } }
        }
    });
}

function drawTrend(rows) {
    if (chartTrend) chartTrend.destroy();
    const ctx = document.getElementById("chartTrend").getContext("2d");
    chartTrend = new Chart(ctx, {
        type: "line",
        data: {
            labels: (rows || []).map(r => r.period),
            datasets: [
                { label: "Cumplimiento %", data: (rows || []).map(r => Number(r.compliance_percent || 0)), borderColor: "#0A84FF", tension: 0.2 },
                { label: "Disponibilidad %", data: (rows || []).map(r => Number(r.availability || 0)), borderColor: "#64b5f6", tension: 0.2 }
            ]
        },
        options: { responsive: true, maintainAspectRatio: false }
    });
}

function drawCauses(rows) {
    if (chartCauses) chartCauses.destroy();
    const ctx = document.getElementById("chartCauses").getContext("2d");
    const top = (rows || []).slice(0, 10);
    chartCauses = new Chart(ctx, {
        type: "bar",
        data: {
            labels: top.map(r => r.cause || "Sin clasificar"),
            datasets: [{ label: "Horas de paro", data: top.map(r => Number(r.downtime_hours || 0)), backgroundColor: "rgba(255,152,0,.85)" }]
        },
        options: { indexAxis: "y", responsive: true, maintainAspectRatio: false }
    });
}

function renderEvents(rows) {
    const tbody = document.getElementById("tableDowntimeBody");
    if (!rows || rows.length === 0) {
        tbody.innerHTML = '<tr><td colspan="10" class="muted-cell">Sin eventos de indisponibilidad.</td></tr>';
        return;
    }
    tbody.innerHTML = rows.map(e => `
        <tr>
            <td>${e.ot_code || "-"}</td><td>${e.date || "-"}</td><td>${e.area || "-"}</td><td>${e.line || "-"}</td><td>${e.equipment || "-"}</td>
            <td>${e.failure_mode || "-"}</td><td>${e.root_cause || "-"}</td><td>${num(e.duration_hours, 2)}</td><td>S/ ${num(e.cost, 2)}</td><td>${e.description || "-"}</td>
        </tr>`).join("");
}

async function loadExecutive() {
    try {
        const data = await getJson(`/api/reports/executive?${qs(currentExecutiveFilters())}`);
        const key = document.getElementById("groupBySelect").value || "areas";
        const rows = (data.breakdown && data.breakdown[key]) ? data.breakdown[key] : [];
        renderSummary(data.summary || {}, data.meta || {});
        renderBreakdown(rows, key);
        drawBreakdown(rows, key);
        drawTrend(data.trend || []);
        drawCauses(data.downtime_causes || []);
        renderEvents(data.downtime_events || []);
    } catch (e) {
        alert(`Error cargando panel ejecutivo: ${e.message}`);
    }
}

function renderRadar(items) {
    const tbody = document.getElementById("tableRecurrentFailures");
    if (!items || items.length === 0) {
        tbody.innerHTML = '<tr><td colspan="8" class="muted-cell">Sin recurrencias en el periodo.</td></tr>';
        return;
    }
    tbody.innerHTML = items.map(i => `
        <tr>
            <td>${i.is_alert ? '<span class="pill pill-red">ALERTA</span>' : '<span class="pill pill-muted">OK</span>'}</td>
            <td>${i.asset_label || "-"}</td>
            <td>${i.failure_mode || "-"}</td>
            <td><strong>${num(i.count)}</strong></td>
            <td>${i.last_date || "-"}</td>
            <td>${(i.ot_codes || []).join(", ")}</td>
            <td>${i.latest_comment || "-"}</td>
            <td>${i.latest_root_cause || "-"}</td>
        </tr>`).join("");
}

async function loadRadar() {
    const params = qs({
        days: document.getElementById("rfDays").value || 60,
        threshold: document.getElementById("rfThreshold").value || 3,
        failure_mode: (document.getElementById("rfMode").value || "").trim(),
        only_alerts: "false"
    });
    try {
        const data = await getJson(`/api/reports/recurrent-failures?${params}`);
        setText("radarStats", `Grupos: ${num(data.total_groups)} | Alertas: ${num(data.alerts)}`);
        renderRadar(data.items || []);
    } catch (e) {
        document.getElementById("tableRecurrentFailures").innerHTML = `<tr><td colspan="8" class="muted-cell">Error: ${e.message}</td></tr>`;
    }
}

function renderWeeklySummary(summary, meta) {
    setText("weeklyPeriod", `${meta.start_date} a ${meta.end_date} | ${meta.days} dias`);
    setText("wkTotal", num(summary.total));
    setText("wkPreventive", num(summary.preventive));
    setText("wkCorrective", num(summary.corrective));
    setText("wkClosed", num(summary.closed));
    setText("wkNoEjecutada", num(summary.no_ejecutada || 0));
    setText("wkBlocked", num(summary.blocked));
    setText("wkCompliance", `${num(summary.completion_percent, 1)}%`);
}

function printWeeklyPlan() {
    const period = document.getElementById("weeklyPeriod").textContent || '-';
    const kpis = [
        ['Total OTs',       document.getElementById('wkTotal').textContent],
        ['Preventivas',     document.getElementById('wkPreventive').textContent],
        ['Correctivas',     document.getElementById('wkCorrective').textContent],
        ['Ejecutadas',      document.getElementById('wkClosed').textContent],
        ['No Ejecutadas',   document.getElementById('wkNoEjecutada').textContent],
        ['Cumplimiento',    document.getElementById('wkCompliance').textContent],
    ];

    function scopeLabel(scope) {
        if (scope === 'FUERA_PLAN') return 'Fuera Plan';
        if (scope === 'GENERAL')    return 'General';
        return 'Plan';
    }
    function statusLabel(status) { return status || '-'; }

    const tableRows = (_lastWeeklyItems || []).map((i, idx) => {
        const bg = idx % 2 === 1 ? 'background:#f7f9ff;' : '';
        const statusStyle =
            i.status === 'Cerrada'       ? 'background:#d4f4d4;color:#1a7a1a;'  :
            i.status === 'En Progreso'   ? 'background:#d4f0ff;color:#0a5a80;'  :
            i.status === 'Programada'    ? 'background:#fff6d4;color:#7a5a00;'  :
            i.status === 'No Ejecutada'  ? 'background:#ffd4d4;color:#7a0000;'  :
                                           'background:#eee;color:#555;';
        const scopeStyle =
            i.scope === 'FUERA_PLAN' ? 'background:#FF9F0A22;color:#b36a00;border:1px solid #FF9F0A55;' :
            i.scope === 'GENERAL'    ? 'background:#BF5AF222;color:#6a0dab;border:1px solid #BF5AF255;' :
                                       'background:#d4f0ff;color:#0a5a80;';
        return `<tr>
            <td style="${bg}font-weight:bold;color:#1a3a6b;">${i.code || '-'}</td>
            <td style="${bg}">${i.notice_code || '-'}</td>
            <td style="${bg}">${i.scheduled_date || '-'}</td>
            <td style="${bg}font-weight:600;">${i.technician || '-'}</td>
            <td style="${bg}">${i.specialty || '-'}</td>
            <td style="${bg}">${i.maintenance_type || '-'}</td>
            <td style="${bg}"><span style="display:inline-block;padding:1px 7px;border-radius:8px;font-weight:bold;font-size:10px;${statusStyle}">${statusLabel(i.status)}</span></td>
            <td style="${bg}">${i.area || '-'}</td>
            <td style="${bg}">${i.line || '-'}</td>
            <td style="${bg}">${i.equipment_tag || '-'}</td>
            <td style="${bg}">${i.equipment || '-'}</td>
            <td style="${bg}">${i.priority || '-'}</td>
            <td style="${bg}"><span style="display:inline-block;padding:1px 7px;border-radius:8px;font-size:10px;${scopeStyle}">${scopeLabel(i.scope)}</span></td>
            <td style="${bg};color:#444;font-size:10px;">${i.description || '-'}</td>
        </tr>`;
    }).join('');

    const html = `<!DOCTYPE html>
<html lang="es"><head><meta charset="UTF-8">
<title>Plan Semanal de Mantenimiento</title>
<style>
    body { font-family: Arial, sans-serif; margin: 20px; color: #111; font-size: 11px; }
    h1 { color: #1a3a6b; border-bottom: 2px solid #1a3a6b; padding-bottom: 6px; font-size: 17px; margin-bottom: 4px; }
    .period { color: #555; margin-bottom: 14px; font-size: 11px; }
    .kpi-grid { display: grid; grid-template-columns: repeat(6, 1fr); gap: 8px; margin-bottom: 16px; }
    .kpi-box { background: #f0f4ff; border: 1px solid #c0cfee; border-radius: 6px; padding: 8px; text-align: center; }
    .kpi-label { font-size: 9px; color: #555; text-transform: uppercase; letter-spacing: .3px; }
    .kpi-value { font-size: 20px; font-weight: bold; color: #1a3a6b; margin-top: 3px; }
    table { width: 100%; border-collapse: collapse; font-size: 10px; table-layout: auto; }
    th { background: #1a3a6b; color: white; padding: 5px 4px; text-align: left; white-space: nowrap; }
    td { padding: 4px 4px; border-bottom: 1px solid #dde; vertical-align: middle; }
    .footer { margin-top: 16px; color: #888; font-size: 9px; }
    @media print {
        body { margin: 8px; }
        @page { size: A4 landscape; margin: 12mm; }
    }
</style></head><body>
<h1>Plan Semanal de Mantenimiento</h1>
<div class="period">${period}</div>
<div class="kpi-grid">
    ${kpis.map(([l, v]) => `<div class="kpi-box"><div class="kpi-label">${l}</div><div class="kpi-value">${v}</div></div>`).join('')}
</div>
<table>
<thead><tr>
    <th>OT</th><th>Aviso</th><th>Fecha</th><th>Técnico</th><th>Especialidad</th>
    <th>Tipo</th><th>Estado</th><th>Área</th><th>Línea</th>
    <th>TAG</th><th>Equipo</th><th>Prioridad</th><th>Alcance</th><th>Descripción</th>
</tr></thead>
<tbody>${tableRows}</tbody>
</table>
<p class="footer">Generado desde CMMS Industrial — ${new Date().toLocaleString('es-PE')}</p>
</body></html>`;

    const win = window.open('', '_blank');
    win.document.write(html);
    win.document.close();
    win.focus();
    setTimeout(() => win.print(), 600);
}

function drawWeeklyLoad(dailyRows) {
    if (chartWeeklyLoad) chartWeeklyLoad.destroy();
    const ctx = document.getElementById("chartWeeklyLoad").getContext("2d");
    const labels = (dailyRows || []).map(d => d.date);
    const preventive = (dailyRows || []).map(d => Number(d.preventive || 0));
    const corrective = (dailyRows || []).map(d => Number(d.corrective || 0));
    const blocked = (dailyRows || []).map(d => Number(d.blocked || 0));

    chartWeeklyLoad = new Chart(ctx, {
        type: "bar",
        data: {
            labels,
            datasets: [
                { label: "Preventivo", data: preventive, backgroundColor: "rgba(76,175,80,.82)" },
                { label: "Correctivo", data: corrective, backgroundColor: "rgba(244,67,54,.82)" },
                { label: "Bloqueadas", data: blocked, backgroundColor: "rgba(255,152,0,.82)" }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: { y: { beginAtZero: true, ticks: { precision: 0 } } }
        }
    });
}

function drawWeeklySpecialty(summary) {
    if (chartWeeklySpecialty) chartWeeklySpecialty.destroy();
    const ctx = document.getElementById("chartWeeklySpecialty").getContext("2d");
    const counts = (summary && summary.specialty_counts) ? summary.specialty_counts : {};
    const labels = Object.keys(counts);
    const values = labels.map(k => Number(counts[k] || 0));

    if (labels.length === 0) {
        labels.push("Sin datos");
        values.push(1);
    }

    chartWeeklySpecialty = new Chart(ctx, {
        type: "doughnut",
        data: {
            labels,
            datasets: [{
                data: values,
                backgroundColor: ["#26a69a", "#42a5f5", "#ab47bc", "#ffa726", "#90a4ae", "#ef5350"]
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { position: "bottom" } }
        }
    });
}

function scopeBadgeReport(scope) {
    if (scope === 'FUERA_PLAN') return '<span class="pill" style="background:#FF9F0A22;color:#FF9F0A;border:1px solid #FF9F0A55">🚧 F.Plan</span>';
    if (scope === 'GENERAL')    return '<span class="pill" style="background:#BF5AF222;color:#BF5AF2;border:1px solid #BF5AF255">🛠️ General</span>';
    return '<span class="pill pill-cyan">🏭 Plan</span>';
}

function renderWeeklyTable(items) {
    const tbody = document.getElementById("tableWeeklyBody");
    if (!items || items.length === 0) {
        tbody.innerHTML = '<tr><td colspan="16" class="muted-cell">Sin actividades para el filtro seleccionado.</td></tr>';
        return;
    }

    tbody.innerHTML = items.map(i => {
        const logisticsClass = i.req_pending > 0 ? "pill-red" : (i.req_total > 0 ? "pill-green" : "pill-muted");
        const reqInfo = i.req_codes && i.req_codes.length ? i.req_codes.slice(0, 3).join(", ") : "-";
        const poInfo = i.po_codes && i.po_codes.length ? i.po_codes.slice(0, 3).join(", ") : "-";
        const statusClass =
            i.status === 'Cerrada'      ? 'pill-green' :
            i.status === 'En Progreso'  ? 'pill-cyan'  :
            i.status === 'Programada'   ? 'pill-yellow':
            i.status === 'No Ejecutada' ? 'pill-red'   : 'pill-muted';
        return `
        <tr>
            <td><a class="weekly-ot-link" href="/ordenes">${i.code || "-"}</a></td>
            <td>${i.notice_code || "-"}</td>
            <td>${i.scheduled_date || "-"}</td>
            <td>${scopeBadgeReport(i.scope)}</td>
            <td style="font-weight:600;">${i.technician || "-"}</td>
            <td>${i.specialty || "-"}</td>
            <td>${i.maintenance_type || "-"}</td>
            <td><span class="pill ${statusClass}">${i.status || "-"}</span></td>
            <td>${i.area || "-"}</td>
            <td>${i.line || "-"}</td>
            <td>${i.equipment_tag || "-"}</td>
            <td>${i.equipment || "-"}</td>
            <td>${i.priority || "-"}</td>
            <td><span class="pill ${logisticsClass}">${i.logistics || "-"}</span></td>
            <td>${reqInfo}</td>
            <td>${poInfo}</td>
        </tr>`;
    }).join("");
}

let _lastWeeklyItems = [];

async function loadWeeklyPlan() {
    try {
        const data = await getJson(`/api/reports/weekly-plan?${qs(currentWeeklyFilters())}`);
        _lastWeeklyItems = data.items || [];
        renderWeeklySummary(data.summary || {}, data.meta || {});
        drawWeeklyLoad(data.daily || []);
        drawWeeklySpecialty(data.summary || {});
        renderWeeklyTable(_lastWeeklyItems);
    } catch (e) {
        alert(`Error cargando plan semanal: ${e.message}`);
    }
}

function exportWeeklyPlan() {
    const url = `/api/reports/weekly-plan/export?${qs(currentWeeklyFilters())}`;
    window.open(url, "_blank");
}

async function initReports() {
    const end = new Date();
    const start = new Date();
    start.setDate(start.getDate() - 30);
    document.getElementById("startDate").valueAsDate = start;
    document.getElementById("endDate").valueAsDate = end;

    document.getElementById("weeklyWindow").value = "current_week";
    setWeeklyWindowDates("current_week");

    const [areas, lines, equipments] = await Promise.all([
        getJson("/api/areas"),
        getJson("/api/lines"),
        getJson("/api/equipments")
    ]);

    state.areas = areas || [];
    state.lines = lines || [];
    state.equipments = equipments || [];
    fillAreas();
    fillLines();
    fillEquipments();

    const syncHierarchyAndReload = () => {
        fillLines();
        document.getElementById("filterLine").value = "";
        fillEquipments();
        document.getElementById("filterEquipment").value = "";
        loadExecutive();
        loadWeeklyPlan();
    };

    document.getElementById("filterArea").addEventListener("change", syncHierarchyAndReload);
    document.getElementById("filterLine").addEventListener("change", () => {
        fillEquipments();
        document.getElementById("filterEquipment").value = "";
        loadExecutive();
        loadWeeklyPlan();
    });
    document.getElementById("filterEquipment").addEventListener("change", () => {
        loadExecutive();
        loadWeeklyPlan();
    });

    document.getElementById("groupBySelect").addEventListener("change", loadExecutive);
    document.getElementById("startDate").addEventListener("change", loadExecutive);
    document.getElementById("endDate").addEventListener("change", loadExecutive);
    document.getElementById("btnRefresh").addEventListener("click", loadExecutive);
    document.getElementById("btnClear").addEventListener("click", () => {
        document.getElementById("filterArea").value = "";
        fillLines();
        document.getElementById("filterLine").value = "";
        fillEquipments();
        document.getElementById("filterEquipment").value = "";
        document.getElementById("groupBySelect").value = "areas";
        loadExecutive();
        loadWeeklyPlan();
    });

    document.getElementById("btnRefreshRadar").addEventListener("click", loadRadar);

    document.getElementById("weeklyWindow").addEventListener("change", (e) => {
        setWeeklyWindowDates(e.target.value);
        loadWeeklyPlan();
    });
    document.getElementById("weeklyStartDate").addEventListener("change", () => {
        document.getElementById("weeklyWindow").value = "custom";
        loadWeeklyPlan();
    });
    document.getElementById("weeklyEndDate").addEventListener("change", () => {
        document.getElementById("weeklyWindow").value = "custom";
        loadWeeklyPlan();
    });
    document.getElementById("weeklySpecialty").addEventListener("change", loadWeeklyPlan);
    document.getElementById("weeklyType").addEventListener("change", loadWeeklyPlan);
    document.getElementById("weeklyStatus").addEventListener("change", loadWeeklyPlan);
    document.getElementById("btnWeeklyRefresh").addEventListener("click", loadWeeklyPlan);
    document.getElementById("btnWeeklyExport").addEventListener("click", exportWeeklyPlan);
    document.getElementById("btnWeeklyPrint").addEventListener("click", printWeeklyPlan);
    document.getElementById("btnWeeklyClear").addEventListener("click", () => {
        document.getElementById("weeklyWindow").value = "current_week";
        setWeeklyWindowDates("current_week");
        document.getElementById("weeklySpecialty").value = "";
        document.getElementById("weeklyType").value = "";
        document.getElementById("weeklyStatus").value = "";
        // Resetear scope al default (solo Plan)
        document.getElementById("scopePlan").checked = true;
        document.getElementById("scopeFueraPlan").checked = false;
        document.getElementById("scopeGeneral").checked = false;
        loadWeeklyPlan();
    });

    await loadExecutive();
    await loadRadar();
    await loadWeeklyPlan();
}

document.addEventListener("DOMContentLoaded", () => {
    initReports().catch((e) => alert(`No se pudo inicializar reportes: ${e.message}`));
});
