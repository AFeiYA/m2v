"""
Cast Studio Storage & Persistence Service
-----------------------------------------
Manages local character folders, reference image uploads, version locking,
and song project binding with multi-tenant ownership and public/private visibility.
"""
from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import secrets

from src.cast_schema import (
    CharacterProfile,
    CharacterIdentity,
    CharacterFaceInvariants,
    VisualHair,
    VisualEyes,
    CharacterOutfit,
    CharacterColorPalette,
    ExpressionSheet,
    VocalProfile,
    PerformanceContext,
    PromptEngine,
    CharacterAssets,
    CharacterVersioning,
)

ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_CHARACTERS_DIR = ROOT_DIR / "work" / "characters"


def get_characters_dir(custom_dir: Path | str | None = None) -> Path:
    p = Path(custom_dir) if custom_dir else DEFAULT_CHARACTERS_DIR
    p.mkdir(parents=True, exist_ok=True)
    return p


def seed_system_characters(storage_dir: Path | str | None = None) -> None:
    """Seeds canonical official benchmark characters (Zero.SOE) if not present."""
    base = get_characters_dir(storage_dir)
    from src.cast_prompts import get_reference_golden_ratio_character
    canonical = get_reference_golden_ratio_character()
    char_folder = base / canonical.id
    profile_file = char_folder / "profile.json"
    if not profile_file.is_file():
        char_folder.mkdir(parents=True, exist_ok=True)
        (char_folder / "images").mkdir(parents=True, exist_ok=True)
        canonical.save_file(profile_file)


def verify_character_ownership(profile: CharacterProfile, current_user_id: str | None) -> None:
    """Ensures current caller has permission to modify or delete this character."""
    if current_user_id is None:
        return
    if profile.user_id == "system":
        raise PermissionError("Official system character is read-only and cannot be modified or deleted")
    if profile.user_id != current_user_id and profile.user_id != "default_local":
        raise PermissionError("Permission denied: You do not have ownership of this character")


def list_characters(
    storage_dir: Path | str | None = None,
    current_user_id: str | None = None,
) -> list[dict[str, Any]]:
    """
    Lists stored characters visible to current_user_id:
    - User's own characters (user_id == current_user_id or 'default_local')
    - Public / official characters (visibility == 'public' or user_id == 'system')
    """
    seed_system_characters(storage_dir)
    base = get_characters_dir(storage_dir)
    results: list[dict[str, Any]] = []

    for char_folder in sorted(base.iterdir()):
        if not char_folder.is_dir():
            continue
        profile_file = char_folder / "profile.json"
        if not profile_file.is_file():
            continue
        try:
            profile = CharacterProfile.load_file(profile_file)
            is_owner = (
                current_user_id is None
                or profile.user_id == current_user_id
                or profile.user_id == "default_local"
            )
            is_visible = profile.visibility == "public" or is_owner
            if not is_visible:
                continue

            results.append({
                "id": profile.id,
                "user_id": profile.user_id,
                "visibility": profile.visibility,
                "is_official": profile.is_official,
                "is_owner": is_owner and profile.user_id != "system",
                "name": profile.identity.name,
                "alias": profile.identity.alias,
                "age": profile.identity.age,
                "gender": profile.identity.gender,
                "tagline": profile.identity.tagline,
                "primary_image_url": profile.assets.primary_image_url,
                "thumbnail_url": profile.assets.thumbnail_url or profile.assets.primary_image_url,
                "version": profile.versioning.version,
                "is_locked": profile.versioning.is_locked,
                "bound_songs_count": len(profile.bound_songs),
                "created_at": profile.created_at,
            })
        except Exception:
            continue

    return results


def get_character(
    char_id: str,
    storage_dir: Path | str | None = None,
    current_user_id: str | None = None,
) -> CharacterProfile | None:
    """Loads a character by ID if visible to current user."""
    seed_system_characters(storage_dir)
    base = get_characters_dir(storage_dir)
    profile_file = base / char_id / "profile.json"
    if not profile_file.is_file():
        return None
    profile = CharacterProfile.load_file(profile_file)

    is_owner = (
        current_user_id is None
        or profile.user_id == current_user_id
        or profile.user_id == "default_local"
    )
    if profile.visibility == "private" and not is_owner:
        return None
    return profile


