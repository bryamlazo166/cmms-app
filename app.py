import os
import logging
from datetime import datetime
from flask import Flask, jsonify, redirect, url_for, request
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, current_user
from sqlalchemy import create_engine, text
from database import db
from dotenv import load_dotenv

load_dotenv()

from models import (
    User,
    Area, Line, Equipment, System, Component, SparePart, MaintenanceNotice,
    WorkOrder, Provider, Technician, Tool, WarehouseItem, OTPersonnel,
    OTMaterial, WarehouseMovement, PurchaseOrder, PurchaseRequest,
    LubricationPoint, LubricationExecution, MonitoringPoint, MonitoringReading,
    PhotoAttachment, OTLogEntry,
    RotativeAsset, RotativeAssetHistory, RotativeAssetSpec, RotativeAssetBOM,
    InspectionRoute, InspectionItem, InspectionExecution, InspectionResult,
    Activity, Milestone, Notification, RolePermission,
    FailureCatalog,
    ThicknessPoint, ThicknessInspection, ThicknessReading,
    Shutdown, ShutdownArea,
    ProductionGoal,
    WeeklyPlan, WeeklyPlanItem,
)
from utils.crud_helpers import create_entry, get_entries, update_entry, delete_entry
from utils.reporting_helpers import (
    _parse_date_flexible,
    _is_in_window,
    _normalize_maintenance_type,
    _safe_duration_hours,
)
from utils.schedule_helpers import (
    _calculate_lubrication_schedule,
    _calculate_monitoring_schedule,
    _monitoring_semaphore_for_value,
    _nice_axis_step,
)
from routes.activity_routes import register_activity_routes
from routes.auth_routes import register_auth_routes
from routes.inspection_routes import register_inspection_routes
from routes.core_routes import register_core_routes
from routes.admin_routes import register_admin_routes
from routes.data_import_routes import register_data_import_routes
from routes.master_data_routes import register_master_data_routes
from routes.lubrication_routes import register_lubrication_routes
from routes.monitoring_routes import register_monitoring_routes
from routes.thickness_routes import register_thickness_routes
from routes.shutdown_routes import register_shutdown_routes
from routes.indicators_routes import register_indicators_routes
from routes.notices_routes import register_notices_routes
from routes.reports_routes import register_reports_routes
from routes.rotative_assets_routes import register_rotative_assets_routes
from routes.tools_routes import register_tools_routes
from routes.purchasing_routes import register_purchasing_routes
from routes.warehouse_routes import register_warehouse_routes
from routes.work_orders_routes import register_work_orders_routes
from routes.production_routes import register_production_routes
from routes.weekly_plan_routes import register_weekly_plan_routes
from routes.insights_routes import register_insights_routes

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

app = Flask(__name__)
APP_BUILD_TAG = "cmms-auth-2026-03-28-01"

# ── Secret key (required for Flask sessions / Flask-Login) ────────────────────
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'cmms-dev-secret-change-in-production')


def _normalize_db_url(raw_url):
    if not raw_url:
        return None
    url = raw_url.strip()
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    return url


def _mask_db_url(raw_url):
    if not raw_url:
        return None
    if "://" not in raw_url or "@" not in raw_url:
        return raw_url
    prefix, rest = raw_url.split("://", 1)
    credentials, host_part = rest.split("@", 1)
    if ":" in credentials:
        user = credentials.split(":", 1)[0]
        credentials = f"{user}:***"
    return f"{prefix}://{credentials}@{host_part}"


def _resolve_database_url():
    db_mode = (os.getenv("DB_MODE", "supabase") or "supabase").strip().lower()
    if db_mode not in {"auto", "local", "supabase"}:
        db_mode = "supabase"

    local_db_url = (os.getenv("LOCAL_DATABASE_URL") or "sqlite:///cmms_v2.db").strip()
    supabase_url = _normalize_db_url(os.getenv("DATABASE_URL"))
    allow_local_fallback = (os.getenv("ALLOW_LOCAL_FALLBACK", "0") or "0").strip().lower() in {
        "1", "true", "yes", "on"
    }
    try:
        probe_timeout = int(os.getenv("SUPABASE_PROBE_TIMEOUT_SEC", "3"))
    except Exception:
        probe_timeout = 3
    probe_timeout = max(1, min(probe_timeout, 15))

    def probe_supabase(url):
        probe_engine = create_engine(
            url,
            pool_pre_ping=True,
            connect_args={"connect_timeout": probe_timeout}
        )
        with probe_engine.connect() as conn:
            conn.execute(text("SELECT 1"))

    if db_mode == "local":
        return local_db_url, "local"

    if db_mode == "supabase":
        if not supabase_url:
            raise RuntimeError("DB_MODE=supabase pero DATABASE_URL no esta configurada.")
        probe_supabase(supabase_url)
        return supabase_url, "supabase"

    if supabase_url:
        try:
            probe_supabase(supabase_url)
            return supabase_url, "supabase"
        except Exception as probe_error:
            if allow_local_fallback:
                logger.warning(f"DATABASE_URL unreachable in auto mode, fallback to local SQLite: {probe_error}")
                return local_db_url, "local"
            raise RuntimeError(
                f"DATABASE_URL unreachable and ALLOW_LOCAL_FALLBACK=0: {probe_error}"
            )

    if allow_local_fallback:
        return local_db_url, "local"

    raise RuntimeError(
        "DATABASE_URL no configurada y ALLOW_LOCAL_FALLBACK=0. "
        "Configura DATABASE_URL o usa DB_MODE=local explicitamente."
    )


