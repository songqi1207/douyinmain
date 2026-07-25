#!/usr/bin/env node
'use strict';

// 基于可正常连线的“每天认识一款香烟_中华”母版生成同结构模板。
//
// 用法:
//   node generate-cigarette-template.js <烟名>
//   node generate-cigarette-template.js 玉溪 --yinse <音色ID>
//   node generate-cigarette-template.js 玉溪 --out <输出路径>
//
// 可选参数:
//   --base  <路径>  母版文件（缺省为每天认识一款香烟_中华_20260708_121403.txt）
//   --out   <路径>  输出文件（缺省为每天认识一款香烟_<烟名>.txt）
//   --yinse <ID>    替换母版中所有固定 voice_id

const fs = require('fs');
const path = require('path');

const DEFAULT_BASE = path.join(
  __dirname,
  '每天认识一款香烟_中华_20260708_121403.txt'
);

function parseArgs(argv) {
  const args = { _: [] };
  const valueOptions = new Set(['--base', '--out', '--yinse']);
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    if (arg === '-h' || arg === '--help') {
      args.help = true;
    } else if (valueOptions.has(arg)) {
      if (i + 1 >= argv.length) throw new Error(`${arg} 缺少参数值`);
      args[arg.slice(2)] = argv[++i];
    } else if (arg.startsWith('-')) {
      throw new Error(`不支持的参数: ${arg}`);
    } else {
      args._.push(arg);
    }
  }
  return args;
}

function allNodes(nodes) {
  const result = [];
  const visit = (items) => {
    for (const node of items || []) {
      result.push(node);
      visit(node.blocks);
      visit(node.data && node.data.blocks);
    }
  };
  visit(nodes);
  return result;
}

function setLiteralVoiceIds(nodes, voiceId) {
  let changed = 0;
  for (const node of allNodes(nodes)) {
    const parameters =
      (node.data && node.data.inputs && node.data.inputs.inputParameters) || [];
    for (const parameter of parameters) {
      const value = parameter.input && parameter.input.value;
      if (
        parameter.name === 'voice_id' &&
        value &&
        value.type === 'literal'
      ) {
        value.content = voiceId;
        changed += 1;
      }
    }
  }
  return changed;
}

function main() {
  const args = parseArgs(process.argv.slice(2));
  if (args.help || args._.length !== 1) {
    console.log(
      '用法: node generate-cigarette-template.js <烟名> ' +
      '[--yinse 音色ID] [--base 母版] [--out 输出]'
    );
    process.exitCode = args.help ? 0 : 1;
    return;
  }

  const cigaretteName = args._[0].trim();
  if (!cigaretteName) throw new Error('烟名不能为空');

  const basePath = args.base ? path.resolve(args.base) : DEFAULT_BASE;
  const outPath = args.out
    ? path.resolve(args.out)
    : path.join(__dirname, `每天认识一款香烟_${cigaretteName}.txt`);

  const raw = fs.readFileSync(basePath, 'utf8').replace(/^\uFEFF/, '');
  const workflow = JSON.parse(raw);
  const nodes = workflow && workflow.json && workflow.json.nodes;
  if (!Array.isArray(nodes)) throw new Error('母版结构异常：找不到 json.nodes');

  const start = nodes.find((node) => String(node.type) === '1');
  if (!start) throw new Error('母版结构异常：找不到开始节点');
  const outputs = (start.data && start.data.outputs) || [];
  const nameOutput = outputs.find((output) => output.name === 'xiangyan_name');
  if (!nameOutput) {
    throw new Error('母版结构异常：开始节点没有 xiangyan_name');
  }

  const oldName = nameOutput.defaultValue || nameOutput.value || '';
  nameOutput.defaultValue = cigaretteName;
  nameOutput.value = cigaretteName;

  let changedVoices = 0;
  const voiceId = String(args.yinse || '').trim();
  if (voiceId) changedVoices = setLiteralVoiceIds(nodes, voiceId);

  fs.writeFileSync(
    outPath,
    JSON.stringify(workflow, null, 2) + '\n',
    'utf8'
  );

  const check = JSON.parse(fs.readFileSync(outPath, 'utf8'));
  const checkStart = check.json.nodes.find((node) => String(node.type) === '1');
  const checkName = checkStart.data.outputs.find(
    (output) => output.name === 'xiangyan_name'
  );
  if (
    checkName.defaultValue !== cigaretteName ||
    checkName.value !== cigaretteName
  ) {
    throw new Error('自校验失败，请勿使用生成文件');
  }

  console.log(`✔ 已生成: ${outPath}`);
  console.log(`  香烟名称: ${oldName} → ${cigaretteName}`);
  console.log(`  节点数: ${nodes.length}`);
  if (voiceId) console.log(`  固定音色槽: 已替换 ${changedVoices} 处`);
}

main();
