(function () {
    const MENU_ITEMS = [
        { href: '/', icon: 'fas fa-chart-line', label: 'Dashboard', tip: 'Dashboard' },
        { href: '/avisos', icon: 'fas fa-bell', label: 'Avisos', tip: 'Avisos' },
        { href: '/ordenes', icon: 'fas fa-tools', label: 'Ordenes', tip: 'Ordenes' },
        { href: '/compras', icon: 'fas fa-shopping-cart', label: 'Compras', tip: 'Compras' },
        { href: '/almacen', icon: 'fas fa-boxes', label: 'Almacen', tip: 'Almacen' },
        { href: '/herramientas', icon: 'fas fa-wrench', label: 'Herramientas', tip: 'Herramientas' },
        { href: '/activos-rotativos', icon: 'fas fa-sync-alt', label: 'Act. Rotativos', tip: 'Act. Rotativos' },
        { href: '/configuracion', icon: 'fas fa-sitemap', label: 'Activos', tip: 'Activos' },
        { href: '/monitoreo', icon: 'fas fa-wave-square', label: 'Monitoreo', tip: 'Monitoreo' },
        { href: '/lubricacion', icon: 'fas fa-oil-can', label: 'Lubricacion', tip: 'Lubricacion' },
        { href: '/inspecciones', icon: 'fas fa-clipboard-check', label: 'Inspecciones', tip: 'Inspecciones' },
        { href: '/seguimiento', icon: 'fas fa-tasks', label: 'Seguimiento', tip: 'Seguimiento' },
        { href: '/reportes', icon: 'fas fa-file-contract', label: 'Reportes', tip: 'Reportes' }
    ];

    const ADMIN_MENU_ITEMS = [
        { href: '/usuarios', icon: 'fas fa-users-cog', label: 'Usuarios', tip: 'Usuarios' }
    ];

    const ROLE_LABELS = { admin: 'Administrador', supervisor: 'Supervisor', tecnico: 'Técnico' };
    const AVATAR_COLORS = ['#0A84FF', '#30D158', '#FF9F0A', '#BF5AF2', '#5AC8FA', '#FF375F', '#FF9F0A'];

    function avatarColor(name) {
        let h = 0;
        for (let c of (name || 'U')) h = (h * 31 + c.charCodeAt(0)) & 0xffff;
        return AVATAR_COLORS[h % AVATAR_COLORS.length];
    }

    function initials(name) {
        if (!name) return '?';
        return name.trim().split(/\s+/).slice(0, 2).map(w => w[0].toUpperCase()).join('');
    }

    function currentPath() {
        return (window.location.pathname || '/').toLowerCase();
    }

    function isActive(href) {
        const path = currentPath();
        if (href === '/') return path === '/';
        return path.startsWith(href.toLowerCase());
    }

    function renderNav(navList, extraItems) {
        if (!navList) return;
        const items = [...MENU_ITEMS, ...(extraItems || [])];
        navList.innerHTML = items.map((item) => {
            const active = isActive(item.href) ? 'active' : '';
            return `<li>
                <a href="${item.href}" class="${active}">
                    <i class="${item.icon}"></i>
                    <span class="links_name">${item.label}</span>
                </a>
                <span class="tooltip">${item.tip}</span>
            </li>`;
        }).join('');
    }

    function renderProfile(sidebar, user) {
        // Remove existing profile section if any
        const existing = sidebar.querySelector('.sidebar-profile');
        if (existing) existing.remove();

        const displayName = user.full_name || user.username;
        const color = avatarColor(user.username);
        const role = ROLE_LABELS[user.role] || user.role;

        const profileEl = document.createElement('div');
        profileEl.className = 'sidebar-profile';
        profileEl.innerHTML = `
            <div class="profile-info">
                <div class="profile-avatar" style="background:${color}">${initials(displayName)}</div>
                <div class="profile-text">
                    <div class="profile-name">${displayName}</div>
                    <div class="profile-role">${role}</div>
                </div>
            </div>
            <a href="/logout" class="btn-logout" title="Cerrar sesión">
                <i class="fas fa-right-from-bracket"></i>
            </a>
        `;
        sidebar.appendChild(profileEl);
    }

    async function loadCurrentUser(sidebar) {
        try {
            const res = await fetch('/api/auth/me');
            if (!res.ok) return;
            const user = await res.json();
            renderProfile(sidebar, user);
            // Add admin-only menu items
            if (user.role === 'admin') {
                const navList = sidebar.querySelector('.nav-list');
                renderNav(navList, ADMIN_MENU_ITEMS);
            }
        } catch (_) {
            // silently skip — user display is non-critical
        }
    }

    function ensureOverlay(sidebar) {
        let overlay = document.getElementById('sidebar-overlay');
        if (!overlay) {
            overlay = document.createElement('div');
            overlay.id = 'sidebar-overlay';
            document.body.appendChild(overlay);
        }
        overlay.onclick = () => {
            sidebar.classList.remove('open');
            overlay.classList.remove('active');
            localStorage.setItem('cmms.sidebar.open', '0');
            const btn = document.getElementById('btn_toggle');
            if (btn) {
                btn.classList.remove('fa-times');
                btn.classList.add('fa-bars');
            }
        };
        return overlay;
    }

    function setBtnIcon(sidebar, btn) {
        if (!btn) return;
        if (sidebar.classList.contains('open')) {
            btn.classList.remove('fa-bars');
            btn.classList.add('fa-times');
        } else {
            btn.classList.remove('fa-times');
            btn.classList.add('fa-bars');
        }
    }

    function initSidebar() {
        const sidebar = document.querySelector('.sidebar');
        if (!sidebar) return;

        const navList = sidebar.querySelector('.nav-list');
        renderNav(navList);
        loadCurrentUser(sidebar);

        const btn = document.getElementById('btn_toggle');
        const overlay = ensureOverlay(sidebar);

        const persisted = localStorage.getItem('cmms.sidebar.open');
        const desktop = window.innerWidth >= 1100;
        const shouldOpen = desktop ? true : (persisted === '1');

        if (shouldOpen) {
            sidebar.classList.add('open');
            if (!desktop) overlay.classList.add('active');
        } else {
            sidebar.classList.remove('open');
            overlay.classList.remove('active');
        }
        setBtnIcon(sidebar, btn);

        if (btn) {
            btn.onclick = () => {
                sidebar.classList.toggle('open');
                const isOpen = sidebar.classList.contains('open');
                localStorage.setItem('cmms.sidebar.open', isOpen ? '1' : '0');
                if (window.innerWidth < 1100) {
                    overlay.classList.toggle('active', isOpen);
                } else {
                    overlay.classList.remove('active');
                }
                setBtnIcon(sidebar, btn);
            };
        }

        window.addEventListener('resize', () => {
            if (window.innerWidth >= 1100) {
                overlay.classList.remove('active');
            }
        });
    }

    function enhanceMobileTables() {
        const isMobile = window.matchMedia('(max-width: 768px)').matches;
        document.body.classList.toggle('is-mobile', isMobile);
        if (!isMobile) return;

        const skipIds = new Set([
            'planningTable',
            'noticesTable'
        ]);

        const tables = document.querySelectorAll('table.data-table, table.table-sm, table.tools-table');
        tables.forEach((table) => {
            if (table.dataset.mobileProcessed === '1') return;
            if (table.id && skipIds.has(table.id)) return;

            const ths = table.querySelectorAll('thead th');
            if (!ths.length) return;

            const headers = Array.from(ths).map((th) => (th.textContent || '').trim() || 'Campo');
            const tbody = table.tBodies && table.tBodies[0] ? table.tBodies[0] : null;
            if (!tbody) return;

            const labelRowCells = () => {
                Array.from(tbody.rows || []).forEach((row) => {
                    Array.from(row.cells || []).forEach((cell, idx) => {
                        cell.setAttribute('data-label', headers[idx] || `Campo ${idx + 1}`);
                    });
                });
            };

            labelRowCells();

            const observer = new MutationObserver(() => labelRowCells());
            observer.observe(tbody, { childList: true, subtree: true });

            table.dataset.mobileProcessed = '1';
            table.classList.add('mobile-pro-table');
        });
    }

    function initMobileProLayer() {
        enhanceMobileTables();
        window.addEventListener('resize', enhanceMobileTables);
        setTimeout(enhanceMobileTables, 500);
        setInterval(enhanceMobileTables, 2500);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => {
            initSidebar();
            initMobileProLayer();
        });
    } else {
        initSidebar();
        initMobileProLayer();
    }
})();

/**
 * Wrap an async handler to disable a button during execution.
 * Usage: onclick="withLoading(this, saveMyForm)"
 *        or in JS: withLoading(buttonEl, async () => { ... })
 */
async function withLoading(btn, fn) {
    if (!btn || btn.disabled) return;
    const original = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = '<i class="fas fa-circle-notch fa-spin"></i> Procesando...';
    try {
        await fn();
    } finally {
        btn.disabled = false;
        btn.innerHTML = original;
    }
}
