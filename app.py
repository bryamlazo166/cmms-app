import os
import logging
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import create_engine, text
from database import db
from dotenv import load_dotenv

load_dotenv()

from models import (
    Area, Line, Equipment, System, Component, SparePart, MaintenanceNotice, 
    WorkOrder, Provider, Technician, Tool, WarehouseItem, OTPersonnel, 
    OTMaterial, WarehouseMovement, PurchaseOrder, PurchaseRequest,
    LubricationPoint, LubricationExecution, MonitoringPoint, MonitoringReading,
    RotativeAsset, RotativeAssetHistory, RotativeAssetSpec
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
APP_BUILD_TAG = "cmms-rotative-fix-specs-2026-03-22-01"


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


@app.after_request
def add_build_header(response):
    response.headers['X-CMMS-Build'] = APP_BUILD_TAG
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

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
    OTMaterial=OTMaterial,
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
        logger.info("Database schema checked/created on startup.")
    except Exception as e:
        logger.error(f"DB startup schema check error: {e}")


_init_schema_on_startup()

# @app.route('/')
# def index():
#     return render_template('index.html')

if __name__ == '__main__':
    print(f"DEBUG: FINAL URI: {app.config.get('SQLALCHEMY_DATABASE_URI')}")
    app.run(host='0.0.0.0', debug=False, use_reloader=False, port=5009)
    










