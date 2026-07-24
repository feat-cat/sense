#!/usr/bin/env node
/**
 * sense — 多模态 AI 桥接 CLI
 *
 * 自动找 bridge.py 并调用 Python 执行。
 * 支持从 npm 全局安装、npx、或 skill 安装后使用。
 */

const { resolve, dirname, join } = require('path');
const { existsSync, readFileSync, mkdirSync, createWriteStream } = require('fs');
const { spawn } = require('child_process');

// 从 package.json 读取版本号（在 bin/ 上一级）
const pkgJson = JSON.parse(readFileSync(resolve(__dirname, '..', 'package.json'), 'utf-8'));
const VERSION = pkgJson.version;

// bridge.py 查找优先级
function findBridgePy() {
  // 1. SENSE_BRIDGE 环境变量（显式指定）
  if (process.env.SENSE_BRIDGE && existsSync(process.env.SENSE_BRIDGE)) {
    return process.env.SENSE_BRIDGE;
  }

  // 2. 相对于 CLI 脚本自身（npm 安装时，在 cli/ 的同级 skill/ 目录下）
  const relativeToCli = resolve(__dirname, '..', '..', 'skill', 'bridge.py');
  if (existsSync(relativeToCli)) return relativeToCli;

  // 3. 当前目录下的 project-level skill 安装
  const projectSkill = join(process.cwd(), '.agents', 'skills', 'sense', 'bridge.py');
  if (existsSync(projectSkill)) return projectSkill;

  // 4. 用户目录下的 global skill 安装
  const home = process.env.HOME || process.env.USERPROFILE;
  if (home) {
    const globalSkill = join(home, '.agents', 'skills', 'sense', 'bridge.py');
    if (existsSync(globalSkill)) return globalSkill;
  }

  // 5. OpenCode 全局 skill 目录
  const opencodeSkill = join(home || '', '.config', 'opencode', 'skills', 'sense', 'bridge.py');
  if (existsSync(opencodeSkill)) return opencodeSkill;

  return null;
}

function getSkillDir(bridgePy) {
  return dirname(bridgePy);
}

// 判断当前 bridge.py 的安装范围
function detectScope(bridgePy) {
  const home = process.env.HOME || process.env.USERPROFILE;
  if (!home) return 'global'; // 保底

  if (bridgePy === join(home, '.agents', 'skills', 'sense', 'bridge.py')) return 'global';
  if (bridgePy === join(home, '.config', 'opencode', 'skills', 'sense', 'bridge.py')) return 'global';
  if (bridgePy === join(process.cwd(), '.agents', 'skills', 'sense', 'bridge.py')) return 'project';
  if (bridgePy === resolve(__dirname, '..', '..', 'skill', 'bridge.py')) return 'dev';   // 开发者模式（repo 内）
  if (process.env.SENSE_BRIDGE) return 'custom';   // 环境变量指定的自定义路径
  return 'custom';
}

// 从 GitHub raw 下载 skill 文件列表
const SKILL_FILES = ['bridge.py', 'SKILL.md', '.env.example'];
const GITHUB_RAW = 'https://raw.githubusercontent.com/feat-cat/sense/main/skill';

async function downloadFile(url, dest) {
  // Python 的 SSL 在 Windows 上更可靠，用它来下载
  const tmpScript = join(require('os').tmpdir(), '_sense_dl_' + Date.now() + '.py');
  const pyCode = `
import urllib.request
url = ${JSON.stringify(url)}
dest = ${JSON.stringify(dest)}
open(dest, 'wb').write(urllib.request.urlopen(url).read())
  `.trim();
  require('fs').writeFileSync(tmpScript, pyCode);
  const code = await run('py', ['-3', tmpScript]);
  try { require('fs').unlinkSync(tmpScript); } catch {}
  if (code !== 0) throw new Error('下载失败');
}

async function downloadSkill(targetDir) {
  mkdirSync(targetDir, { recursive: true });
  for (const file of SKILL_FILES) {
    const url = `${GITHUB_RAW}/${file}`;
    const dest = join(targetDir, file);
    process.stdout.write(`  下载 ${file} ... `);
    try {
      await downloadFile(url, dest);
      console.log('✓');
    } catch (err) {
      console.log('×');
      throw new Error(`下载 ${file} 失败: ${err.message}`);
    }
  }
}

function run(cmd, args) {
  return new Promise((resolve, reject) => {
    // Windows 上 npm/npx 是 .cmd 文件，用 cmd.exe /c 启动
    // 避免使用 shell:true（Node.js v24+ 会触发 DEP0190 告警）
    if (process.platform === 'win32' && (cmd === 'npm' || cmd === 'npx')) {
      const child = spawn('cmd.exe', ['/c', cmd, ...args], { stdio: 'inherit' });
      child.on('exit', (code) => resolve(code ?? 1));
      child.on('error', (err) => reject(err));
    } else {
      const child = spawn(cmd, args, { stdio: 'inherit' });
      child.on('exit', (code) => resolve(code ?? 1));
      child.on('error', (err) => reject(err));
    }
  });
}

