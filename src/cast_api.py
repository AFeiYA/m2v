"""
Cast Studio FastAPI Router
--------------------------
HTTP Endpoints for Character CRUD, Reference Image Uploads, Version Confirmation,
and Song Project Bindings with multi-tenant ownership & visibility validation.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Literal
from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from src.cast_schema import CharacterProfile
from src.cast_storage import (
    create_character,
    list_characters,
    get_character,
    save_character,
    upload_reference_image,
    confirm_character_version,
    bind_character_to_song,
    unbind_character_from_song,
    delete_character,
    verify_character_ownership,
    get_characters_dir,
)

router = APIRouter(prefix="/api/characters", tags=["cast"])


async def get_cast_user_id(request: Request) -> str:
    """
    Extracts current user identifier:
    - If Bearer token is provided: decodes and verifies via auth module. If token is invalid/expired -> raises 401.
    - If no token is provided:
        - If app is in explicit local mode (request.app.state.is_local_mode == True): defaults to 'default_local'.
        - If app is in cloud/SaaS mode: raises 401 Unauthorized.
    """
    token = None
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header.split(" ", 1)[1].strip()
    if not token:
        token = request.query_params.get("token")

    if token:
        try:
            from src.auth import decode_token
            payload = decode_token(token)
            if payload and ("sub" in payload or "uid" in payload or "user_id" in payload):
                return str(payload.get("sub") or payload.get("uid") or payload.get("user_id"))
            raise HTTPException(status_code=401, detail="Invalid token payload")
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(status_code=401, detail="Invalid or expired token")

    # No token provided
    is_local_mode = getattr(request.app.state, "is_local_mode", False)
    if is_local_mode:
        return getattr(request.app.state, "default_user_id", "default_local")

    # Cloud mode requires authentication; never fallback to shared default_local
    raise HTTPException(status_code=401, detail="Authentication credentials required")


class CreateCharacterRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    alias: str = Field(default="", max_length=128)
    age: int = Field(default=16, ge=1, le=1000)
    gender: str = Field(default="neutral")
    tagline: str = Field(default="", max_length=256)
    visibility: Literal["private", "public"] = Field(default="private")


class SongBindingRequest(BaseModel):
    song_id: str = Field(..., min_length=1)


class UpdateVisibilityRequest(BaseModel):
    visibility: Literal["private", "public"]


async def sync_profile_to_db(profile: CharacterProfile) -> None:
    """Persists character profile to database for cloud resilience."""
    try:
        from src.database import async_session
        from src.models import CharacterEntity
        from sqlalchemy import select

        async with async_session() as session:
            stmt = select(CharacterEntity).where(CharacterEntity.id == profile.id)
            res = await session.execute(stmt)
            entity = res.scalars().first()
            if not entity:
                entity = CharacterEntity(
                    id=profile.id,
                    user_id=profile.user_id,
                    name=profile.identity.name,
                    alias=profile.identity.alias,
                    age=profile.identity.age,
                    gender=profile.identity.gender,
                    tagline=profile.identity.tagline,
                    visibility=profile.visibility,
                    primary_image_key=profile.assets.primary_image_url,
                    profile_json=profile.model_dump_json(),
                )
                session.add(entity)
            else:
                entity.name = profile.identity.name
                entity.alias = profile.identity.alias
                entity.age = profile.identity.age
                entity.gender = profile.identity.gender
                entity.tagline = profile.identity.tagline
                entity.visibility = profile.visibility
                entity.primary_image_key = profile.assets.primary_image_url
                entity.profile_json = profile.model_dump_json()
            await session.commit()
    except Exception:
        pass


async def delete_profile_from_db(char_id: str) -> None:
    """Removes character profile from database."""
    try:
        from src.database import async_session
        from src.models import CharacterEntity
        from sqlalchemy import delete

        async with async_session() as session:
            await session.execute(delete(CharacterEntity).where(CharacterEntity.id == char_id))
            await session.commit()
    except Exception:
        pass


async def restore_character_from_db(char_id: str, storage_dir: Path | str | None = None) -> CharacterProfile | None:
    """Restores character profile from database if missing locally."""
    try:
        from src.database import async_session
        from src.models import CharacterEntity
        from sqlalchemy import select

        async with async_session() as session:
            stmt = select(CharacterEntity).where(CharacterEntity.id == char_id)
            res = await session.execute(stmt)
            entity = res.scalars().first()
            if entity and entity.profile_json:
                data = json.loads(entity.profile_json)
                profile = CharacterProfile.model_validate(data)
                base = get_characters_dir(storage_dir)
                char_dir = base / char_id
                char_dir.mkdir(parents=True, exist_ok=True)
                profile.save_file(char_dir / "profile.json")
                return profile
    except Exception:
        pass
    return None


@router.get("")
async def api_list_characters(request: Request):
    """Lists summary cards for all characters visible to current caller."""
    storage_dir = getattr(request.app.state, "characters_dir", None)
    user_id = await get_cast_user_id(request)
    # Cloud DB hydration if container scratch disk is clean
    try:
        from src.database import async_session
        from src.models import CharacterEntity
        from sqlalchemy import select
        async with async_session() as session:
            stmt = select(CharacterEntity)
            res = await session.execute(stmt)
            for entity in res.scalars().all():
                base = get_characters_dir(storage_dir)
                p_file = base / entity.id / "profile.json"
                if not p_file.is_file() and entity.profile_json:
                    p_file.parent.mkdir(parents=True, exist_ok=True)
                    p_file.write_text(entity.profile_json, encoding="utf-8")
    except Exception:
        pass
    return {"characters": list_characters(storage_dir, current_user_id=user_id)}


@router.post("")
async def api_create_character(req: CreateCharacterRequest, request: Request):
    """Creates a new character owned by current user."""
    storage_dir = getattr(request.app.state, "characters_dir", None)
    user_id = await get_cast_user_id(request)
    profile = create_character(
        name=req.name,
        alias=req.alias,
        age=req.age,
        gender=req.gender,
        tagline=req.tagline,
        user_id=user_id,
        visibility=req.visibility,
        storage_dir=storage_dir,
    )
    await sync_profile_to_db(profile)
    return profile.model_dump()


@router.get("/{char_id}")
async def api_get_character(char_id: str, request: Request):
    """Gets complete character profile if caller has permission."""
    storage_dir = getattr(request.app.state, "characters_dir", None)
    user_id = await get_cast_user_id(request)
    profile = get_character(char_id, storage_dir, current_user_id=user_id)
    if not profile:
        profile = await restore_character_from_db(char_id, storage_dir)
    if not profile:
        raise HTTPException(status_code=404, detail="Character not found")
    return profile.model_dump()


@router.put("/{char_id}")
async def api_update_character(char_id: str, data: dict[str, Any], request: Request):
    """Updates character profile (including age, identity, etc.) with ownership validation."""
    storage_dir = getattr(request.app.state, "characters_dir", None)
    user_id = await get_cast_user_id(request)
    existing = get_character(char_id, storage_dir, current_user_id=None)
    if not existing:
        existing = await restore_character_from_db(char_id, storage_dir)
    if not existing:
        raise HTTPException(status_code=404, detail="Character not found")

    try:
        verify_character_ownership(existing, current_user_id=user_id)

        # Support flexible partial or full updates
        if "identity" in data and isinstance(data["identity"], dict):
            ident = data["identity"]
            if "name" in ident and ident["name"]:
                existing.identity.name = str(ident["name"]).strip()
            if "alias" in ident:
                existing.identity.alias = str(ident["alias"]).strip()
            if "age" in ident and ident["age"] is not None:
                existing.identity.age = int(ident["age"])
            if "gender" in ident and ident["gender"]:
                existing.identity.gender = str(ident["gender"])
            if "tagline" in ident:
                existing.identity.tagline = str(ident["tagline"]).strip()
        else:
            if "name" in data and data["name"]:
                existing.identity.name = str(data["name"]).strip()
            if "alias" in data:
                existing.identity.alias = str(data["alias"]).strip()
            if "age" in data and data["age"] is not None:
                existing.identity.age = int(data["age"])
            if "gender" in data and data["gender"]:
                existing.identity.gender = str(data["gender"])
            if "tagline" in data:
                existing.identity.tagline = str(data["tagline"]).strip()

        if "visibility" in data and data["visibility"] in ("private", "public"):
            existing.visibility = data["visibility"]

        if "prompt_engine" in data and isinstance(data["prompt_engine"], dict):
            pe = data["prompt_engine"]
            if "positive_character_anchor" in pe:
                existing.prompt_engine.positive_character_anchor = str(pe["positive_character_anchor"])
            if "negative_prompt_anchor" in pe:
                existing.prompt_engine.negative_prompt_anchor = str(pe["negative_prompt_anchor"])

        save_character(existing, current_user_id=user_id, storage_dir=storage_dir)
        await sync_profile_to_db(existing)
        return existing.model_dump()
    except PermissionError as pe:
        raise HTTPException(status_code=403, detail=str(pe))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid profile update: {e}")


@router.post("/{char_id}/upload-reference")
async def api_upload_reference_image(
    char_id: str,
    request: Request,
    file: UploadFile = File(...),
):
    """Uploads a reference portrait/image to the character's asset library with Pillow validation."""
    storage_dir = getattr(request.app.state, "characters_dir", None)
    user_id = await get_cast_user_id(request)
    contents = await file.read()
    if len(contents) == 0:
        raise HTTPException(status_code=400, detail="Empty image file")
    if len(contents) > 20 * 1024 * 1024:  # 20MB limit
        raise HTTPException(status_code=400, detail="Image exceeds 20MB limit")

    try:
        profile, rel_url = upload_reference_image(
            char_id=char_id,
            image_bytes=contents,
            filename=file.filename or "reference.png",
            is_primary=True,
            current_user_id=user_id,
            storage_dir=storage_dir,
        )
        try:
            from src.storage import get_storage
            storage = get_storage()
            obj_key = f"characters/{char_id}/images/{Path(rel_url).name}"
            local_path = get_characters_dir(storage_dir) / char_id / "images" / Path(rel_url).name
            if local_path.is_file():
                await storage.save(obj_key, local_path)
        except Exception:
            pass
        await sync_profile_to_db(profile)
        return {"status": "ok", "image_url": rel_url, "character": profile.model_dump()}
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except PermissionError as pe:
        raise HTTPException(status_code=403, detail=str(pe))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Character not found")


