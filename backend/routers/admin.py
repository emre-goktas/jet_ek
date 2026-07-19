"""
Admin-only metrics dashboard — GET /admin/metrics (HTML) and
GET /admin/metrics/export/{table}.csv (raw export). Gated by
auth_service.require_admin (ADMIN_EMAILS in .env), not a general user route —
never registered with the app's normal _auth_dependency in main.py.
"""
import csv
import io
import logging

# pyrefly: ignore [missing-import]
from fastapi import APIRouter, Depends, HTTPException, Request
# pyrefly: ignore [missing-import]
from fastapi.responses import StreamingResponse

from backend.services import auth_service, db_service
from backend.templating import templates

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/admin/metrics")
async def admin_metrics_page(request: Request, admin=Depends(auth_service.require_admin)):
    return templates.TemplateResponse(
        request=request,
        name="admin_metrics.html",
        context={
            "request": request,
            "summary": db_service.performance_summary(),
            "performance_logs": db_service.list_performance_logs(200),
            "usage_events": db_service.list_usage_events(200),
            "ai_rename_logs": db_service.list_ai_rename_logs(200),
        },
    )


@router.get("/admin/metrics/export/{table}.csv")
async def export_metrics_csv(table: str, admin=Depends(auth_service.require_admin)):
    if table not in db_service.ALL_TABLES:
        raise HTTPException(status_code=404, detail="Bilinmeyen tablo.")

    rows = db_service.export_table_rows(table)
    buf = io.StringIO()
    if rows:
        writer = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{table}.csv"'},
    )