function detectPython() {
  const envPy = process.env.SENSE_PYTHON;
  const candidates = envPy ? [envPy] : ['py', 'python', 'python3'];
  const found = candidates.find(c => {
    try { return require('child_process').spawnSync(c, ['--version']).status === 0; }
    catch { return false; }
  }) || null;
  if (!found) return { cmd: null, version: '未检测到', path: null };
  const ver = require('child_process').spawnSync(found, ['--version']).stdout.toString().trim()
            || require('child_process').spawnSync(found, ['--version']).stderr.toString().trim()
            || '未知';
  return { cmd: found, version: ver, path: found };
}

function showHelp(bridgePy, pythonInfo) {
  console.log('');
  console.log('  sense — 多模态 AI 桥接 CLI v' + VERSION);
  console.log('');
  console.log('  用法:');
  console.log('    sense new --prompt "描述这张图片" --file photo.jpg');
  console.log('    sense new --prompt-stdin --file photo.jpg < prompt.txt');
  console.log('    sense continue <session_id> --prompt "继续分析"');
  console.log('    sense list');
  console.log('    sense get <session_id>');
  console.log('    sense delete <session_id>');
  console.log('    sense delete --all');
  console.log('    sense status');
  console.log('');
  console.log('  管理:');
  console.log('    sense update              安装/更新 sense CLI + skill 到最新');
  console.log('');
  console.log('  Python: ' + pythonInfo.version + ' (' + pythonInfo.cmd + ')');
  if (bridgePy) {
    console.log('  bridge: ' + bridgePy);
  }
  console.log('  CLI:    @feat-cat/sense v' + VERSION);
  console.log('');
}

async function main() {
  const args = process.argv.slice(2);

  // --- 这些命令不需要 bridge.py ---
  if (args[0] === '--version' || args[0] === '-V') {
    const py = detectPython();
    console.log('@feat-cat/sense v' + VERSION + ' | ' + py.version + ' | ' + (findBridgePy() || '未安装'));
    return;
  }

  if (args.length === 0 || args[0] === '--help' || args[0] === '-h') {
    showHelp(findBridgePy(), detectPython());
    return;
  }

  if (args[0] === 'update') {
    const bridgePy = findBridgePy();
    let targetDir;

    // 确定 skill 安装目录
    if (!bridgePy) {
      // 没装 skill：默认装到全局
      const home = process.env.HOME || process.env.USERPROFILE;
      if (!home) { console.error('× 无法确定用户目录'); process.exit(1); }
      targetDir = join(home, '.agents', 'skills', 'sense');
    } else {
      targetDir = dirname(bridgePy);
    }

    console.log('正在更新 sense skill...');
    console.log('来源: ' + GITHUB_RAW);
    console.log('目标: ' + targetDir);
    try {
      await downloadSkill(targetDir);
      console.log('✓ sense skill 已更新');
    } catch (err) {
      console.error('× ' + err.message);
      process.exit(1);
    }

    console.log('正在更新 sense CLI...');
    console.log('来源: https://www.npmjs.com/package/@feat-cat/sense');
    const code2 = await run('npm', ['install', '-g', '@feat-cat/sense']);
    if (code2 === 0) console.log('✓ sense CLI 已更新到最新');
    else console.error('× CLI 更新失败，可手动运行: npm install -g @feat-cat/sense');
    process.exit(code2);
  }

  // --- 以下命令需要 bridge.py ---
  const bridgePy = findBridgePy();

  if (!bridgePy) {
    console.error('');
    console.error('  ╔══════════════════════════════════════════════════════════╗');
    console.error('  ║  找不到 bridge.py — 需要安装 sense skill              ║');
    console.error('  ╚══════════════════════════════════════════════════════════╝');
    console.error('');
    console.error('  运行 sense update 即可自动安装:');
    console.error('');
    console.error('    sense update');
    console.error('');
    console.error('  或手动安装:');
    console.error('    npx skills add feat-cat/sense');
    console.error('');
    console.error('  或用 SENSE_BRIDGE 环境变量手动指定 bridge.py 路径:');
    console.error('    $env:SENSE_BRIDGE = "D:\\path\\to\\bridge.py"');
    console.error('');
    process.exit(1);
  }

  const skillDir = getSkillDir(bridgePy);

  // 找可用的 Python
  const pythonInfo = detectPython();
  if (!pythonInfo.cmd) {
    console.error('× 找不到 Python，请安装 Python 3');
    process.exit(1);
  }
  const pythonCmd = pythonInfo.cmd;
  const pythonArgs = (pythonCmd === 'py' ? ['-3', bridgePy, ...args] : [bridgePy, ...args]);

  await run(pythonCmd, pythonArgs);
}

main().catch((err) => {
  console.error('❌ 错误:', err.message);
  process.exit(1);
});
