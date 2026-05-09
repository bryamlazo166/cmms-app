"""Decoradores de rate-limit reutilizables por las rutas.

El `limiter` global se define en app.py. Aqui exponemos decoradores con
limites preconfigurados para distintos casos de uso. Si Flask-Limiter no
esta instalado, app.py provee un stub no-op, asi que los decoradores no
rompen la aplicacion.

Uso:
    from utils.rate_limit import limit_export

    @app.route('/api/foo/export')
    @login_required
    @limit_export
    def export_foo():
        ...

Las rutas se registran dentro de funciones `register_xxx_routes(app, ...)`
que se invocan despues de que app.py haya creado el limiter, por lo que el
import perezoso de abajo siempre encuentra el limiter ya inicializado.
"""


def _make_limit(limit_str):
    def decorator(fn):
        try:
            from app import limiter
            return limiter.limit(limit_str)(fn)
        except Exception:
            # Si el limiter no esta disponible por cualquier razon, devolver
            # la funcion sin proteccion en lugar de romper el arranque.
            return fn
    return decorator


# Exportaciones de Excel/PDF: caras en CPU/memoria + riesgo de exfiltracion
# de datos. 10 por hora por IP es razonable para uso humano normal.
limit_export = _make_limit("10 per hour")

# Operaciones masivas (importacion, generacion de OTs en lote): mas raras aun.
limit_bulk = _make_limit("5 per hour")

# Login: protege contra fuerza bruta. 10 intentos por minuto por IP.
limit_login = _make_limit("10 per minute")

# Endpoints publicos sin autenticacion (programa nocturno con token, etc).
limit_public = _make_limit("60 per minute")