final_db_url, resolved_db_mode = _resolve_database_url()

app.config['SQLALCHEMY_DATABASE_URI'] = final_db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_pre_ping': True,
    'pool_recycle': 280,
}
app.config['CMMS_DB_MODE'] = resolved_db_mode
app.config['CMMS_DB_URI_MASKED'] = _mask_db_url(final_db_url)
print(f"----> APPLICATION STARTING ON PORT 5009 <----")
print(f"----> DATABASE MODE: {resolved_db_mode.upper()} <----")
print(f"----> DATABASE URI: {app.config['CMMS_DB_URI_MASKED']} <----")
print(f"----> BUILD TAG: {APP_BUILD_TAG} <----")

db.init_app(app)

# ── Cache busting: inject version into all templates ────────────────────────
_ASSET_VERSION = datetime.now().strftime('%Y%m%d%H%M%S')

@app.context_processor
def inject_globals():
    role = getattr(current_user, 'role', 'viewer') if current_user.is_authenticated else 'viewer'
    perms = _DEFAULT_PERMS.get(role, {}) if role != 'admin' else {}
    def can_view(mod):
        return role == 'admin' or perms.get(mod, {}).get('view', False)
    def can_edit(mod):
        return role == 'admin' or perms.get(mod, {}).get('edit', False)
    return dict(v=_ASSET_VERSION, user_role=role, can_view=can_view, can_edit=can_edit)

# ── Flask-Login setup ─────────────────────────────────────────────────────────
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = None  # Suppress default flash message

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# ── Auth guard: require login for all routes except /login and /static ────────
_AUTH_EXEMPT = {'login', 'logout', 'static', 'health_check'}

# ── Dynamic role-based access control ─────────────────────────────────────────

# Map module keys → page paths and API prefixes
_MODULE_ROUTES = {
    'avisos':           {'pages': ['/avisos'], 'api': ['/api/notices']},
    'ordenes':          {'pages': ['/ordenes'], 'api': ['/api/work-orders', '/api/work_orders', '/api/generate-preventive', '/api/pending-reports']},
    'compras':          {'pages': ['/compras'], 'api': ['/api/purchase']},
    'almacen':          {'pages': ['/almacen'], 'api': ['/api/warehouse']},
    'herramientas':     {'pages': ['/herramientas'], 'api': ['/api/tools']},
    'activos_rotativos':{'pages': ['/activos-rotativos'], 'api': ['/api/rotative-assets']},
    'activos_config':   {'pages': ['/configuracion'], 'api': ['/api/areas', '/api/lines', '/api/equipments', '/api/systems', '/api/components', '/api/spare-parts', '/api/upload-excel', '/api/bulk-paste']},
    'monitoreo':        {'pages': ['/monitoreo'], 'api': ['/api/monitoring']},
    'lubricacion':      {'pages': ['/lubricacion'], 'api': ['/api/lubrication']},
    'inspecciones':     {'pages': ['/inspecciones'], 'api': ['/api/inspection']},
    'espesores':        {'pages': ['/espesores'], 'api': ['/api/thickness']},
    'cockpit':          {'pages': ['/cockpit'], 'api': []},
    'indicadores': {'view': False, 'edit': False},
    'indicadores':      {'pages': ['/indicadores'], 'api': ['/api/indicators']},
    'produccion':       {'pages': ['/produccion'], 'api': ['/api/production']},
    'programa_nocturno': {'pages': ['/programa-nocturno'], 'api': ['/api/weekly-plans', '/api/preventive-sources']},
    'insights':          {'pages': ['/insights', '/optimizacion-preventivos'], 'api': ['/api/insights']},
    'paradas':          {'pages': ['/paradas'], 'api': ['/api/shutdowns']},
    'seguimiento':      {'pages': ['/seguimiento'], 'api': ['/api/activities', '/api/milestones']},
    'reportes':         {'pages': ['/reportes'], 'api': ['/api/reports']},
    'historial_equipo': {'pages': ['/equipo-historial'], 'api': ['/api/equipment/']},
    'exportar':         {'pages': [], 'api': ['/api/reports/powerbi-export', '/api/warehouse/export', '/api/reports/weekly-plan/export', '/api/warehouse/export-kardex']},
    'usuarios':         {'pages': ['/usuarios'], 'api': ['/api/auth/users']},
}

