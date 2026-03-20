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
        { href: '/reportes', icon: 'fas fa-file-contract', label: 'Reportes', tip: 'Reportes' }
    ];

    function currentPath() {
        return (window.location.pathname || '/').toLowerCase();
    }

    function isActive(href) {
        const path = currentPath();
        if (href === '/') return path === '/';
        return path.startsWith(href.toLowerCase());
    }

    function renderNav(navList) {
        if (!navList) return;
        navList.innerHTML = MENU_ITEMS.map((item) => {
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

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initSidebar);
    } else {
        initSidebar();
    }
})();

