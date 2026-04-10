// Cockpit Gerencial — Dashboard ejecutivo con ECharts
let _charts = {};
let _currentData = null;
let _prevData = null;

document.addEventListener('DOMContentLoaded', () => {
    loadCockpit();
    window.addEventListener('resize', () => {
        Object.values(_charts).forEach(c => c && c.resize());
    });
});

function onPeriodChange() {
    const period = document.getElementById('periodSelect').value;
    const startInp = document.getElementById('startDate');
    const endInp = document.getElementById('endDate');
    if (period === 'custom') {
        startInp.style.display = 'inline-block';
        endInp.style.display = 'inline-block';
    } else {
        startInp.style.display = 'none';
        endInp.style.display = 'none';
        loadCockpit();
    }
}

function getPeriodDates() {
    const period = document.getElementById('periodSelect').value;
    const today = new Date();
    let start, end;
    end = new Date(today);
    if (period === 'month') {
        start = new Date(today.getFullYear(), today.getMonth(), 1);
    } else if (period === 'last_month') {
        start = new Date(today.getFullYear(), today.getMonth() - 1, 1);
        end = new Date(today.getFullYear(), today.getMonth(), 0);
    } else if (period === 'quarter') {
        start = new Date(today);
        start.setDate(start.getDate() - 90);
    } else if (period === 'year') {
        start = new Date(today);
        start.setDate(start.getDate() - 365);
    } else if (period === 'custom') {
        const s = document.getElementById('startDate').value;
        const e = document.getElementById('endDate').value;
        if (s && e) return { start: s, end: e };
        start = new Date(today.getFullYear(), today.getMonth(), 1);
    }
    const fmt = d => d.toISOString().slice(0, 10);
    return { start: fmt(start), end: fmt(end) };
}

function getPrevPeriodDates(start, end) {
    const s = new Date(start);
    const e = new Date(end);
    const diffDays = Math.max(1, Math.round((e - s) / 86400000));
    const prevEnd = new Date(s);
    prevEnd.setDate(prevEnd.getDate() - 1);
    const prevStart = new Date(prevEnd);
    prevStart.setDate(prevStart.getDate() - diffDays);
    const fmt = d => d.toISOString().slice(0, 10);
    return { start: fmt(prevStart), end: fmt(prevEnd) };
}

async function loadCockpit() {
    try {
        const { start, end } = getPeriodDates();
        const prev = getPrevPeriodDates(start, end);
        document.getElementById('cockpitSubtitle').textContent =
            `Periodo: ${start} → ${end}`;

        const [curRes, prevRes] = await Promise.all([
            fetch(`/api/reports/executive?start_date=${start}&end_date=${end}`),
            fetch(`/api/reports/executive?start_date=${prev.start}&end_date=${prev.end}`)
        ]);
        if (!curRes.ok) {
            console.error('Error cargando cockpit');
            return;
        }
        _currentData = await curRes.json();
        _prevData = prevRes.ok ? await prevRes.json() : null;

        renderKpis();
        renderTrendChart();
        renderDonutChart();
        renderTopEquipsChart();
        renderDowntimeCausesChart();
        renderAreaHeatmap();
    } catch (e) {
        console.error('loadCockpit error:', e);
    }
}

function trendFormat(currentVal, prevVal, unit, higherIsBetter = true) {
    if (prevVal == null || prevVal === 0) return { text: '—', cls: 'neutral' };
    const diff = currentVal - prevVal;
    const pct = Math.abs((diff / prevVal) * 100);
    const up = diff > 0;
    const isBetter = (up && higherIsBetter) || (!up && !higherIsBetter);
    const arrow = up ? '▲' : (diff < 0 ? '▼' : '—');
    const cls = diff === 0 ? 'neutral' : (isBetter ? 'up' : 'down');
    const sign = diff > 0 ? '+' : '';
    return { text: `${arrow} ${sign}${diff.toFixed(1)}${unit} (${pct.toFixed(1)}%)`, cls };
}