# Default permissions (used when no DB config exists)
# view=can see page/data, edit=can create/modify/delete
_DEFAULT_PERMS = {
    'jefe_mtto': {
        'avisos': {'view': True, 'edit': True}, 'ordenes': {'view': True, 'edit': True},
        'compras': {'view': True, 'edit': True}, 'almacen': {'view': True, 'edit': True},
        'herramientas': {'view': True, 'edit': True}, 'lubricacion': {'view': True, 'edit': True},
        'inspecciones': {'view': True, 'edit': True}, 'monitoreo': {'view': True, 'edit': True},
        'espesores': {'view': True, 'edit': True}, 'cockpit': {'view': True, 'edit': False},
        'indicadores': {'view': True, 'edit': False},
        'produccion': {'view': True, 'edit': True},
        'programa_nocturno': {'view': True, 'edit': True},
        'insights': {'view': True, 'edit': False},
        'seguimiento': {'view': True, 'edit': True}, 'reportes': {'view': True, 'edit': True},
        'activos_rotativos': {'view': True, 'edit': True}, 'activos_config': {'view': True, 'edit': False},
        'historial_equipo': {'view': True, 'edit': False}, 'exportar': {'view': False, 'edit': False},
        'usuarios': {'view': False, 'edit': False},
    },
    'planner': {
        'avisos': {'view': True, 'edit': True}, 'ordenes': {'view': True, 'edit': True},
        'compras': {'view': True, 'edit': True}, 'almacen': {'view': True, 'edit': False},
        'herramientas': {'view': True, 'edit': False}, 'lubricacion': {'view': True, 'edit': True},
        'inspecciones': {'view': True, 'edit': True}, 'monitoreo': {'view': True, 'edit': True},
        'espesores': {'view': True, 'edit': True},
        'paradas': {'view': True, 'edit': True},
        'produccion': {'view': True, 'edit': True},
        'programa_nocturno': {'view': True, 'edit': True},
        'insights': {'view': True, 'edit': False},
        'seguimiento': {'view': True, 'edit': True}, 'reportes': {'view': True, 'edit': False},
        'activos_rotativos': {'view': True, 'edit': False}, 'activos_config': {'view': True, 'edit': False},
        'historial_equipo': {'view': True, 'edit': False}, 'exportar': {'view': False, 'edit': False},
        'usuarios': {'view': False, 'edit': False},
    },
    'supervisor': {
        'avisos': {'view': True, 'edit': True}, 'ordenes': {'view': True, 'edit': False},
        'compras': {'view': True, 'edit': False}, 'almacen': {'view': True, 'edit': False},
        'herramientas': {'view': True, 'edit': False}, 'lubricacion': {'view': True, 'edit': True},
        'inspecciones': {'view': True, 'edit': True}, 'monitoreo': {'view': True, 'edit': True},
        'espesores': {'view': True, 'edit': True},
        'paradas': {'view': True, 'edit': True},
        'seguimiento': {'view': True, 'edit': True}, 'reportes': {'view': True, 'edit': False},
        'activos_rotativos': {'view': True, 'edit': False}, 'activos_config': {'view': True, 'edit': False},
        'historial_equipo': {'view': True, 'edit': False}, 'exportar': {'view': False, 'edit': False},
        'usuarios': {'view': False, 'edit': False},
    },
    'tecnico': {
        'avisos': {'view': True, 'edit': True}, 'ordenes': {'view': True, 'edit': True},
        'compras': {'view': False, 'edit': False}, 'almacen': {'view': False, 'edit': False},
        'herramientas': {'view': True, 'edit': False}, 'lubricacion': {'view': True, 'edit': True},
        'inspecciones': {'view': True, 'edit': True}, 'monitoreo': {'view': True, 'edit': True},
        'espesores': {'view': True, 'edit': True},
        'paradas': {'view': True, 'edit': False},
        'seguimiento': {'view': False, 'edit': False}, 'reportes': {'view': False, 'edit': False},
        'activos_rotativos': {'view': False, 'edit': False}, 'activos_config': {'view': False, 'edit': False},
        'historial_equipo': {'view': False, 'edit': False}, 'exportar': {'view': False, 'edit': False},
        'usuarios': {'view': False, 'edit': False},
    },
    'operador': {
        'avisos': {'view': True, 'edit': True}, 'ordenes': {'view': False, 'edit': False},
        'compras': {'view': False, 'edit': False}, 'almacen': {'view': False, 'edit': False},
        'herramientas': {'view': False, 'edit': False}, 'lubricacion': {'view': False, 'edit': False},
        'inspecciones': {'view': False, 'edit': False}, 'monitoreo': {'view': False, 'edit': False},
        'espesores': {'view': False, 'edit': False},
        'paradas': {'view': False, 'edit': False},
        'seguimiento': {'view': False, 'edit': False}, 'reportes': {'view': False, 'edit': False},
        'activos_rotativos': {'view': False, 'edit': False}, 'activos_config': {'view': False, 'edit': False},
        'historial_equipo': {'view': False, 'edit': False}, 'exportar': {'view': False, 'edit': False},
        'usuarios': {'view': False, 'edit': False},
    },
    'almacenero': {
        'avisos': {'view': False, 'edit': False}, 'ordenes': {'view': False, 'edit': False},
        'compras': {'view': True, 'edit': True}, 'almacen': {'view': True, 'edit': True},
        'herramientas': {'view': True, 'edit': True}, 'lubricacion': {'view': False, 'edit': False},
        'inspecciones': {'view': False, 'edit': False}, 'monitoreo': {'view': False, 'edit': False},
        'espesores': {'view': False, 'edit': False},
        'paradas': {'view': False, 'edit': False},
        'seguimiento': {'view': False, 'edit': False}, 'reportes': {'view': False, 'edit': False},
        'activos_rotativos': {'view': False, 'edit': False}, 'activos_config': {'view': False, 'edit': False},
        'historial_equipo': {'view': False, 'edit': False}, 'exportar': {'view': False, 'edit': False},
        'usuarios': {'view': False, 'edit': False},
    },
    'gerencia': {
        'avisos': {'view': True, 'edit': False}, 'ordenes': {'view': True, 'edit': False},
        'compras': {'view': True, 'edit': False}, 'almacen': {'view': True, 'edit': False},
        'herramientas': {'view': True, 'edit': False}, 'lubricacion': {'view': True, 'edit': False},
        'inspecciones': {'view': True, 'edit': False}, 'monitoreo': {'view': True, 'edit': False},
        'espesores': {'view': True, 'edit': False}, 'cockpit': {'view': True, 'edit': False},
        'indicadores': {'view': True, 'edit': False},
        'produccion': {'view': True, 'edit': True},
        'programa_nocturno': {'view': True, 'edit': False},
        'insights': {'view': True, 'edit': False},
        'paradas': {'view': True, 'edit': False},
        'seguimiento': {'view': True, 'edit': False}, 'reportes': {'view': True, 'edit': False},
        'activos_rotativos': {'view': True, 'edit': False}, 'activos_config': {'view': True, 'edit': False},
        'historial_equipo': {'view': True, 'edit': False}, 'exportar': {'view': False, 'edit': False},
        'usuarios': {'view': False, 'edit': False},
    },
}

