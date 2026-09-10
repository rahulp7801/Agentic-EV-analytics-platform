import path from 'path';
import fs from 'fs';
export const ROOT = path.resolve(process.cwd(), '..');
const local = path.join(ROOT, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
export const PYTHON = fs.existsSync(local) ? local : 'python';
