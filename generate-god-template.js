#!/usr/bin/env node
'use strict';

// 神工作流模板生成器
// 以 神工作流模板_修改版-开场静态修正-v7.json 为母版，输入新的神名，
// 生成一份除"开始节点 3 个默认值"外与母版逐字节一致的新模板。
//
// 用法:
//   node generate-god-template.js <神名>
//   node generate-god-template.js 哪吒
//   node generate-god-template.js 杨戬 --desc "额生天眼，手持三尖两刃刀，银甲白袍"
//   node generate-god-template.js 妈祖 --out 神工作流模板_妈祖-v7.json
//   node generate-god-template.js --list          # 查看内置形象库
//
// 可选参数:
//   --desc  <文>  主神形象描述（接在"主神形象必须贴合：<神名>为"之后，不带句号）
//   --wenan <文>  解说文案默认值（缺省: <神名>的身份背景、成名经历、…）
//   --cankao <文> 参考文案默认值（非空则运行时走 137312 爆款改写模式；缺省为空走 176492 自动生成）
//   --shuliang <数> 分镜/生图数量默认值（1~22，缺省沿用母版）
//   --audio <URL> 背景音乐默认值（缺省沿用母版）
//   --yinse <ID>  配音音色默认值（缺省沿用母版）
//   --base  <路径> 母版文件（缺省 v7 母版，也可用之前生成的任意神模板）
//   --out   <路径> 输出文件（缺省 神工作流模板_<神名>-v7.json）
//
// 只做 3 处定点替换，不重新序列化 JSON（避免破坏大整数/浮点/格式）:
//   1) 开始节点 zhuti 默认值   "defaultValue": "<旧神名>"
//   2) 开始节点 wenan 默认值   "<旧神名>的身份背景、成名经历、…文化影响"
//   3) 开始节点 fengge 默认值中 "主神形象必须贴合：<旧神名>为…。" 一句
// 开场名字轮盘(节点175205)按运行时 zhuti 自动剔除同名陪跑并锁定，无需改动。

const fs = require('fs');
const path = require('path');

const DEFAULT_BASE = path.join(__dirname, '神工作流模板_修改版-开场静态修正-v7.json');

// 内置形象库：值为"<神名>为"之后的谓语部分（不带句号），与米核生图提示词句式衔接
const GOD_DESC = {
  '盘古': '开天辟地的创世巨神，手持巨斧，长发虬髯，肌体如山岳，于鸿蒙混沌中顶天立地',
  '女娲': '人首蛇身的创世母神，手托五色石，青丝广袖，慈悲庄严，周身灵光祥云环绕',
  '伏羲': '人首蛇身的人文始祖，手持八卦图，长须古朴，目蕴天机，智慧深邃',
  '神农': '尝百草的农耕药祖，头生双角，身披草叶蓑衣，手持赭鞭与灵草药篓',
  '黄帝': '人文共主轩辕帝，冕服黄袍，手按轩辕剑，长须威严，帝者气象',
  '玉皇大帝': '帝王神格，冕旒衮冕，手持玉圭，长须端庄，至尊威仪',
  '西王母': '昆仑女仙之首，凤冠霞帔，手持蟠桃玉杖，雍容华贵，仙姿威仪',
  '太上老君': '道祖神格，鹤发童颜，白须白眉，手持拂尘与丹葫芦，骑青牛，仙风道骨',
  '二郎神': '天庭战神真君，额生天眼，手持三尖两刃刀，银甲白袍，英武冷峻，哮天犬随行',
  '哪吒': '莲花化身的少年战神，脚踏风火轮，手持火尖枪，臂缠混天绫，项戴乾坤圈',
  '孙悟空': '斗战胜佛，猴相金睛，身披黄金锁子甲，头戴凤翅紫金冠，手持如意金箍棒',
  '后羿': '射日英雄，身背神弓箭囊，猎装劲束，目光如炬，挽弓射天之姿',
  '嫦娥': '月宫仙子，广袖流仙裙，怀抱玉兔，裙带当风，清冷绝尘',
  '真武大帝': '北方玄天上帝，披发跣足，玄袍金甲，仗剑而立，脚踏龟蛇',
  '关帝': '武圣神格，红面长髯，绿袍金甲，手持青龙偃月刀，凛然正气',
  '妈祖': '海上守护女神，凤冠霞帔，手持如意，慈眉善目，海浪祥云相伴',
  '财神': '司财正神，黑面浓须，头戴铁冠，手持钢鞭，身骑黑虎，元宝金光相随',
  '钟馗': '驱邪判官，豹头环眼，铁面虬髯，绯袍乌帽，仗剑怒目',
  '姜子牙': '封神太师，白发白须，手持打神鞭与杏黄旗，道袍飘然，骑四不像',
  '刑天': '不屈战神，无首而立，以乳为目、以脐为口，一手持干盾一手执戚斧',
  '夸父': '逐日巨人，身形魁伟如山，手持桃木杖，大步奔行于山川大地之间',
  '精卫': '填海神鸟所化的少女神，衣袂素白，身旁花首白喙赤足神鸟衔石，翱翔于怒海之上',
  '东皇太一': '上古至高天帝，冕服执长剑，神光浩荡，星辰环绕',
  '后土': '大地之母，凤冠帝服，手持宝印，端庄厚重，携山川黄土之气',
  '雷公': '司雷之神，鸟喙肉翅，手持雷锤凿钻，环绕连鼓，电光缠身',
  '龙王': '司雨水族之王，龙首人身，金鳞铠甲，手持定海珠，风雨云涛相随',
  '共工': '上古水神，人面蛇身赤发，周身怒涛洪水环绕，狂放不羁',
  '祝融': '上古火神，兽身人面，乘双龙，周身火光赤霞环绕，威烈庄严',
  '月老': '姻缘之神，白须慈颜，手持姻缘簿与红线，宽袍大袖，月下祥和',
  '土地公': '一方守护福神，白须笑颜，员外袍服，手持拐杖与元宝，和蔼亲切',
  '灶王爷': '司灶福神，官帽官袍，长须慈和，手持笏板，烟火人间气',
  '阎王': '幽冥之主，冕冠玄袍，面容威严，手持生死簿与判官笔，森然正气',
  '孟婆': '幽冥忘川之神，苍发布衣，手持汤碗与木勺，立于奈何桥头，沧桑慈悲',
};

