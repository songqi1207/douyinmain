#!/usr/bin/env node
/**
 * 书单荐书工作流生成器（2026-07-08 换底：书籍解读 → 书单荐书风格）
 *
 * 母版：书单工作流模板_荐书-v1.json（本会话从「哲学」神派生工作流改造而来）。
 * 风格：开场 10 张固定通用书封轮换（竖屏 1080x1920）→ 文学荐书体旁白（LLM 由书名生成）
 *       → AI 正文配图 + 神工作流同款运镜。每次生成只变「旁白讲的这本书」+ 配图，
 *       开场 10 张书封固定不动（用户 2026-07-08 定：固定一套通用书封）。
 *
 * 用法：
 *   node generate-book-template.js <书名> [选项]
 * 选项：
 *   --desc <画面气质>   注入配图提示词的视觉方向（可选）
 *   --wenan <资料>      这本书的资料/摘要，注入旁白提示词做事实锚定（不照抄，可选）
 *   --cankao <参考文案> 参考文案，供旁白化用立意/金句（用自己的话重写，可选）
 *   --shuliang <N>      正文配图张数（→ 开始节点 img_count，默认沿用母版 6）
 *   --audio <BGM链接>   背景音乐链接（→ 104671 bg_music）
 *   --yinse <音色ID>    配音音色（→ 开始节点 yinse，全片 3 处配音统一走它）
 *   --texiao <特效>     兼容旧接口，书单母版无独立特效层，忽略
 *   --base <母版路径>   默认 书单工作流模板_荐书-v1.json
 *   --out <输出路径>    默认打印到 stdout
 */

'use strict';

const fs = require('fs');
const path = require('path');

const DEFAULT_BASE = path.join(__dirname, '书单工作流模板_荐书-v1.json');

const BOOK_IMAGE_USER_PROMPT = `书名：{{subject}}
作者：{{author}}
正文字幕时间线：{{wenanTimeline}}
配图数量：{{img_count}}

请严格按正文叙事顺序，将全部字幕划分为恰好 {{img_count}} 个连续视觉章节，并为每章生成一条与《{{subject}}》内容直接相关的配图提示词。所有章节合起来必须完整覆盖字幕时间线。`;

const BOOK_IMAGE_SYSTEM_PROMPT = `# 角色
你是文学作品视觉改编导演，负责把荐书口播转化为忠于书籍主体的竖屏视频配图。书名、作者和当前字幕是最高优先级依据，禁止套用与本书无关的通用哲学画面。

# 核心要求
1. 先确认书名、作者、时代背景、地域环境、主要人物及标志性事件，再理解当前视觉章节表达的具体内容。
2. 每个提示词必须直接呈现该书相关的具体人物、场景、物件或事件。优先使用原作中可识别的环境、服饰、建筑、生活细节和人物关系，不能只写“孤独的人影”“抽象宇宙”“迷宫”“破碎面孔”等万能意象。
3. 画面主体必须与当前章节字幕一致。字幕讲人物就画该人物及其行动；讲地点就画该地点；讲关键情节就画该情节；讲作品主题时，也要用书中的人物、场景或标志性物件承载主题。
4. 对知名作品，使用可靠的原作常识校准人物身份、历史年代和环境，不得串入其他作品的人物、服饰或世界观。对不熟悉的作品，只依据书名、作者和字幕中明确出现的信息，不得编造具体姓名或情节。
5. 同一本书的全部图片保持统一的时代、人物外观、服装、色彩和绘画风格。人物再次出现时，年龄、发型、服饰和气质保持连续。
6. 可以艺术化，但必须“内容准确优先”。仅当字幕本身表达抽象思想时才允许象征表达，而且象征物必须来自本书已出现的场景或物件。
7. 每条提示词使用中文，包含：主体身份与动作、具体环境、时代与服饰、镜头构图、光线、色彩、情绪、统一艺术风格。画面为竖屏 9:16，电影感叙事插画，细节丰富。
8. 图片中不得出现书名、字幕、文字、标志、水印、UI、边框或书籍封面排版；不要生成现代摄影棚、无关名人或与原作时代冲突的物品。

# 分组与时间线
- 按语义和情节转折划分视觉章节，不要机械按字数截断。
- 必须输出恰好用户指定的数量，不多不少。
- 每项 start 等于本章第一句字幕的 start，end 等于本章最后一句字幕的 end。
- 第一项从全部字幕的最早 start 开始，最后一项到全部字幕的最晚 end 结束；相邻章节连续且不重叠、不留空档。

# 输出格式
只输出 JSON 数组，不要 Markdown，不要解释：
[
  {
    "img_prompt": "与该书及本章字幕直接相关的中文绘画提示词",
    "start": 1000000,
    "end": 5000000
  }
]`;

