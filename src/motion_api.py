"""Motion Studio uses the existing song store; Node is only a render worker."""
from __future__ import annotations
import json
import os
from pathlib import Path
import shutil
import subprocess
import threading
import time
import uuid
from typing import Literal
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from src.motion_director import validate_plan, rule_plan, llm_prompt, director_input, line_prompt_bundle, line_response, cue_signature

ROOT = Path(__file__).resolve().parent.parent

class ProjectRequest(BaseModel):
    project_id: str
    style: Literal['impact', 'neon'] = 'impact'
    line_id: str | None = None
    instruction: str = Field(default='', max_length=2000)

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
        return path, payload

    def plan_path(path):
        return path.with_name(path.stem.removesuffix('_alignment').removesuffix('_project') + '_motion_plan.json')

    def previous(path):
        p = plan_path(path)
        return json.loads(p.read_text(encoding='utf-8')) if p.exists() else None

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
            return {'input': director_input(payload), 'prompt': llm_prompt(payload, previous(path), req.style, req.instruction)}
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
        try: return line_prompt_bundle(payload, req.line_id, previous(path), req.style, req.instruction)
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
                        jobs[job_id].update(status='done' if code == 0 and out.exists() else 'failed', error='' if code == 0 else diagnostics)
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