const ALIAS = {
  '杨戬': '二郎神',
  '齐天大圣': '孙悟空',
  '玉帝': '玉皇大帝',
  '王母': '西王母',
  '王母娘娘': '西王母',
  '老君': '太上老君',
  '关公': '关帝',
  '关羽': '关帝',
  '关圣帝君': '关帝',
  '赵公明': '财神',
  '武财神': '财神',
  '雷神': '雷公',
  '天后': '妈祖',
  '阎罗': '阎王',
  '阎罗王': '阎王',
  '灶神': '灶王爷',
  '土地爷': '土地公',
  '玄天上帝': '真武大帝',
};

const FALLBACK_DESC = '中国神话中的正神，衣冠、法器与坐骑严格符合其经典神格形象与古籍记载，庄严神圣';

function jsonEscape(s) {
  return JSON.stringify(String(s)).slice(1, -1);
}

// 恰好替换一次；出现次数不为 1 时报错终止，防止误伤其他节点
function replaceExactlyOnce(raw, find, replacement, label) {
  let count = 0;
  let idx = -1;
  if (find instanceof RegExp) {
    const m = raw.match(new RegExp(find.source, 'g'));
    count = m ? m.length : 0;
  } else {
    let k = -1;
    while ((k = raw.indexOf(find, k + 1)) > -1) { count++; idx = idx < 0 ? k : idx; }
  }
  if (count !== 1) {
    throw new Error(`[${label}] 锚点在母版中出现 ${count} 次（应为 1 次），已终止。锚点: ${find}`);
  }
  if (find instanceof RegExp) {
    return raw.replace(find, () => replacement);
  }
  return raw.slice(0, idx) + replacement + raw.slice(idx + find.length);
}

// 改写开始节点某个输出参数的 defaultValue（锚定 "name" 与 "defaultValue" 近邻，全文必须恰好一处）
function replaceParamDefault(raw, param, newVal, span, label) {
  const re = new RegExp(
    '("name": "' + param + '"[\\s\\S]{0,' + span + '}?"defaultValue": ")[^"]*(")'
  );
  const m = raw.match(new RegExp(re.source, 'g'));
  const count = m ? m.length : 0;
  if (count !== 1) {
    throw new Error(`[${label}] 锚点在母版中出现 ${count} 次（应为 1 次），已终止`);
  }
  if (!m[0].includes('"required"')) {
    throw new Error(`[${label}] 匹配到的不是开始节点输出（缺少 required 字段），已终止`);
  }
  return raw.replace(re, (_, p1, p2) => p1 + jsonEscape(String(newVal)) + p2);
}

