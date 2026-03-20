# CMMS Architecture

This project is now modularized by domain.

## Runtime entrypoint
- `app.py` initializes Flask, database URL resolution, and registers route modules.

## Route modules
- `routes/core_routes.py`: page routes and dashboard/system status.
- `routes/admin_routes.py`: admin endpoints (`/api/initialize`).
- `routes/master_data_routes.py`: providers, technicians, areas, lines, equipments, systems, components, spare-parts.
- `routes/warehouse_routes.py`: inventory, kardex, stock calculations and movements.
- `routes/work_orders_routes.py`: OT lifecycle, personnel, materials, exports, feedback.
- `routes/notices_routes.py`: notices and predictive duplicate/suggestion helpers.
- `routes/reports_routes.py`: KPI, recurrent failures and executive reporting.
- `routes/lubrication_routes.py`: lubrication points, executions and dashboard.
- `routes/monitoring_routes.py`: monitoring points/readings and dashboard.
- `routes/rotative_assets_routes.py`: rotative asset catalog, install/remove/history.
- `routes/tools_routes.py`: tools catalog endpoints.
- `routes/data_import_routes.py`: upload excel, bulk paste, hierarchy paste, export, template.
- `routes/purchasing_routes.py`: purchase requests/orders and spare list endpoint.

## Helper modules
- `utils/crud_helpers.py`: generic CRUD wrappers.
- `utils/reporting_helpers.py`: shared date/type/duration helpers.
- `utils/schedule_helpers.py`: schedule and axis helpers for lubrication/monitoring.

## Validation
- Use `scripts/smoke_test.ps1` to quickly verify key routes after changes.
