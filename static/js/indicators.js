// Indicadores para Directorio — Drill-down interactivo
let _indChart = null;
let _indLevel = 'areas';  // areas | equipments | failures
let _indAreaId = null;
let _indAreaName = '';
let _indEquipId = null;
let _indEquipName = '';

// Dia de inicio del corte semanal (0=lunes..6=domingo) — config global
let IND_WEEK_START = 0;

document.addEventListener('DOMContentLoaded', async () => {
    try {
        const s = await fetch('/api/settings').then(r => r.json());
        IND_WEEK_START = parseInt(s.week_start_day) || 0;
    } catch (_) { /* default lunes */ }
    loadIndicators();
    window.addEventListener('resize', () => {
        if (_indChart) _indChart.resize();
        if (_paretoChart) _paretoChart.resize();
    });
});

function onIndPeriodChange() {
    const p = document.getElementById('indPeriod').value;
    document.getElementById('indStart').style.display = p === 'custom' ? 'inline-block' : 'none';
    document.getElementById('indEnd').style.display = p === 'custom' ? 'inline-block' : 'none';
    if (p !== 'custom') loadIndicators();
}

function getIndDates() {
    const p = document.getElementById('indPeriod').value;
    const today = new Date();
    let s, e = new Date(today);
    if (p === 'week' || p === 'last_week') {
        // Semana con corte configurable (ej. viernes a jueves)
        const pyDay = (today.getDay() + 6) % 7;   // 0=lunes..6=domingo
        const offset = -((pyDay - IND_WEEK_START + 7) % 7);
        s = new Date(today);
        s.setDate(today.getDate() + offset);
        if (p === 'last_week') s.setDate(s.getDate() - 7);
        e = new Date(s);
        e.setDate(e.getDate() + 6);
        return { start: s.toISOString().slice(0, 10), end: e.toISOString().slice(0, 10) };
    }
    if (p === 'month') { s = new Date(today.getFullYear(), today.getMonth(), 1); }
    else if (p === 'last_month') { s = new Date(today.getFullYear(), today.getMonth() - 1, 1); e = new Date(today.getFullYear(), today.getMonth(), 0); }
    else if (p === 'quarter') { s = new Date(today); s.setDate(s.getDate() - 90); }
    else if (p === 'semester') { s = new Date(today); s.setDate(s.getDate() - 180); }
    else if (p === 'year') { s = new Date(today); s.setDate(s.getDate() - 365); }
    else { return { start: document.getElementById('indStart').value, end: document.getElementById('indEnd').value }; }
    return { start: s.toISOString().slice(0, 10), end: e.toISOString().slice(0, 10) };
}

function getIndMode() {
    const el = document.getElementById('indMode');
    return (el && el.value) || 'operativa';
}

function dateParams() {
    const { start, end } = getIndDates();
    return `start_date=${start}&end_date=${end}&mode=${getIndMode()}`;
}

function availLabel() {
    return getIndMode() === 'inherente' ? 'Disp. Inherente' : 'Disp. Operativa';
}

async function loadIndicators() {
    _indLevel = 'areas';
    _indAreaId = null;
    _indEquipId = null;
    try {
        const res = await fetch(`/api/indicators/areas?${dateParams()}`);
        const data = await res.json();
        if (data.error) { console.error(data.error); return; }
        renderBreadcrumb();
        renderAreasChart(data);
    } catch (e) { console.error('loadIndicators:', e); }
    loadPareto();
}

async function drillToEquipments(areaId, areaName) {
    _indLevel = 'equipments';
    _indAreaId = areaId;
    _indAreaName = areaName;
    try {
        const res = await fetch(`/api/indicators/area/${areaId}/equipments?${dateParams()}`);
        const data = await res.json();
        renderBreadcrumb();
        renderEquipmentsChart(data);
    } catch (e) { console.error('drillToEquipments:', e); }
}

async function drillToFailures(equipId, equipName) {
    _indLevel = 'failures';
    _indEquipId = equipId;
    _indEquipName = equipName;
    try {
        const res = await fetch(`/api/indicators/equipment/${equipId}/failures?${dateParams()}`);
        const data = await res.json();
        renderBreadcrumb();
        renderFailures(data);
    } catch (e) { console.error('drillToFailures:', e); }
}