_perms_cache = {}
_perms_cache_ts = 0

_PERM_ACTIONS = ('view', 'create', 'edit', 'delete', 'export', 'import', 'close', 'approve')


def _expand_legacy_perm(p):
    """Convierte el formato legado {view,edit} al de 8 flags. Sirve
    como fallback cuando _DEFAULT_PERMS aun usa el formato corto."""
    if not isinstance(p, dict):
        return {a: False for a in _PERM_ACTIONS}
    edit = bool(p.get('edit', False))
    return {
        'view':    bool(p.get('view', True)),
        'create':  bool(p.get('create', edit)),
        'edit':    edit,
        'delete':  bool(p.get('delete', edit)),
        'export':  bool(p.get('export', edit)),
        'import':  bool(p.get('import', False)),
        'close':   bool(p.get('close', edit)),
        'approve': bool(p.get('approve', False)),
    }


def _load_role_perms(role):
    """Load permissions for a role from DB, fallback to defaults.
    Devuelve {modulo: {accion: bool, ...}} con las 8 acciones."""
    import time
    global _perms_cache, _perms_cache_ts
    now = time.time()
    # Cache for 60 seconds
    if now - _perms_cache_ts < 60 and role in _perms_cache:
        return _perms_cache[role]

    defaults = _DEFAULT_PERMS.get(role, {})
    result = {}
    try:
        from models import RolePermission
        for mod_key in _MODULE_ROUTES:
            perm = RolePermission.query.filter_by(role=role, module=mod_key).first()
            default_perm = _expand_legacy_perm(defaults.get(mod_key, {}))
            if perm:
                result[mod_key] = {
                    'view':    perm.can_view,
                    'create':  perm.can_create,
                    'edit':    perm.can_edit,
                    'delete':  perm.can_delete,
                    'export':  perm.can_export,
                    'import':  perm.can_import,
                    'close':   perm.can_close,
                    'approve': perm.can_approve,
                }
            else:
                result[mod_key] = default_perm
    except Exception:
        # Si la BD no esta disponible o aun no migrada, usar defaults legados
        for mod_key in _MODULE_ROUTES:
            result[mod_key] = _expand_legacy_perm(defaults.get(mod_key, {}))

    _perms_cache[role] = result
    _perms_cache_ts = now
    return result


def _action_for_request(method, path):
    """Mapea metodo HTTP + path a la accion granular requerida.
    Ej: GET /api/avisos -> 'view'
        POST /api/avisos -> 'create'
        PUT /api/avisos/3 -> 'edit'
        DELETE /api/avisos/3 -> 'delete'
        GET /api/warehouse/export -> 'export'
        POST /api/upload-excel -> 'import'
        POST /api/work-orders/3/close -> 'close'
    """
    p = path.lower()
    # Excepciones por path antes que por metodo
    if any(seg in p for seg in ('/export', '/excel', '/pdf', '/powerbi', '/kardex')):
        return 'export'
    if any(seg in p for seg in ('/import', '/upload-excel', '/bulk-paste', '/bulk-import')):
        return 'import'
    if '/close' in p or '/cerrar' in p or '/finish' in p:
        return 'close'
    if '/approve' in p or '/aprobar' in p:
        return 'approve'

    # Por metodo HTTP
    if method == 'GET':
        return 'view'
    if method == 'POST':
        return 'create'
    if method in ('PUT', 'PATCH'):
        return 'edit'
    if method == 'DELETE':
        return 'delete'
    return 'view'


def _find_module_for_path(path):
    """Find which module a request path belongs to. More specific paths match first."""
    best_match = None
    best_len = 0
    for mod_key, routes in _MODULE_ROUTES.items():
        for p in routes.get('pages', []):
            if (path == p or path.startswith(p + '/')) and len(p) > best_len:
                best_match = (mod_key, 'page')
                best_len = len(p)
        for a in routes.get('api', []):
            if path.startswith(a) and len(a) > best_len:
                best_match = (mod_key, 'api')
                best_len = len(a)
    return best_match if best_match else (None, None)