function parseArgs(argv) {
  const out = { _: [] };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--desc' || a === '--wenan' || a === '--cankao' || a === '--shuliang'
      || a === '--audio' || a === '--yinse' || a === '--texiao' || a === '--author'
      || a === '--base' || a === '--out') {
      out[a.slice(2)] = argv[++i];
    } else {
      out._.push(a);
    }
  }
  return out;
}

function loadTemplate(p) {
  let t = fs.readFileSync(p, 'utf8');
  if (t.charCodeAt(0) === 0xFEFF) t = t.slice(1);
  return JSON.parse(t);
}

function nodeById(doc, id) {
  return doc.json.nodes.find((n) => n.id === id);
}

// 设开始节点某个输出的默认值
function setStartDefault(doc, name, value) {
  const start = nodeById(doc, '100001');
  const o = (start.data.outputs || []).find((x) => x.name === name);
  if (!o) throw new Error(`开始节点没有输出 ${name}`);
  o.defaultValue = value;
  return true;
}

// 设某节点某个 inputParameter 字面量
function setLiteral(doc, nodeId, paramName, content) {
  const n = nodeById(doc, nodeId);
  if (!n) throw new Error(`节点 ${nodeId} 不存在`);
  const p = (n.data.inputs.inputParameters || []).find((x) => x.name === paramName);
  if (!p) throw new Error(`节点 ${nodeId} 没有参数 ${paramName}`);
  p.input.value = { type: 'literal', content, rawMeta: { type: 1 } };
}

// 取某 LLM 节点的某段提示词
function llmPrompt(doc, nodeId, which) {
  const n = nodeById(doc, nodeId);
  const p = (n.data.inputs.llmParam || []).find((x) => x.name === which);
  if (!p) throw new Error(`节点 ${nodeId} 没有 ${which}`);
  return p;
}

function ensureRefInput(doc, nodeId, name, blockID, outputName) {
  const n = nodeById(doc, nodeId);
  if (!n) throw new Error(`节点 ${nodeId} 不存在`);
  const params = n.data.inputs.inputParameters || (n.data.inputs.inputParameters = []);
  let item = params.find((x) => x.name === name);
  if (!item) {
    item = { name, input: { type: 'string', value: {} } };
    params.push(item);
  }
  item.input = {
    type: 'string',
    value: {
      type: 'ref',
      content: { source: 'block-output', blockID, name: outputName },
      rawMeta: { type: 1 },
    },
  };
}

function applyBookImagePrompt(doc) {
  ensureRefInput(doc, '172269', 'subject', '100001', 'subject');
  ensureRefInput(doc, '172269', 'author', '100001', 'author');
  llmPrompt(doc, '172269', 'prompt').input.value.content = BOOK_IMAGE_USER_PROMPT;
  llmPrompt(doc, '172269', 'systemPrompt').input.value.content = BOOK_IMAGE_SYSTEM_PROMPT;
}