function renderBreadcrumb() {
    const bc = document.getElementById('breadcrumb');
    let html = '';
    if (_indLevel === 'areas') {
        html = '<span class="current"><i class="fas fa-industry"></i> Todas las Áreas</span>';
    } else if (_indLevel === 'equipments') {
        html = `<span onclick="loadIndicators()"><i class="fas fa-industry"></i> Áreas</span>
                <span class="sep">›</span>
                <span class="current">${_indAreaName}</span>`;
    } else {
        html = `<span onclick="loadIndicators()"><i class="fas fa-industry"></i> Áreas</span>
                <span class="sep">›</span>
                <span onclick="drillToEquipments(${_indAreaId},'${_indAreaName}')">${_indAreaName}</span>
                <span class="sep">›</span>
                <span class="current">${_indEquipName}</span>`;
    }
    bc.innerHTML = html;
}

function renderKpiStrip(ind) {
    // Mostrar SIEMPRE las dos disponibilidades: la del modo activo en grande
    // y la otra como referencia debajo (la brecha entre ambas = costo del
    // mantenimiento planificado).
    const isInh = getIndMode() === 'inherente';
    let sub = '';
    if (isInh && ind.availability_operativa != null) {
        sub = `Operativa: ${ind.availability_operativa}%`;
    } else if (!isInh && ind.availability_inherente != null) {
        sub = `Inherente: ${ind.availability_inherente}%`;
    }
    document.getElementById('kpiStrip').innerHTML = `
        <div class="kpi-item avail"><div class="label">${availLabel()}</div><div class="value">${ind.availability}<span class="unit">%</span></div>${sub ? `<div class="sub">${sub}</div>` : ''}</div>
        <div class="kpi-item mtbf"><div class="label">MTBF</div><div class="value">${ind.mtbf}<span class="unit">h</span></div></div>
        <div class="kpi-item mttr"><div class="label">MTTR</div><div class="value">${ind.mttr}<span class="unit">h</span></div></div>
        <div class="kpi-item rel"><div class="label">Confiabilidad</div><div class="value">${ind.reliability}<span class="unit">%</span></div></div>
    `;
}

function barColor(value, type) {
    if (type === 'availability' || type === 'reliability') {
        if (value >= 95) return '#30D158';
        if (value >= 85) return '#FF9F0A';
        return '#FF453A';
    }
    if (type === 'mtbf') return '#BF5AF2';
    if (type === 'mttr') return '#FF9F0A';
    return '#5ac8fa';
}

function initChart() {
    const el = document.getElementById('mainChart');
    if (_indChart) _indChart.dispose();
    _indChart = echarts.init(el, 'dark');
    return _indChart;
}

function renderAreasChart(data) {
    const chart = initChart();
    const areas = data.areas || [];
    const { start, end } = getIndDates();
    document.getElementById('failuresPanel').style.display = 'none';

    // KPIs globales promedio
    const totalOts = areas.reduce((s, a) => s + (a.total_ots || 0), 0);
    const totalDown = areas.reduce((s, a) => s + (a.downtime_hours || 0), 0);
    const totalFail = areas.reduce((s, a) => s + (a.failure_count || 0), 0);
    const avgKey = k => areas.length ? round2(areas.reduce((s, a) => s + (a[k] != null ? a[k] : 100), 0) / areas.length) : 100;
    const globalMtbf = totalFail > 0 ? round2((data.period.hours * areas.length - totalDown) / totalFail) : data.period.hours;
    const globalMttr = totalFail > 0 ? round2(totalDown / totalFail) : 0;
    renderKpiStrip({
        availability: avgKey('availability'),
        availability_operativa: avgKey('availability_operativa'),
        availability_inherente: avgKey('availability_inherente'),
        mtbf: globalMtbf, mttr: globalMttr,
        reliability: round2(Math.exp(-data.period.hours / Math.max(globalMtbf, 1)) * 100),
    });

    const modeNote = getIndMode() === 'inherente'
        ? '🔬 INHERENTE (ISO 14224): (T − paro planificado − averías) / (T − paro planificado). Solo las averías la castigan; el mantenimiento planificado sale de la base — salud del activo.'
        : '⚙️ OPERATIVA: (T − paro planificado − averías) / T. Descuenta TODO el paro sobre las horas calendario — lo que producción realmente tuvo disponible.';
    document.getElementById('chartTitle').textContent = `Indicadores por Área — ${start} a ${end}`;
    document.getElementById('chartMethod').textContent = modeNote + ' Click en una barra para ver detalle. Cocción/Secado: ponderado por capacidad. Molino: cálculo en serie.';

    const names = areas.map(a => a.area_name);
    const metrics = [
        { name: availLabel() + ' %', key: 'availability', color: '#30D158' },
        { name: 'Confiabilidad %', key: 'reliability', color: '#5ac8fa' },
        { name: 'MTBF (h)', key: 'mtbf', color: '#BF5AF2' },
        { name: 'MTTR (h)', key: 'mttr', color: '#FF9F0A' },
    ];

    chart.setOption({
        backgroundColor: 'transparent',
        tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
        legend: { data: metrics.map(m => m.name), textStyle: { color: '#bfd2ec' } },
        grid: { top: 60, right: 20, bottom: names.length > 5 ? 80 : 50, left: 60 },
        xAxis: {
            type: 'category', data: names,
            axisLabel: {
                color: '#d5e2f5', fontSize: 11, fontWeight: 700,
                interval: 0,                       // mostrar TODOS los nombres (no salta)
                rotate: names.length > 5 ? 25 : 0, // rotar si hay muchas areas
                hideOverlap: false,
                margin: 14,
                formatter: v => v && v.length > 22 ? v.slice(0, 20) + '…' : v,
            },
            axisLine: { lineStyle: { color: '#344964' } },
        },
        yAxis: [
            { type: 'value', name: '%', max: 100, position: 'left', axisLabel: { color: '#9ab0cb', formatter: '{value}%' }, splitLine: { lineStyle: { color: 'rgba(255,255,255,.06)' } } },
            { type: 'value', name: 'horas', position: 'right', axisLabel: { color: '#9ab0cb' }, splitLine: { show: false } },
        ],
        series: metrics.map(m => ({
            name: m.name,
            type: 'bar',
            yAxisIndex: m.key.startsWith('mt') ? 1 : 0,
            data: areas.map(a => a[m.key] || 0),
            itemStyle: { color: m.color },
            label: { show: true, position: 'top', color: '#d5e2f5', fontSize: 11, fontWeight: 700, formatter: p => m.key.includes('mt') ? p.value + 'h' : p.value + '%' },
            barGap: '10%',
        })),
    });

    chart.off('click');
    chart.on('click', p => {
        if (p.componentType === 'series' && p.dataIndex != null) {
            const area = areas[p.dataIndex];
            if (area) drillToEquipments(area.area_id, area.area_name);
        }
    });
}

