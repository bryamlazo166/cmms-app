// ── BUSQUEDA GLOBAL (Cmd+K / Ctrl+K) ─────────────────────────────────────────
(function initGlobalSearch() {
    function ensureModal() {
        if (document.getElementById('globalSearchOverlay')) return;
        const css = document.createElement('style');
        css.textContent = `
            #globalSearchOverlay{position:fixed;inset:0;background:rgba(0,0,0,.65);
                z-index:9999;display:none;align-items:flex-start;justify-content:center;padding-top:10vh;}
            #globalSearchOverlay.show{display:flex;}
            #globalSearchBox{width:min(720px,92vw);background:#1c1c1e;border:1px solid #344964;
                border-radius:14px;box-shadow:0 12px 60px rgba(0,0,0,.7);overflow:hidden;}
            #globalSearchBox header{display:flex;align-items:center;gap:10px;padding:12px 16px;border-bottom:1px solid #2f4257;}
            #globalSearchBox header i{color:#5ac8fa;}
            #globalSearchInput{flex:1;background:transparent;border:0;color:#eff6ff;font-size:1rem;outline:0;}
            #globalSearchInput::placeholder{color:#6b7c95;}
            #globalSearchHint{font-size:.7rem;color:#6b7c95;border:1px solid #344964;padding:1px 6px;border-radius:4px;}
            #globalSearchBody{max-height:60vh;overflow-y:auto;}
            .gs-section{padding:8px 14px;font-size:.7rem;color:#9ab0cb;text-transform:uppercase;
                letter-spacing:.5px;border-top:1px solid rgba(255,255,255,.04);background:rgba(255,255,255,.02);}
            .gs-item{padding:10px 16px;cursor:pointer;display:flex;align-items:center;gap:10px;
                color:#eff6ff;border-bottom:1px solid rgba(255,255,255,.03);text-decoration:none;}
            .gs-item:hover, .gs-item.active{background:rgba(10,132,255,.18);}
            .gs-item .gs-label{flex:1;font-weight:600;font-size:.88rem;}
            .gs-item .gs-sub{font-size:.78rem;color:#9ab0cb;display:block;margin-top:2px;font-weight:400;}
            .gs-badge{font-size:.7rem;padding:2px 8px;border-radius:6px;background:rgba(255,255,255,.08);color:#bfd2ec;}
            #globalSearchEmpty{padding:30px;text-align:center;color:#6b7c95;font-size:.88rem;}
        `;
        document.head.appendChild(css);
        const overlay = document.createElement('div');
        overlay.id = 'globalSearchOverlay';
        overlay.innerHTML = `
            <div id="globalSearchBox">
                <header>
                    <i class="fas fa-search"></i>
                    <input id="globalSearchInput" type="search" placeholder="Buscar en todo el CMMS — avisos, OTs, equipos, actividades, compras..." autocomplete="off">
                    <span id="globalSearchHint">ESC</span>
                </header>
                <div id="globalSearchBody">
                    <div id="globalSearchEmpty">Escribe al menos 2 caracteres…</div>
                </div>
            </div>`;
        document.body.appendChild(overlay);
        overlay.addEventListener('click', e => { if (e.target === overlay) closeGS(); });
    }
    let _gsTimer = null, _gsActiveIdx = -1, _gsItems = [];
    async function runSearch(q) {
        const body = document.getElementById('globalSearchBody');
        if (!q || q.length < 2) {
            body.innerHTML = '<div id="globalSearchEmpty">Escribe al menos 2 caracteres…</div>';
            _gsItems = []; return;
        }
        body.innerHTML = '<div id="globalSearchEmpty"><i class="fas fa-spinner fa-spin"></i> Buscando…</div>';
        try {
            const r = await fetch('/api/global-search?q=' + encodeURIComponent(q));
            const d = await r.json();
            if (!r.ok) { body.innerHTML = '<div id="globalSearchEmpty">Error: ' + (d.error || r.statusText) + '</div>'; return; }
            renderResults(d.results || {}, d.total || 0);
        } catch (e) {
            body.innerHTML = '<div id="globalSearchEmpty">Error: ' + e.message + '</div>';
        }
    }
    const SECTION_LABELS = {
        avisos: '🔔 Avisos', ots: '🛠️ Órdenes de Trabajo', equipos: '⚙️ Equipos',
        actividades: '📋 Seguimiento', compras: '🛒 Compras', lubricacion: '🛢️ Lubricación',
    };
    function renderResults(results, total) {
        const body = document.getElementById('globalSearchBody');
        if (total === 0) {
            body.innerHTML = '<div id="globalSearchEmpty">Sin coincidencias. Prueba otra palabra.</div>';
            _gsItems = []; return;
        }
        const parts = [];
        _gsItems = [];
        for (const [key, items] of Object.entries(results)) {
            if (!items || !items.length) continue;
            parts.push(`<div class="gs-section">${SECTION_LABELS[key] || key} <span style="opacity:.6;">(${items.length})</span></div>`);
            for (const it of items) {
                const idx = _gsItems.length;
                _gsItems.push(it.href);
                parts.push(`<a class="gs-item" data-idx="${idx}" href="${it.href}">
                    <div class="gs-label">${escGS(it.label)}<span class="gs-sub">${escGS(it.subtitle || '')}</span></div>
                    ${it.badge ? `<span class="gs-badge">${escGS(it.badge)}</span>` : ''}
                </a>`);
            }
        }
        body.innerHTML = parts.join('');
        _gsActiveIdx = 0;
        updateActive();
    }
    function escGS(s) {
        return String(s == null ? '' : s).replace(/[&<>"']/g,
            c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
    }
    function updateActive() {
        document.querySelectorAll('.gs-item').forEach((el, i) => {
            el.classList.toggle('active', i === _gsActiveIdx);
            if (i === _gsActiveIdx) el.scrollIntoView({ block: 'nearest' });
        });
    }
    function openGS() {
        ensureModal();
        document.getElementById('globalSearchOverlay').classList.add('show');
        const inp = document.getElementById('globalSearchInput');
        inp.value = ''; inp.focus();
        inp.oninput = e => {
            clearTimeout(_gsTimer);
            const q = e.target.value.trim();
            _gsTimer = setTimeout(() => runSearch(q), 220);
        };
        inp.onkeydown = e => {
            if (e.key === 'Escape') { closeGS(); return; }
            if (e.key === 'ArrowDown') { e.preventDefault(); if (_gsItems.length) { _gsActiveIdx = (_gsActiveIdx + 1) % _gsItems.length; updateActive(); } }
            if (e.key === 'ArrowUp')   { e.preventDefault(); if (_gsItems.length) { _gsActiveIdx = (_gsActiveIdx - 1 + _gsItems.length) % _gsItems.length; updateActive(); } }
            if (e.key === 'Enter')     { e.preventDefault(); if (_gsItems[_gsActiveIdx]) location.href = _gsItems[_gsActiveIdx]; }
        };
    }
    function closeGS() {
        const o = document.getElementById('globalSearchOverlay');
        if (o) o.classList.remove('show');
    }
    document.addEventListener('keydown', e => {
        const isMac = navigator.platform.toUpperCase().includes('MAC');
        const cmd = isMac ? e.metaKey : e.ctrlKey;
        if (cmd && (e.key === 'k' || e.key === 'K')) {
            e.preventDefault(); openGS();
        }
    });
    window.openGlobalSearch = openGS;
})();

// ── PWA (Progressive Web App) ────────────────────────────────────────────────
// Inyecta link rel=manifest, meta theme-color y registra el Service Worker.
// Hacerlo desde sidebar.js evita modificar 30+ templates HTML.
(function initPWA() {
    try {
        if (!document.querySelector('link[rel="manifest"]')) {
            const l = document.createElement('link');
            l.rel = 'manifest';
            l.href = '/manifest.webmanifest';
            document.head.appendChild(l);
        }
        if (!document.querySelector('meta[name="theme-color"]')) {
            const m = document.createElement('meta');
            m.name = 'theme-color';
            m.content = '#0A84FF';
            document.head.appendChild(m);
        }
        // PWA standalone hints (Apple legacy + estándar W3C nuevo)
        if (!document.querySelector('meta[name="apple-mobile-web-app-capable"]')) {
            const m1 = document.createElement('meta');
            m1.name = 'apple-mobile-web-app-capable';
            m1.content = 'yes';
            document.head.appendChild(m1);
            // Estándar W3C reemplazo de la propiedad Apple
            const m1b = document.createElement('meta');
            m1b.name = 'mobile-web-app-capable';
            m1b.content = 'yes';
            document.head.appendChild(m1b);
            const m2 = document.createElement('meta');
            m2.name = 'apple-mobile-web-app-status-bar-style';
            m2.content = 'black-translucent';
            document.head.appendChild(m2);
            const m3 = document.createElement('link');
            m3.rel = 'apple-touch-icon';
            m3.href = '/static/icon-192.png';
            document.head.appendChild(m3);
        }
        if ('serviceWorker' in navigator && location.protocol === 'https:') {
            // Solo en HTTPS (los SW no funcionan en HTTP plano salvo localhost)
            window.addEventListener('load', () => {
                navigator.serviceWorker.register('/sw.js', { scope: '/' })
                    .catch((e) => console.warn('SW registration failed:', e));
            });
        } else if ('serviceWorker' in navigator && location.hostname === 'localhost') {
            window.addEventListener('load', () => {
                navigator.serviceWorker.register('/sw.js', { scope: '/' })
                    .catch((e) => console.warn('SW registration failed:', e));
            });
        }

        // ── Install prompt: banner discreto cuando es instalable ─────────
        // Android dispara beforeinstallprompt cuando los criterios PWA se
        // cumplen y el usuario aun no ha instalado. iOS no lo dispara (hay
        // que usar 'Añadir a pantalla de inicio' desde Safari).
        let _deferredInstallPrompt = null;
        const HIDE_KEY = 'cmms.pwa.installHidden';
        window.addEventListener('beforeinstallprompt', (e) => {
            e.preventDefault();
            _deferredInstallPrompt = e;
            _injectInstallSidebarItem();
            // Respetar si el usuario ya rechazo recientemente el banner
            try {
                const hidden = localStorage.getItem(HIDE_KEY);
                if (hidden && (Date.now() - parseInt(hidden, 10)) < 7 * 86400000) return;
            } catch (_) {}
            _showInstallBanner();
        });
        window.addEventListener('appinstalled', () => {
            _deferredInstallPrompt = null;
            const banner = document.getElementById('cmmsInstallBanner');
            if (banner) banner.remove();
            const item = document.getElementById('cmmsInstallSidebarItem');
            if (item) item.remove();
        });

        // Detectar si ya esta instalada (display-mode standalone) o si ya
        // fue agregada en iOS (navigator.standalone). En ese caso no
        // tiene sentido mostrar el boton.
        function _isAlreadyInstalled() {
            try {
                if (window.matchMedia && window.matchMedia('(display-mode: standalone)').matches) return true;
                if (window.navigator && window.navigator.standalone === true) return true;
            } catch (_) {}
            return false;
        }

        // Inyecta un item "Instalar app" en la sidebar nav-list, siempre
        // visible cuando es instalable. Si el click llega y no hay
        // deferred prompt (ya rechazado, iOS, etc.), muestra instrucciones.
        function _injectInstallSidebarItem() {
            return; // Boton "Instalar app" del sidebar retirado a pedido del usuario.
            // eslint-disable-next-line no-unreachable
            if (_isAlreadyInstalled()) return;
            if (document.getElementById('cmmsInstallSidebarItem')) return;
            const navList = document.querySelector('.sidebar .nav-list');
            if (!navList) return;
            const li = document.createElement('li');
            li.id = 'cmmsInstallSidebarItem';
            li.innerHTML = `
                <a href="#" id="cmmsInstallSidebarLink" style="background:linear-gradient(145deg,#0a4d8c,#0a84ff);">
                    <i class="fas fa-mobile-alt"></i>
                    <span class="links_name">Instalar app</span>
                </a>
                <span class="tooltip">Instalar como app</span>
            `;
            navList.appendChild(li);
            document.getElementById('cmmsInstallSidebarLink').addEventListener('click', (ev) => {
                ev.preventDefault();
                _triggerInstall();
            });
        }
        // Inyectar el boton en el sidebar Y un boton flotante fallback.
        // El boton flotante no depende del DOM del sidebar y es mas visible
        // para el usuario en planta con celular.
        function _tryInjectInstallItem() {
            if (_isAlreadyInstalled()) return;
            _injectInstallSidebarItem();
            // Retry varias veces por si el sidebar se renderiza tarde
            let tries = 0;
            const retryInterval = setInterval(() => {
                tries++;
                if (document.getElementById('cmmsInstallSidebarItem') || tries > 10) {
                    clearInterval(retryInterval);
                    return;
                }
                _injectInstallSidebarItem();
            }, 400);
            // Boton flotante siempre visible como respaldo
            _injectFloatingInstallButton();
        }

        function _injectFloatingInstallButton() {
            return; // Boton flotante "Instalar app" retirado a pedido del usuario.
            // eslint-disable-next-line no-unreachable
            if (_isAlreadyInstalled()) return;
            if (document.getElementById('cmmsInstallFab')) return;
            const fab = document.createElement('button');
            fab.id = 'cmmsInstallFab';
            fab.title = 'Instalar CMMS como app';
            fab.style.cssText = 'position:fixed;bottom:18px;left:18px;z-index:9997;background:linear-gradient(145deg,#0a4d8c,#0a84ff);color:#fff;border:none;padding:11px 16px;border-radius:30px;box-shadow:0 4px 14px rgba(10,132,255,.5);cursor:pointer;font-weight:600;font-size:.85rem;display:flex;align-items:center;gap:8px;font-family:Roboto,sans-serif;';
            fab.innerHTML = '<i class="fas fa-mobile-alt" style="font-size:1.1rem;"></i> <span>Instalar app</span>';
            fab.addEventListener('click', _triggerInstall);
            document.body.appendChild(fab);
        }

        async function _triggerInstall() {
            if (_deferredInstallPrompt) {
                _deferredInstallPrompt.prompt();
                try {
                    const choice = await _deferredInstallPrompt.userChoice;
                    if (choice.outcome === 'accepted') {
                        const item = document.getElementById('cmmsInstallSidebarItem');
                        if (item) item.remove();
                        const fab = document.getElementById('cmmsInstallFab');
                        if (fab) fab.remove();
                    }
                } catch (_) {}
                _deferredInstallPrompt = null;
                return;
            }
            // Fallback: instrucciones especificas
            const ua = navigator.userAgent || '';
            const isIOS = /iPad|iPhone|iPod/.test(ua) && !window.MSStream;
            if (isIOS) {
                alert('En iPhone/iPad:\n\n1. Asegurate de estar usando Safari (no Chrome)\n2. Toca el boton Compartir (cuadrado con flecha arriba ↑)\n3. Desplazate y elige "Añadir a pantalla de inicio"\n4. Confirma');
            } else {
                alert('En Android Chrome:\n\n1. Toca los 3 puntos arriba derecha (menu Chrome)\n2. Busca "Instalar aplicacion" o "Añadir a pantalla principal"\n3. Confirma\n\nSi la opcion no aparece, recarga la pagina o espera unos segundos (Chrome necesita evaluar la app).');
            }
        }

        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', _tryInjectInstallItem);
        } else {
            _tryInjectInstallItem();
        }

        function _showInstallBanner() {
            return; // Banner "Instalar app" retirado a pedido del usuario.
            // eslint-disable-next-line no-unreachable
            if (document.getElementById('cmmsInstallBanner')) return;
            const banner = document.createElement('div');
            banner.id = 'cmmsInstallBanner';
            banner.style.cssText = 'position:fixed;bottom:16px;right:16px;z-index:9998;background:linear-gradient(145deg,#0a4d8c,#0a84ff);color:#fff;padding:10px 14px;border-radius:10px;box-shadow:0 6px 20px rgba(0,0,0,.4);display:flex;align-items:center;gap:10px;max-width:320px;font-size:.85rem;font-family:Roboto,sans-serif;';
            banner.innerHTML = `
                <i class="fas fa-mobile-alt" style="font-size:1.4rem;"></i>
                <div style="flex:1;">
                    <div style="font-weight:600;margin-bottom:2px;">Instalar CMMS en tu celular</div>
                    <div style="opacity:.85;font-size:.75rem;">Acceso rapido y funciona sin internet en planta.</div>
                </div>
                <button id="cmmsInstallBtn" style="background:#fff;color:#0a4d8c;border:none;padding:6px 12px;border-radius:6px;font-weight:600;cursor:pointer;font-size:.82rem;">Instalar</button>
                <button id="cmmsInstallClose" style="background:transparent;color:#fff;border:none;cursor:pointer;font-size:1.2rem;padding:0 4px;opacity:.7;" title="Recordar mas tarde">&times;</button>
            `;
            document.body.appendChild(banner);
            document.getElementById('cmmsInstallBtn').addEventListener('click', async () => {
                if (!_deferredInstallPrompt) return;
                _deferredInstallPrompt.prompt();
                try { await _deferredInstallPrompt.userChoice; } catch (_) {}
                _deferredInstallPrompt = null;
                banner.remove();
            });
            document.getElementById('cmmsInstallClose').addEventListener('click', () => {
                try { localStorage.setItem(HIDE_KEY, String(Date.now())); } catch (_) {}
                banner.remove();
            });
        }

        // ── Indicador online/offline ─────────────────────────────────────
        // Pequeno badge fijo arriba derecha que solo aparece offline.
        function _renderOfflineBadge(isOffline) {
            let b = document.getElementById('cmmsOfflineBadge');
            if (isOffline) {
                if (b) return;
                b = document.createElement('div');
                b.id = 'cmmsOfflineBadge';
                b.style.cssText = 'position:fixed;top:10px;right:14px;z-index:9999;background:#FF453A;color:#fff;padding:5px 11px;border-radius:14px;font-size:.78rem;font-weight:700;box-shadow:0 4px 12px rgba(0,0,0,.3);font-family:Roboto,sans-serif;display:flex;align-items:center;gap:6px;';
                b.innerHTML = '<i class="fas fa-wifi-slash"></i> SIN CONEXION';
                document.body.appendChild(b);
            } else if (b) {
                b.remove();
            }
        }
        window.addEventListener('online', () => _renderOfflineBadge(false));
        window.addEventListener('offline', () => _renderOfflineBadge(true));
        // Check inicial
        if (typeof navigator !== 'undefined' && navigator.onLine === false) {
            // Esperar a que el DOM este listo
            if (document.readyState === 'loading') {
                document.addEventListener('DOMContentLoaded', () => _renderOfflineBadge(true));
            } else {
                _renderOfflineBadge(true);
            }
        }
    } catch (e) { console.warn('PWA init error:', e); }
})();

// ── THEME SYSTEM (Developer / Management mode) ────────────────────────────────
// Runs synchronously when sidebar.js is parsed so data-theme is on <html>
// before paint-relevant DOM is mutated. style.css uses CSS variable
// overrides keyed off [data-theme="management"], so applying the attribute
// is sufficient to switch the entire UI.
(function initTheme() {
    const KEY = 'cmms.theme';
    const saved = (() => {
        try { return localStorage.getItem(KEY); } catch (_) { return null; }
    })();
    if (saved === 'management' || saved === 'developer') {
        document.documentElement.setAttribute('data-theme', saved);
    }
    // Expose helpers for the toggle and Chart.js retheming
    window.CMMS_THEME = {
        get: () => document.documentElement.getAttribute('data-theme') || 'developer',
        set(theme) {
            const v = (theme === 'management') ? 'management' : 'developer';
            if (v === 'developer') {
                document.documentElement.removeAttribute('data-theme');
            } else {
                document.documentElement.setAttribute('data-theme', v);
            }
            try { localStorage.setItem(KEY, v); } catch (_) {}
            applyChartTheme();
            window.dispatchEvent(new CustomEvent('cmms:themechange', { detail: { theme: v } }));
        },
        toggle() { this.set(this.get() === 'management' ? 'developer' : 'management'); }
    };

    function readVar(name, fallback) {
        const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
        return v || fallback;
    }

    function applyChartTheme() {
        if (typeof Chart === 'undefined') return;
        const text = readVar('--chart-text', '') || readVar('--label-primary', '#333');
        const grid = readVar('--chart-grid', '') || readVar('--sep', '#E5E7EB');
        Chart.defaults.color = text;
        Chart.defaults.borderColor = grid;
        if (Chart.defaults.scale && Chart.defaults.scale.grid) {
            Chart.defaults.scale.grid.color = grid;
        }
        if (Chart.defaults.scales) {
            ['x', 'y', 'r', 'linear', 'category', 'time', 'logarithmic'].forEach(k => {
                if (Chart.defaults.scales[k]) {
                    Chart.defaults.scales[k].grid = Chart.defaults.scales[k].grid || {};
                    Chart.defaults.scales[k].grid.color = grid;
                    Chart.defaults.scales[k].ticks = Chart.defaults.scales[k].ticks || {};
                    Chart.defaults.scales[k].ticks.color = text;
                }
            });
        }
        // Refresh existing chart instances
        try {
            const reg = (Chart.instances || {});
            const list = Array.isArray(reg) ? reg : Object.values(reg);
            list.forEach(c => {
                if (!c) return;
                if (c.options && c.options.scales) {
                    Object.values(c.options.scales).forEach(sc => {
                        if (sc.ticks) sc.ticks.color = text;
                        if (sc.grid)  sc.grid.color  = grid;
                        if (sc.title) sc.title.color = text;
                    });
                }
                if (c.options && c.options.plugins && c.options.plugins.legend && c.options.plugins.legend.labels) {
                    c.options.plugins.legend.labels.color = text;
                }
                c.update('none');
            });
        } catch (_) {}
    }

    // Apply once Chart.js finishes loading (it's a separate <script> on the page)
    function whenChartReady(cb) {
        if (typeof Chart !== 'undefined') return cb();
        let tries = 0;
        const t = setInterval(() => {
            if (typeof Chart !== 'undefined' || tries++ > 40) {
                clearInterval(t);
                if (typeof Chart !== 'undefined') cb();
            }
        }, 100);
    }
    whenChartReady(applyChartTheme);
    window.addEventListener('cmms:themechange', () => whenChartReady(applyChartTheme));

    // Inject toggle button (next to the notification bell)
    function injectToggle() {
        if (document.getElementById('theme-toggle')) return;
        const btn = document.createElement('div');
        btn.id = 'theme-toggle';
        btn.title = 'Cambiar a Modo Gerencial / Desarrollador';
        btn.setAttribute('role', 'button');
        btn.setAttribute('tabindex', '0');
        const renderIcon = () => {
            const isMgmt = window.CMMS_THEME.get() === 'management';
            btn.innerHTML = `<i class="fas ${isMgmt ? 'fa-moon' : 'fa-briefcase'}"></i>`;
            btn.title = isMgmt ? 'Cambiar a Modo Desarrollador' : 'Cambiar a Modo Gerencial';
        };
        renderIcon();
        btn.onclick = () => { window.CMMS_THEME.toggle(); renderIcon(); };
        btn.onkeydown = (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); btn.click(); } };
        document.body.appendChild(btn);
        window.addEventListener('cmms:themechange', renderIcon);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', injectToggle);
    } else {
        injectToggle();
    }
})();

