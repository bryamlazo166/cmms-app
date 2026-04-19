// Módulo Producción vs Mantenimiento — Dashboard gerencial
// Muestra comparativas entre disponibilidad actual vs requerida, TM y sacos perdidos,
// proyección de cumplimiento y diagnóstico IA.

let charts = {};
let currentMetrics = null;
let cachedAreas = [];

// ── Inicialización ──────────────────────────────────────────────────────
function currentPeriod() {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
}

document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('periodSelect').value = currentPeriod();
    // Cargar áreas una vez para el selector del modal
    fetch('/api/areas').then(r => r.json()).then(data => {
        cachedAreas = data || [];
    }).catch(() => {});
    loadProduction();
});

function getSelectedPeriod() {
    return document.getElementById('periodSelect').value || currentPeriod();
}

// ── Carga principal ─────────────────────────────────────────────────────
async function loadProduction() {
    const period = getSelectedPeriod();
    try {
        const [metrics, trend] = await Promise.all([
            fetch(`/api/production/metrics?period=${period}`).then(r => r.json()),
            fetch(`/api/production/trend?months=6`).then(r => r.json()),
        ]);
        currentMetrics = metrics;
        renderKpis(metrics);
        renderBanner(metrics);
        renderGauge(metrics);
        renderAreasBar(metrics);
        renderTrend(trend);
        renderTopEquips(metrics);
        renderProjection(metrics);
        renderAreaTable(metrics);
    } catch (e) {
        console.error('loadProduction error', e);
        alert('Error cargando métricas: ' + e.message);
    }
}

// ── KPI Cards ───────────────────────────────────────────────────────────
function renderKpis(m) {
    const t = m.totals || {};
    document.getElementById('kpiActual').innerHTML = `${t.avg_availability || 0}<span class="unit">%</span>`;
    document.getElementById('kpiRequired').innerHTML = `${t.avg_required_availability || 0}<span class="unit">%</span>`;
    document.getElementById('kpiTons').innerHTML = `${Math.round(t.total_tons_lost || 0).toLocaleString()}<span class="unit">TM</span>`;
    document.getElementById('kpiSacks').innerHTML = `${(t.total_sacks_lost || 0).toLocaleString()}<span class="unit">sacos</span>`;

    const gap = t.global_gap_pp || 0;
    const gapEl = document.getElementById('kpiGap');
    gapEl.innerHTML = `${gap >= 0 ? '+' : ''}${gap}<span class="unit">pp</span>`;
    gapEl.classList.toggle('pos', gap >= 0);
    gapEl.classList.toggle('neg', gap < 0);
    document.getElementById('kpiGapSub').textContent = gap >= 0
        ? 'Por encima de meta ✓'
        : 'Bajo meta requerida ⚠';
}

function renderBanner(m) {
    const t = m.totals || {};
    const banner = document.getElementById('riskBanner');
    const txt = document.getElementById('riskBannerText');
    if (t.areas_count === 0) {
        banner.style.display = 'flex';
        banner.className = 'risk-banner ok';
        txt.innerHTML = `<i class="fas fa-info-circle"></i> No hay metas cargadas para ${m.period}. Usa "Capturar meta" para activar el análisis.`;
        return;
    }
    banner.style.display = 'flex';
    if (t.global_at_risk) {
        banner.className = 'risk-banner risk';
        txt.innerHTML = `<i class="fas fa-exclamation-triangle"></i> <strong>META EN RIESGO:</strong> Disponibilidad actual ${t.avg_availability}% está ${Math.abs(t.global_gap_pp)}pp bajo la requerida (${t.avg_required_availability}%). Pérdida acumulada: ${t.total_tons_lost} TM / ${t.total_sacks_lost.toLocaleString()} sacos.`;
    } else {
        banner.className = 'risk-banner ok';
        txt.innerHTML = `<i class="fas fa-check-circle"></i> <strong>META EN RUMBO:</strong> Disponibilidad ${t.avg_availability}% supera la requerida ${t.avg_required_availability}% por ${t.global_gap_pp}pp.`;
    }
}

