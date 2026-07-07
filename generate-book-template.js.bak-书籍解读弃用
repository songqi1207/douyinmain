#!/usr/bin/env node
'use strict';

// 书籍工作流模板生成器
// 以 书工作流模板_书籍解读-v1.json 为母版（由 v7 神模板主题化派生），输入书名，
// 生成一份除开始节点默认值外与母版逐字节一致的新模板。
//
// 用法:
//   node generate-book-template.js <书名>
//   node generate-book-template.js 围城 --desc "民国上海与旅途客船的灰调胶片,旧西装、汽灯、雨巷"
//   node generate-book-template.js 三体 --shuliang 14 --out xxx.txt
//   node generate-book-template.js --list          # 查看内置画面气质库
//
// 可选参数:
//   --desc  <文>  画面气质描述（接在"本书画面气质必须贴合:《书名》为"之后，不带句号）
//   --wenan <文>  解说方向默认值（缺省: <书名>的核心主题、成书背景、…）
//   --cankao <文> 参考文案默认值（非空则运行时走 137312 爆款改写模式；缺省为空走 176492 解读旁白）
//   --shuliang <数> 分镜/生图数量默认值（1~22，缺省沿用母版）
//   --audio <URL> 背景音乐默认值（缺省沿用母版）
//   --yinse <ID>  配音音色默认值（缺省沿用母版）
//   --texiao <名> 全片画面特效（剪映特效库名字，如 大雪纷飞II；缺省金粉闪闪，结尾1.8s金粉闪闪爆发层始终保留）
//   --base  <路径> 母版文件（注意 --texiao 依赖母版原始特效行，请勿以已换特效的产物为母版）
//   --out   <路径> 输出文件（缺省 书工作流模板_<书名>-v1.json）
//
// 与换神生成器同一套机制：字节级定点替换，不重新序列化 JSON。

const fs = require('fs');
const path = require('path');

const DEFAULT_BASE = path.join(__dirname, '书工作流模板_书籍解读-v1.json');

// 内置画面气质库：值为"《书名》为"之后的谓语部分（不带句号）
const BOOK_DESC = {
  '活着': '二十世纪中国乡土的做旧胶片色调,土黄、灰青、烟褐,苦难中的平静',
  '围城': '民国上海与旅途客船的灰调胶片,旧西装、汽灯、雨巷,讽刺下的苍凉',
  '三体': '红色年代基地与深空寒光交错的冷色调,钢铁、雪原、星空,理性的孤独',
  '红楼梦': '大观园的工笔气韵与暖烛冷月,朱楼、纱窗、残雪,繁华将尽的凉意',
  '百年孤独': '拉美小镇的湿热黄昏,香蕉林、老宅、细雨,魔幻而衰败',
  '平凡的世界': '黄土高原的窑洞与麦田,尘土金黄、青灰山峁,苦中带光的年代感',
  '白鹿原': '关中平原的麦浪祠堂与土墙,厚重土黄、暗褐,家族兴衰的沉郁',
  '老人与海': '加勒比海上的孤舟与烈日,靛蓝海面、盐渍船板,硬朗的孤独',
  '边城': '湘西渡口的青山绿水与吊脚楼,烟雨青灰、竹绿,干净克制的哀愁',
  '骆驼祥子': '旧北平的胡同与黄包车,尘土灰黄、暮色昏黄,底层挣扎的年代感',
  '我与地坛': '北京老园子的四季光影,古柏、残墙、轮椅辙印,静穆的生命感',
  '人间失格': '昭和日本的夜色酒馆与纸窗,青灰、暗金,颓靡而清冷',
};

const FALLBACK_DESC = '贴合本书年代与地域的真实生活场景,低饱和做旧胶片色,朴素克制的文学质感';

function jsonEscape(s) {
  return JSON.stringify(String(s)).slice(1, -1);
}

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
      || a === '--shuliang' || a === '--audio' || a === '--yinse' || a === '--cankao'
      || a === '--texiao') {
      args[a.slice(2)] = argv[++i];
    } else if (a === '-h' || a === '--help') args.help = true;
    else args._.push(a);
  }
  return args;
}