function renderEquipmentsChart(data) {
    const chart = initChart();
    const equips = data.equipments || [];
    document.getElementById('failuresPanel').style.display = 'none';

    // KPIs del área
    const totalDown = equips.reduce((s, e) => s + (e.downtime_hours || 0), 0);
    const totalFail = equips.reduce((s, e) => s + (e.failure_count || 0), 0);
    const avgEq = k => equips.length ? round2(equips.reduce((s, e) => s + (e[k] != null ? e[k] : 100), 0) / equips.length) : 100;
    renderKpiStrip({
        availability: avgEq('availability'),
        availability_operativa: avgEq('availability_operativa'),
        availability_inherente: avgEq('availability_inherente'),
        mtbf: totalFail > 0 ? round2((data.period.hours * equips.length - totalDown) / totalFail) : data.period.hours,
        mttr: totalFail > 0 ? round2(totalDown / totalFail) : 0,
        reliability: round2(Math.exp(-data.period.hours / Math.max(data.period.hours, 1)) * 100),
    });

    const method = data.is_series ? 'Cálculo en SERIE (disponibilidades se multiplican)' : 'Disponibilidad PONDERADA por capacidad (TM)';
    document.getElementById('chartTitle').textContent = `Equipos en ${data.area_name}`;
    document.getElementById('chartMethod').textContent = `${method}. Click en una barra para ver fallas del equipo.`;

    const names = equips.map(e => {
        const cap = e.capacity ? ` (${(e.capacity/1000).toFixed(0)}k)` : '';
        return `${e.equipment_tag}${cap}`;
    });

    chart.setOption({
        backgroundColor: 'transparent',
        tooltip: {
            trigger: 'axis', axisPointer: { type: 'shadow' },
            formatter: params => {
                const idx = params[0].dataIndex;
                const eq = equips[idx];
                let tip = `<b>${eq.equipment_tag} — ${eq.equipment_name}</b>`;
                if (eq.capacity) tip += `<br/>Capacidad: ${eq.capacity.toLocaleString()} TM`;
                params.forEach(p => { tip += `<br/>${p.seriesName}: <b>${p.value}</b>`; });
                tip += `<br/>Fallas: ${eq.failure_count} | Downtime: ${eq.downtime_hours}h`;
                return tip;
            }
        },
        legend: { data: [availLabel() + ' %', 'MTBF (h)', 'MTTR (h)'], textStyle: { color: '#bfd2ec' } },
        grid: { top: 60, right: 20, bottom: names.length > 8 ? 90 : 60, left: 60 },
        xAxis: {
            type: 'category', data: names,
            axisLabel: {
                color: '#d5e2f5', fontSize: 11, fontWeight: 700,
                interval: 0,
                rotate: names.length > 6 ? 30 : 0,
                hideOverlap: false,
                margin: 14,
                formatter: v => v && v.length > 22 ? v.slice(0, 20) + '…' : v,
            },
        },
        yAxis: [
            { type: 'value', name: '%', max: 100, position: 'left', axisLabel: { color: '#9ab0cb', formatter: '{value}%' }, splitLine: { lineStyle: { color: 'rgba(255,255,255,.06)' } } },
            { type: 'value', name: 'horas', position: 'right', axisLabel: { color: '#9ab0cb' }, splitLine: { show: false } },
        ],
        series: [
            {
                name: availLabel() + ' %', type: 'bar', yAxisIndex: 0,
                data: equips.map(e => ({ value: e.availability, itemStyle: { color: barColor(e.availability, 'availability') } })),
                label: { show: true, position: 'top', color: '#d5e2f5', fontSize: 11, fontWeight: 700, formatter: p => p.value + '%' },
            },
            {
                name: 'MTBF (h)', type: 'bar', yAxisIndex: 1,
                data: equips.map(e => e.mtbf),
                itemStyle: { color: '#BF5AF2' },
                label: { show: true, position: 'top', color: '#BF5AF2', fontSize: 10, formatter: p => p.value + 'h' },
            },
            {
                name: 'MTTR (h)', type: 'bar', yAxisIndex: 1,
                data: equips.map(e => e.mttr),
                itemStyle: { color: '#FF9F0A' },
                label: { show: true, position: 'top', color: '#FF9F0A', fontSize: 10, formatter: p => p.value + 'h' },
            },
        ],
    });

    chart.off('click');
    chart.on('click', p => {
        if (p.componentType === 'series' && p.dataIndex != null) {
            const eq = equips[p.dataIndex];
            if (eq) drillToFailures(eq.equipment_id, `${eq.equipment_tag} — ${eq.equipment_name}`);
        }
    });
}

