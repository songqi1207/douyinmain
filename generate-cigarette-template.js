#!/usr/bin/env node
'use strict';

// 香烟工作流模板生成器
// 以 烟工作流模板_香烟鉴赏-v1.json 为母版（由 v7 神模板主题化派生），输入烟名，
// 生成一份除开始节点默认值外与母版逐字节一致的新模板。
//
// 用法:
//   node generate-cigarette-template.js <烟名>
//   node generate-cigarette-template.js 玉溪 --shuliang 12
//   node generate-cigarette-template.js --list          # 查看内置画面气质库
//
// 可选参数:
//   --desc  <文>  画面气质描述（接在"这款烟画面气质必须贴合:<烟名>为"之后，不带句号）
//   --wenan <文>  解说方向默认值（缺省: <烟名>的品牌来历、产地年代、…）
//   --cankao <文> 参考文案默认值（非空则运行时走 137312 爆款改写模式；缺省为空走 176492 品牌解说）
//   --shuliang <数> 分镜/生图数量默认值（1~22，缺省沿用母版）
//   --audio <URL> 背景音乐默认值（缺省沿用母版）
//   --yinse <ID>  配音音色默认值（缺省沿用母版）
//   --texiao <名> 全片画面特效（剪映特效库名字，如 大雪纷飞II；缺省金粉闪闪，结尾1.8s金粉闪闪爆发层始终保留）
//   --base  <路径> 母版文件（注意 --texiao 依赖母版原始特效行，请勿以已换特效的产物为母版）
//   --out   <路径> 输出文件（缺省 烟工作流模板_<烟名>-v1.json）
//
// 与换神生成器同一套机制：字节级定点替换，不重新序列化 JSON。

const fs = require('fs');
const path = require('path');

const DEFAULT_BASE = path.join(__dirname, '烟工作流模板_香烟鉴赏-v1.json');

// 内置画面气质库：值为"<烟名>为"之后的谓语部分（不带句号）
const CIG_DESC = {
  '中华': '天安门红与描金的国民体面,庄重大气的年代质感',
  '玉溪': '青瓷白与烟田晨雾的清雅,滇中坝子的温润质感',
  '红塔山': '红塔剪影与滇中阳光,九十年代国民烟的踏实暖调',
  '芙蓉王': '鎏金黄与商务沉稳,世纪之交的体面与野心',
  '黄鹤楼': '楼影金橙与江城暮色,楚地风韵的雅致',
  '利群': '蓝灰与江南烟雨,平实耐处的市井温度',
  '南京': '金陵紫金与民国街景,六朝烟水气',
  '云烟': '云岭红土与烟叶金黄,云南烟草的本色',
  '双喜': '大红喜庆与市井烟火,粤地婚宴的热闹体面',
  '白沙': '银白鹤影与湘江晨雾,飞翔意象的轻盈',
  '七匹狼': '深蓝与海风硬朗,闽南江湖气',
  '黄金叶': '麦浪金黄与中原厚土,朴实的粮仓气质',
  '银钗': '淡绿烟盒与银灰线条,薄荷微凉的清晨气息',
  '金陵十二钗': '金陵画卷与钗影,古典婉约的江南气韵',
};

const FALLBACK_DESC = '经典国产卷烟的年代质感,包装主色调的复古胶片氛围';

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
    console.log('内置画面气质库（不在库中的烟请用 --desc 提供画面气质）:\n');
    for (const [k, v] of Object.entries(CIG_DESC)) console.log(`  ${k}：${v}`);
    return;
  }

  if (args.help || args._.length !== 1) {
    console.log('用法: node generate-cigarette-template.js <烟名> [--desc 画面气质] [--wenan 解说方向] [--cankao 参考文案] [--shuliang 数量] [--audio BGM链接] [--yinse 音色ID] [--base 母版] [--out 输出]');
    console.log('      node generate-cigarette-template.js --list');
    process.exitCode = args.help ? 0 : 1;
    return;
  }

  const cig = args._[0].trim();
  const basePath = args.base ? path.resolve(args.base) : DEFAULT_BASE;
  const outPath = args.out ? path.resolve(args.out) : path.join(__dirname, `烟工作流模板_${cig}-v1.json`);

  let desc = args.desc ? args.desc.trim().replace(/。+$/, '') : null;
  if (!desc) {
    desc = CIG_DESC[cig] || null;
    if (!desc) {
      desc = FALLBACK_DESC;
      console.warn(`⚠ 「${cig}」不在内置画面气质库中，已使用通用描述。建议用 --desc 指定画面气质，如:`);
      console.warn(`  node generate-cigarette-template.js ${cig} --desc "包装主色与年代场景,XX色调,XX气质"`);
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
  const oldCig = zhutiOut && zhutiOut.defaultValue;
  if (!oldCig) throw new Error('母版结构异常：开始节点没有 zhuti 默认值');

  if (oldCig === cig) {
    console.warn(`⚠ 母版主烟已经是「${cig}」，仍会按当前参数重写默认值。`);
  }

  const cigEsc = jsonEscape(cig);

  // 1) fengge 默认值中的画面气质句
  raw = replaceExactlyOnce(
    raw,
    /这款烟画面气质必须贴合:[^。"]+。/,
    `这款烟画面气质必须贴合:${cigEsc}为${jsonEscape(desc)}。`,
    'fengge 画面气质句'
  );

  // 2) wenan 默认值
  const wenanText = args.wenan
    ? args.wenan.trim()
    : `${cig}的名字与包装意象、系列典故、口感层次、可寄托的情感记忆`;
  raw = replaceExactlyOnce(
    raw,
    /"defaultValue": "[^"]*的名字与包装意象、系列典故、口感层次、可寄托的情感记忆"/,
    `"defaultValue": "${jsonEscape(wenanText)}"`,
    'wenan 默认值'
  );

  // 3) zhuti 默认值
  raw = replaceExactlyOnce(
    raw,
    `"defaultValue": "${oldCig}"`,
    `"defaultValue": "${cigEsc}"`,
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
    pick('zhuti').defaultValue === cig &&
    pick('fengge').defaultValue.includes(`这款烟画面气质必须贴合:${cig}为${desc}。`) &&
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
  console.log(`  主烟(zhuti): ${oldCig} → ${cig}`);
  console.log(`  画面气质: ${desc}`);
  console.log(`  解说方向: ${wenanText}`);
  if (texiao) console.log(`  全片特效: ${texiao}（结尾金粉闪闪爆发层保留）`);
  console.log(`  节点数: ${cNodes.length}（与母版一致），除开始节点默认值外与母版逐字节相同`);
  console.log('  直接把整份 JSON 复制到 Coze 画布粘贴即可导入。');
}

main();
