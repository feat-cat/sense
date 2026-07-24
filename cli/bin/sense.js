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

function run(cmd, args) {
  return new Promise((resolve, reject) => {
    const child = spawn(cmd, args, { stdio: 'inherit' });
    child.on('exit', (code) => resolve(code ?? 1));
    child.on('error', (err) => reject(err));
  });
}

function showHelp(bridgePy) {
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
  console.log('    sense install             安装/修复 sense skill 本体');
  console.log('    sense update              更新 sense CLI + skill 到最新');
  console.log('');
  console.log('  --prompt-stdin: 从标准输入读取提示文本，避免 shell 引号转义问题');
  if (bridgePy) {
    console.log('');
    console.log('  bridge.py 位置: ' + bridgePy);
  }
  console.log('');
}

async function main() {
  const args = process.argv.slice(2);

  // --- 这些命令不需要 bridge.py ---
  if (args[0] === '--version' || args[0] === '-V') {
    console.log('@feat-cat/sense v' + VERSION);
    return;
  }

  if (args.length === 0 || args[0] === '--help' || args[0] === '-h') {
    showHelp(findBridgePy());
    return;
  }

  if (args[0] === 'install') {
    console.log('正在安装 sense skill...');
    const code = await run('npx', ['skills', 'add', 'feat-cat/sense', '-y', '-g']);
    if (code === 0) console.log('✓ sense skill 安装完成');
    process.exit(code);
  }

  if (args[0] === 'update') {
    console.log('正在更新 sense skill...');
    const code1 = await run('npx', ['skills', 'add', 'feat-cat/sense', '-y', '-g']);
    if (code1 !== 0) process.exit(code1);
    console.log('✓ sense skill 已更新');

    console.log('正在更新 sense CLI...');
    const code2 = await run('npm', ['install', '-g', '@feat-cat/sense']);
    if (code2 === 0) console.log('✓ sense CLI 已更新到最新');
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
    console.error('  运行 sense install 即可自动安装:');
    console.error('');
    console.error('    sense install');
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

  // Windows: 优先用 py 启动器，再 fallback 到 python
  // Unix: python3 优先
  const pythonCmd = process.platform === 'win32' ? 'py' : 'python3';
  const pythonArgs = process.platform === 'win32' ? ['-3', bridgePy, ...args] : [bridgePy, ...args];

  await run(pythonCmd, pythonArgs);
}

main().catch((err) => {
  console.error('❌ 错误:', err.message);
  process.exit(1);
});
