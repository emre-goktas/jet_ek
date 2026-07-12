"""
User profile — onboarding form (name/title/template/il) backing the
per-user template selection that document-builder.js reads via GET /api/me.
"""
import logging

# pyrefly: ignore [missing-import]
from fastapi import APIRouter, Request, Depends, HTTPException
# pyrefly: ignore [missing-import]
from pydantic import BaseModel, field_validator

from backend.services import auth_service, db_service
from backend.templating import templates
from backend.rate_limit import limiter

logger = logging.getLogger(__name__)
router = APIRouter()

TEMPLATE_CHOICES = [
    {"id": "sgk", "label": "SGK Müfettiş Ek Belge Listesi", "needs_il": False},
    # "saglik_bakanligi" (Sağlık Bakanlığı Dizi Pusulası) is deliberately hidden from
    # selection here — not deleted, just no longer offered as a choice. Its
    # templates.json entry, .docx file, and VALID_TEMPLATE_IDS membership are all
    # left intact so it still works for any profile that already has it saved,
    # and so it can be re-added to this list later with no further work.
    {"id": "sgk_denetmen", "label": "SGK Denetmen Ek Belge Listesi", "needs_il": True},
    {"id": "duz_tablo", "label": "Şablonsuz (Düz Tablo)", "needs_il": False},
    {"id": "duz_tablo_excel", "label": "Şablonsuz (Excel)", "needs_il": False},
]

IL_LIST = [
    "Adana", "Adıyaman", "Afyonkarahisar", "Ağrı", "Amasya", "Ankara", "Antalya", "Artvin",
    "Aydın", "Balıkesir", "Bilecik", "Bingöl", "Bitlis", "Bolu", "Burdur", "Bursa",
    "Çanakkale", "Çankırı", "Çorum", "Denizli", "Diyarbakır", "Edirne", "Elazığ", "Erzincan",
    "Erzurum", "Eskişehir", "Gaziantep", "Giresun", "Gümüşhane", "Hakkari", "Hatay", "Isparta",
    "Mersin", "İstanbul", "İzmir", "Kars", "Kastamonu", "Kayseri", "Kırklareli", "Kırşehir",
    "Kocaeli", "Konya", "Kütahya", "Malatya", "Manisa", "Kahramanmaraş", "Mardin", "Muğla",
    "Muş", "Nevşehir", "Niğde", "Ordu", "Rize", "Sakarya", "Samsun", "Siirt",
    "Sinop", "Sivas", "Tekirdağ", "Tokat", "Trabzon", "Tunceli", "Şanlıurfa", "Uşak",
    "Van", "Yozgat", "Zonguldak", "Aksaray", "Bayburt", "Karaman", "Kırıkkale", "Batman",
    "Şırnak", "Bartın", "Ardahan", "Iğdır", "Yalova", "Karabük", "Kilis", "Osmaniye", "Düzce",
]


def get_current_profile(request: Request) -> tuple[dict, dict | None]:
    """Returns (session_user, profile_row_or_None). Requires a valid session —
    only meaningful once auth is enabled, so this dependency should only be
    used on routes that are themselves already behind auth."""
    user = auth_service.get_current_user(request)
    return user, db_service.get_profile(user["email"])


@router.get("/onboarding")
async def onboarding_page(request: Request):
    user = auth_service.get_current_user_optional(request)
    if user is None:
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url="/login")

    profile = db_service.get_profile(user["email"])
    return templates.TemplateResponse(
        request=request,
        name="onboarding.html",
        context={
            "request": request,
            "user": user,
            "profile": profile,
            "template_choices": TEMPLATE_CHOICES,
            "il_list": IL_LIST,
        },
    )


@router.get("/api/me")
async def api_me(current=Depends(get_current_profile)):
    user, profile = current
    return {"email": user["email"], "name": user.get("name"), "profile": profile}


class ProfileRequest(BaseModel):
    name: str
    title: str = ""
    template_id: str
    il: str | None = None

    @field_validator("name")
    @classmethod
    def name_not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("İsim boş olamaz.")
        return v[:150]

    @field_validator("template_id")
    @classmethod
    def template_id_known(cls, v: str) -> str:
        if v not in db_service.VALID_TEMPLATE_IDS:
            raise ValueError(f"Bilinmeyen şablon: {v}")
        return v


@router.post("/api/profile")
@limiter.limit("20/minute")
async def save_profile(req: ProfileRequest, request: Request):
    user = auth_service.get_current_user(request)

    needs_il = next((t["needs_il"] for t in TEMPLATE_CHOICES if t["id"] == req.template_id), False)
    il = (req.il or "").strip() or None
    if needs_il and not il:
        raise HTTPException(status_code=400, detail="Bu şablon için il seçimi zorunludur.")
    if not needs_il:
        il = None

    try:
        profile = db_service.upsert_profile(
            email=user["email"], name=req.name, title=req.title.strip()[:150],
            template_id=req.template_id, il=il,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    db_service.log_event_safe(user["email"], "profile_saved", {"template_id": req.template_id})
    return {"profile": profile}