function main() {
  const args = parseArgs(process.argv.slice(2));
  const bookName = (args._[0] || '').trim();
  if (!bookName) {
    console.error('用法: node generate-book-template.js <书名> [--author 作者] [--desc 画面气质] [--wenan 资料] [--cankao 参考文案] [--shuliang 张数] [--audio BGM链接] [--yinse 音色ID] [--base 母版] [--out 输出]');
    process.exit(1);
  }
  const basePath = args.base || DEFAULT_BASE;
  const doc = loadTemplate(basePath);

  const changes = [];

  // 始终修正历史母版中遗留的“泛哲学抽象画”提示词，让正文配图锚定本书。
  applyBookImagePrompt(doc);
  changes.push('正文配图提示词(172269): 已按书名、作者和字幕锚定');

  // 1) 书名 → 旁白主题（开始节点 subject）
  setStartDefault(doc, 'subject', bookName);
  changes.push(`书名(subject): ${bookName}`);

  // 1b) 作者 → 开场"《书名》 作者著"字幕（开始节点 author）
  if (args.author && String(args.author).trim() !== '') {
    setStartDefault(doc, 'author', String(args.author).trim());
    changes.push(`作者(author): ${args.author}`);
  }

  // 2) 配图张数 → img_count
  if (args.shuliang && String(args.shuliang).trim() !== '') {
    setStartDefault(doc, 'img_count', String(args.shuliang).trim());
    changes.push(`配图张数(img_count): ${args.shuliang}`);
  }

  // 3) 音色 → yinse（3 处配音都引 100001.yinse）
  if (args.yinse && String(args.yinse).trim() !== '') {
    setStartDefault(doc, 'yinse', String(args.yinse).trim());
    changes.push(`音色(yinse): ${args.yinse}`);
  }

  // 4) BGM → 104671 bg_music
  if (args.audio && String(args.audio).trim() !== '') {
    setLiteral(doc, '104671', 'bg_music', String(args.audio).trim());
    changes.push('BGM(104671.bg_music): 已替换');
  }

  // 5) 旁白事实锚定：资料/参考文案注入 157315 用户提示词（不照抄）
  const grounds = [];
  if (args.wenan && String(args.wenan).trim() !== '') {
    grounds.push(`【关于这本书的资料，仅供你了解，不要照抄原句】：${String(args.wenan).trim()}`);
  }
  if (args.cankao && String(args.cankao).trim() !== '') {
    grounds.push(`【参考文案，可化用其立意与金句，但必须用你自己的话重写】：${String(args.cankao).trim()}`);
  }
  if (grounds.length) {
    const p = llmPrompt(doc, '157315', 'prompt');
    p.input.value.content = p.input.value.content + '\n\n' + grounds.join('\n\n');
    changes.push(`旁白锚定(157315): 注入 ${grounds.length} 段参考`);
  }

  // 6) 画面气质 → 172269 配图提示词系统提示追加
  if (args.desc && String(args.desc).trim() !== '') {
    const p = llmPrompt(doc, '172269', 'systemPrompt');
    p.input.value.content = p.input.value.content + `\n\n【本片视觉气质要求】：${String(args.desc).trim()}`;
    changes.push('画面气质(172269): 已追加');
  }

  // 7) --texiao 兼容旧接口，书单母版无独立特效层
  if (args.texiao && String(args.texiao).trim() !== '') {
    changes.push('（--texiao 已忽略：书单母版无独立特效层）');
  }

  const output = JSON.stringify(doc);
  if (args.out) {
    fs.writeFileSync(args.out, output);
    console.log('已生成书单荐书工作流：');
    changes.forEach((c) => console.log('  ' + c));
    console.log(`  节点数: ${doc.json.nodes.length}（开场 10 张书封固定不动）`);
    console.log(`  输出: ${args.out}`);
    console.log('  直接把整份 JSON 复制到 Coze 画布粘贴即可导入。');
  } else {
    process.stdout.write(output);
  }
}

main();
