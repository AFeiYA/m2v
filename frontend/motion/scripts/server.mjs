// Development entry shares Python's song store, director API and render jobs.
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
const repo=fileURLToPath(new URL('../../../',import.meta.url));
const child=spawn(process.env.M2V_PYTHON||'python3',['-m','src.local_editor','--dir','output','--port',process.env.MOTION_PORT||'8768','--no-browser'],{cwd:repo,stdio:'inherit'});
child.on('error',error=>{console.error(error.message);process.exit(1);});
child.on('exit',code=>process.exit(code||0));
process.on('SIGTERM',()=>child.kill('SIGTERM'));
process.on('SIGINT',()=>child.kill('SIGINT'));