@app.before_request
def require_login():
    # Rutas públicas tokenizadas (proveedor turno noche) — sin login requerido
    if request.path.startswith('/programa-nocturno/publico/') or request.path.startswith('/api/public/'):
        return

    if current_user.is_authenticated:
        role = getattr(current_user, 'role', None)

        # Admin has full access
        if role == 'admin':
            return

        perms = _load_role_perms(role)
        module, route_type = _find_module_for_path(request.path)

        if module and module in perms:
            p = perms[module]

            # Toda solicitud requiere view del modulo
            if not p.get('view', True):
                if route_type == 'page':
                    return redirect(url_for('index'))
                elif route_type == 'api':
                    return jsonify({"error": "No tienes permiso para ver este modulo."}), 403

            # Si es API mutante / export / import / close / approve,
            # validar la accion granular
            if route_type == 'api':
                action = _action_for_request(request.method, request.path)
                if action != 'view' and not p.get(action, False):
                    msgs = {
                        'create':  "No tienes permiso para crear en este modulo.",
                        'edit':    "No tienes permiso para modificar en este modulo.",
                        'delete':  "No tienes permiso para eliminar en este modulo.",
                        'export':  "No tienes permiso para exportar en este modulo.",
                        'import':  "No tienes permiso para importar en este modulo.",
                        'close':   "No tienes permiso para cerrar/finalizar en este modulo.",
                        'approve': "No tienes permiso para aprobar en este modulo.",
                    }
                    return jsonify({"error": msgs.get(action, "Accion no autorizada.")}), 403

        return
    if request.endpoint in _AUTH_EXEMPT:
        return
    if request.path.startswith('/api/'):
        return jsonify({"error": "No autorizado. Inicia sesion.", "redirect": "/login"}), 401
    return redirect(url_for('login', next=request.path))


@app.after_request
def add_build_header(response):
    response.headers['X-CMMS-Build'] = APP_BUILD_TAG
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response


# ── Register all route modules ────────────────────────────────────────────────
register_auth_routes(app=app, db=db, logger=logger, User=User, RolePermission=RolePermission)

register_activity_routes(app=app, db=db, logger=logger, Activity=Activity, Milestone=Milestone)

register_inspection_routes(
    app=app,
    db=db,
    logger=logger,
    InspectionRoute=InspectionRoute,
    InspectionItem=InspectionItem,
    InspectionExecution=InspectionExecution,
    InspectionResult=InspectionResult,
    MaintenanceNotice=MaintenanceNotice,
    _calculate_lubrication_schedule=_calculate_lubrication_schedule,
    _parse_date_flexible=_parse_date_flexible,
)

register_core_routes(
    app=app,
    db=db,
    logger=logger,
    app_build_tag=APP_BUILD_TAG,
    WorkOrder=WorkOrder,
    MaintenanceNotice=MaintenanceNotice,
    Technician=Technician,
    Area=Area,
    Line=Line,
    Equipment=Equipment,
    OTPersonnel=OTPersonnel,
    _parse_date_flexible=_parse_date_flexible,
    _safe_duration_hours=_safe_duration_hours,
    LubricationPoint=LubricationPoint,
    LubricationExecution=LubricationExecution,
    InspectionRoute=InspectionRoute,
    InspectionExecution=InspectionExecution,
    MonitoringPoint=MonitoringPoint,
    MonitoringReading=MonitoringReading,
    Notification=Notification,
    WarehouseItem=WarehouseItem,
    _calculate_lubrication_schedule=_calculate_lubrication_schedule,
    FailureCatalog=FailureCatalog,
)

register_master_data_routes(
    app=app,
    db=db,
    Provider=Provider,
    Technician=Technician,
    Area=Area,
    Line=Line,
    Equipment=Equipment,
    System=System,
    Component=Component,
    SparePart=SparePart,
    create_entry=create_entry,
    get_entries=get_entries,
    update_entry=update_entry,
    delete_entry=delete_entry,
)

register_warehouse_routes(
    app=app,
    db=db,
    logger=logger,
    WarehouseItem=WarehouseItem,
    WarehouseMovement=WarehouseMovement,
)

register_work_orders_routes(
    app=app,
    db=db,
    logger=logger,
    OTPersonnel=OTPersonnel,
    OTMaterial=OTMaterial,
    WarehouseItem=WarehouseItem,
    WarehouseMovement=WarehouseMovement,
    Tool=Tool,
    WorkOrder=WorkOrder,
    MaintenanceNotice=MaintenanceNotice,
    Area=Area,
    Line=Line,
    Equipment=Equipment,
    System=System,
    Component=Component,
    Provider=Provider,
    Technician=Technician,
    PurchaseRequest=PurchaseRequest,
    delete_entry=delete_entry,
    LubricationPoint=LubricationPoint,
    InspectionRoute=InspectionRoute,
    MonitoringPoint=MonitoringPoint,
    OTLogEntry=OTLogEntry,
    _calculate_lubrication_schedule=_calculate_lubrication_schedule,
    _calculate_monitoring_schedule=_calculate_monitoring_schedule,
)

register_notices_routes(
    app=app,
    db=db,
    logger=logger,
    MaintenanceNotice=MaintenanceNotice,
    WorkOrder=WorkOrder,
    System=System,
    Component=Component,
    Tool=Tool,
    WarehouseItem=WarehouseItem,
    update_entry=update_entry,
    delete_entry=delete_entry,
)

