document.addEventListener('DOMContentLoaded', () => {
    loadDashboardData();
});

async function loadDashboardData() {
    try {
        const res = await fetch('/api/dashboard-stats');
        const data = await res.json();

        if (data.error) {
            console.error(data.error);
            return;
        }

        // 1. Update KPIs
        animateValue("kpiOpenOTs", 0, data.kpi.open_ots, 1000);
        animateValue("kpiPendingNotices", 0, data.kpi.pending_notices, 1000);
        animateValue("kpiClosedOTs", 0, data.kpi.closed_ots, 1000);
        animateValue("kpiActiveTechs", 0, data.kpi.active_techs, 1000);

        // 2. Charts
        renderStatusChart(data.charts.status);
        renderTypeChart(data.charts.types);
        renderFailureChart(data.charts.failures);

        // 3. Recent Activity
        renderRecentActivity(data.recent);

    } catch (e) {
        console.error("Dashboard Load Error:", e);
    }
}

function animateValue(id, start, end, duration) {
    const obj = document.getElementById(id);
    let startTimestamp = null;
    const step = (timestamp) => {
        if (!startTimestamp) startTimestamp = timestamp;
        const progress = Math.min((timestamp - startTimestamp) / duration, 1);
        obj.innerHTML = Math.floor(progress * (end - start) + start);
        if (progress < 1) {
            window.requestAnimationFrame(step);
        }
    };
    window.requestAnimationFrame(step);
}

function renderStatusChart(data) {
    const ctx = document.getElementById('statusChart').getContext('2d');
    const labels = Object.keys(data);
    const values = Object.values(data);

    // Custom Colors
    const colors = {
        'Abierta': '#ff9800',
        'Programada': '#2196f3',
        'En Progreso': '#03dac6',
        'Cerrada': '#4caf50'
    };

    new Chart(ctx, {
        type: 'bar', // or 'doughnut'
        data: {
            labels: labels,
            datasets: [{
                label: 'Cantidad de OTs',
                data: values,
                backgroundColor: labels.map(l => colors[l] || '#777'),
                borderWidth: 0,
                borderRadius: 4
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false }
            },
            scales: {
                y: { grid: { color: '#333' } },
                x: { grid: { display: false } }
            }
        }
    });
}

function renderTypeChart(data) {
    const ctx = document.getElementById('typeChart').getContext('2d');
    new Chart(ctx, {
        type: 'doughnut',
        data: {
            labels: Object.keys(data),
            datasets: [{
                data: Object.values(data),
                backgroundColor: ['#bb86fc', '#3700b3', '#03dac6', '#cf6679'],
                borderWidth: 0
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { position: 'right' }
            }
        }
    });
}

function renderFailureChart(dataArray) {
    const ctx = document.getElementById('failureChart').getContext('2d');
    const labels = dataArray.map(x => x.mode);
    const values = dataArray.map(x => x.count);

    new Chart(ctx, {
        type: 'bar',
        indexAxis: 'y', // Horizontal
        data: {
            labels: labels,
            datasets: [{
                label: 'Frecuencia',
                data: values,
                backgroundColor: '#cf6679',
                borderRadius: 4
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { display: false } },
            scales: {
                x: { grid: { color: '#333' } },
                y: { grid: { display: false } }
            }
        }
    });
}

function renderRecentActivity(list) {
    const container = document.getElementById('activityListBody');
    if (list.length === 0) {
        container.innerHTML = '<div style="padding:20px; text-align:center; color:#666;">No hay actividad reciente</div>';
        return;
    }

    container.innerHTML = list.map(item => `
        <div class="activity-item">
            <div>
                <strong style="color: #03dac6;">${item.code}</strong>
                <span style="color:#aaa; font-size:0.9em;"> - ${item.date || 'Sin Fecha'}</span>
                <div style="font-size:0.9em; margin-top:3px;">${item.description || 'Sin descripción'}</div>
            </div>
            <span class="badge ${getStatusClass(item.status)}">${item.status}</span>
        </div>
    `).join('');
}

function getStatusClass(status) {
    if (status === 'Abierta') return 'status-open';
    if (status === 'En Progreso') return 'status-progress';
    if (status === 'Cerrada') return 'status-closed';
    return ''; // Default
}
