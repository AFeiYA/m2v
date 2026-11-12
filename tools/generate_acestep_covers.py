#!/usr/bin/env python3
"""
Generate ACE-Step covers for Jingle Bells via local ComfyUI (127.0.0.1:8188).
Covers:
1. Rock Cover: Energetic modern holiday rock, electric guitars, punchy drums.
2. Female Cover: Sweet, clear modern Christmas pop female vocals, acoustic guitars, crisp sleigh bells.
"""

import copy
import json
import random
import sys
import time
import uuid
from pathlib import Path
import requests

COMFYUI_URL = "http://127.0.0.1:8188"
WORKFLOW_TEMPLATE = Path("/Users/luca/OpenMontage/tools/_comfyui/workflows/ace-step-1-t2a.json")
DOWNLOADS_DIR = Path("/Users/luca/Downloads")
PROJECTS_DIR = Path("/Users/luca/suno2MV/projects/christmas_album/02_Jingle_Bells")

# Clean lyrics extracted from Jingle Bells_reference.lrc
LYRICS = """[verse]
Dashing through the snow
In a one-horse open sleigh
O'er the fields we go
Laughing all the way
Bells on bobtails ring
Making spirits bright
What fun it is to ride and sing
A sleighing song tonight!

[chorus]
Jingle bells, jingle bells,
Jingle all the way!
O what fun it is to ride
In a one-horse open sleigh, hey!
Jingle bells, jingle bells,
Jingle all the way!
O what fun it is to ride
In a one-horse open sleigh!"""

CONFIGS = [
    {
        "id": "rock",
        "name": "Jingle_Bells_Cover_Rock",
        "tags": "modern holiday punk rock, energetic driving rock, electric guitars, punchy live drums, powerful driving bassline, male rock vocals, dynamic Christmas anthem, high energy tempo, crisp sleigh bells, 2026 studio mastering, high fidelity",
        "seed": 42,
        "seconds": 60,
    },
    {
        "id": "female",
        "name": "Jingle_Bells_Cover_Female",
        "tags": "modern Christmas pop, sweet clear female vocals, acoustic guitars, warm piano, soft synth pads, crisp festive sleigh bells, gentle holiday groove, uplifting cheerful, sparkling stereo production, 2026 studio mastering, high fidelity",
        "seed": 108,
        "seconds": 60,
    },
]

def check_server():
    try:
        r = requests.get(f"{COMFYUI_URL}/system_stats", timeout=5)
        r.raise_for_status()
        print(f"Connected to ComfyUI at {COMFYUI_URL}")
        return True
    except Exception as e:
        print(f"Failed to connect to ComfyUI: {e}", file=sys.stderr)
        return False

def generate_cover(cfg: dict, base_wf: dict):
    name = cfg["name"]
    tags = cfg["tags"]
    seed = cfg["seed"]
    seconds = cfg["seconds"]
    
    print(f"\n=======================================================")
    print(f"  Starting Generation: {name}")
    print(f"  Style Tags: {tags}")
    print(f"  Duration: {seconds}s | Seed: {seed}")
    print(f"=======================================================")

    wf = copy.deepcopy(base_wf)
    
    # 1. Checkpoint Loader
    wf["1"]["inputs"]["ckpt_name"] = "ace_step_v1_3.5b.safetensors"
    # 2. TextEncodeAceStepAudio
    wf["2"]["inputs"]["tags"] = tags
    wf["2"]["inputs"]["lyrics"] = LYRICS
    wf["2"]["inputs"]["lyrics_strength"] = 0.99
    # 4. EmptyAceStepLatentAudio
    wf["4"]["inputs"]["seconds"] = seconds
    # 8. KSampler
    wf["8"]["inputs"]["seed"] = seed
    wf["8"]["inputs"]["steps"] = 50
    wf["8"]["inputs"]["cfg"] = 5.0
    # 10. SaveAudioMP3
    wf["10"]["inputs"]["filename_prefix"] = name

    client_id = str(uuid.uuid4())
    resp = requests.post(
        f"{COMFYUI_URL}/prompt",
        json={"prompt": wf, "client_id": client_id},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    if "error" in data:
        raise RuntimeError(f"ComfyUI prompt error: {data['error']}")
    prompt_id = data["prompt_id"]
    print(f"Prompt queued successfully: prompt_id = {prompt_id}")

    # Polling history
    print("Waiting for generation to complete (approx 60~80s on Apple Silicon)...")
    start_t = time.time()
    while True:
        elapsed = int(time.time() - start_t)
        sys.stdout.write(f"\r  Elapsed: {elapsed}s...")
        sys.stdout.flush()
        
        try:
            h_resp = requests.get(f"{COMFYUI_URL}/history/{prompt_id}", timeout=10)
            if h_resp.status_code == 200:
                h_data = h_resp.json()
                if prompt_id in h_data:
                    print(f"\nGeneration completed in {elapsed}s!")
                    entry = h_data[prompt_id]
                    outputs = entry.get("outputs", {})
                    node10 = outputs.get("10", {})
                    items = node10.get("audio", []) or node10.get("images", [])
                    if not items:
                        raise RuntimeError(f"No audio output found in node 10: {outputs}")
                    item = items[0]
                    filename = item["filename"]
                    subfolder = item.get("subfolder", "")
                    folder_type = item.get("type", "output")
                    
                    # Download
                    down_resp = requests.get(
                        f"{COMFYUI_URL}/view",
                        params={"filename": filename, "subfolder": subfolder, "type": folder_type},
                        timeout=60,
                    )
                    down_resp.raise_for_status()
                    
                    # Save to Downloads & Projects
                    dl_dest = DOWNLOADS_DIR / f"{name}.mp3"
                    dl_dest.write_bytes(down_resp.content)
                    print(f"Saved to Downloads: {dl_dest} ({len(down_resp.content) / 1024 / 1024:.2f} MB)")
                    
                    proj_dest = PROJECTS_DIR / f"{name}.mp3"
                    proj_dest.write_bytes(down_resp.content)
                    print(f"Saved to Project:   {proj_dest}")
                    return dl_dest
        except Exception as poll_err:
            if "prompt_id" in str(poll_err):
                pass
        
        if elapsed > 600:
            raise TimeoutError("Timed out waiting for ComfyUI generation.")
        time.sleep(5)

def main():
    if not check_server():
        sys.exit(1)
    
    with open(WORKFLOW_TEMPLATE, "r", encoding="utf-8") as f:
        base_wf = json.load(f)
    
    for cfg in CONFIGS:
        generate_cover(cfg, base_wf)
    
    print("\nAll ACE-Step covers generated successfully!")

if __name__ == "__main__":
    main()