// ── Chart 1: Gauge dual Actual vs Requerida ─────────────────────────────
function renderGauge(m) {
    if (!charts.gauge) charts.gauge = echarts.init(document.getElementById('chartGauge'));
    const t = m.totals || {};
    const actual = t.avg_availability || 0;
    const required = t.avg_required_availability || 0;

    charts.gauge.setOption({
        series: [
            {
                type: 'gauge',
                center: ['50%', '60%'],
                radius: '90%',
                min: 0, max: 100,
                splitNumber: 10,
                startAngle: 200, endAngle: -20,
                axisLine: {
                    lineStyle: {
                        width: 22,
                        color: [
                            [0.6, '#FF453A'],
                            [0.85, '#FF9F0A'],
                            [1, '#30D158'],
                        ],
                    },
                },
                pointer: { icon: 'triangle', length: '55%', width: 10, itemStyle: { color: '#30D158' } },
                axisTick: { distance: -25, length: 6, lineStyle: { color: '#fff' } },
                splitLine: { distance: -28, length: 12, lineStyle: { color: '#fff' } },
                axisLabel: { color: '#9ab0cb', distance: -45, fontSize: 10 },
                detail: {
                    valueAnimation: true,
                    formatter: `{value}%\n{a|ACTUAL}`,
                    rich: { a: { fontSize: 11, color: '#30D158', fontWeight: 700 } },
                    offsetCenter: [0, '35%'],
                    fontSize: 22, color: '#fff', fontWeight: 700,
                },
                data: [{ value: actual }],
            },
            {
                type: 'gauge',
                center: ['50%', '60%'],
                radius: '90%',
                min: 0, max: 100,
                startAngle: 200, endAngle: -20,
                axisLine: { show: false },
                axisTick: { show: false },
                splitLine: { show: false },
                axisLabel: { show: false },
                pointer: { icon: 'triangle', length: '45%', width: 7, itemStyle: { color: '#FF9F0A' } },
                detail: {
                    valueAnimation: true,
                    formatter: `Req: {value}%`,
                    offsetCenter: [0, '60%'],
                    fontSize: 12, color: '#FF9F0A', fontWeight: 600,
                },
                data: [{ value: required }],
            },
        ],
    });
}

// ── Chart 2: Barras Meta vs Teórica vs Pérdida por área ─────────────────
function renderAreasBar(m) {
    if (!charts.areas) charts.areas = echarts.init(document.getElementById('chartAreas'));
    const areas = m.areas || [];
    const names = areas.map(a => a.area_name);
    const metas = areas.map(a => a.monthly_target_tons);
    const producido = areas.map(a => a.tons_produced_theoretical);
    const perdido = areas.map(a => a.tons_lost);

    charts.areas.setOption({
        tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
        legend: { data: ['Meta', 'Producido (teórico)', 'Perdido'], textStyle: { color: '#d5e2f5' }, top: 0 },
        grid: { left: 50, right: 20, bottom: 40, top: 30 },
        xAxis: { type: 'category', data: names, axisLabel: { color: '#9ab0cb', rotate: 20 } },
        yAxis: { type: 'value', name: 'TM', axisLabel: { color: '#9ab0cb' }, splitLine: { lineStyle: { color: '#2a3a50' } } },
        series: [
            { name: 'Meta', type: 'bar', data: metas, itemStyle: { color: '#0a84ff' }, barGap: '10%' },
            { name: 'Producido (teórico)', type: 'bar', data: producido, itemStyle: { color: '#30D158' } },
            { name: 'Perdido', type: 'bar', data: perdido, itemStyle: { color: '#FF453A' } },
        ],
    });
}

// ── Chart 3: Tendencia 6 meses Disponibilidad Actual vs Requerida ───────
function renderTrend(trendData) {
    if (!charts.trend) charts.trend = echarts.init(document.getElementById('chartTrend'));
    const series = trendData.series || [];
    const labels = series.map(s => s.period);
    const actuals = series.map(s => s.availability);
    const required = series.map(s => s.required);

    charts.trend.setOption({
        tooltip: { trigger: 'axis' },
        legend: { data: ['Disp. Actual', 'Disp. Requerida (c/FS)'], textStyle: { color: '#d5e2f5' }, top: 0 },
        grid: { left: 50, right: 20, bottom: 30, top: 30 },
        xAxis: { type: 'category', data: labels, axisLabel: { color: '#9ab0cb' } },
        yAxis: { type: 'value', name: '%', min: 50, max: 100, axisLabel: { color: '#9ab0cb' }, splitLine: { lineStyle: { color: '#2a3a50' } } },
        series: [
            {
                name: 'Disp. Actual',
                type: 'line',
                data: actuals,
                smooth: true,
                symbolSize: 8,
                lineStyle: { width: 3, color: '#30D158' },
                itemStyle: { color: '#30D158' },
                areaStyle: { color: 'rgba(48,209,88,.15)' },
            },
            {
                name: 'Disp. Requerida (c/FS)',
                type: 'line',
                data: required,
                smooth: true,
                symbolSize: 6,
                lineStyle: { width: 2, color: '#FF9F0A', type: 'dashed' },
                itemStyle: { color: '#FF9F0A' },
            },
        ],
    });
}