@router.get("/{char_id}/assets/{filename}")
async def api_get_character_asset(char_id: str, filename: str, request: Request):
    """
    Serves uploaded reference images with private asset authorization:
    - If character is private: caller must be authenticated and own the character.
    - If character is public: accessible publicly.
    """
    storage_dir = getattr(request.app.state, "characters_dir", None)
    base = get_characters_dir(storage_dir)
    profile_file = base / char_id / "profile.json"
    if not profile_file.is_file():
        # Try database recovery
        await restore_character_from_db(char_id, storage_dir)
    if not profile_file.is_file():
        raise HTTPException(status_code=404, detail="Character not found")

    profile = CharacterProfile.load_file(profile_file)
    if profile.visibility == "private":
        try:
            caller_id = await get_cast_user_id(request)
        except HTTPException:
            raise HTTPException(status_code=403, detail="Forbidden: Private asset")

        is_owner = (
            profile.user_id == caller_id
            or (caller_id == "default_local" and profile.user_id == "default_local")
        )
        if not is_owner:
            raise HTTPException(status_code=403, detail="Forbidden: Private asset")

    file_path = base / char_id / "images" / filename
    if not file_path.is_file():
        # Cloud object storage asset recovery if local scratch was wiped
        try:
            from src.storage import get_storage
            storage = get_storage()
            obj_key = f"characters/{char_id}/images/{filename}"
            if await storage.exists(obj_key):
                file_path.parent.mkdir(parents=True, exist_ok=True)
                await storage.load(obj_key, file_path)
        except Exception:
            pass

    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="Asset not found")
    return FileResponse(file_path)