function main() {
  const args = parseArgs(process.argv.slice(2));

  if (args.list) {
    console.log('内置画面气质库（不在库中的书请用 --desc 提供画面气质）:\n');
    for (const [k, v] of Object.entries(BOOK_DESC)) console.log(`  ${k}：${v}`);
    return;
  }

  if (args.help || args._.length !== 1) {
    console.log('用法: node generate-book-template.js <书名> [--desc 画面气质] [--wenan 解说方向] [--cankao 参考文案] [--shuliang 数量] [--audio BGM链接] [--yinse 音色ID] [--base 母版] [--out 输出]');
    console.log('      node generate-book-template.js --list');
    process.exitCode = args.help ? 0 : 1;
    return;
  }

  const book = args._[0].trim();
  const basePath = args.base ? path.resolve(args.base) : DEFAULT_BASE;
  const outPath = args.out ? path.resolve(args.out) : path.join(__dirname, `书工作流模板_${book}-v1.json`);

  let desc = args.desc ? args.desc.trim().replace(/。+$/, '') : null;
  if (!desc) {
    desc = BOOK_DESC[book] || null;
    if (!desc) {
      desc = FALLBACK_DESC;
      console.warn(`⚠ 「${book}」不在内置画面气质库中，已使用通用描述。建议用 --desc 指定画面气质，如:`);
      console.warn(`  node generate-book-template.js ${book} --desc "XX年代XX地域的场景,XX色调,XX气质"`);
    }
  }

  let raw = fs.readFileSync(basePath, 'utf8');
  let bom = '';
  if (raw.charCodeAt(0) === 0xFEFF) { bom = '﻿'; raw = raw.slice(1); }

  const doc = JSON.parse(raw);
  const nodes = doc && doc.json && doc.json.nodes;
  if (!Array.isArray(nodes)) throw new Error('母版结构异常：找不到 json.nodes');
  const start = nodes.find(n => String(n.type) === '1');
  if (!start) throw new Error('母版结构异常：找不到开始节点');
  const zhutiOut = (start.data.outputs || []).find(o => o.name === 'zhuti');
  const oldBook = zhutiOut && zhutiOut.defaultValue;
  if (!oldBook) throw new Error('母版结构异常：开始节点没有 zhuti 默认值');

  if (oldBook === book) {
    console.warn(`⚠ 母版主书已经是「${book}」，仍会按当前参数重写默认值。`);
  }

  const bookEsc = jsonEscape(book);

  // 1) fengge 默认值中的画面气质句
  raw = replaceExactlyOnce(
    raw,
    /本书画面气质必须贴合:[^。"]+。/,
    `本书画面气质必须贴合:《${bookEsc}》为${jsonEscape(desc)}。`,
    'fengge 画面气质句'
  );

  // 2) wenan 默认值
  const wenanText = args.wenan
    ? args.wenan.trim()
    : `${book}的核心主题、成书背景、书中人物命运、最打动人的段落、思想内核与现实意义`;
  raw = replaceExactlyOnce(
    raw,
    /"defaultValue": "[^"]*的核心主题、成书背景、书中人物命运、最打动人的段落、思想内核与现实意义"/,
    `"defaultValue": "${jsonEscape(wenanText)}"`,
    'wenan 默认值'
  );

  // 3) zhuti 默认值
  raw = replaceExactlyOnce(
    raw,
    `"defaultValue": "${oldBook}"`,
    `"defaultValue": "${bookEsc}"`,
    'zhuti 默认值'
  );

  // 4) 可选：数量/背景音乐/音色/参考文案默认值
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
  const texiao = args.texiao !== undefined ? String(args.texiao).trim() : '';
  if (texiao) {
    if (/['"\\\r\n]/.test(texiao)) throw new Error('--texiao 含非法字符（引号/反斜杠/换行），已终止');
    raw = replaceExactlyOnce(
      raw,
      "effect_titles_all = ['金粉闪闪', '金粉闪闪']",
      `effect_titles_all = ['${texiao}', '金粉闪闪']`,
      '全片画面特效'
    );
  }

  fs.writeFileSync(outPath, bom + raw, 'utf8');

  // 自校验
  const check = JSON.parse(fs.readFileSync(outPath, 'utf8').replace(/^﻿/, ''));
  const cNodes = check.json.nodes;
  const cStart = cNodes.find(n => String(n.type) === '1');
  const cOuts = cStart.data.outputs;
  const pick = name => cOuts.find(o => o.name === name);
  const ok =
    cNodes.length === nodes.length &&
    pick('zhuti').defaultValue === book &&
    pick('fengge').defaultValue.includes(`本书画面气质必须贴合:《${book}》为${desc}。`) &&
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
  let fxOk = true;
  if (texiao) {
    const c205 = cNodes.find(n => n.id === '175205');
    fxOk = !!c205 && c205.data.inputs.code.includes(`effect_titles_all = ['${texiao}', '金粉闪闪']`);
  }
  if (!ok || !voiceOk || !fxOk) throw new Error('自校验失败，请勿使用生成文件');

  console.log(`✔ 已生成: ${outPath}`);
  console.log(`  主书(zhuti): ${oldBook} → ${book}`);
  console.log(`  画面气质: ${desc}`);
  console.log(`  解说方向: ${wenanText}`);
  if (texiao) console.log(`  全片特效: ${texiao}（结尾金粉闪闪爆发层保留）`);
  console.log(`  节点数: ${cNodes.length}（与母版一致），除开始节点默认值外与母版逐字节相同`);
  console.log('  直接把整份 JSON 复制到 Coze 画布粘贴即可导入。');
}

main();
