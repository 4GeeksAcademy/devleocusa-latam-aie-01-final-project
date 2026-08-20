"""Profile endpoints for authenticated users."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from src.cache import me_cache, profile_cache
from src.models.profile import Profile, ProfileResponse
from src.models.user import User
from src.services.auth_service import get_current_user
from src.services.profile_service import create_profile_for_user, get_profile_by_user_id, update_profile

profiles_router = APIRouter(prefix="/profiles", tags=["profiles"])


class ProfileUpdateRequest(BaseModel):
    name: str | None = None
    phone: str | None = None
    address: str | None = None


def _to_profile_response(profile: Profile) -> ProfileResponse:
    return ProfileResponse(
        name=profile.name,
        phone=profile.phone,
        address=profile.address,
    )


@profiles_router.get("/me", response_model=ProfileResponse)
def get_my_profile(current_user: User = Depends(get_current_user)) -> ProfileResponse:
    # Per-user cache key — no data leak between users
    cache_key = str(current_user.id)
    cached = profile_cache.get(cache_key)
    if cached is not None:
        return cached  # type: ignore[return-value]

    profile = get_profile_by_user_id(current_user.id)
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Profile not found",
        )
    result = _to_profile_response(profile)
    profile_cache.set(cache_key, result)
    return result


@profiles_router.put("/me", response_model=ProfileResponse)
def update_my_profile(
    payload: ProfileUpdateRequest,
    current_user: User = Depends(get_current_user),
) -> ProfileResponse:
    updates = payload.model_dump(exclude_none=True)
    profile = update_profile(current_user.id, updates)
    if profile is None:
        profile = create_profile_for_user(
            user_id=current_user.id,
            name=str(updates.get("name", "")),
            phone=str(updates.get("phone", "")),
            address=str(updates.get("address", "")),
        )

    # Invalidate /auth/me and /profiles/me caches — profile data changed for this user
    me_cache.invalidate(str(current_user.id))
    profile_cache.invalidate(str(current_user.id))

    return _to_profile_response(profile)