@router.post("/{char_id}/confirm-version")
async def api_confirm_version(char_id: str, request: Request):
    """Deprecated: keeps character profile updated without strict version freezing."""
    storage_dir = getattr(request.app.state, "characters_dir", None)
    user_id = await get_cast_user_id(request)
    try:
        profile = confirm_character_version(char_id, current_user_id=user_id, storage_dir=storage_dir)
        await sync_profile_to_db(profile)
        return {"status": "ok", "character": profile.model_dump()}
    except PermissionError as pe:
        raise HTTPException(status_code=403, detail=str(pe))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Character not found")


@router.post("/{char_id}/bind-song")
async def api_bind_song(char_id: str, req: SongBindingRequest, request: Request):
    """Binds character to a song project, validating song presence and cleaning up old bindings."""
    storage_dir = getattr(request.app.state, "characters_dir", None)
    scan_dir = getattr(request.app.state, "scan_dir", None)
    user_id = await get_cast_user_id(request)
    try:
        profile = bind_character_to_song(
            char_id=char_id,
            song_folder_name=req.song_id,
            scan_dir=scan_dir,
            current_user_id=user_id,
            storage_dir=storage_dir,
        )
        await sync_profile_to_db(profile)
        return {"status": "ok", "bound_songs": profile.bound_songs, "character": profile.model_dump()}
    except PermissionError as pe:
        raise HTTPException(status_code=403, detail=str(pe))
    except FileNotFoundError as fe:
        raise HTTPException(status_code=404, detail=str(fe))