function renderKpis() {
    if (!_currentData) return;
    const s = _currentData.summary || {};
    const ps = (_prevData && _prevData.summary) || null;

    document.getElementById('kpiAvailability').innerHTML = `${s.availability || 0}<span class="unit">%</span>`;
    document.getElementById('kpiCompliance').innerHTML = `${s.compliance_percent || 0}<span class="unit">%</span>`;
    document.getElementById('kpiMtbf').innerHTML = `${s.mtbf || 0}<span class="unit">h</span>`;
    document.getElementById('kpiMttr').innerHTML = `${s.mttr || 0}<span class="unit">h</span>`;
    document.getElementById('kpiDowntime').innerHTML = `${s.downtime_hours || 0}<span class="unit">h</span>`;
    document.getElementById('kpiCost').innerHTML = `S/ ${(s.cost || 0).toLocaleString('es-PE', { maximumFractionDigits: 0 })}`;
    document.getElementById('kpiTotalOts').textContent = s.total_ots || 0;

    const totalTypes = (s.preventive_count || 0) + (s.corrective_count || 0);
    const prevPct = totalTypes > 0 ? ((s.preventive_count / totalTypes) * 100).toFixed(0) : 0;
    document.getElementById('kpiPrevPct').innerHTML = `${prevPct}<span class="unit">%</span>`;

    // Trends
    if (ps) {
        const t1 = trendFormat(s.availability, ps.availability, '%', true);
        document.getElementById('trendAvailability').innerHTML = t1.text + ' vs periodo anterior';
        document.getElementById('trendAvailability').className = 'trend ' + t1.cls;

        const t2 = trendFormat(s.compliance_percent, ps.compliance_percent, '%', true);
        document.getElementById('trendCompliance').innerHTML = t2.text + ' vs periodo anterior';
        document.getElementById('trendCompliance').className = 'trend ' + t2.cls;

        const t3 = trendFormat(s.mtbf, ps.mtbf, 'h', true);
        document.getElementById('trendMtbf').innerHTML = t3.text;
        document.getElementById('trendMtbf').className = 'trend ' + t3.cls;

        const t4 = trendFormat(s.mttr, ps.mttr, 'h', false);
        document.getElementById('trendMttr').innerHTML = t4.text;
        document.getElementById('trendMttr').className = 'trend ' + t4.cls;
    }
}

function initChart(id) {
    if (_charts[id]) {
        _charts[id].dispose();
    }
    const el = document.getElementById(id);
    if (!el) return null;
    _charts[id] = echarts.init(el, 'dark');
    return _charts[id];
}

function renderTrendChart() {
    const chart = initChart('chartTrend');
    if (!chart || !_currentData) return;
    const trend = _currentData.trend || [];
    const dates = trend.map(t => t.date || t.day || t.label || '');
    const availability = trend.map(t => t.availability != null ? Number(t.availability) : null);
    const compliance = trend.map(t => t.compliance_percent != null ? Number(t.compliance_percent) : null);

    chart.setOption({
        backgroundColor: 'transparent',
        tooltip: { trigger: 'axis' },
        legend: { data: ['Disponibilidad %', 'Cumplimiento %'], textStyle: { color: '#bfd2ec' } },
        grid: { top: 40, right: 20, bottom: 40, left: 50 },
        xAxis: { type: 'category', data: dates, axisLine: { lineStyle: { color: '#344964' } }, axisLabel: { color: '#9ab0cb', fontSize: 10 } },
        yAxis: { type: 'value', min: 0, max: 100, axisLine: { lineStyle: { color: '#344964' } }, axisLabel: { color: '#9ab0cb', formatter: '{value}%' }, splitLine: { lineStyle: { color: 'rgba(255,255,255,0.06)' } } },
        series: [
            {
                name: 'Disponibilidad %', type: 'line', data: availability,
                smooth: true, lineStyle: { color: '#30D158', width: 3 }, itemStyle: { color: '#30D158' },
                areaStyle: { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: 'rgba(48,209,88,0.35)' }, { offset: 1, color: 'rgba(48,209,88,0)' }] } }
            },
            {
                name: 'Cumplimiento %', type: 'line', data: compliance,
                smooth: true, lineStyle: { color: '#0A84FF', width: 3 }, itemStyle: { color: '#0A84FF' },
            }
        ]
    });
}

