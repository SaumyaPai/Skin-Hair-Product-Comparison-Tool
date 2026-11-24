from fastapi import APIRouter, Depends, Request

from app import db
from app.deps import Services, get_services
from app.models import CompareRequest
from app.services import compare as compare_service

router = APIRouter(prefix="/v1")


@router.post("/compare")
def compare(req: CompareRequest, request: Request, services: Services = Depends(get_services)):
    request.state.log_extra = {"product_type": req.product_type, "n_products": len(req.products)}
    conn = db.connect()
    try:
        result = compare_service.run(req, conn, services)
    finally:
        conn.close()
    request.state.log_extra.update(n_unresolved=len(result["unresolved"]), summary_source=result["summary_source"])
    result["request_id"] = request.state.request_id
    return result