function renderFailures(data) {
    document.getElementById('chartPanel').querySelector('.chart-box').style.display = 'none';
    document.getElementById('chartTitle').textContent = `${data.equipment_tag} — ${data.equipment_name}`;
    const methodParts = [];
    if (data.capacity) methodParts.push(`Capacidad: ${data.capacity.toLocaleString()} TM`);
    if (data.downtime_planned_hours != null) {
        methodParts.push(`Paro planificado: ${data.downtime_planned_hours}h · Paro por averías: ${data.downtime_unplanned_hours}h`);
        methodParts.push(`Disp. Operativa: ${data.availability_operativa}% · Disp. Inherente: ${data.availability_inherente}%`);
    }
    document.getElementById('chartMethod').textContent = methodParts.join('  |  ');

    renderKpiStrip(data);

    const panel = document.getElementById('failuresPanel');
    panel.style.display = 'block';
    document.getElementById('failuresTitle').innerHTML = `<i class="fas fa-exclamation-triangle"></i> Fallas y actividades con downtime (${data.failure_count})`;

    const failures = data.failures || [];
    const allOts = data.all_ots || [];

    if (!allOts.length) {
        document.getElementById('failuresList').innerHTML = '<div class="empty">Sin OTs cerradas en este periodo para este equipo.</div>';
        return;
    }

    document.getElementById('failuresList').innerHTML = `
        <div class="failure-row head"><div>OT</div><div>Descripción</div><div>Tipo</div><div>Downtime</div><div>Estado</div></div>
        ${allOts.map(ot => {
            const dh = ot.downtime_hours_calc || 0;
            // Clasificacion del paro: campo explicito o derivada del tipo
            const planned = ot.downtime_planned != null
                ? !!ot.downtime_planned
                : !/correct/i.test(ot.maintenance_type || '');
            const tipoParo = dh > 0
                ? `<br><span style="font-size:.72em;font-weight:700;color:${planned ? '#FF9F0A' : '#FF453A'};">${planned ? 'paro planificado' : 'avería'}</span>`
                : '';
            const color = dh > 0 ? (planned ? '#FF9F0A' : '#FF453A') : '#30D158';
            return `<div class="failure-row">
                <div style="font-weight:700;color:#5ac8fa;">${ot.code || 'OT-' + ot.id}</div>
                <div style="color:#d5e2f5;">${ot.description || '-'}</div>
                <div style="color:#9ab0cb;">${ot.maintenance_type || '-'}${tipoParo}</div>
                <div style="color:${color};font-weight:700;">${dh > 0 ? dh + 'h' : '-'}</div>
                <div style="color:#30D158;">${ot.status || '-'}</div>
            </div>`;
        }).join('')}
        <div class="failure-row" style="border-top:2px solid #344964;font-weight:700;">
            <div></div><div style="color:#9ab0cb;">TOTAL</div><div></div>
            <div style="color:#FF453A;">${data.downtime_hours}h</div><div>${data.failure_count} fallas</div>
        </div>
    `;
}