// ── Chart 4: Top 5 equipos con mayor impacto ────────────────────────────
function renderTopEquips(m) {
    if (!charts.topEquips) charts.topEquips = echarts.init(document.getElementById('chartTopEquips'));
    const items = (m.top_equipments || []).slice().reverse();
    const names = items.map(e => `${e.equipment_tag} (${e.area_name})`);
    const tons = items.map(e => e.tons_lost);
    const sacks = items.map(e => e.sacks_lost);

    if (items.length === 0) {
        charts.topEquips.setOption({
            graphic: { type: 'text', left: 'center', top: 'middle', style: { text: 'Sin datos de downtime en el periodo', fill: '#9ab0cb', fontSize: 14 } },
        });
        return;
    }

    charts.topEquips.setOption({
        tooltip: {
            trigger: 'axis',
            formatter: params => {
                const p = params[0];
                const i = items.length - 1 - p.dataIndex;
                const e = items[items.length - 1 - p.dataIndex];
                return `<b>${e.equipment_tag}</b> — ${e.equipment_name}<br/>
                        Área: ${e.area_name}<br/>
                        Fallas: ${e.failure_count}<br/>
                        Downtime: ${e.downtime_hours} h<br/>
                        <b style="color:#FF453A">${e.tons_lost} TM / ${e.sacks_lost.toLocaleString()} sacos</b>`;
            },
        },
        grid: { left: 140, right: 30, bottom: 30, top: 10 },
        xAxis: { type: 'value', axisLabel: { color: '#9ab0cb' }, splitLine: { lineStyle: { color: '#2a3a50' } } },
        yAxis: { type: 'category', data: names, axisLabel: { color: '#9ab0cb', fontSize: 11 } },
        series: [
            {
                name: 'TM perdidas',
                type: 'bar',
                data: tons,
                itemStyle: {
                    color: { type: 'linear', x: 0, y: 0, x2: 1, y2: 0, colorStops: [{ offset: 0, color: '#FF9F0A' }, { offset: 1, color: '#FF453A' }] },
                    borderRadius: [0, 6, 6, 0],
                },
                label: { show: true, position: 'right', color: '#fff', formatter: p => `${p.value} TM` },
            },
        ],
    });
}

// ── Chart 5: Proyección de cumplimiento por área ────────────────────────
function renderProjection(m) {
    if (!charts.projection) charts.projection = echarts.init(document.getElementById('chartProjection'));
    const areas = m.areas || [];
    const names = areas.map(a => a.area_name);
    const compliance = areas.map(a => a.compliance_pct);

    charts.projection.setOption({
        tooltip: {
            trigger: 'axis',
            formatter: params => {
                const a = areas[params[0].dataIndex];
                return `<b>${a.area_name}</b><br/>
                        Meta: ${a.monthly_target_tons} TM<br/>
                        Proyección: ${a.projected_tons_month} TM<br/>
                        Cumplimiento: <b>${a.compliance_pct}%</b>`;
            },
        },
        grid: { left: 50, right: 30, bottom: 40, top: 30 },
        xAxis: { type: 'category', data: names, axisLabel: { color: '#9ab0cb', rotate: 20 } },
        yAxis: {
            type: 'value',
            name: '% cumplimiento',
            min: 0, max: Math.max(110, ...compliance, 100),
            axisLabel: { color: '#9ab0cb' },
            splitLine: { lineStyle: { color: '#2a3a50' } },
        },
        series: [
            {
                type: 'bar',
                data: compliance.map(v => ({
                    value: v,
                    itemStyle: { color: v >= 100 ? '#30D158' : v >= 90 ? '#FF9F0A' : '#FF453A' },
                })),
                markLine: {
                    data: [{ yAxis: 100, name: 'Meta' }],
                    lineStyle: { color: '#5ac8fa', type: 'dashed', width: 2 },
                    label: { formatter: 'Meta 100%', color: '#5ac8fa' },
                },
                label: { show: true, position: 'top', color: '#fff', formatter: '{c}%' },
            },
        ],
    });
}

// ── Tabla detalle por área ──────────────────────────────────────────────
function renderAreaTable(m) {
    const tbody = document.querySelector('#areaDetailTable tbody');
    tbody.innerHTML = '';
    (m.areas || []).forEach(a => {
        const riskClr = a.at_risk ? '#FF453A' : '#30D158';
        const row = document.createElement('tr');
        row.innerHTML = `
            <td><b>${a.area_name}</b></td>
            <td style="color:${riskClr}"><b>${a.availability_actual}%</b></td>
            <td>${a.required_with_sf}%</td>
            <td>${a.safety_factor}</td>
            <td>${a.tons_lost}</td>
            <td>${a.sacks_lost.toLocaleString()}</td>
            <td style="color:${a.compliance_pct >= 100 ? '#30D158' : a.compliance_pct >= 90 ? '#FF9F0A' : '#FF453A'}">${a.compliance_pct}%</td>
        `;
        tbody.appendChild(row);
    });
    if ((m.areas || []).length === 0) {
        tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;color:#9ab0cb;padding:20px;">Sin metas cargadas para este periodo</td></tr>';
    }
}

