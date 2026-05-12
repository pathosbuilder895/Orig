const { spawn } = require('child_process');
const args = ['/Users/andrew/Desktop/Original/run.py'].concat(process.argv.slice(2));
const child = spawn('/usr/bin/python3', args, { stdio: 'inherit', cwd: '/Users/andrew/Desktop/Original' });
child.on('exit', (code) => process.exit(code || 0));