// ── Pareto de Fallas (80/20) ─────────────────────────────────────────────
let _paretoChart = null;

async function loadPareto() {
    const box = document.getElementById('paretoChart');
    if (!box || typeof echarts === 'undefined') return;
    const group = (document.getElementById('paretoGroup') || {}).value || 'mode';
    const { start, end } = getIndDates();
    try {
        const res = await fetch(`/api/indicators/pareto-fallas?start_date=${start}&end_date=${end}&group=${group}`);
        const data = await res.json();
        if (data.error) { console.error(data.error); return; }

        if (!_paretoChart) _paretoChart = echarts.init(box);
        const items = (data.items || []).slice(0, 15);  // top 15 legible
        const labels = items.map(i => i.label);
        const counts = items.map(i => i.count);
        const cum = items.map(i => i.cum_pct);

        _paretoChart.setOption({
            backgroundColor: 'transparent',
            tooltip: {
                trigger: 'axis',
                formatter: (ps) => {
                    const it = items[ps[0].dataIndex];
                    return `<b>${it.label}</b><br/>Ocurrencias: ${it.count} (${it.pct}%)<br/>` +
                           `Acumulado: ${it.cum_pct}%<br/>Horas de parada: ${it.downtime_hours}h`;
                },
            },
            grid: { left: 50, right: 55, top: 30, bottom: 90 },
            xAxis: {
                type: 'category', data: labels,
                axisLabel: { rotate: 40, color: '#9ab0cb', fontSize: 10, width: 110, overflow: 'truncate' },
                axisLine: { lineStyle: { color: '#344964' } },
            },
            yAxis: [
                { type: 'value', name: 'OTs', axisLabel: { color: '#9ab0cb' },
                  splitLine: { lineStyle: { color: '#233246' } } },
                { type: 'value', name: '% acum', min: 0, max: 100,
                  axisLabel: { color: '#9ab0cb', formatter: '{value}%' }, splitLine: { show: false } },
            ],
            series: [
                { name: 'Ocurrencias', type: 'bar', data: counts, barMaxWidth: 34,
                  itemStyle: { color: '#0A84FF', borderRadius: [4, 4, 0, 0] },
                  label: { show: true, position: 'top', color: '#dce7f5', fontSize: 10 } },
                { name: '% acumulado', type: 'line', yAxisIndex: 1, data: cum, smooth: true,
                  symbolSize: 6, itemStyle: { color: '#FF9F0A' }, lineStyle: { width: 2 },
                  markLine: { silent: true, symbol: 'none',
                    data: [{ yAxis: 80 }],
                    lineStyle: { color: '#FF453A', type: 'dashed' },
                    label: { formatter: '80%', color: '#FF453A' } } },
            ],
        });
    } catch (e) { console.error('loadPareto:', e); }
}
window.loadPareto = loadPareto;

function round2(v) { return Math.round(v * 100) / 100; }

async function exportIndPdf() {
    const content = document.getElementById('indicatorsContent');
    try {
        const canvas = await html2canvas(content, { backgroundColor: '#0a0e14', scale: 1.5, useCORS: true, logging: false });
        const imgData = canvas.toDataURL('image/png');
        const { jsPDF } = window.jspdf;
        const pdf = new jsPDF({ orientation: 'landscape', unit: 'mm', format: 'a4' });
        const pageW = pdf.internal.pageSize.getWidth();
        const imgW = pageW - 10;
        const imgH = (canvas.height * imgW) / canvas.width;
        const pageH = pdf.internal.pageSize.getHeight();
        let heightLeft = imgH, position = 5;
        pdf.addImage(imgData, 'PNG', 5, position, imgW, imgH);
        heightLeft -= (pageH - 10);
        while (heightLeft > 0) { position = heightLeft - imgH + 5; pdf.addPage(); pdf.addImage(imgData, 'PNG', 5, position, imgW, imgH); heightLeft -= (pageH - 10); }
        pdf.save(`Indicadores_Directorio_${new Date().toISOString().slice(0, 10)}.pdf`);
    } catch (e) { console.error('exportPdf:', e); alert('Error al generar PDF'); }
}

window.loadIndicators = loadIndicators;
window.drillToEquipments = drillToEquipments;
window.drillToFailures = drillToFailures;
window.onIndPeriodChange = onIndPeriodChange;
window.exportIndPdf = exportIndPdf;
