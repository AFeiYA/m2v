"""Motion Studio uses the existing song store; Node is only a render worker."""
from __future__ import annotations
import json
import hashlib
from dataclasses import replace
import os
from pathlib import Path
import shutil
import subprocess
import threading
import time
import uuid
from typing import Literal
from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel, Field
from src.motion_director import validate_plan, rule_plan, llm_prompt, director_input, line_prompt_bundle, line_response, cue_signature, source_signature
from src.r2_storage import r2_storage

from src.song_cover import resolve_cover, prepare_cover, cover_path, MAX_BYTES
from src.song_identity import SongIdentity, identity_path, resolve_identity

from src.motion_llm import configuration, generate_json, DirectorAPIError, DirectorQuotaError

ROOT = Path(__file__).resolve().parent.parent

class ProjectRequest(BaseModel):
    project_id: str
    style: str = 'impact'
    line_id: str | None = None
    instruction: str = Field(default='', max_length=2000)

class CoverRequest(ProjectRequest):
    restore: bool = False

class IdentityRequest(BaseModel):
    project_id: str
    identity: SongIdentity

class LineInputRequest(ProjectRequest):
    line_id: str
    instruction: str = Field(default='', max_length=2000)

class LineApplyRequest(LineInputRequest):
    response: dict

class PlanRequest(ProjectRequest):
    plan: dict
    from_llm: bool = True

class RenderRequest(ProjectRequest):
    aspect: Literal['16:9', '9:16'] = '16:9'
    height: Literal[360, 720] = 720
    start: float = Field(default=0, ge=0, allow_inf_nan=False)
    length: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    bloom: float = Field(default=.7, ge=0, le=1.4, allow_inf_nan=False)
    shake: float = Field(default=.65, ge=0, le=1.5, allow_inf_nan=False)
    post: bool = True