(function () {
    // Grupos del menu (colapsables). Los items sin 'group' van sueltos arriba.
    // El estado abierto/cerrado se persiste en localStorage y el grupo que
    // contiene la pagina activa se expande automaticamente.
    const G_TRABAJO = 'Gestión de Trabajo';
    const G_COMPRAS = 'Compras y Almacén';
    const G_PREVENTIVOS = 'Preventivos';
    const G_ACTIVOS = 'Activos y Planta';
    const G_ANALISIS = 'Análisis y Gerencia';
    const G_ADMIN = 'Administración';
    const GROUP_ORDER = [G_TRABAJO, G_COMPRAS, G_PREVENTIVOS, G_ACTIVOS, G_ANALISIS, G_ADMIN];

    const MENU_ITEMS = [
        { href: '/', icon: 'fas fa-chart-line', label: 'Dashboard', tip: 'Dashboard' },
        { onclick: 'openGlobalSearch()', icon: 'fas fa-search', label: 'Buscar (⌘K)', tip: 'Busqueda global Ctrl+K' },

        { group: G_TRABAJO, href: '/avisos', icon: 'fas fa-bell', label: 'Avisos', tip: 'Avisos' },
        { group: G_TRABAJO, href: '/ordenes', icon: 'fas fa-tools', label: 'Ordenes', tip: 'Ordenes' },
        { group: G_TRABAJO, href: '/requerimientos', icon: 'fas fa-clipboard-check', label: 'Requerimientos', tip: 'Backlog tecnico: compras especiales, fabricaciones, mejoras' },
        { group: G_TRABAJO, href: '/calendario', icon: 'fas fa-calendar-alt', label: 'Calendario', tip: 'Plan Mtto' },
        { group: G_TRABAJO, href: '/seguimiento', icon: 'fas fa-tasks', label: 'Seguimiento', tip: 'Seguimiento' },
        { group: G_TRABAJO, href: '/paradas', icon: 'fas fa-hard-hat', label: 'Paradas', tip: 'Parada de Planta' },
        { group: G_TRABAJO, href: '/plantillas-paradas', icon: 'fas fa-clipboard-list', label: 'Plantillas Parada', tip: 'Plantillas reutilizables de tareas para paradas' },
        { group: G_TRABAJO, href: '/programa-nocturno', icon: 'fas fa-moon', label: 'Programa Nocturno', tip: 'Preventivos turno noche', restricted: true },

        { group: G_TRABAJO, href: '/campo', icon: 'fas fa-mobile-alt', label: 'Modo Campo', tip: 'Vista móvil para técnicos: reportar fallas, cerrar OTs, lubricación y ronda eléctrica' },

        { group: G_COMPRAS, href: '/compras', icon: 'fas fa-shopping-cart', label: 'Compras', tip: 'Compras' },
        { group: G_COMPRAS, href: '/almacen', icon: 'fas fa-boxes', label: 'Almacen', tip: 'Almacen' },
        { group: G_COMPRAS, href: '/herramientas', icon: 'fas fa-wrench', label: 'Herramientas', tip: 'Herramientas' },
        { group: G_COMPRAS, href: '/activos-rotativos', icon: 'fas fa-sync-alt', label: 'Act. Rotativos', tip: 'Act. Rotativos' },
        { group: G_COMPRAS, href: '/martillos', icon: 'fas fa-gavel', label: 'Martillos', tip: 'Martillos FAPMETAL' },

        { group: G_PREVENTIVOS, href: '/lubricacion', icon: 'fas fa-oil-can', label: 'Lubricacion', tip: 'Lubricacion' },
        { group: G_PREVENTIVOS, href: '/monitoreo', icon: 'fas fa-wave-square', label: 'Monitoreo', tip: 'Monitoreo' },
        { group: G_PREVENTIVOS, href: '/motores-electricos', icon: 'fas fa-bolt', label: 'Motores Eléctricos', tip: 'Megado, corriente y temperatura de motores' },
        { group: G_PREVENTIVOS, href: '/inspecciones', icon: 'fas fa-clipboard-check', label: 'Inspecciones', tip: 'Inspecciones' },
        { group: G_PREVENTIVOS, href: '/espesores', icon: 'fas fa-ruler-vertical', label: 'Espesores', tip: 'Espesores UT' },
        { group: G_PREVENTIVOS, href: '/espesores/predictivo', icon: 'fas fa-chart-line', label: 'Predictivo Espesores', tip: 'Tasa de desgaste y vida remanente proyectada por punto (IA)' },
        { group: G_PREVENTIVOS, href: '/cumplimiento-preventivos', icon: 'fas fa-calendar-check', label: 'Cumplim. Preventivos', tip: 'Frecuencia real vs planificada (lubricación, inspección, monitoreo)', restricted: true },
        { group: G_PREVENTIVOS, href: '/optimizacion-preventivos', icon: 'fas fa-sliders-h', label: 'Optimizar Preventivos', tip: 'Detectar puntos sobre/sub-mantenidos', restricted: true },

        { group: G_ACTIVOS, href: '/configuracion', icon: 'fas fa-sitemap', label: 'Activos', tip: 'Activos' },
        { group: G_ACTIVOS, href: '/equipos-alquilados', icon: 'fas fa-truck-pickup', label: 'Equipos Alquilados', tip: 'Montacargas y minicargadores alquilados: horometros, fallas y responsabilidad' },
        { group: G_ACTIVOS, href: '/equipo-historial', icon: 'fas fa-book-open', label: 'Hist. Equipo', tip: 'Historial Equipo' },
        { group: G_ACTIVOS, href: '/responsabilidades', icon: 'fas fa-user-tag', label: 'Responsabilidades', tip: 'Asignar responsable de mantenimiento por equipo', restricted: true },
        { group: G_ACTIVOS, href: '/flujo-planta', icon: 'fas fa-project-diagram', label: 'Flujo de Planta', tip: 'Diagrama de flujo con disponibilidad por equipo', restricted: true },

        { group: G_ANALISIS, href: '/reportes', icon: 'fas fa-file-contract', label: 'Reportes', tip: 'Reportes' },
        { group: G_ANALISIS, href: '/indicadores', icon: 'fas fa-chart-bar', label: 'Indicadores', tip: 'Indicadores Directorio', restricted: true },
        { group: G_ANALISIS, href: '/diagnostico', icon: 'fas fa-stethoscope', label: 'Diagnóstico Mensual', tip: 'Informe ejecutivo con IA + programación del próximo mes', restricted: true },
        { group: G_ANALISIS, href: '/analisis-pf', icon: 'fas fa-wave-square', label: 'Confiabilidad P-F', tip: 'Correlación predictivos vs fallas — curva P-F con datos reales', restricted: true },
        { group: G_ANALISIS, href: '/cockpit', icon: 'fas fa-chart-pie', label: 'Cockpit Gerencial', tip: 'Cockpit Gerencial', restricted: true },
        { group: G_ANALISIS, href: '/produccion', icon: 'fas fa-seedling', label: 'Produccion vs Mtto', tip: 'Confiabilidad de Produccion', restricted: true },
        { group: G_ANALISIS, href: '/operatividad-anual', icon: 'fas fa-calendar-check', label: 'Operatividad Anual', tip: 'Grilla anual de operatividad por equipo (semanas)', restricted: true },
        { group: G_ANALISIS, href: '/perdidas-produccion', icon: 'fas fa-fire', label: 'Pérdidas Producción', tip: 'Sankey de horas perdidas — para presentar a jefatura', restricted: true },
        { group: G_ANALISIS, href: '/insights', icon: 'fas fa-brain', label: 'Resumen Ejecutivo', tip: 'Resumen IA para gerencia', restricted: true }
    ];

    const ADMIN_MENU_ITEMS = [
        { group: G_ADMIN, href: '/usuarios', icon: 'fas fa-users-cog', label: 'Usuarios', tip: 'Usuarios' },
        { group: G_ADMIN, href: '/admin/telegram-users', icon: 'fab fa-telegram', label: 'Reporters Bot', tip: 'Usuarios autorizados del bot Telegram' },
        { group: G_ADMIN, href: '/admin/whatsapp-users', icon: 'fab fa-whatsapp', label: 'Bot WhatsApp', tip: 'Numeros autorizados del bot WhatsApp: rol, areas y grupo destino' },
        { group: G_ADMIN, href: '/admin/bot-usage', icon: 'fas fa-robot', label: 'Uso del Bot', tip: 'Telemetría y costo del bot Telegram' },
        { group: G_ADMIN, href: '/mantenimiento-bd', icon: 'fas fa-database', label: 'Mant. BD', tip: 'Mantenimiento BD' },
        { group: G_ADMIN, href: '/admin/backup', icon: 'fas fa-cloud-download-alt', label: 'Backup BD', tip: 'Snapshot/restore de BD', restricted: true },
        { group: G_ADMIN, href: '/configuracion-kpi', icon: 'fas fa-filter', label: 'Alcance KPIs', tip: 'Que areas/equipos entran en indicadores', restricted: true }
    ];

    const ROLE_LABELS = {
        admin: 'Administrador', jefe_mtto: 'Jefe de Mantenimiento', planner: 'Planner',
        supervisor: 'Supervisor', tecnico: 'Técnico', mecanico: 'Mecánico',
        electricista: 'Electricista', operador: 'Operador',
        almacenero: 'Almacenero', gerencia: 'Gerencia', asistente: 'Asistente',
        practicante: 'Practicante', automotriz: 'Automotriz', viewer: 'Solo Lectura'
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

    const GROUPS_STORE_KEY = 'cmms.sidebar.groups';

    function loadGroupState() {
        try { return JSON.parse(localStorage.getItem(GROUPS_STORE_KEY) || '{}'); }
        catch (_) { return {}; }
    }

    function saveGroupState(state) {
        try { localStorage.setItem(GROUPS_STORE_KEY, JSON.stringify(state)); } catch (_) {}
    }

    window.cmmsToggleNavGroup = function (key) {
        const header = document.querySelector(`.nav-group[data-group="${key}"]`);
        const body = document.querySelector(`.nav-group-items[data-group-items="${key}"]`);
        if (!header || !body) return;
        const nowOpen = !header.classList.contains('open');
        header.classList.toggle('open', nowOpen);
        body.classList.toggle('collapsed', !nowOpen);
        const state = loadGroupState();
        state[key] = nowOpen ? 1 : 0;
        saveGroupState(state);
    };

    function itemHtml(item) {
        const active = item.href && isActive(item.href) ? 'active' : '';
        const handler = item.onclick
            ? `href="javascript:void(0)" onclick="${item.onclick}"`
            : `href="${item.href}"`;
        return `<li>
            <a ${handler} class="${active}">
                <i class="${item.icon}"></i>
                <span class="links_name">${item.label}</span>
            </a>
            <span class="tooltip">${item.tip}</span>
        </li>`;
    }

    function renderNav(navList, extraItems, baseItems) {
        if (!navList) return;
        const items = [...(baseItems || MENU_ITEMS), ...(extraItems || [])];
        const state = loadGroupState();

        // Items sueltos (sin grupo) van arriba
        let html = items.filter(i => !i.group).map(itemHtml).join('');

        GROUP_ORDER.forEach(g => {
            const groupItems = items.filter(i => i.group === g);
            if (!groupItems.length) return;
            const hasActive = groupItems.some(i => i.href && isActive(i.href));
            // Abierto si contiene la pagina activa, o si el usuario lo dejo abierto.
            // Sin estado guardado: cerrado por defecto (menu compacto).
            const open = hasActive || state[g] === 1;
            html += `<li class="nav-group ${open ? 'open' : ''}" data-group="${g}">
                <a href="javascript:void(0)" onclick="cmmsToggleNavGroup('${g}')" class="nav-group-header">
                    <span class="nav-group-title">${g}</span>
                    <i class="fas fa-chevron-right nav-group-chevron"></i>
                </a>
            </li>
            <li class="nav-group-items ${open ? '' : 'collapsed'}" data-group-items="${g}">
                <ul>${groupItems.map(itemHtml).join('')}</ul>
            </li>`;
        });

        navList.innerHTML = html;
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
        'requerimientos': '/requerimientos',
        'almacen': '/almacen', 'herramientas': '/herramientas',
        'activos_rotativos': '/activos-rotativos', 'martillos': '/martillos', 'activos_config': '/configuracion',
        'equipos_alquilados': '/equipos-alquilados',
        'responsabilidades': '/responsabilidades',
        'monitoreo': '/monitoreo', 'lubricacion': '/lubricacion',
        'inspecciones': '/inspecciones', 'espesores': '/espesores',
        'paradas': '/paradas', 'plantillas_paradas': '/plantillas-paradas',
        'indicadores': '/indicadores', 'diagnostico': '/diagnostico', 'analisis_pf': '/analisis-pf', 'cockpit': '/cockpit',
        'produccion': '/produccion',
        'programa_nocturno': '/programa-nocturno',
        'flujo_planta': '/flujo-planta',
        'perdidas_produccion': '/perdidas-produccion',
        'insights': '/insights',
        'seguimiento': '/seguimiento',
        'calendario': '/calendario',
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
            const isAdmin = user.role === 'admin';
            if (!isAdmin) {
                let permsLoaded = false;
                try {
                    const permRes = await fetch('/api/auth/permissions');
                    if (permRes.ok) {
                        const permData = await permRes.json();
                        // Si es admin /api/auth/permissions devuelve {permissions:..., modules, roles}
                        // Si es usuario normal devuelve {role: {modulo:{...}}}
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
                    // Sub-páginas que heredan el permiso de su módulo padre
                    if (hidden.includes('/espesores')) hidden.push('/espesores/predictivo');
                }
            }

            // Expone helper global de permisos para los templates.
            // Admin obtiene bypass total: can(*, *) === true.
            window.CMMS_PERMS = {
                role: user.role,
                isAdmin: isAdmin,
                _perms: rolePerms,
                can(module, action) {
                    if (this.isAdmin) return true;
                    const p = this._perms[module];
                    if (!p) return false;
                    return Boolean(p[action || 'view']);
                },
                applyToDom(root) {
                    // Oculta o deshabilita elementos con data-perm="modulo.accion"
                    // que el usuario no tiene permitidos. Admin siempre los muestra.
                    if (this.isAdmin) return;
                    const scope = root || document;
                    scope.querySelectorAll('[data-perm]').forEach(el => {
                        const spec = (el.getAttribute('data-perm') || '').trim();
                        if (!spec) return;
                        const [mod, act] = spec.split('.');
                        if (!this.can(mod, act)) {
                            // Por defecto ocultar; si el elemento tiene
                            // data-perm-mode="disable" se deshabilita en lugar de ocultar.
                            const mode = el.getAttribute('data-perm-mode') || 'hide';
                            if (mode === 'disable') {
                                el.disabled = true;
                                el.classList.add('perm-disabled');
                                el.title = 'No tienes permiso para esta accion';
                            } else {
                                el.style.display = 'none';
                            }
                        }
                    });
                }
            };
            // Aplicar al DOM actual y observar cambios para nodos inyectados luego
            window.CMMS_PERMS.applyToDom();
            try {
                const obs = new MutationObserver(muts => {
                    for (const m of muts) {
                        m.addedNodes.forEach(n => {
                            if (n.nodeType === 1) window.CMMS_PERMS.applyToDom(n);
                        });
                    }
                });
                obs.observe(document.body, { childList: true, subtree: true });
            } catch (_) {}

            // ── Proteccion global de copia ─────────────────────────────────
            // Solo admin puede copiar/seleccionar/arrastrar datos desde
            // cualquier tabla o grid-container del CMMS. El resto de roles
            // tiene esos eventos bloqueados. Ojo: es disuasivo, no a prueba
            // de devtools — pero cubre los flujos normales de uso.
            try {
                if (!window.CMMS_PERMS.isAdmin) {
                    // CSS reglas para todas las tablas y grids de datos
                    if (!document.getElementById('cmms-copy-protection-style')) {
                        const st = document.createElement('style');
                        st.id = 'cmms-copy-protection-style';
                        st.textContent = `
                            body.cmms-no-copy table,
                            body.cmms-no-copy .grid-container,
                            body.cmms-no-copy .kanban-body,
                            body.cmms-no-copy .data-table,
                            body.cmms-no-copy [data-no-copy] {
                                -webkit-user-select: none !important;
                                -moz-user-select: none !important;
                                -ms-user-select: none !important;
                                user-select: none !important;
                            }
                        `;
                        document.head.appendChild(st);
                    }
                    document.body.classList.add('cmms-no-copy');

                    const insideProtected = (el) => {
                        if (!el || el.nodeType !== 1) return false;
                        return !!el.closest(
                            'table, .grid-container, .kanban-body, .data-table, [data-no-copy]'
                        );
                    };
                    const blockEvent = (e) => {
                        const sel = window.getSelection && window.getSelection();
                        let node = sel && sel.anchorNode;
                        if (node && node.nodeType !== 1) node = node.parentElement;
                        if (insideProtected(node) || insideProtected(e.target)) {
                            e.preventDefault();
                            try {
                                e.clipboardData && e.clipboardData.setData('text/plain', '');
                            } catch (_) {}
                        }
                    };
                    document.addEventListener('copy', blockEvent);
                    document.addEventListener('cut', blockEvent);
                    document.addEventListener('contextmenu', (e) => {
                        if (insideProtected(e.target)) e.preventDefault();
                    });
                    document.addEventListener('selectstart', (e) => {
                        if (insideProtected(e.target)) e.preventDefault();
                    });
                    document.addEventListener('dragstart', (e) => {
                        if (insideProtected(e.target)) e.preventDefault();
                    });

                    // ── Bloqueo global de copia/descarga (no-admin) ─────────
                    // Ctrl/Cmd + C/X (copiar), S (guardar pagina), U (ver
                    // codigo fuente), P (imprimir/PDF) y F12 / Ctrl+Shift+I/J/C
                    // (DevTools). Disuasivo: el objetivo es que un usuario
                    // normal no pueda copiarse los datos ni el modulo.
                    const BLOCKED_KEYS = new Set(['c', 'x', 's', 'u', 'p']);
                    const inFormField = (el) =>
                        el && el.nodeType === 1 && ['INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName);
                    document.addEventListener('keydown', (e) => {
                        const k = (e.key || '').toLowerCase();
                        const ctrl = e.ctrlKey || e.metaKey;
                        // Ctrl+C/X se permite dentro de campos de formulario
                        // (el usuario copia/corta lo que el mismo escribio).
                        if (ctrl && !e.shiftKey && BLOCKED_KEYS.has(k)) {
                            if (['c', 'x'].includes(k) && inFormField(e.target)) return;
                            e.preventDefault();
                            e.stopPropagation();
                            return;
                        }
                        if (ctrl && e.shiftKey && ['i', 'j', 'c'].includes(k)) {
                            e.preventDefault();
                            e.stopPropagation();
                            return;
                        }
                        if (k === 'f12') {
                            e.preventDefault();
                            e.stopPropagation();
                        }
                    }, true);
                    // Copia via menu del navegador / extensiones: vaciar el
                    // portapapeles tambien fuera de tablas.
                    document.addEventListener('copy', (e) => {
                        const t = e.target;
                        const isFormField = t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA');
                        if (!isFormField) {
                            e.preventDefault();
                            try { e.clipboardData && e.clipboardData.setData('text/plain', ''); } catch (_) {}
                        }
                    }, true);
                }
            } catch (_) {}

            const hrefToModule = Object.fromEntries(
                Object.entries(MODULE_TO_HREF).map(([m, h]) => [h, m])
            );
            // Aliases extra: rutas adicionales que comparten modulo de permisos
            hrefToModule['/optimizacion-preventivos'] = 'insights';
            hrefToModule['/cumplimiento-preventivos'] = 'insights';
            hrefToModule['/motores-electricos'] = 'motores';

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
            // Solo no-leidas: las resueltas (auto o manual) dejan de aparecer.
            const res = await fetch('/api/notifications?unread=true');
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