register_reports_routes(
    app=app,
    db=db,
    logger=logger,
    Area=Area,
    Line=Line,
    Equipment=Equipment,
    System=System,
    Component=Component,
    WarehouseItem=WarehouseItem,
    WorkOrder=WorkOrder,
    MaintenanceNotice=MaintenanceNotice,
    OTPersonnel=OTPersonnel,
    OTMaterial=OTMaterial,
    Technician=Technician,
    Provider=Provider,
    LubricationPoint=LubricationPoint,
    LubricationExecution=LubricationExecution,
    MonitoringPoint=MonitoringPoint,
    MonitoringReading=MonitoringReading,
    InspectionRoute=InspectionRoute,
    InspectionItem=InspectionItem,
    InspectionExecution=InspectionExecution,
    InspectionResult=InspectionResult,
    Activity=Activity,
    Milestone=Milestone,
    _parse_date_flexible=_parse_date_flexible,
    _is_in_window=_is_in_window,
    _normalize_maintenance_type=_normalize_maintenance_type,
    _safe_duration_hours=_safe_duration_hours,
)

register_lubrication_routes(
    app=app,
    db=db,
    logger=logger,
    LubricationPoint=LubricationPoint,
    LubricationExecution=LubricationExecution,
    MaintenanceNotice=MaintenanceNotice,
    _calculate_lubrication_schedule=_calculate_lubrication_schedule,
)

register_monitoring_routes(
    app=app,
    db=db,
    MonitoringPoint=MonitoringPoint,
    MonitoringReading=MonitoringReading,
    MaintenanceNotice=MaintenanceNotice,
    _calculate_monitoring_schedule=_calculate_monitoring_schedule,
    _monitoring_semaphore_for_value=_monitoring_semaphore_for_value,
    _nice_axis_step=_nice_axis_step,
    _parse_date_flexible=_parse_date_flexible,
)

register_thickness_routes(
    app=app,
    db=db,
    logger=logger,
    ThicknessPoint=ThicknessPoint,
    ThicknessInspection=ThicknessInspection,
    ThicknessReading=ThicknessReading,
    Equipment=Equipment,
    MaintenanceNotice=MaintenanceNotice,
)

register_shutdown_routes(
    app=app,
    db=db,
    logger=logger,
    Shutdown=Shutdown,
    ShutdownArea=ShutdownArea,
    WorkOrder=WorkOrder,
    Area=Area,
    Equipment=Equipment,
    Line=Line,
    OTPersonnel=OTPersonnel,
    Technician=Technician,
)

register_indicators_routes(
    app=app,
    db=db,
    logger=logger,
    WorkOrder=WorkOrder,
    Area=Area,
    Line=Line,
    Equipment=Equipment,
)

register_production_routes(
    app=app,
    db=db,
    logger=logger,
    ProductionGoal=ProductionGoal,
    WorkOrder=WorkOrder,
    Area=Area,
    Line=Line,
    Equipment=Equipment,
)

register_weekly_plan_routes(
    app=app,
    db=db,
    logger=logger,
    WeeklyPlan=WeeklyPlan,
    WeeklyPlanItem=WeeklyPlanItem,
    Area=Area,
    Line=Line,
    Equipment=Equipment,
    WorkOrder=WorkOrder,
    Provider=Provider,
    LubricationPoint=LubricationPoint,
    InspectionRoute=InspectionRoute,
    MonitoringPoint=MonitoringPoint,
    _calculate_lubrication_schedule=_calculate_lubrication_schedule,
    _calculate_monitoring_schedule=_calculate_monitoring_schedule,
)

register_insights_routes(
    app=app,
    db=db,
    logger=logger,
    WorkOrder=WorkOrder,
    MaintenanceNotice=MaintenanceNotice,
    Area=Area,
    Line=Line,
    Equipment=Equipment,
    LubricationPoint=LubricationPoint,
    InspectionRoute=InspectionRoute,
    MonitoringPoint=MonitoringPoint,
    Shutdown=Shutdown,
    LubricationExecution=LubricationExecution,
    InspectionExecution=InspectionExecution,
    MonitoringReading=MonitoringReading,
)

register_rotative_assets_routes(
    app=app,
    db=db,
    RotativeAsset=RotativeAsset,
    RotativeAssetHistory=RotativeAssetHistory,
    RotativeAssetSpec=RotativeAssetSpec,
    RotativeAssetBOM=RotativeAssetBOM,
    WarehouseItem=WarehouseItem,
    WorkOrder=WorkOrder,
    LubricationExecution=LubricationExecution,
    LubricationPoint=LubricationPoint,
)

register_tools_routes(
    app=app,
    db=db,
    Tool=Tool,
)

register_data_import_routes(
    app=app,
    db=db,
    logger=logger,
    Area=Area,
    Line=Line,
    Equipment=Equipment,
    System=System,
    Component=Component,
    SparePart=SparePart,
)

register_purchasing_routes(
    app=app,
    db=db,
    PurchaseRequest=PurchaseRequest,
    PurchaseOrder=PurchaseOrder,
    WarehouseItem=WarehouseItem,
    WarehouseMovement=WarehouseMovement,
)

register_admin_routes(
    app=app,
    db=db,
    logger=logger,
)