def create_motion_router(get_scan_dir, validate_path, find_audio):
    router = APIRouter(prefix='/api/motion')
    jobs, processes = {}, {}
    lock = threading.Lock()
    plan_lock = threading.Lock()
    director_jobs = {}

    def project_path(project_id):
        scan = get_scan_dir().resolve()
        path = (scan / project_id).resolve()
        if not path.is_relative_to(scan) or not path.name.endswith(('_alignment.json', '_project.json')):
            raise HTTPException(400, '歌曲工程路径无效')
        return validate_path(path)

    def read(project_id):
        path = project_path(project_id)
        payload = json.loads(path.read_text(encoding='utf-8'))
        payload['title'] = payload.get('title') or path.parent.name
        audio = find_audio(path.stem.removesuffix('_alignment').removesuffix('_project'), song_output_dir=path.parent)
        identity = resolve_identity(path, payload, ROOT / 'input', Path(audio) if audio else None)
        payload.update(title=identity['title'], artist=identity['artist'], song_identity=identity,
                       song_cover=resolve_cover(path, payload, ROOT / 'input', Path(audio) if audio else None))
        return path, payload

    def plan_path(path):
        return path.with_name(path.stem.removesuffix('_alignment').removesuffix('_project') + '_motion_plan.json')

    def previous(path, payload=None):
        p = plan_path(path)
        if not p.exists(): return None
        data = json.loads(p.read_text(encoding='utf-8'))
        if payload is not None:
            try: validate_plan(payload, data)
            except ValueError: return None
        return data

    def atomic_write(path, data):
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False) as stream:
            temp = Path(stream.name)
            json.dump(data, stream, ensure_ascii=False, indent=2)
        try: temp.replace(path)
        finally: temp.unlink(missing_ok=True)

    @router.get('/projects')
    def projects():
        scan = get_scan_dir()
        return [{'id': str(p.relative_to(scan)), 'name': p.parent.name} for p in sorted(scan.rglob('*_alignment.json'))]

    @router.get('/project')
    def project(project_id: str):
        path, payload = read(project_id)
        audio = find_audio(path.stem.removesuffix('_alignment').removesuffix('_project'), song_output_dir=path.parent)
        saved = previous(path)
        error = ''
        if saved:
            try: validate_plan(payload, saved)
            except ValueError as exc: saved, error = None, str(exc)
        return {'project': payload, 'plan': saved, 'plan_error': error,
                'audio_url': '/api/audio?path=' + __import__('urllib.parse', fromlist=['quote']).quote(str(audio)) if audio else None}

    @router.put('/identity')
    def save_identity(req: IdentityRequest):
        with plan_lock:
            path, _ = read(req.project_id)
            atomic_write(identity_path(path), req.identity.model_dump())
            _, payload = read(req.project_id)
        return {'identity': payload['song_identity']}

    def store_cover(path, content, custom=True):
        try:
            image, _, _ = prepare_cover(content)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        dest = cover_path(path, custom)
        temporary = dest.with_name(dest.name + '.' + uuid.uuid4().hex + '.tmp')
        try:
            temporary.write_bytes(image)
            os.replace(temporary, dest)
        finally:
            temporary.unlink(missing_ok=True)

    @router.post('/cover')
    async def upload_cover(project_id: str = Form(...), file: UploadFile = File(...)):
        path = project_path(project_id)
        content = await file.read(MAX_BYTES + 1)
        with plan_lock:
            store_cover(path, content)
            _, payload = read(project_id)
        return {'cover': payload['song_cover']}

    @router.post('/cover/suno')
    def import_suno_cover(req: CoverRequest):
        import requests
        from urllib.parse import urlparse
        path, payload = read(req.project_id)
        if cover_path(path, False).is_file():
            with plan_lock:
                if req.restore:
                    cover_path(path).unlink(missing_ok=True)
                _, payload = read(req.project_id)
            return {'cover': payload['song_cover']}
        url = payload['song_cover']['source_url']
        host = urlparse(url).hostname or ''
        if urlparse(url).scheme != 'https' or not (host.endswith('.suno.ai') or host.endswith('.suno.com')):
            raise HTTPException(422, '未找到可读取的 Suno 封面，请上传图片')
        try:
            with requests.get(url, timeout=(3, 10), stream=True, allow_redirects=False) as response:
                response.raise_for_status()
                content = bytearray()
                for chunk in response.iter_content(65536):
                    content.extend(chunk)
                    if len(content) > MAX_BYTES:
                        raise HTTPException(422, 'Suno 封面超过 10 MB')
            with plan_lock:
                store_cover(path, bytes(content), custom=False)
                if req.restore:
                    cover_path(path).unlink(missing_ok=True)
                _, payload = read(req.project_id)
        except requests.RequestException as exc:
            raise HTTPException(502, 'Suno 封面下载失败，可重试或上传图片') from exc
        return {'cover': payload['song_cover']}

    @router.post('/director/rules')
    def rules(req: ProjectRequest):
        with plan_lock:
            path, payload = read(req.project_id)
            old = previous(path)
            # A changed alignment invalidates the whole old plan including old locks.
            if old:
                try: validate_plan(payload, old)
                except ValueError: old = None
            try: result = rule_plan(payload, old, req.style).model_dump()
            except ValueError as exc: raise HTTPException(422, str(exc))
            if req.line_id:
                if not old or req.line_id not in {cue['line_id'] for cue in result['cues']}:
                    raise HTTPException(422, '局部重新导演需要有效的已保存句子')
                result['cues'] = [cue if cue['line_id'] == req.line_id else next(c for c in old['cues'] if c['line_id'] == cue['line_id']) for cue in result['cues']]
            result = validate_plan(payload, result).model_dump()
            atomic_write(plan_path(path), result)
        return result

    @router.post('/director/input')
    def prompt(req: ProjectRequest):
        path, payload = read(req.project_id)
        try:
            return {'input': director_input(payload), 'prompt': llm_prompt(payload, previous(path, payload), req.style, req.instruction)}
        except ValueError as exc: raise HTTPException(422, str(exc))

    def checked_plan(payload, data, old, from_llm):
        result = validate_plan(payload, data).model_dump()
        if from_llm and old:
            canonical = validate_plan(payload, old).model_dump()
            locked = {cue['line_id']: cue for cue in canonical['cues'] if cue['locked']}
            if locked and result['seed'] != canonical['seed']:
                raise ValueError('存在锁定句子时不能改变随机种子')
            for cue in result['cues']:
                if cue['line_id'] in locked and cue != locked[cue['line_id']]:
                    raise ValueError('LLM 方案修改了锁定句子，请保留锁定条目')
        return result

    def snapshot(payload, old):
        return hashlib.sha256(json.dumps([source_signature(payload), old], sort_keys=True, ensure_ascii=False).encode()).hexdigest()

    @router.get('/director/config')
    def director_config():
        try:
            config = configuration()
            return {'configured': True, 'model': config.model, 'fallback_model': config.fallback_model}
        except DirectorAPIError as exc:
            return {'configured': False, 'message': str(exc)}

    @router.post('/director/generate', status_code=202)
    def generate_director(req: ProjectRequest):
        try: config = configuration()
        except DirectorAPIError as exc: raise HTTPException(503, str(exc))
        with plan_lock:
            path, payload = read(req.project_id)
            old = previous(path, payload)
            try:
                if req.line_id:
                    bundle = line_prompt_bundle(payload, req.line_id, old, req.style, req.instruction)
                    if not bundle['can_apply']: raise HTTPException(409, '当前句已锁定，请先解锁')
                    prompt_text = bundle['prompt']
                else: prompt_text = llm_prompt(payload, old, req.style, req.instruction)
            except ValueError as exc: raise HTTPException(422, str(exc))
            baseline = snapshot(payload, old)
            with lock:
                if any(j['status'] in ('queued', 'running', 'validating', 'repairing') for j in director_jobs.values()):
                    raise HTTPException(409, '已有自动导演任务正在运行，请等待完成')
                if len(director_jobs) >= 20: director_jobs.pop(next(iter(director_jobs)))
                job_id = uuid.uuid4().hex
                director_jobs[job_id] = {'id': job_id, 'project_id': req.project_id, 'line_id': req.line_id,
                                         'status': 'queued', 'model': config.model, 'requested_model': config.model, 'fallback_used': False, 'attempt': 0,
                                         'baseline': baseline, 'result': None, 'error': ''}

        def run():
            def update(**values):
                with lock: director_jobs[job_id].update(values)
            try:
                repair = ''
                active_config = config
                fallback_used = False
                for attempt in (1, 2):
                    update(status='running' if attempt == 1 else 'repairing', attempt=attempt)
                    try:
                        try:
                            data = generate_json(active_config, prompt_text, repair)
                        except DirectorQuotaError:
                            if fallback_used or not config.fallback_model or active_config.model == config.fallback_model:
                                raise DirectorAPIError('模型额度不足，主模型或备用模型均无法继续，原方案未修改')
                            active_config = replace(config, model=config.fallback_model)
                            fallback_used = True
                            update(model=active_config.model, fallback_used=True)
                            # One switch per task; any JSON repair stays on the fallback model.
                            try: data = generate_json(active_config, prompt_text, repair)
                            except DirectorQuotaError:
                                raise DirectorAPIError('备用模型也限流或额度不足，原方案未修改，请稍后重试') from None
                        update(status='validating')
                        if req.line_id:
                            response, _ = line_response(payload, data, req.line_id)
                            baseline_plan = validate_plan(payload, old) if old else None
                            expected = cue_signature(baseline_plan, req.line_id) if baseline_plan else None
                            if response.base_cue_signature != expected: raise ValueError('必须原样保留 base_cue_signature')
                            base = baseline_plan or rule_plan(payload, style=req.style)
                            result = base.model_copy(deep=True)
                            result.cues = [response.cue if c.line_id == req.line_id else c for c in result.cues]
                            result = checked_plan(payload, result.model_dump(), old, True)
                        else: result = checked_plan(payload, data, old, True)
                        missing = [c['line_id'] for c in result['cues'] if (not req.line_id or c['line_id'] == req.line_id) and not c['locked'] and not c.get('poster')]
                        if missing: raise ValueError('每个未锁定句子必须有 poster 海报设计：' + ', '.join(missing))
                        update(status='ready', result=result)
                        return
                    except DirectorAPIError: raise
                    except ValueError as exc:
                        repair = str(exc)[:4000]
                        if attempt == 2: raise DirectorAPIError('模型结果两次未通过导演校验：' + repair)
            except DirectorAPIError as exc: update(status='failed', error=str(exc))
            except Exception: update(status='failed', error='自动导演任务失败，原方案未修改，请检查服务端配置')

        threading.Thread(target=run, daemon=True).start()
        return {'id': job_id, 'status': 'queued'}

    @router.get('/director/jobs/{job_id}')
    def director_job(job_id: str):
        with lock:
            if job_id not in director_jobs: raise HTTPException(404, '导演任务不存在或服务已重启')
            return {k: v for k, v in director_jobs[job_id].items() if k != 'baseline'}

    @router.post('/director/jobs/{job_id}/apply')
    def apply_director_job(job_id: str):
        with plan_lock:
            with lock:
                job = dict(director_jobs.get(job_id, {}))
            if not job: raise HTTPException(404, '导演任务不存在或服务已重启')
            if job['status'] != 'ready': raise HTTPException(409, '导演任务尚未就绪或已应用')
            path, payload = read(job['project_id'])
            old = previous(path)
            if snapshot(payload, old) != job['baseline']:
                raise HTTPException(409, '生成期间歌词或导演方案已修改，请重新生成，当前方案未被覆盖')
            try: result = checked_plan(payload, job['result'], old, True)
            except ValueError as exc: raise HTTPException(422, str(exc))
            atomic_write(plan_path(path), result)
            with lock: director_jobs[job_id]['status'] = 'applied'
        return {'plan': result}

    @router.post('/director/validate')
    def validate_full(req: PlanRequest):
        with plan_lock:
            _, payload = read(req.project_id)
            path = project_path(req.project_id)
            try: result = checked_plan(payload, req.plan, previous(path), req.from_llm)
            except ValueError as exc: raise HTTPException(422, str(exc))
        return {'valid': True, 'plan': result}

    @router.put('/plan')
    def save(req: PlanRequest):
        with plan_lock:
            path, payload = read(req.project_id)
            try: result = checked_plan(payload, req.plan, previous(path), req.from_llm)
            except ValueError as exc: raise HTTPException(422, str(exc))
            atomic_write(plan_path(path), result)
        return result

    @router.post('/director/line/input')
    def line_input(req: LineInputRequest):
        path, payload = read(req.project_id)
        try: return line_prompt_bundle(payload, req.line_id, previous(path, payload), req.style, req.instruction)
        except ValueError as exc: raise HTTPException(422, str(exc))

    def prepare_line(req, apply=False):
        with plan_lock:
            path, payload = read(req.project_id)
            try:
                response, compiled = line_response(payload, req.response, req.line_id)
                old = previous(path)
                baseline = validate_plan(payload, old) if old else None
                if baseline:
                    target = next(cue for cue in baseline.cues if cue.line_id == req.line_id)
                    if target.locked: raise HTTPException(409, '当前句已锁定，请先解锁')
                    if response.base_cue_signature != cue_signature(baseline, req.line_id):
                        raise HTTPException(409, '当前句在提示词生成后已修改，请重新获取提示词')
                elif response.base_cue_signature is not None:
                    raise HTTPException(409, '原导演方案已移除，请重新获取提示词')
                base = baseline or rule_plan(payload, style=req.style)
                result = base.model_copy(deep=True)
                result.cues = [response.cue if cue.line_id == req.line_id else cue for cue in result.cues]
                result = validate_plan(payload, result.model_dump()).model_dump()
            except ValueError as exc: raise HTTPException(422, str(exc))
            if apply: atomic_write(plan_path(path), result)
        return {'valid': True, 'applied': apply, 'cue': response.cue.model_dump(), 'compiled_groups': compiled, 'compiled_nodes': compiled, 'plan': result}

    @router.post('/director/line/validate')
    def validate_line(req: LineApplyRequest):
        return prepare_line(req)

    @router.post('/director/line/apply')
    def apply_line(req: LineApplyRequest):
        return prepare_line(req, apply=True)

    @router.post('/render', status_code=202)
    def render(req: RenderRequest):
        path, payload = read(req.project_id)
        saved = previous(path)
        if not saved: raise HTTPException(422, '请先生成并保存动效导演方案')
        try: plan = validate_plan(payload, saved).model_dump()
        except ValueError as exc: raise HTTPException(422, str(exc))
        audio = find_audio(path.stem.removesuffix('_alignment').removesuffix('_project'), song_output_dir=path.parent)
        if not audio: raise HTTPException(404, '没有原曲音频，无法输出带音乐的 MP4')
        audio = validate_path(audio)
        import soundfile as sf
        # Export duration follows actual audio, never the last sung word.
        duration = sf.info(str(audio)).duration
        length = req.length if req.length is not None else duration - req.start
        if length <= 0 or req.start + length > duration + .001:
            raise HTTPException(422, '导出范围超出原曲')
        node = shutil.which('node')
        if not node: raise HTTPException(503, '渲染环境缺少 Node.js')
        if not (ROOT / 'frontend/local/remotion/index.html').exists():
            raise HTTPException(503, '请先构建动效前端')
        with lock:
            if any(job['status'] in ('running', 'queued') for job in jobs.values()):
                raise HTTPException(409, '已有视频正在导出，请等待完成或取消')
            job_id = uuid.uuid4().hex
            outdir = path.parent / 'motion_exports'
            outdir.mkdir(exist_ok=True)
            out = outdir / f'{job_id}.mp4'
            snapshot = outdir / f'{job_id}.json'
            payload['duration'] = duration
            payload['motion_plan'] = plan
            options = {'aspect': req.aspect, 'height': req.height, 'mode': 'phrase', 'preset': req.style,
                       'bloom': req.bloom, 'grain': .035, 'shake': req.shake, 'punch': .7, 'post': req.post}
            atomic_write(snapshot, {'project': payload, 'options': options, 'audioPath': str(audio), 'start': req.start, 'length': length})
            jobs[job_id] = {'id': job_id, 'status': 'queued', 'frames': 0, 'total': round(length*30), 'error': '', 'created_at': time.time(), 'width': round(req.height*16/9) if req.aspect == '16:9' else req.height, 'height': req.height if req.aspect == '16:9' else round(req.height*16/9), 'output': str(out)}

        def run():
            diagnostics = ''
            try:
                with lock:
                    if jobs[job_id]['status'] == 'cancelled': return
                    child = subprocess.Popen([node, str(ROOT/'frontend/motion/scripts/render-remotion.mjs'), str(snapshot), str(out)],
                                             cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, start_new_session=True)
                    processes[job_id] = child
                    jobs[job_id]['status'] = 'running'
                for line in child.stdout:
                    if line.startswith('PROGRESS '):
                        value, total = line.split()[1].split('/')
                        jobs[job_id].update(frames=int(value), total=int(total))
                    else: diagnostics = (diagnostics + line)[-3000:]
                code = child.wait()
                with lock:
                    if jobs[job_id]['status'] != 'cancelled':
                        is_done = code == 0 and out.exists()
                        jobs[job_id].update(status='done' if is_done else 'failed', error='' if code == 0 else diagnostics)
                        if is_done and r2_storage.is_configured():
                            try:
                                r2_res = r2_storage.upload_video(out, f"exports/{job_id}.mp4")
                                if r2_res:
                                    jobs[job_id]['cdn_url'] = r2_res['url']
                                    jobs[job_id]['r2_key'] = r2_res['key']
                            except Exception:
                                pass
            except Exception as exc:
                jobs[job_id].update(status='failed', error=str(exc))
            finally:
                atomic_write(outdir / f'{job_id}_status.json', {key: value for key, value in jobs[job_id].items() if key != 'output'})
                processes.pop(job_id, None)
                if jobs[job_id]['status'] != 'done': out.unlink(missing_ok=True)
        threading.Thread(target=run, daemon=True).start()
        return {'id': job_id}

    @router.get('/exports')
    def exports(project_id: str):
        path = project_path(project_id)
        records = []
        for p in (path.parent / 'motion_exports').glob('*_status.json'):
            record = json.loads(p.read_text(encoding='utf-8'))
            record['created_at'] = record.get('created_at', p.stat().st_mtime)
            records.append(record)
        return sorted(records, key=lambda j: j['created_at'], reverse=True)

    @router.get('/r2/status')
    def r2_status():
        return r2_storage.get_status_info()

    @router.get('/gallery')
    def gallery(project_id: str | None = None):
        """获取所有已导出的视频作品库（供展厅与播放器使用）"""
        records = []
        scan = get_scan_dir()
        pattern = f'{project_id.split("/")[0]}/motion_exports/*_status.json' if project_id else '*/motion_exports/*_status.json'
        for p in scan.glob(pattern):
            try:
                data = json.loads(p.read_text(encoding='utf-8'))
                if data.get('status') == 'done':
                    job_id = data.get('id', p.stem.replace('_status', ''))
                    song_dir = p.parent.parent
                    song_title = song_dir.name.removesuffix('_project').removesuffix('_alignment')
                    job_snapshot = p.with_name(f'{job_id}.json')
                    if job_snapshot.exists():
                        try:
                            snap_data = json.loads(job_snapshot.read_text(encoding='utf-8'))
                            song_title = snap_data.get('project', {}).get('title') or song_title
                        except Exception:
                            pass
                    mp4_file = p.with_name(f'{job_id}.mp4')
                    size = mp4_file.stat().st_size if mp4_file.exists() else data.get('size', 0)
                    total_frames = data.get('total', 0)
                    records.append({
                        'id': job_id,
                        'song_title': song_title,
                        'created_at': data.get('created_at', p.stat().st_mtime),
                        'width': data.get('width', 1280),
                        'height': data.get('height', 720),
                        'aspect': '9:16' if data.get('height', 720) > data.get('width', 1280) else '16:9',
                        'frames': data.get('frames', total_frames),
                        'total': total_frames,
                        'duration': round(total_frames / 30, 2) if total_frames else 0,
                        'cdn_url': data.get('cdn_url', ''),
                        'local_url': f'/api/motion/render/{job_id}/download',
                        'stream_url': f'/api/motion/render/{job_id}/stream',
                        'file_size': size,
                        'exists_locally': mp4_file.exists(),
                    })
            except Exception:
                continue
        return sorted(records, key=lambda x: x['created_at'], reverse=True)

    @router.post('/render/{job_id}/sync_r2')
    def sync_r2(job_id: str):
        """将已存在的本地视频同步上传至 Cloudflare R2"""
        if not r2_storage.is_configured():
            raise HTTPException(400, 'Cloudflare R2 尚未配置')
        candidates = list(get_scan_dir().glob(f'*/motion_exports/{job_id}_status.json'))
        if not candidates:
            raise HTTPException(404, '视频任务不存在')
        status_path = candidates[0]
        mp4_path = status_path.with_name(f'{job_id}.mp4')
        if not mp4_path.exists():
            raise HTTPException(404, '本地 MP4 文件不存在')

        status_data = json.loads(status_path.read_text(encoding='utf-8'))
        r2_key = f"exports/{job_id}.mp4"
        upload_res = r2_storage.upload_video(mp4_path, r2_key)
        if not upload_res or not upload_res.get('url'):
            raise HTTPException(500, '上传到 Cloudflare R2 失败，请检查网络和存储桶权限')

        status_data['cdn_url'] = upload_res['url']
        status_data['r2_key'] = upload_res['key']
        status_path.write_text(json.dumps(status_data, ensure_ascii=False, indent=2), encoding='utf-8')
        if job_id in jobs:
            jobs[job_id]['cdn_url'] = upload_res['url']
            jobs[job_id]['r2_key'] = upload_res['key']

        # 自动同步 R2 全量作品索引 gallery.json
        try:
            client = r2_storage.get_client()
            if client:
                items = gallery()
                client.put_object(
                    Bucket=r2_storage.bucket,
                    Key="gallery.json",
                    Body=json.dumps(items, ensure_ascii=False, indent=2).encode("utf-8"),
                    ContentType="application/json; charset=utf-8",
                    CacheControl="public, max-age=60",
                )
        except Exception:
            pass

        return {'success': True, 'cdn_url': upload_res['url'], 'r2_key': upload_res['key']}

    @router.get('/render/{job_id}')
    def status(job_id: str):
        if job_id not in jobs: raise HTTPException(404, '导出任务不存在')
        return {key: value for key, value in jobs[job_id].items() if key != 'output'}

    @router.post('/render/{job_id}/cancel')
    def cancel(job_id: str):
        import signal
        with lock:
            if job_id not in jobs: raise HTTPException(404, '导出任务不存在')
            if jobs[job_id]['status'] in ('queued', 'running'):
                jobs[job_id]['status'] = 'cancelled'
                child = processes.get(job_id)
                if child:
                    try: os.killpg(child.pid, signal.SIGTERM)
                    except ProcessLookupError: pass
        return status(job_id)

    @router.get('/render/{job_id}/stream')
    def stream_video(job_id: str):
        """流式播放视频，若存在 R2 CDN 直链则重定向，否则本地回退"""
        if job_id in jobs and jobs[job_id].get('cdn_url'):
            return RedirectResponse(jobs[job_id]['cdn_url'], status_code=307)
        candidates = list(get_scan_dir().glob(f'*/motion_exports/{job_id}_status.json'))
        if candidates:
            data = json.loads(candidates[0].read_text(encoding='utf-8'))
            if data.get('cdn_url'):
                return RedirectResponse(data['cdn_url'], status_code=307)
            local_mp4 = candidates[0].with_name(f'{job_id}.mp4')
            if local_mp4.exists():
                return FileResponse(local_mp4, media_type='video/mp4')
        if job_id in jobs and jobs[job_id].get('output') and Path(jobs[job_id]['output']).exists():
            return FileResponse(Path(jobs[job_id]['output']), media_type='video/mp4')
        raise HTTPException(404, '视频尚未就绪或不存在')

    @router.get('/render/{job_id}/download')
    def download(job_id: str):
        if job_id in jobs and jobs[job_id]['status'] == 'done':
            out = Path(jobs[job_id]['output'])
        else:
            if len(job_id) != 32 or any(c not in '0123456789abcdef' for c in job_id):
                raise HTTPException(404, '成片不存在')
            candidates = list(get_scan_dir().glob(f'*/motion_exports/{job_id}_status.json'))
            if not candidates or json.loads(candidates[0].read_text())['status'] != 'done':
                raise HTTPException(404, '成片尚未完成')
            out = candidates[0].with_name(f'{job_id}.mp4')
        return FileResponse(out, media_type='video/mp4', filename='motion-studio.mp4')

    return router
