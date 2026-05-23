// Helpers globales para formatear fechas/horas en formato 24 horas.
//
// Motivo: `new Date().toLocaleString('es-PE')` sin opciones explicitas
// produce formatos distintos segun navegador/SO (algunos 12h con a.m./p.m.,
// otros 24h). Estas funciones fuerzan `hour12: false` para garantizar
// consistencia en toda la app.
//
// IMPORTANTE: si vas a mostrar una fecha/hora en cualquier vista nueva,
// usa estos helpers en lugar de toLocaleString directo. Asi evitamos que
// vuelva a aparecer el problema de 12h vs 24h.

(function () {
    'use strict';

    function _toDate(input) {
        if (!input) return null;
        const d = (input instanceof Date) ? input : new Date(input);
        return isNaN(d.getTime()) ? null : d;
    }

    // Fecha + hora en 24h. Ej: '23/05/2026 14:30'
    window.fmtDateTime = function (input, extraOpts) {
        const d = _toDate(input);
        if (!d) return '-';
        const opts = Object.assign({
            year: 'numeric', month: '2-digit', day: '2-digit',
            hour: '2-digit', minute: '2-digit',
            hour12: false,
        }, extraOpts || {});
        return d.toLocaleString('es-PE', opts);
    };

    // Solo fecha. Ej: '23/05/2026'
    window.fmtDate = function (input) {
        const d = _toDate(input);
        if (!d) return '-';
        return d.toLocaleDateString('es-PE', {
            year: 'numeric', month: '2-digit', day: '2-digit',
        });
    };

    // Solo hora en 24h. Ej: '14:30'
    window.fmtTime = function (input, withSeconds) {
        const d = _toDate(input);
        if (!d) return '-';
        const opts = { hour: '2-digit', minute: '2-digit', hour12: false };
        if (withSeconds) opts.second = '2-digit';
        return d.toLocaleTimeString('es-PE', opts);
    };
})();
