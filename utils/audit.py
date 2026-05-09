"""Helpers para registro de eventos de auditoria.

Uso:
    from utils.audit import audit_log

    # En un endpoint, despues de la accion exitosa:
    audit_log('OT_DELETE', module='work_orders', entity_id=ot.id,
              detail=f"OT {ot.code} eliminada")

    # Para registrar un fallo:
    audit_log('LOGIN_FAIL', success=False, detail=f"username={username}",
              user_id=None, username=username)

El helper jamas levanta excepciones al codigo de la ruta: si por alguna razon
el insert falla (BD caida, tabla aun no migrada), se loguea por logger y se
retorna False sin propagar el error. La accion principal ya ocurrio y no
queremos romper el flujo del usuario por una falla del audit.

Convenciones de `action` (en MAYUSCULAS, separado por guiones bajos):

  Autenticacion:
    LOGIN_OK, LOGIN_FAIL, LOGOUT, PASSWORD_CHANGE
  Gestion de usuarios:
    USER_CREATE, USER_UPDATE, USER_DELETE, ROLE_CHANGE
  Operaciones sensibles:
    OT_DELETE, NOTICE_DELETE, DB_RESET, PERMISSION_CHANGE
  Exportacion / importacion:
    EXPORT_MASS, IMPORT_EXCEL
"""
import logging

from flask import has_request_context, request
from flask_login import current_user

logger = logging.getLogger(__name__)


def _client_ip():
    """Obtiene la IP del cliente respetando proxies confiables.

    Render / la mayoria de PaaS setean X-Forwarded-For. Como nuestros
    despliegues estan detras de un proxy controlado, podemos confiar en
    el primer valor de esa cabecera.
    """
    if not has_request_context():
        return None
    fwd = request.headers.get('X-Forwarded-For', '')
    if fwd:
        # X-Forwarded-For: client, proxy1, proxy2 -> tomamos el primero.
        return fwd.split(',')[0].strip()
    return request.remote_addr


def audit_log(action, module=None, entity_id=None, detail=None,
              user_id=None, username=None, success=True):
    """Inserta un registro en la tabla audit_logs.

    Si user_id/username no se pasan, se intenta extraer de current_user.
    Devuelve True en exito, False si fallo (sin propagar excepciones).
    """
    try:
        from database import db
        from models import AuditLog

        # Resolver usuario actual si no se pasa explicito
        if user_id is None and has_request_context():
            try:
                if current_user and current_user.is_authenticated:
                    user_id = current_user.id
                    if not username:
                        username = current_user.username
            except Exception:
                pass

        ip = _client_ip()
        ua = None
        if has_request_context():
            try:
                ua = (request.user_agent.string or '')[:255] or None
            except Exception:
                ua = None

        # Recortar campos largos para no sobrepasar limites de columna
        safe_detail = (detail[:1000] if isinstance(detail, str) else None)

        entry = AuditLog(
            action=action[:50] if action else 'UNKNOWN',
            module=(module[:50] if module else None),
            entity_id=entity_id,
            detail=safe_detail,
            user_id=user_id,
            username=(username[:80] if username else None),
            ip_address=(ip[:45] if ip else None),
            user_agent=ua,
            success=bool(success),
        )
        db.session.add(entry)
        db.session.commit()
        return True
    except Exception as e:
        # Nunca rompemos el flujo del usuario por una falla en audit.
        try:
            from database import db
            db.session.rollback()
        except Exception:
            pass
        logger.warning(f"audit_log({action}) falló: {e}")
        return False