def create_character(
    name: str,
    alias: str = "",
    age: int = 16,
    gender: str = "neutral",
    tagline: str = "",
    archetype: str = "Original Artist",
    user_id: str = "default_local",
    visibility: str = "private",
    storage_dir: Path | str | None = None,
) -> CharacterProfile:
    """Creates a new minimal character profile ready for reference image upload."""
    base = get_characters_dir(storage_dir)
    char_id = f"char_{secrets.token_hex(6)}"
    char_folder = base / char_id
    char_folder.mkdir(parents=True, exist_ok=True)
    (char_folder / "images").mkdir(parents=True, exist_ok=True)

    profile = CharacterProfile(
        id=char_id,
        user_id=user_id,
        visibility=visibility,
        identity=CharacterIdentity(
            name=name.strip(),
            alias=alias.strip() or name.strip(),
            age=age,
            age_locked=True,
            gender=gender,
            tagline=tagline.strip() or "Independent Virtual Artist",
            archetype=archetype,
            core_contradiction="A passionate performer pursuing authenticity amidst digital precision",
            personality_traits=["Creative", "Authentic", "Perceptive"]
        ),
        face_invariants=CharacterFaceInvariants(
            silhouette="Natural silhouette",
            hair=VisualHair(style="Medium cut", color="Natural", highlights="", texture="Standard"),
            eyes=VisualEyes(shape="Expressive", iris_color="Deep hazel", pupil_feature="", gaze_expression="Direct"),
            facial_marks=[]
        ),
        active_outfit_id="outfit_default",
        outfits=[
            CharacterOutfit(
                id="outfit_default",
                name="Default Attire",
                genre_style="Contemporary Studio Wear",
                signature_outerwear="Light jacket",
                innerwear="Cotton tee",
                accessories=[],
                materials=["Cotton", "Denim"],
                color_palette=CharacterColorPalette(
                    dominant_hex="#1E2024",
                    dominant_name="Charcoal",
                    secondary_hex="#8A92A0",
                    secondary_name="Silver Gray",
                    accent_hex="#3B82F6",
                    accent_name="Electric Blue"
                ),
                signature_prop=""
            )
        ],
        expression_sheet=ExpressionSheet(
            neutral="Calm, focused expression",
            performance_focus="Energetic, impassioned singing",
            vulnerable_climax="Subtle emotional resonance",
            smug_ironic="Playful smirk"
        ),
        vocal_profile=VocalProfile(
            timbre_description="Balanced clear vocal",
            pitch_range="Mid range",
            delivery_style="Natural melodic flow",
            signature_audio_tag=""
        ),
        performance_context=PerformanceContext(
            primary_environment="Modern minimalist soundstage",
            lighting_atmosphere="Soft cinematic key light with cool rim light",
            camera_feel="Dynamic 16:9 and 9:16 portrait framing"
        ),
        prompt_engine=PromptEngine(
            positive_character_anchor=f"masterpiece, best quality, 1person, {gender}, {age} years old, {name}, expressive eyes",
            negative_prompt_anchor="worst quality, low quality, deformed, blurry, bad anatomy, bad hands",
            recommended_aspect_ratios=["9:16", "16:9", "1:1"]
        ),
        assets=CharacterAssets(),
        versioning=CharacterVersioning(version=1, is_locked=False),
        bound_songs=[]
    )

    profile.save_file(char_folder / "profile.json")
    return profile


def save_character(
    profile: CharacterProfile,
    current_user_id: str | None = None,
    storage_dir: Path | str | None = None,
) -> CharacterProfile:
    """Persists updates to an existing character profile with ownership check."""
    base = get_characters_dir(storage_dir)
    char_folder = base / profile.id
    profile_file = char_folder / "profile.json"
    if profile_file.is_file():
        existing = CharacterProfile.load_file(profile_file)
        verify_character_ownership(existing, current_user_id)

    char_folder.mkdir(parents=True, exist_ok=True)
    profile.save_file(profile_file)
    return profile


def upload_reference_image(
    char_id: str,
    image_bytes: bytes,
    filename: str,
    is_primary: bool = True,
    current_user_id: str | None = None,
    storage_dir: Path | str | None = None,
) -> tuple[CharacterProfile, str]:
    """
    Saves an uploaded reference image to the character's images directory,
    ensuring caller is owner before modifying.
    """
    base = get_characters_dir(storage_dir)
    char_folder = base / char_id
    profile_file = char_folder / "profile.json"
    if not profile_file.is_file():
        raise FileNotFoundError(f"Character {char_id} not found")

    profile = CharacterProfile.load_file(profile_file)
    verify_character_ownership(profile, current_user_id)

    images_dir = char_folder / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    # Sanitize extension
    suffix = Path(filename).suffix.lower()
    if suffix not in (".png", ".jpg", ".jpeg", ".webp"):
        suffix = ".png"
    safe_name = f"ref_{secrets.token_hex(4)}{suffix}"
    dest_path = images_dir / safe_name
    dest_path.write_bytes(image_bytes)

    # Relative asset path served via API
    rel_url = f"/api/characters/{char_id}/assets/{safe_name}"

    if is_primary or not profile.assets.primary_image_url:
        profile.assets.primary_image_url = rel_url
        profile.assets.thumbnail_url = rel_url
    else:
        profile.assets.secondary_images.append(rel_url)

    profile.save_file(profile_file)
    return profile, rel_url


