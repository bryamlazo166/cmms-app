let chartBreakdown = null;
let chartTrend = null;
let chartCauses = null;

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

function currentFilters() {
    return {
        start_date: document.getElementById("startDate").value,
        end_date: document.getElementById("endDate").value,
        area_id: document.getElementById("filterArea").value || null,
        line_id: document.getElementById("filterLine").value || null,
        equipment_id: document.getElementById("filterEquipment").value || null
    };
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
        options: { responsive: true, maintainAspectRatio: false, plugins: { title: { display: true, text: `Preventivo vs Correctivo (${key})`, color: "#d8ebff" } } }
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
                { label: "Cumplimiento %", data: (rows || []).map(r => Number(r.compliance_percent || 0)), borderColor: "#03dac6", tension: 0.2 },
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
        data: { labels: top.map(r => r.cause || "Sin clasificar"), datasets: [{ label: "Horas de paro", data: top.map(r => Number(r.downtime_hours || 0)), backgroundColor: "rgba(255,152,0,.85)" }] },
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
        const data = await getJson(`/api/reports/executive?${qs(currentFilters())}`);
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

async function initReports() {
    const end = new Date();
    const start = new Date();
    start.setDate(start.getDate() - 30);
    document.getElementById("startDate").valueAsDate = start;
    document.getElementById("endDate").valueAsDate = end;

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

    document.getElementById("filterArea").addEventListener("change", () => { fillLines(); document.getElementById("filterLine").value = ""; fillEquipments(); document.getElementById("filterEquipment").value = ""; loadExecutive(); });
    document.getElementById("filterLine").addEventListener("change", () => { fillEquipments(); document.getElementById("filterEquipment").value = ""; loadExecutive(); });
    document.getElementById("filterEquipment").addEventListener("change", loadExecutive);
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
    });
    document.getElementById("btnRefreshRadar").addEventListener("click", loadRadar);

    await loadExecutive();
    await loadRadar();
}

document.addEventListener("DOMContentLoaded", () => {
    initReports().catch((e) => alert(`No se pudo inicializar reportes: ${e.message}`));
});