_ENSURE_INDEXES_SQL = [
    "CREATE INDEX IF NOT EXISTS ix_notices_status        ON maintenance_notices(status)",
    "CREATE INDEX IF NOT EXISTS ix_notices_equipment_id  ON maintenance_notices(equipment_id)",
    "CREATE INDEX IF NOT EXISTS ix_notices_area_id       ON maintenance_notices(area_id)",
    "CREATE INDEX IF NOT EXISTS ix_wo_status             ON work_orders(status)",
    "CREATE INDEX IF NOT EXISTS ix_wo_equipment_id       ON work_orders(equipment_id)",
    "CREATE INDEX IF NOT EXISTS ix_wo_notice_id          ON work_orders(notice_id)",
    "CREATE INDEX IF NOT EXISTS ix_otp_work_order_id     ON ot_personnel(work_order_id)",
    "CREATE INDEX IF NOT EXISTS ix_otm_work_order_id     ON ot_materials(work_order_id)",
    "CREATE INDEX IF NOT EXISTS ix_otm_item_type_id      ON ot_materials(item_type, item_id)",
    "CREATE INDEX IF NOT EXISTS ix_wm_item_id            ON warehouse_movements(item_id)",
    "CREATE INDEX IF NOT EXISTS ix_wm_reference_id       ON warehouse_movements(reference_id)",
    "CREATE INDEX IF NOT EXISTS ix_pr_work_order_id      ON purchase_requests(work_order_id)",
    "CREATE INDEX IF NOT EXISTS ix_pr_purchase_order_id  ON purchase_requests(purchase_order_id)",
    "CREATE INDEX IF NOT EXISTS ix_pr_status             ON purchase_requests(status)",
    "CREATE INDEX IF NOT EXISTS ix_lp_equipment_id       ON lubrication_points(equipment_id)",
    "CREATE INDEX IF NOT EXISTS ix_lp_is_active          ON lubrication_points(is_active)",
    "CREATE INDEX IF NOT EXISTS ix_mp_equipment_id       ON monitoring_points(equipment_id)",
    "CREATE INDEX IF NOT EXISTS ix_mp_is_active          ON monitoring_points(is_active)",
]


def _create_default_admin():
    """Create the initial admin user if no users exist."""
    try:
        with app.app_context():
            if User.query.count() == 0:
                admin = User(
                    username='admin',
                    role='admin',
                    full_name='Administrador',
                )
                admin.set_password('admin123')
                db.session.add(admin)
                db.session.commit()
                logger.info("Default admin user created: admin / admin123  — CHANGE THIS PASSWORD.")
                print("----> DEFAULT USER CREATED: admin / admin123  <---- CHANGE THIS PASSWORD!")
    except Exception as e:
        logger.error(f"Error creating default admin: {e}")


_ENSURE_COLUMNS = [
    ("work_orders", "caused_downtime", "BOOLEAN DEFAULT false"),
    ("work_orders", "downtime_hours", "FLOAT"),
    ("work_orders", "source_type", "VARCHAR(20)"),
    ("work_orders", "source_id", "INTEGER"),
    ("maintenance_notices", "source_type", "VARCHAR(20)"),
    ("maintenance_notices", "source_id", "INTEGER"),
    ("work_orders", "rotative_asset_id", "INTEGER"),
    ("maintenance_notices", "rotative_asset_id", "INTEGER"),
    ("maintenance_notices", "failure_mode", "VARCHAR(100)"),
    ("maintenance_notices", "failure_category", "VARCHAR(50)"),
    ("maintenance_notices", "blockage_object", "VARCHAR(100)"),
    ("maintenance_notices", "closed_date", "VARCHAR(20)"),
    ("work_orders", "report_required", "BOOLEAN DEFAULT false"),
    ("work_orders", "report_status", "VARCHAR(20)"),
    ("work_orders", "report_due_date", "VARCHAR(20)"),
    ("work_orders", "report_received_date", "VARCHAR(20)"),
    ("rotative_asset_bom", "free_text", "VARCHAR(200)"),
    ("maintenance_notices", "scope", "VARCHAR(20) DEFAULT 'PLAN' NOT NULL"),
    ("maintenance_notices", "free_location", "VARCHAR(255)"),
    ("ot_materials", "subtype", "VARCHAR(20)"),
    ("ot_materials", "item_name_free", "VARCHAR(200)"),
    ("ot_materials", "unit", "VARCHAR(20)"),
    ("ot_materials", "is_installed", "BOOLEAN DEFAULT true"),
    ("technicians", "user_id", "INTEGER"),
    ("thickness_inspections", "pdf_url", "VARCHAR(500)"),
    ("work_orders", "shutdown_id", "INTEGER"),
    ("shutdowns", "code", "VARCHAR(30)"),
    # Permisos granulares por accion (ver, crear, editar, eliminar,
    # exportar, importar, cerrar, aprobar). can_view/can_edit/can_export
    # ya existian; las 5 nuevas se inicializan derivando de can_edit
    # mediante el bloque post-create-all (ver _backfill_perm_actions).
    ("role_permissions", "can_create",  "BOOLEAN DEFAULT false"),
    ("role_permissions", "can_delete",  "BOOLEAN DEFAULT false"),
    ("role_permissions", "can_import",  "BOOLEAN DEFAULT false"),
    ("role_permissions", "can_close",   "BOOLEAN DEFAULT false"),
    ("role_permissions", "can_approve", "BOOLEAN DEFAULT false"),
]