function parseArgs(argv) {
  const args = { _: [] };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--list') args.list = true;
    else if (a === '--desc' || a === '--wenan' || a === '--base' || a === '--out'
      || a === '--shuliang' || a === '--audio' || a === '--yinse' || a === '--cankao') {
      args[a.slice(2)] = argv[++i];
    } else if (a === '-h' || a === '--help') args.help = true;
    else args._.push(a);
  }
  return args;
}

function main() {
  const args = parseArgs(process.argv.slice(2));

  if (args.list) {
    console.log('内置形象库（不在库中的神请用 --desc 提供形象描述）:\n');
    for (const [k, v] of Object.entries(GOD_DESC)) console.log(`  ${k}：${v}`);
    console.log('\n别名: ' + Object.entries(ALIAS).map(([a, b]) => `${a}→${b}`).join('、'));
    return;
  }

  if (args.help || args._.length !== 1) {
    console.log('用法: node generate-god-template.js <神名> [--desc 形象描述] [--wenan 解说文案] [--cankao 参考文案] [--shuliang 数量] [--audio BGM链接] [--yinse 音色ID] [--base 母版] [--out 输出]');
    console.log('      node generate-god-template.js --list');
    process.exitCode = args.help ? 0 : 1;
    return;
  }

  const god = args._[0].trim();
  const basePath = args.base ? path.resolve(args.base) : DEFAULT_BASE;
  const outPath = args.out ? path.resolve(args.out) : path.join(__dirname, `神工作流模板_${god}-v7.json`);

  let desc = args.desc ? args.desc.trim().replace(/。+$/, '') : null;
  if (!desc) {
    const key = GOD_DESC[god] ? god : ALIAS[god];
    desc = key ? GOD_DESC[key] : null;
    if (!desc) {
      desc = FALLBACK_DESC;
      console.warn(`⚠ 「${god}」不在内置形象库中，已使用通用描述。建议用 --desc 指定形象，如:`);
      console.warn(`  node generate-god-template.js ${god} --desc "手持XX法器，XX袍服，XX气质"`);
    }
  }

  let raw = fs.readFileSync(basePath, 'utf8');
  let bom = '';
  if (raw.charCodeAt(0) === 0xFEFF) { bom = '﻿'; raw = raw.slice(1); }

  // 从母版解析出旧神名（只读，不用于序列化）
  const doc = JSON.parse(raw);
  const nodes = doc && doc.json && doc.json.nodes;
  if (!Array.isArray(nodes)) throw new Error('母版结构异常：找不到 json.nodes');
  const start = nodes.find(n => String(n.type) === '1');
  if (!start) throw new Error('母版结构异常：找不到开始节点');
  const zhutiOut = (start.data.outputs || []).find(o => o.name === 'zhuti');
  const oldGod = zhutiOut && zhutiOut.defaultValue;
  if (!oldGod) throw new Error('母版结构异常：开始节点没有 zhuti 默认值');

  if (oldGod === god) {
    console.warn(`⚠ 母版主神已经是「${god}」，仍会按当前参数重写 3 个默认值。`);
  }

  const godEsc = jsonEscape(god);

  // 1) fengge 默认值中的主神形象句（先替换长句，再替换短锚点）
  raw = replaceExactlyOnce(
    raw,
    /主神形象必须贴合：[^。"]+。/,
    `主神形象必须贴合：${godEsc}为${jsonEscape(desc)}。`,
    'fengge 主神形象句'
  );

  // 2) wenan 默认值
  const wenanText = args.wenan
    ? args.wenan.trim()
    : `${god}的身份背景、成名经历、最重要的经历、记忆点的传说、象征能力与文化影响`;
  raw = replaceExactlyOnce(
    raw,
    /"defaultValue": "[^"]*的身份背景、成名经历、最重要的经历、记忆点的传说、象征能力与文化影响"/,
    `"defaultValue": "${jsonEscape(wenanText)}"`,
    'wenan 默认值'
  );

  // 3) zhuti 默认值
  raw = replaceExactlyOnce(
    raw,
    `"defaultValue": "${oldGod}"`,
    `"defaultValue": "${godEsc}"`,
    'zhuti 默认值'
  );

  // 4) 可选：数量/背景音乐/音色默认值（未提供则沿用母版）
  if (args.shuliang !== undefined && String(args.shuliang).trim() !== '') {
    const n = parseInt(String(args.shuliang).trim(), 10);
    if (!Number.isInteger(n) || n < 1 || n > 22) {
      throw new Error(`--shuliang 必须是 1~22 的整数，收到: ${args.shuliang}`);
    }
    raw = replaceParamDefault(raw, 'shuliang', String(n), 300, 'shuliang 默认值');
  }
  if (args.audio !== undefined && String(args.audio).trim() !== '') {
    raw = replaceParamDefault(raw, 'audio', String(args.audio).trim(), 600, 'audio 默认值');
  }
  if (args.yinse !== undefined && String(args.yinse).trim() !== '') {
    const vid = String(args.yinse).trim();
    // 开始节点 yinse 是死参数（无节点引用），真正生效的是 3 个配音节点写死的 voice_id：
    // 开场配音 310628 / 标题配音 1711088 / 正文循环内分镜配音 135573/102982
    raw = replaceParamDefault(raw, 'yinse', vid, 300, 'yinse 默认值');
    const vre = /("name": "voice_id",\s*"input": \{\s*"type": "string",\s*"value": \{\s*"type": "literal",\s*"content": ")[^"]*(")/g;
    const vm = raw.match(vre);
    if (!vm || vm.length !== 3) {
      throw new Error(`voice_id 取值槽出现 ${vm ? vm.length : 0} 处（应为 3：开场/标题/正文配音），已终止`);
    }
    raw = raw.replace(vre, (_, p1, p2) => p1 + jsonEscape(vid) + p2);
  }
  if (args.cankao !== undefined && String(args.cankao).trim() !== '') {
    raw = replaceParamDefault(raw, 'cankao', String(args.cankao).trim(), 400, 'cankao 默认值');
  }

  fs.writeFileSync(outPath, bom + raw, 'utf8');

  // 自校验：可解析、节点数一致、默认值已生效
  const check = JSON.parse(fs.readFileSync(outPath, 'utf8').replace(/^﻿/, ''));
  const cNodes = check.json.nodes;
  const cStart = cNodes.find(n => String(n.type) === '1');
  const cOuts = cStart.data.outputs;
  const pick = name => cOuts.find(o => o.name === name);
  const ok =
    cNodes.length === nodes.length &&
    pick('zhuti').defaultValue === god &&
    pick('fengge').defaultValue.includes(`主神形象必须贴合：${god}为${desc}。`) &&
    (args.shuliang === undefined || String(args.shuliang).trim() === '' ||
      pick('shuliang').defaultValue === String(parseInt(String(args.shuliang).trim(), 10))) &&
    (args.audio === undefined || String(args.audio).trim() === '' ||
      pick('audio').defaultValue === String(args.audio).trim()) &&
    (args.yinse === undefined || String(args.yinse).trim() === '' ||
      pick('yinse').defaultValue === String(args.yinse).trim()) &&
    (args.cankao === undefined || String(args.cankao).trim() === '' ||
      (pick('cankao') && pick('cankao').defaultValue === String(args.cankao).trim()));
  let voiceOk = true;
  if (args.yinse !== undefined && String(args.yinse).trim() !== '') {
    const vid = String(args.yinse).trim();
    const voices = [];
    (function walk(list) {
      for (const nd of list || []) {
        for (const p of ((nd.data && nd.data.inputs && nd.data.inputs.inputParameters) || [])) {
          if (p.name === 'voice_id' && p.input && p.input.value && p.input.value.type === 'literal') {
            voices.push(p.input.value.content);
          }
        }
        if (nd.blocks) walk(nd.blocks);
        if (nd.data && nd.data.blocks) walk(nd.data.blocks);
      }
    })(cNodes);
    voiceOk = voices.length === 3 && voices.every(v => v === vid);
  }
  if (!ok || !voiceOk) throw new Error('自校验失败，请勿使用生成文件');

  console.log(`✔ 已生成: ${outPath}`);
  console.log(`  主神(zhuti): ${oldGod} → ${god}`);
  console.log(`  形象描述: ${desc}`);
  console.log(`  解说文案: ${wenanText}`);
  console.log(`  节点数: ${cNodes.length}（与母版一致），除 3 个默认值外与母版逐字节相同`);
  console.log('  直接把整份 JSON 复制到 Coze 画布粘贴即可导入。');
}

main();
