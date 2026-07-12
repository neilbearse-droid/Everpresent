from typing import Annotated

from fastapi import APIRouter, Depends

from api.auth import AuthedUser, get_current_user

router = APIRouter()


@router.get("/me")
def me(authed: Annotated[AuthedUser, Depends(get_current_user)]) -> dict:
    return {
        "email": authed.user.email,
        "display_name": authed.user.display_name,
        "is_superadmin": authed.user.is_superadmin,
        "org_id": authed.org_id,
    }