def _init_schema_on_startup():
    auto_create = (os.getenv('CMMS_AUTO_CREATE_TABLES', 'true') or 'true').strip().lower() in {
        '1', 'true', 'yes', 'on'
    }
    if not auto_create:
        logger.info("CMMS_AUTO_CREATE_TABLES disabled; skipping db.create_all() on startup.")
        return
    try:
        with app.app_context():
            db.create_all()
            # Cada CREATE INDEX en su propia transacción: en PostgreSQL un error
            # aborta toda la transacción y las siguientes sentencias fallan.
            for stmt in _ENSURE_INDEXES_SQL:
                try:
                    db.session.execute(text(stmt))
                    db.session.commit()
                except Exception as idx_err:
                    db.session.rollback()
                    logger.warning(f"Index creation skipped: {idx_err}")
            # Auto-add missing columns to existing tables — cada ALTER en su
            # propia transacción para no envenenar la sesión si la columna ya existe.
            for table, col, col_type in _ENSURE_COLUMNS:
                try:
                    db.session.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}"))
                    db.session.commit()
                    logger.info(f"Column {table}.{col} added.")
                except Exception:
                    db.session.rollback()  # CRÍTICO en PostgreSQL
            # Make warehouse_item_id nullable in BOM
            try:
                db.session.execute(text("ALTER TABLE rotative_asset_bom ALTER COLUMN warehouse_item_id DROP NOT NULL"))
                db.session.commit()
            except Exception:
                db.session.rollback()

            # Backfill: derivar can_create/can_delete/can_close/can_approve
            # de can_edit en filas existentes que aun los tengan en NULL/false
            # tras la primera migracion. Solo se ejecuta una vez por instalacion;
            # si todos ya estan inicializados queda como no-op.
            try:
                db.session.execute(text("""
                    UPDATE role_permissions
                    SET can_create  = COALESCE(can_create, false),
                        can_delete  = COALESCE(can_delete, false),
                        can_import  = COALESCE(can_import, false),
                        can_close   = COALESCE(can_close, false),
                        can_approve = COALESCE(can_approve, false)
                    WHERE can_create IS NULL OR can_delete IS NULL OR can_import IS NULL
                       OR can_close IS NULL OR can_approve IS NULL
                """))
                # Solo derivar de can_edit cuando los flags estan en false
                # y can_edit es true, evitando pisar configuraciones manuales.
                db.session.execute(text("""
                    UPDATE role_permissions
                    SET can_create  = true,
                        can_delete  = true,
                        can_close   = true,
                        can_approve = true
                    WHERE can_edit = true
                      AND can_create = false
                      AND can_delete = false
                      AND can_close  = false
                      AND can_approve = false
                """))
                db.session.commit()
            except Exception:
                db.session.rollback()

            # Backfill de códigos de parada (PP-YYYY-MM-NNN) para registros legacy
            try:
                from models import Shutdown
                legacy_shutdowns = Shutdown.query.filter(
                    (Shutdown.code.is_(None)) | (Shutdown.code == '')
                ).order_by(Shutdown.shutdown_date, Shutdown.id).all()
                counters = {}
                for sh in legacy_shutdowns:
                    ym = (sh.shutdown_date or '')[:7] or datetime.now().strftime('%Y-%m')
                    prefix = f"PP-{ym}-"
                    if ym not in counters:
                        existing = Shutdown.query.filter(Shutdown.code.like(f"{prefix}%")).all()
                        max_n = 0
                        for s in existing:
                            try:
                                n = int((s.code or '').rsplit('-', 1)[-1])
                                max_n = max(max_n, n)
                            except Exception:
                                pass
                        counters[ym] = max_n
                    counters[ym] += 1
                    sh.code = f"{prefix}{counters[ym]:03d}"
                db.session.commit()
                if legacy_shutdowns:
                    logger.info(f"Backfilled codes for {len(legacy_shutdowns)} shutdowns.")
            except Exception as bf_err:
                logger.warning(f"Shutdown code backfill skipped: {bf_err}")
                db.session.rollback()
        logger.info("Database schema and indexes checked/created on startup.")
    except Exception as e:
        logger.error(f"DB startup schema check error: {e}")


_init_schema_on_startup()
_create_default_admin()


# ── Supabase keep-alive: ping DB every 24h to prevent free-tier suspension ────
def _start_keepalive():
    import threading
    INTERVAL = 24 * 60 * 60  # 24 hours

    def ping():
        while True:
            import time
            time.sleep(INTERVAL)
            try:
                with app.app_context():
                    db.session.execute(text("SELECT 1"))
                    db.session.commit()
                logger.info("Supabase keep-alive ping OK")
            except Exception as e:
                logger.warning(f"Supabase keep-alive ping failed: {e}")

    t = threading.Thread(target=ping, daemon=True)
    t.start()
    logger.info("Supabase keep-alive thread started (24h interval)")


if resolved_db_mode == 'supabase':
    _start_keepalive()

# ── Telegram Bot ──────────────────────────────────────────────────────────────
try:
    from bot.telegram_bot import start_telegram_bot
    start_telegram_bot(app)
except Exception as e:
    logger.warning(f"Telegram bot not started: {e}")


if __name__ == '__main__':
    print(f"DEBUG: FINAL URI: {app.config.get('SQLALCHEMY_DATABASE_URI')}")
    app.run(host='0.0.0.0', debug=False, use_reloader=False, port=5009)