def confirm_character_version(
    char_id: str,
    current_user_id: str | None = None,
    storage_dir: Path | str | None = None,
) -> CharacterProfile:
    """
    Locks the character baseline version (e.g. v1) so it cannot be accidentally
    overwritten or drift during future prompt executions.
    """
    base = get_characters_dir(storage_dir)
    char_folder = base / char_id
    profile_file = char_folder / "profile.json"
    if not profile_file.is_file():
        raise FileNotFoundError(f"Character {char_id} not found")

    profile = CharacterProfile.load_file(profile_file)
    verify_character_ownership(profile, current_user_id)

    if profile.versioning.is_locked:
        # Increment to next version if re-confirming an already locked version
        profile.versioning.version += 1

    profile.versioning.is_locked = True
    profile.versioning.confirmed_at = datetime.now(timezone.utc).isoformat()
    profile.save_file(profile_file)
    return profile


def bind_character_to_song(
    char_id: str,
    song_folder_name: str,
    scan_dir: Path | str | None = None,
    current_user_id: str | None = None,
    storage_dir: Path | str | None = None,
) -> CharacterProfile:
    """
    Binds a character to a song project, persisting character_id into
    the song's alignment/project JSON. Users can bind their own characters
    or official public characters to their songs.
    """
    base = get_characters_dir(storage_dir)
    profile_file = base / char_id / "profile.json"
    if not profile_file.is_file():
        raise FileNotFoundError(f"Character {char_id} not found")

    profile = CharacterProfile.load_file(profile_file)

    # Verify visibility: user can bind own character or public character
    is_owner = (
        current_user_id is None
        or profile.user_id == current_user_id
        or profile.user_id == "default_local"
    )
    if profile.visibility == "private" and not is_owner:
        raise PermissionError("Cannot bind a private character you do not own")

    # Update song JSON if scan_dir is present
    if scan_dir:
        resolved_scan_dir = scan_dir() if callable(scan_dir) else scan_dir
        s_dir = Path(resolved_scan_dir) / song_folder_name
        if s_dir.is_dir():
            for jf in s_dir.glob("*_alignment.json"):
                try:
                    data = json.loads(jf.read_text(encoding="utf-8"))
                    data["character_id"] = profile.id
                    data["character_version"] = profile.versioning.version
                    jf.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
                except Exception:
                    pass

    # Record on character profile only if user owns it (system profile is not mutated per song)
    if profile.user_id != "system":
        if song_folder_name not in profile.bound_songs:
            profile.bound_songs.append(song_folder_name)
            profile.save_file(profile_file)

    return profile


def unbind_character_from_song(
    char_id: str,
    song_folder_name: str,
    scan_dir: Path | str | None = None,
    current_user_id: str | None = None,
    storage_dir: Path | str | None = None,
) -> CharacterProfile:
    """Unbinds character from song project."""
    base = get_characters_dir(storage_dir)
    profile_file = base / char_id / "profile.json"
    if not profile_file.is_file():
        raise FileNotFoundError(f"Character {char_id} not found")

    profile = CharacterProfile.load_file(profile_file)

    if scan_dir:
        resolved_scan_dir = scan_dir() if callable(scan_dir) else scan_dir
        s_dir = Path(resolved_scan_dir) / song_folder_name
        if s_dir.is_dir():
            for jf in s_dir.glob("*_alignment.json"):
                try:
                    data = json.loads(jf.read_text(encoding="utf-8"))
                    if data.get("character_id") == char_id:
                        data.pop("character_id", None)
                        data.pop("character_version", None)
                        jf.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
                except Exception:
                    pass

    if profile.user_id != "system":
        if song_folder_name in profile.bound_songs:
            profile.bound_songs.remove(song_folder_name)
            profile.save_file(profile_file)

    return profile


def delete_character(
    char_id: str,
    current_user_id: str | None = None,
    storage_dir: Path | str | None = None,
) -> bool:
    """Permanently deletes a character folder after verifying caller ownership."""
    base = get_characters_dir(storage_dir)
    char_folder = base / char_id
    profile_file = char_folder / "profile.json"
    if not profile_file.is_file():
        return False

    profile = CharacterProfile.load_file(profile_file)
    verify_character_ownership(profile, current_user_id)

    if char_folder.is_dir():
        shutil.rmtree(char_folder, ignore_errors=True)
        return True
    return False
