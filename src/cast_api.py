"""
Cast Studio FastAPI Router
--------------------------
HTTP Endpoints for Character CRUD, Reference Image Uploads, Version Confirmation,
and Song Project Bindings with multi-tenant ownership & visibility validation.
"""
from __future__ import annotations

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
    - If Bearer token is provided, decodes via auth module (supports Firebase and JWT).
    - If running in local standalone mode or unauthenticated, defaults to 'default_local'.
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
            if payload and "sub" in payload:
                return str(payload["sub"])
        except Exception:
            pass

    return getattr(request.app.state, "default_user_id", "default_local")


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


@router.get("")
async def api_list_characters(request: Request):
    """Lists summary cards for all characters visible to current caller."""
    storage_dir = getattr(request.app.state, "characters_dir", None)
    user_id = await get_cast_user_id(request)
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
    return profile.model_dump()


@router.get("/{char_id}")
async def api_get_character(char_id: str, request: Request):
    """Gets complete character profile if caller has permission."""
    storage_dir = getattr(request.app.state, "characters_dir", None)
    user_id = await get_cast_user_id(request)
    profile = get_character(char_id, storage_dir, current_user_id=user_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Character not found")
    return profile.model_dump()


@router.put("/{char_id}")
async def api_update_character(char_id: str, data: dict[str, Any], request: Request):
    """Updates character profile with ownership validation."""
    storage_dir = getattr(request.app.state, "characters_dir", None)
    user_id = await get_cast_user_id(request)
    existing = get_character(char_id, storage_dir, current_user_id=None)
    if not existing:
        raise HTTPException(status_code=404, detail="Character not found")

    try:
        verify_character_ownership(existing, current_user_id=user_id)
        data["id"] = char_id  # Enforce ID immutable
        data["user_id"] = existing.user_id  # Preserve original creator
        profile = CharacterProfile.model_validate(data)
        save_character(profile, current_user_id=user_id, storage_dir=storage_dir)
        return profile.model_dump()
    except PermissionError as pe:
        raise HTTPException(status_code=403, detail=str(pe))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid profile schema: {e}")


@router.post("/{char_id}/upload-reference")
async def api_upload_reference_image(
    char_id: str,
    request: Request,
    file: UploadFile = File(...),
):
    """Uploads a reference portrait/image to the character's asset library."""
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
        return {"status": "ok", "image_url": rel_url, "character": profile.model_dump()}
    except PermissionError as pe:
        raise HTTPException(status_code=403, detail=str(pe))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Character not found")


@router.get("/{char_id}/assets/{filename}")
async def api_get_character_asset(char_id: str, filename: str, request: Request):
    """Serves uploaded reference images."""
    storage_dir = getattr(request.app.state, "characters_dir", None)
    base = get_characters_dir(storage_dir)
    file_path = base / char_id / "images" / filename
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="Asset not found")
    return FileResponse(file_path)


@router.post("/{char_id}/confirm-version")
async def api_confirm_version(char_id: str, request: Request):
    """Locks the active baseline version (v1, v2, etc.)."""
    storage_dir = getattr(request.app.state, "characters_dir", None)
    user_id = await get_cast_user_id(request)
    try:
        profile = confirm_character_version(char_id, current_user_id=user_id, storage_dir=storage_dir)
        return {"status": "ok", "version": profile.versioning.version, "character": profile.model_dump()}
    except PermissionError as pe:
        raise HTTPException(status_code=403, detail=str(pe))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Character not found")


@router.post("/{char_id}/bind-song")
async def api_bind_song(char_id: str, req: SongBindingRequest, request: Request):
    """Binds character to a song project."""
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
        return {"status": "ok", "bound_songs": profile.bound_songs, "character": profile.model_dump()}
    except PermissionError as pe:
        raise HTTPException(status_code=403, detail=str(pe))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Character not found")


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
        return {"status": "ok", "bound_songs": profile.bound_songs, "character": profile.model_dump()}
    except PermissionError as pe:
        raise HTTPException(status_code=403, detail=str(pe))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Character not found")


@router.post("/{char_id}/visibility")
async def api_update_character_visibility(char_id: str, req: UpdateVisibilityRequest, request: Request):
    """Updates character visibility (private/public) with ownership validation."""
    storage_dir = getattr(request.app.state, "characters_dir", None)
    user_id = await get_cast_user_id(request)
    profile = get_character(char_id, storage_dir, current_user_id=None)
    if not profile:
        raise HTTPException(status_code=404, detail="Character not found")
    try:
        verify_character_ownership(profile, current_user_id=user_id)
        profile.visibility = req.visibility
        save_character(profile, current_user_id=user_id, storage_dir=storage_dir)
        return {"status": "ok", "visibility": profile.visibility, "character": profile.model_dump()}
    except PermissionError as pe:
        raise HTTPException(status_code=403, detail=str(pe))


@router.delete("/{char_id}")
async def api_delete_character(char_id: str, request: Request):
    """Deletes character and all associated assets with ownership validation."""
    storage_dir = getattr(request.app.state, "characters_dir", None)
    user_id = await get_cast_user_id(request)
    try:
        deleted = delete_character(char_id, current_user_id=user_id, storage_dir=storage_dir)
        if not deleted:
            raise HTTPException(status_code=404, detail="Character not found")
        return {"status": "ok"}
    except PermissionError as pe:
        raise HTTPException(status_code=403, detail=str(pe))