// ── Diagnóstico IA ──────────────────────────────────────────────────────
async function loadAiDiagnosis() {
    const body = document.getElementById('aiDiagnosisBody');
    const src = document.getElementById('aiSource');
    body.textContent = '⏳ Generando diagnóstico ejecutivo con DeepSeek...';
    src.textContent = '';
    try {
        const r = await fetch('/api/production/ai-diagnosis', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ period: getSelectedPeriod() }),
        });
        const j = await r.json();
        body.textContent = j.diagnosis || 'Sin diagnóstico disponible.';
        src.textContent = j.source === 'deepseek'
            ? '🤖 Generado por DeepSeek AI'
            : (j.source === 'rule-based' ? '📋 Diagnóstico básico (configura DEEPSEEK_API_KEY para análisis IA)' : '⚠ Fallback');
    } catch (e) {
        body.textContent = 'Error al generar diagnóstico: ' + e.message;
    }
}

// ── Export Excel ────────────────────────────────────────────────────────
function exportExcel() {
    const period = getSelectedPeriod();
    window.location.href = `/api/production/export?period=${period}`;
}

// ── Modal captura meta ──────────────────────────────────────────────────
function openGoalModal() {
    document.getElementById('goalModal').classList.add('open');
    document.getElementById('goalPeriod').value = getSelectedPeriod();
    const sel = document.getElementById('goalAreaId');
    sel.innerHTML = '<option value="">-- Seleccionar área --</option>';
    cachedAreas.forEach(a => {
        sel.insertAdjacentHTML('beforeend', `<option value="${a.id}">${a.name}</option>`);
    });
    loadGoalsList();
}

function closeGoalModal() {
    document.getElementById('goalModal').classList.remove('open');
}

async function loadGoalsList() {
    const period = document.getElementById('goalPeriod').value;
    const tbody = document.querySelector('#goalsList tbody');
    tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;color:#9ab0cb;">Cargando...</td></tr>';
    try {
        const r = await fetch(`/api/production/goals${period ? '?period=' + period : ''}`);
        const goals = await r.json();
        tbody.innerHTML = '';
        if (!goals.length) {
            tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;color:#9ab0cb;">Sin metas registradas</td></tr>';
            return;
        }
        goals.forEach(g => {
            const row = document.createElement('tr');
            row.innerHTML = `
                <td>${g.goal_period}</td>
                <td>${g.area_name || '-'}</td>
                <td>${g.monthly_avg_yield_tons} TM</td>
                <td>${g.monthly_target_tons} TM</td>
                <td><button class="action-btn delete" onclick="deleteGoal(${g.id})"><i class="fas fa-trash"></i></button></td>
            `;
            tbody.appendChild(row);
        });
    } catch (e) {
        tbody.innerHTML = `<tr><td colspan="5" style="color:#FF453A;">Error: ${e.message}</td></tr>`;
    }
}

async function saveGoal() {
    const payload = {
        goal_period: document.getElementById('goalPeriod').value,
        area_id: document.getElementById('goalAreaId').value,
        monthly_avg_yield_tons: parseFloat(document.getElementById('goalYield').value || 0),
        monthly_target_tons: parseFloat(document.getElementById('goalTarget').value || 0),
        operating_hours_month: parseFloat(document.getElementById('goalHours').value || 720),
        notes: document.getElementById('goalNotes').value,
    };
    if (!payload.goal_period || !payload.area_id || !payload.monthly_avg_yield_tons || !payload.monthly_target_tons) {
        alert('Completa periodo, área, rendimiento y meta.');
        return;
    }
    try {
        const r = await fetch('/api/production/goals', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        const j = await r.json();
        if (r.ok) {
            document.getElementById('goalYield').value = '';
            document.getElementById('goalTarget').value = '';
            document.getElementById('goalNotes').value = '';
            loadGoalsList();
            loadProduction();
        } else {
            alert('Error: ' + (j.error || 'desconocido'));
        }
    } catch (e) {
        alert('Error de red: ' + e.message);
    }
}

async function deleteGoal(id) {
    if (!confirm('¿Eliminar esta meta?')) return;
    await fetch(`/api/production/goals/${id}`, { method: 'DELETE' });
    loadGoalsList();
    loadProduction();
}

// Responsive
window.addEventListener('resize', () => {
    Object.values(charts).forEach(c => c && c.resize());
});