function renderDonutChart() {
    const chart = initChart('chartDonut');
    if (!chart || !_currentData) return;
    const s = _currentData.summary || {};
    chart.setOption({
        backgroundColor: 'transparent',
        tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
        legend: { bottom: 0, textStyle: { color: '#bfd2ec' } },
        series: [{
            name: 'OTs', type: 'pie', radius: ['50%', '75%'], center: ['50%', '45%'],
            avoidLabelOverlap: false,
            label: { show: true, color: '#bfd2ec', formatter: '{b}\n{d}%' },
            data: [
                { value: s.preventive_count || 0, name: 'Preventivo', itemStyle: { color: '#30D158' } },
                { value: s.corrective_count || 0, name: 'Correctivo', itemStyle: { color: '#FF453A' } }
            ]
        }]
    });
}

function renderTopEquipsChart() {
    const chart = initChart('chartTopEquips');
    if (!chart || !_currentData) return;
    const equips = (_currentData.breakdown && _currentData.breakdown.equipments) || [];
    const top = [...equips].sort((a, b) => (b.total_ots || 0) - (a.total_ots || 0)).slice(0, 10).reverse();
    chart.setOption({
        backgroundColor: 'transparent',
        tooltip: { trigger: 'axis' },
        grid: { top: 20, right: 20, bottom: 30, left: 110 },
        xAxis: { type: 'value', axisLine: { lineStyle: { color: '#344964' } }, axisLabel: { color: '#9ab0cb' }, splitLine: { lineStyle: { color: 'rgba(255,255,255,0.06)' } } },
        yAxis: { type: 'category', data: top.map(e => e.name || e.tag || '-'), axisLine: { lineStyle: { color: '#344964' } }, axisLabel: { color: '#9ab0cb', fontSize: 11 } },
        series: [{
            name: 'OTs', type: 'bar', data: top.map(e => e.total_ots || 0),
            itemStyle: { color: { type: 'linear', x: 0, y: 0, x2: 1, y2: 0, colorStops: [{ offset: 0, color: '#0a84ff' }, { offset: 1, color: '#5ac8fa' }] } },
            label: { show: true, position: 'right', color: '#bfd2ec' }
        }]
    });
}

function renderDowntimeCausesChart() {
    const chart = initChart('chartDowntimeCauses');
    if (!chart || !_currentData) return;
    const causes = _currentData.downtime_causes || [];
    if (!causes.length) {
        chart.setOption({
            backgroundColor: 'transparent',
            title: { text: 'Sin datos de downtime', textStyle: { color: '#9ab0cb', fontSize: 14 }, left: 'center', top: 'center' }
        });
        return;
    }
    const sorted = [...causes].sort((a, b) => (b.hours || b.total_hours || 0) - (a.hours || a.total_hours || 0)).slice(0, 10).reverse();
    chart.setOption({
        backgroundColor: 'transparent',
        tooltip: { trigger: 'axis', formatter: '{b}<br/>{a}: {c} h' },
        grid: { top: 20, right: 30, bottom: 30, left: 140 },
        xAxis: { type: 'value', axisLine: { lineStyle: { color: '#344964' } }, axisLabel: { color: '#9ab0cb', formatter: '{value}h' }, splitLine: { lineStyle: { color: 'rgba(255,255,255,0.06)' } } },
        yAxis: { type: 'category', data: sorted.map(c => c.name || c.cause || c.label || '-'), axisLine: { lineStyle: { color: '#344964' } }, axisLabel: { color: '#9ab0cb', fontSize: 11 } },
        series: [{
            name: 'Horas', type: 'bar', data: sorted.map(c => Number(c.hours || c.total_hours || 0).toFixed(1)),
            itemStyle: { color: { type: 'linear', x: 0, y: 0, x2: 1, y2: 0, colorStops: [{ offset: 0, color: '#FF453A' }, { offset: 1, color: '#FF9F0A' }] } },
            label: { show: true, position: 'right', color: '#bfd2ec', formatter: '{c} h' }
        }]
    });
}

