import os
import logging
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
    RotativeAsset, RotativeAssetHistory, RotativeAssetSpec,
    InspectionRoute, InspectionItem, InspectionExecution, InspectionResult
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
from routes.auth_routes import register_auth_routes
from routes.inspection_routes import register_inspection_routes
from routes.core_routes import register_core_routes
from routes.admin_routes import register_admin_routes
from routes.data_import_routes import register_data_import_routes
from routes.master_data_routes import register_master_data_routes
from routes.lubrication_routes import register_lubrication_routes
from routes.monitoring_routes import register_monitoring_routes
from routes.notices_routes import register_notices_routes
from routes.reports_routes import register_reports_routes
from routes.rotative_assets_routes import register_rotative_assets_routes
from routes.tools_routes import register_tools_routes
from routes.purchasing_routes import register_purchasing_routes
from routes.warehouse_routes import register_warehouse_routes
from routes.work_orders_routes import register_work_orders_routes

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
app.config['CMMS_DB_MODE'] = resolved_db_mode
app.config['CMMS_DB_URI_MASKED'] = _mask_db_url(final_db_url)
print(f"----> APPLICATION STARTING ON PORT 5009 <----")
print(f"----> DATABASE MODE: {resolved_db_mode.upper()} <----")
print(f"----> DATABASE URI: {app.config['CMMS_DB_URI_MASKED']} <----")
print(f"----> BUILD TAG: {APP_BUILD_TAG} <----")

db.init_app(app)

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

@app.before_request
def require_login():
    if current_user.is_authenticated:
        return
    if request.endpoint in _AUTH_EXEMPT:
        return
    # API calls → return JSON 401
    if request.path.startswith('/api/'):
        return jsonify({"error": "No autorizado. Inicia sesion.", "redirect": "/login"}), 401
    # Page requests → redirect to login
    return redirect(url_for('login', next=request.path))


@app.after_request
def add_build_header(response):
    response.headers['X-CMMS-Build'] = APP_BUILD_TAG
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response


# ── Register all route modules ────────────────────────────────────────────────
register_auth_routes(app=app, db=db, logger=logger, User=User)

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

register_rotative_assets_routes(
    app=app,
    db=db,
    RotativeAsset=RotativeAsset,
    RotativeAssetHistory=RotativeAssetHistory,
    RotativeAssetSpec=RotativeAssetSpec,
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
            for stmt in _ENSURE_INDEXES_SQL:
                try:
                    db.session.execute(text(stmt))
                except Exception as idx_err:
                    logger.warning(f"Index creation skipped: {idx_err}")
            db.session.commit()
        logger.info("Database schema and indexes checked/created on startup.")
    except Exception as e:
        logger.error(f"DB startup schema check error: {e}")


_init_schema_on_startup()
_create_default_admin()

if __name__ == '__main__':
    print(f"DEBUG: FINAL URI: {app.config.get('SQLALCHEMY_DATABASE_URI')}")
    app.run(host='0.0.0.0', debug=False, use_reloader=False, port=5009)
