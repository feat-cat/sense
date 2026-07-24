#!/usr/bin/env node
/**
 * sense — 多模态 AI 桥接 CLI
 *
 * 自动找 bridge.py 并调用 Python 执行。
 * 支持从 npm 全局安装、npx、或 skill 安装后使用。
 */

const { resolve, dirname, join } = require('path');
const { existsSync, readFileSync } = require('fs');
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

function main() {
  const bridgePy = findBridgePy();

  if (!bridgePy) {
    console.error('');
    console.error('  ╔══════════════════════════════════════════════════════════╗');
    console.error('  ║  找不到 bridge.py — 需要安装 sense skill              ║');
    console.error('  ╚══════════════════════════════════════════════════════════╝');
    console.error('');
    console.error('  @feat-cat/sense 是 CLI 外壳，还需要安装 skill 本体:');
    console.error('');
    console.error('    npx skills add feat-cat/sense');
    console.error('');
    console.error('  或在项目目录安装 skill 到本地 .agents/skills/sense/');
    console.error('  完整安装后结构:');
    console.error('    .agents/skills/sense/');
    console.error('    ├── SKILL.md');
    console.error('    ├── bridge.py');
    console.error('    └── .env.example');
    console.error('');
    console.error('  或用 SENSE_BRIDGE 环境变量手动指定 bridge.py 路径:');
    console.error('    # PowerShell');
    console.error('    $env:SENSE_BRIDGE = "D:\\path\\to\\bridge.py"');
    console.error('    # CMD');
    console.error('    set SENSE_BRIDGE=D:\\path\\to\\bridge.py');
    console.error('');
    process.exit(1);
  }

  const skillDir = getSkillDir(bridgePy);
  const args = process.argv.slice(2);

  if (args[0] === '--version' || args[0] === '-V') {
    console.log('@feat-cat/sense v' + VERSION);
    process.exit(0);
  }

  if (args.length === 0 || args[0] === '--help' || args[0] === '-h') {
    console.log('');
    console.log('  sense — 多模态 AI 桥接 CLI');
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
    console.log('  --prompt-stdin: 从标准输入读取提示文本，避免 shell 引号转义问题');
    console.log('');
    console.log('  bridge.py 位置: ' + bridgePy);
    process.exit(0);
  }

  // Windows: 优先用 py 启动器，再 fallback 到 python
  // Unix: python3 优先
  const pythonCmd = process.platform === 'win32' ? 'py' : 'python3';
  const pythonArgs = process.platform === 'win32' ? ['-3', bridgePy, ...args] : [bridgePy, ...args];

  const child = spawn(pythonCmd, pythonArgs, {
    cwd: skillDir,
    stdio: 'inherit',
    env: { ...process.env }
  });

  child.on('exit', (code) => {
    process.exit(code ?? 1);
  });

  child.on('error', (err) => {
    console.error('❌ 启动失败:', err.message);
    process.exit(1);
  });
}

main();
