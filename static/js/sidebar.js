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
        { href: '/equipo-historial', icon: 'fas fa-book-open', label: 'Hist. Equipo', tip: 'Historial Equipo' },
        { href: '/monitoreo', icon: 'fas fa-wave-square', label: 'Monitoreo', tip: 'Monitoreo' },
        { href: '/lubricacion', icon: 'fas fa-oil-can', label: 'Lubricacion', tip: 'Lubricacion' },
        { href: '/inspecciones', icon: 'fas fa-clipboard-check', label: 'Inspecciones', tip: 'Inspecciones' },
        { href: '/espesores', icon: 'fas fa-ruler-vertical', label: 'Espesores', tip: 'Espesores UT' },
        { href: '/paradas', icon: 'fas fa-hard-hat', label: 'Paradas', tip: 'Parada de Planta' },
        { href: '/indicadores', icon: 'fas fa-chart-bar', label: 'Indicadores', tip: 'Indicadores Directorio', restricted: true },
        { href: '/cockpit', icon: 'fas fa-chart-pie', label: 'Cockpit Gerencial', tip: 'Cockpit Gerencial', restricted: true },
        { href: '/produccion', icon: 'fas fa-seedling', label: 'Produccion vs Mtto', tip: 'Confiabilidad de Produccion', restricted: true },
        { href: '/programa-nocturno', icon: 'fas fa-moon', label: 'Programa Nocturno', tip: 'Preventivos turno noche', restricted: true },
        { href: '/seguimiento', icon: 'fas fa-tasks', label: 'Seguimiento', tip: 'Seguimiento' },
        { href: '/calendario', icon: 'fas fa-calendar-alt', label: 'Calendario', tip: 'Plan Mtto' },
        { href: '/reportes', icon: 'fas fa-file-contract', label: 'Reportes', tip: 'Reportes' }
    ];

    const ADMIN_MENU_ITEMS = [
        { href: '/usuarios', icon: 'fas fa-users-cog', label: 'Usuarios', tip: 'Usuarios' },
        { href: '/mantenimiento-bd', icon: 'fas fa-database', label: 'Mant. BD', tip: 'Mantenimiento BD' }
    ];

    const ROLE_LABELS = {
        admin: 'Administrador', jefe_mtto: 'Jefe de Mantenimiento', planner: 'Planner',
        supervisor: 'Supervisor', tecnico: 'Técnico', operador: 'Operador',
        almacenero: 'Almacenero', gerencia: 'Gerencia', viewer: 'Solo Lectura'
    };
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

    function renderNav(navList, extraItems, baseItems) {
        if (!navList) return;
        const items = [...(baseItems || MENU_ITEMS), ...(extraItems || [])];
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

    // Module key → sidebar href mapping
    const MODULE_TO_HREF = {
        'avisos': '/avisos', 'ordenes': '/ordenes', 'compras': '/compras',
        'almacen': '/almacen', 'herramientas': '/herramientas',
        'activos_rotativos': '/activos-rotativos', 'activos_config': '/configuracion',
        'monitoreo': '/monitoreo', 'lubricacion': '/lubricacion',
        'inspecciones': '/inspecciones', 'espesores': '/espesores',
        'paradas': '/paradas', 'indicadores': '/indicadores', 'cockpit': '/cockpit',
        'produccion': '/produccion',
        'programa_nocturno': '/programa-nocturno',
        'seguimiento': '/seguimiento',
        'reportes': '/reportes', 'historial_equipo': '/equipo-historial',
    };

    async function loadCurrentUser(sidebar) {
        try {
            const res = await fetch('/api/auth/me');
            if (!res.ok) return;
            const user = await res.json();
            renderProfile(sidebar, user);

            // Load permissions to filter sidebar
            let hidden = [];
            let rolePerms = {};
            if (user.role !== 'admin') {
                let permsLoaded = false;
                try {
                    const permRes = await fetch('/api/auth/permissions');
                    if (permRes.ok) {
                        const permData = await permRes.json();
                        rolePerms = permData[user.role] || {};
                        permsLoaded = Object.keys(rolePerms).length > 0;
                    }
                } catch (_) {}
                // Solo ocultar items si logramos cargar permisos; si falla, mostrar todo y dejar que el backend bloquee acceso
                if (permsLoaded) {
                    for (const [mod, href] of Object.entries(MODULE_TO_HREF)) {
                        const p = rolePerms[mod];
                        if (!p || !p.view) {
                            hidden.push(href);
                        }
                    }
                }
            }

            const hrefToModule = Object.fromEntries(
                Object.entries(MODULE_TO_HREF).map(([m, h]) => [h, m])
            );

            const navList = sidebar.querySelector('.nav-list');
            const extra = user.role === 'admin' ? ADMIN_MENU_ITEMS : [];
            const filtered = MENU_ITEMS.filter(item => {
                if (hidden.includes(item.href)) return false;
                if (item.restricted && user.role !== 'admin') {
                    const mod = hrefToModule[item.href];
                    if (!mod || !rolePerms[mod] || !rolePerms[mod].view) return false;
                }
                return true;
            });
            renderNav(navList, extra, filtered);
        } catch (_) {}
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
            const mobileBtn = document.getElementById('mobile-menu-btn');
            if (mobileBtn) mobileBtn.style.display = 'flex';
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

        function toggleSidebar() {
            sidebar.classList.toggle('open');
            const isOpen = sidebar.classList.contains('open');
            localStorage.setItem('cmms.sidebar.open', isOpen ? '1' : '0');
            if (window.innerWidth < 1100) {
                overlay.classList.toggle('active', isOpen);
                // Hide/show mobile button
                const mobileBtn = document.getElementById('mobile-menu-btn');
                if (mobileBtn) mobileBtn.style.display = isOpen ? 'none' : 'flex';
            } else {
                overlay.classList.remove('active');
            }
            setBtnIcon(sidebar, btn);
        }

        if (btn) {
            btn.onclick = toggleSidebar;
        }

        // Create external mobile menu button (outside sidebar, always reachable)
        if (!document.getElementById('mobile-menu-btn')) {
            const mobileBtn = document.createElement('div');
            mobileBtn.id = 'mobile-menu-btn';
            mobileBtn.innerHTML = '<i class="fas fa-bars"></i>';
            mobileBtn.onclick = toggleSidebar;
            document.body.appendChild(mobileBtn);
            // Hide if sidebar is open
            if (sidebar.classList.contains('open') && window.innerWidth < 1100) {
                mobileBtn.style.display = 'none';
            }
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

// ── Notification Bell ─────────────────────────────────────────────────────────
(function() {
    function createBell() {
        // Bell button (top-right)
        const bell = document.createElement('div');
        bell.id = 'notif-bell';
        bell.innerHTML = '<i class="fas fa-bell"></i><span id="notif-badge" style="display:none">0</span>';
        bell.onclick = toggleNotifPanel;
        document.body.appendChild(bell);

        // Panel
        const panel = document.createElement('div');
        panel.id = 'notif-panel';
        panel.innerHTML = `
            <div style="display:flex;align-items:center;justify-content:space-between;padding:12px 14px;border-bottom:1px solid rgba(255,255,255,.08)">
                <strong style="color:rgba(255,255,255,.90);font-size:.92rem"><i class="fas fa-bell" style="margin-right:6px;color:#FF9F0A"></i>Notificaciones</strong>
                <div style="display:flex;gap:6px">
                    <button onclick="scanNotifications()" style="background:rgba(10,132,255,.18);border:none;border-radius:6px;color:#5AC8FA;padding:4px 8px;font-size:.72rem;cursor:pointer" title="Escanear alertas"><i class="fas fa-sync"></i></button>
                    <button onclick="markAllRead()" style="background:rgba(255,255,255,.08);border:none;border-radius:6px;color:rgba(255,255,255,.50);padding:4px 8px;font-size:.72rem;cursor:pointer">Marcar leidas</button>
                </div>
            </div>
            <div id="notif-list" style="max-height:400px;overflow-y:auto;padding:4px 0"></div>
        `;
        document.body.appendChild(panel);

        // CSS
        const style = document.createElement('style');
        style.textContent = `
            #notif-bell{position:fixed;top:12px;right:16px;width:40px;height:40px;background:rgba(20,20,22,.94);backdrop-filter:blur(16px);border:1px solid rgba(255,255,255,.10);border-radius:50%;display:flex;align-items:center;justify-content:center;cursor:pointer;z-index:2002;color:rgba(255,255,255,.70);font-size:1rem;transition:all 150ms}
            #notif-bell:hover{color:#FF9F0A;border-color:rgba(255,159,10,.30)}
            #notif-badge{position:absolute;top:-2px;right:-2px;background:#FF453A;color:#fff;font-size:.62rem;font-weight:700;min-width:16px;height:16px;border-radius:8px;display:flex;align-items:center;justify-content:center;padding:0 4px}
            #notif-panel{position:fixed;top:58px;right:16px;width:min(380px,92vw);background:rgba(28,28,30,.96);backdrop-filter:blur(20px);border:1px solid rgba(255,255,255,.10);border-radius:14px;box-shadow:0 16px 48px rgba(0,0,0,.6);z-index:2002;display:none;overflow:hidden}
            #notif-panel.open{display:block}
            .notif-item{display:flex;gap:10px;padding:10px 14px;border-bottom:1px solid rgba(255,255,255,.05);cursor:pointer;transition:background 100ms}
            .notif-item:hover{background:rgba(255,255,255,.04)}
            .notif-item.unread{background:rgba(10,132,255,.06)}
            .notif-icon{width:28px;height:28px;border-radius:8px;display:flex;align-items:center;justify-content:center;font-size:.75rem;flex-shrink:0;margin-top:2px}
            .ni-VENCIDO{background:rgba(255,69,58,.18);color:#FF6B61}
            .ni-STOCK_BAJO{background:rgba(255,159,10,.18);color:#FFB340}
            .ni-OT{background:rgba(10,132,255,.18);color:#5AC8FA}
            .ni-AVISO{background:rgba(191,90,242,.18);color:#D77AF5}
            .ni-SISTEMA,.ni-INFO{background:rgba(255,255,255,.08);color:rgba(255,255,255,.50)}
            .notif-body{flex:1;min-width:0}
            .notif-title{font-size:.82rem;color:rgba(255,255,255,.85);font-weight:600}
            .notif-msg{font-size:.75rem;color:rgba(255,255,255,.45);margin-top:2px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
            .notif-time{font-size:.68rem;color:rgba(255,255,255,.25);margin-top:2px}
            .notif-empty{text-align:center;color:rgba(255,255,255,.30);padding:30px;font-size:.85rem}
        `;
        document.head.appendChild(style);

        // Auto-load count
        refreshNotifCount();
        setInterval(refreshNotifCount, 60000); // Every 60s
        // Auto-scan on first load
        scanNotifications();
    }

    function toggleNotifPanel() {
        const panel = document.getElementById('notif-panel');
        panel.classList.toggle('open');
        if (panel.classList.contains('open')) loadNotifications();
    }

    async function refreshNotifCount() {
        try {
            const res = await fetch('/api/notifications/count');
            const data = await res.json();
            const badge = document.getElementById('notif-badge');
            if (badge) {
                badge.textContent = data.count;
                badge.style.display = data.count > 0 ? 'flex' : 'none';
            }
        } catch (_) {}
    }

    async function loadNotifications() {
        try {
            const res = await fetch('/api/notifications');
            const items = await res.json();
            const list = document.getElementById('notif-list');
            if (!items.length) {
                list.innerHTML = '<div class="notif-empty"><i class="fas fa-check-circle" style="margin-right:6px;color:#30D158"></i>Sin notificaciones</div>';
                return;
            }
            const ICONS = { VENCIDO: 'fa-clock', STOCK_BAJO: 'fa-box-open', OT: 'fa-tools', AVISO: 'fa-bell', SISTEMA: 'fa-cog', INFO: 'fa-info' };
            list.innerHTML = items.map(n => {
                const icon = ICONS[n.category] || 'fa-info';
                const cls = n.is_read ? '' : ' unread';
                const ago = n.created_at ? timeAgo(n.created_at) : '';
                return `<div class="notif-item${cls}" onclick="goNotif('${n.link||''}', ${n.id})">
                    <div class="notif-icon ni-${n.category}"><i class="fas ${icon}"></i></div>
                    <div class="notif-body">
                        <div class="notif-title">${n.title}</div>
                        ${n.message ? `<div class="notif-msg">${n.message}</div>` : ''}
                        <div class="notif-time">${ago}</div>
                    </div>
                </div>`;
            }).join('');
        } catch (_) {}
    }

    function timeAgo(iso) {
        const d = new Date(iso);
        const diff = (Date.now() - d.getTime()) / 1000;
        if (diff < 60) return 'Ahora';
        if (diff < 3600) return Math.floor(diff / 60) + ' min';
        if (diff < 86400) return Math.floor(diff / 3600) + ' h';
        return Math.floor(diff / 86400) + ' d';
    }

    window.goNotif = function(link, id) {
        fetch('/api/notifications/read', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ids: [id] })
        }).then(() => refreshNotifCount());
        if (link) window.location.href = link;
    };
    window.markAllRead = function() {
        fetch('/api/notifications/read', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' })
            .then(() => { refreshNotifCount(); loadNotifications(); });
    };
    window.scanNotifications = async function() {
        await fetch('/api/notifications/scan', { method: 'POST' });
        refreshNotifCount();
        loadNotifications();
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', createBell);
    } else {
        createBell();
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
