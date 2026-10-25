"""
Cast Studio FastAPI Router
--------------------------
HTTP Endpoints for Character CRUD, Reference Image Uploads, Version Confirmation,
and Song Project Bindings.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any
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
    get_characters_dir,
)

router = APIRouter(prefix="/api/characters", tags=["cast"])


class CreateCharacterRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    alias: str = Field(default="", max_length=128)
    age: int = Field(default=16, ge=1, le=1000)
    gender: str = Field(default="neutral")
    tagline: str = Field(default="", max_length=256)


class SongBindingRequest(BaseModel):
    song_id: str = Field(..., min_length=1)


@router.get("")
async def api_list_characters(request: Request):
    """Lists summary cards for all stored characters."""
    storage_dir = getattr(request.app.state, "characters_dir", None)
    return {"characters": list_characters(storage_dir)}


@router.post("")
async def api_create_character(req: CreateCharacterRequest, request: Request):
    """Creates a new character."""
    storage_dir = getattr(request.app.state, "characters_dir", None)
    profile = create_character(
        name=req.name,
        alias=req.alias,
        age=req.age,
        gender=req.gender,
        tagline=req.tagline,
        storage_dir=storage_dir,
    )
    return profile.model_dump()


@router.get("/{char_id}")
async def api_get_character(char_id: str, request: Request):
    """Gets complete character profile."""
    storage_dir = getattr(request.app.state, "characters_dir", None)
    profile = get_character(char_id, storage_dir)
    if not profile:
        raise HTTPException(status_code=404, detail="Character not found")
    return profile.model_dump()


@router.put("/{char_id}")
async def api_update_character(char_id: str, data: dict[str, Any], request: Request):
    """Updates character profile."""
    storage_dir = getattr(request.app.state, "characters_dir", None)
    existing = get_character(char_id, storage_dir)
    if not existing:
        raise HTTPException(status_code=404, detail="Character not found")

    try:
        data["id"] = char_id  # Enforce ID immutable
        profile = CharacterProfile.model_validate(data)
        save_character(profile, storage_dir)
        return profile.model_dump()
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
            storage_dir=storage_dir,
        )
        return {"status": "ok", "image_url": rel_url, "character": profile.model_dump()}
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
    try:
        profile = confirm_character_version(char_id, storage_dir)
        return {"status": "ok", "version": profile.versioning.version, "character": profile.model_dump()}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Character not found")


@router.post("/{char_id}/bind-song")
async def api_bind_song(char_id: str, req: SongBindingRequest, request: Request):
    """Binds character to a song project."""
    storage_dir = getattr(request.app.state, "characters_dir", None)
    scan_dir = getattr(request.app.state, "scan_dir", None)
    try:
        profile = bind_character_to_song(
            char_id=char_id,
            song_folder_name=req.song_id,
            scan_dir=scan_dir,
            storage_dir=storage_dir,
        )
        return {"status": "ok", "bound_songs": profile.bound_songs, "character": profile.model_dump()}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Character not found")


@router.post("/{char_id}/unbind-song")
async def api_unbind_song(char_id: str, req: SongBindingRequest, request: Request):
    """Unbinds character from a song project."""
    storage_dir = getattr(request.app.state, "characters_dir", None)
    scan_dir = getattr(request.app.state, "scan_dir", None)
    try:
        profile = unbind_character_from_song(
            char_id=char_id,
            song_folder_name=req.song_id,
            scan_dir=scan_dir,
            storage_dir=storage_dir,
        )
        return {"status": "ok", "bound_songs": profile.bound_songs, "character": profile.model_dump()}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Character not found")


@router.delete("/{char_id}")
async def api_delete_character(char_id: str, request: Request):
    """Deletes character and all associated assets."""
    storage_dir = getattr(request.app.state, "characters_dir", None)
    deleted = delete_character(char_id, storage_dir)
    if not deleted:
        raise HTTPException(status_code=404, detail="Character not found")
    return {"status": "ok"}