function renderAreaHeatmap() {
    const container = document.getElementById('areaHeatmap');
    if (!container || !_currentData) return;
    const areas = (_currentData.breakdown && _currentData.breakdown.areas) || [];
    if (!areas.length) {
        container.innerHTML = '<div class="loading-msg">No hay datos de áreas en el periodo seleccionado.</div>';
        return;
    }
    container.innerHTML = areas.map(a => {
        const total = a.total_ots || 0;
        const correct = a.corrective_count || 0;
        const downtime = a.downtime_hours || 0;
        const compliance = a.compliance_percent != null ? a.compliance_percent : (a.compliance || 0);
        let cls = 'ok';
        if (correct >= 10 || downtime >= 20) cls = 'critical';
        else if (correct >= 3 || downtime >= 5) cls = 'warning';
        return `
        <div class="area-tile ${cls}">
            <div class="name"><i class="fas fa-industry"></i> ${a.name || a.label || '-'}</div>
            <div class="meta">${total} OTs | ${downtime.toFixed(1)} h downtime</div>
            <div class="stats">
                <div class="stat">
                    <div class="val">${correct}</div>
                    <div class="lbl">Correctivos</div>
                </div>
                <div class="stat">
                    <div class="val">${(a.preventive_count || 0)}</div>
                    <div class="lbl">Preventivos</div>
                </div>
                <div class="stat">
                    <div class="val">${Number(compliance).toFixed(0)}%</div>
                    <div class="lbl">Cumplimiento</div>
                </div>
            </div>
        </div>`;
    }).join('');
}

async function exportPdf() {
    const content = document.getElementById('cockpitContent');
    if (!content) return;
    try {
        const btn = event.target.closest('button');
        const oldText = btn ? btn.innerHTML : '';
        if (btn) btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Generando...';

        // Usar html2canvas + jsPDF
        const canvas = await html2canvas(content, {
            backgroundColor: '#0a0e14',
            scale: 1.5,
            useCORS: true,
            logging: false,
        });
        const imgData = canvas.toDataURL('image/png');
        const { jsPDF } = window.jspdf;
        const pdf = new jsPDF({ orientation: 'landscape', unit: 'mm', format: 'a4' });
        const pageW = pdf.internal.pageSize.getWidth();
        const pageH = pdf.internal.pageSize.getHeight();
        const imgW = pageW - 10;
        const imgH = (canvas.height * imgW) / canvas.width;
        let heightLeft = imgH;
        let position = 5;
        pdf.addImage(imgData, 'PNG', 5, position, imgW, imgH);
        heightLeft -= (pageH - 10);
        while (heightLeft > 0) {
            position = heightLeft - imgH + 5;
            pdf.addPage();
            pdf.addImage(imgData, 'PNG', 5, position, imgW, imgH);
            heightLeft -= (pageH - 10);
        }
        const today = new Date().toISOString().slice(0, 10);
        pdf.save(`Cockpit_Gerencial_${today}.pdf`);

        if (btn) btn.innerHTML = oldText;
    } catch (e) {
        console.error('exportPdf error:', e);
        alert('Error al generar PDF: ' + e.message);
    }
}

window.loadCockpit = loadCockpit;
window.onPeriodChange = onPeriodChange;
window.exportPdf = exportPdf;
