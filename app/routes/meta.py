from fastapi import APIRouter, Depends

from app.deps import Services, get_services

router = APIRouter(prefix="/v1")


@router.get("/meta/options")
def options(services: Services = Depends(get_services)):
    """Product types, and for each the concerns that have rules. The UI builds its dropdowns from this."""
    labels = {c["concern_id"]: c["label"] for c in services.data["concerns"]}
    return {
        "product_types": [
            {"id": t["product_type"], "label": t["label"], "category": t["category"], "application": t["application"],
             "concerns": [{"id": c, "label": labels.get(c, c)} for c in services.dropdown[t["product_type"]]]}
            for t in services.data["product_types"]
        ],
        "profile_options": {
            "skin_type": ["oily", "dry", "combination", "normal", "not sure"],
            "scalp_type": ["oily", "dry", "normal", "not sure"],
            "sensitive": [True, False],
            "avoid_fragrance": [True, False],
        },
    }