@router.post("/{char_id}/unbind-song")
async def api_unbind_song(char_id: str, req: SongBindingRequest, request: Request):
    """Unbinds character from a song project."""
    storage_dir = getattr(request.app.state, "characters_dir", None)
    scan_dir = getattr(request.app.state, "scan_dir", None)
    user_id = await get_cast_user_id(request)
    try:
        profile = unbind_character_from_song(
            char_id=char_id,
            song_folder_name=req.song_id,
            scan_dir=scan_dir,
            current_user_id=user_id,
            storage_dir=storage_dir,
        )
        await sync_profile_to_db(profile)
        return {"status": "ok", "bound_songs": profile.bound_songs, "character": profile.model_dump()}
    except PermissionError as pe:
        raise HTTPException(status_code=403, detail=str(pe))
    except FileNotFoundError as fe:
        raise HTTPException(status_code=404, detail=str(fe))


@router.post("/{char_id}/visibility")
async def api_update_character_visibility(char_id: str, req: UpdateVisibilityRequest, request: Request):
    """Updates character visibility (private/public) with ownership validation."""
    storage_dir = getattr(request.app.state, "characters_dir", None)
    user_id = await get_cast_user_id(request)
    profile = get_character(char_id, storage_dir, current_user_id=None)
    if not profile:
        profile = await restore_character_from_db(char_id, storage_dir)
    if not profile:
        raise HTTPException(status_code=404, detail="Character not found")
    try:
        verify_character_ownership(profile, current_user_id=user_id)
        profile.visibility = req.visibility
        save_character(profile, current_user_id=user_id, storage_dir=storage_dir)
        await sync_profile_to_db(profile)
        return {"status": "ok", "visibility": profile.visibility, "character": profile.model_dump()}
    except PermissionError as pe:
        raise HTTPException(status_code=403, detail=str(pe))


@router.delete("/{char_id}")
async def api_delete_character(char_id: str, request: Request):
    """Deletes character and cascades unbinding from songs with ownership validation."""
    storage_dir = getattr(request.app.state, "characters_dir", None)
    scan_dir = getattr(request.app.state, "scan_dir", None)
    user_id = await get_cast_user_id(request)
    try:
        deleted = delete_character(char_id, current_user_id=user_id, scan_dir=scan_dir, storage_dir=storage_dir)
        if not deleted:
            raise HTTPException(status_code=404, detail="Character not found")
        await delete_profile_from_db(char_id)
        return {"status": "ok"}
    except PermissionError as pe:
        raise HTTPException(status_code=403, detail=str(pe))
