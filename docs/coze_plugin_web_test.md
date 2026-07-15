# Coze 插件网页自动化测试

这套脚本用于直接操作 Coze 插件调试页，验证某个工具作为 Coze 插件时是否能正常使用。

当前实现是“半自动网页测试”：

- 第一次运行时，需要你在浏览器里手工登录 Coze
- 登录态会保存在本地，下次可直接复用
- 登录后脚本会自动：
  - 打开插件页
  - 尝试切换到指定工具
  - 填入调试参数
  - 点击“运行”
  - 保存截图和响应结果

## 适用场景

- 验证 `add_images` / `add_captions` / `add_audios` 等工具在 Coze 页面里能否正常调试
- 验证工具是否启用
- 验证页面上返回的是成功、超时还是参数错误

## 安装

在项目根目录执行：

```bash
npm install
npx playwright install chromium
```

## 基本用法

```bash
npm run test:coze-plugin -- \
  --url "https://www.coze.cn/space/7660814090591584275/plugin/7660820108490604607" \
  --tool add_images \
  --payload-file docs/coze_add_images_payload.sample.json
```

## 首次登录

第一次运行通常会弹出浏览器并停住，等待你手工登录 Coze。

完成登录后，回到终端按一次 Enter，脚本会继续执行。

登录态保存在：

```text
temp/coze_ui_test/profile
```

## 输出结果

每次运行会在下面目录生成结果：

```text
temp/coze_ui_test/<时间戳>/
```

其中包含：

- `before-fill.png`
- `after-fill.png`
- `after-run.png`
- `failure.png`（失败时）
- `result.json`

`result.json` 会包含：

- 当前页面 URL
- 工具名
- 响应文本摘要
- 结果目录

## 示例：测试 add_images

示例 payload 文件见：

```text
docs/coze_add_images_payload.sample.json
```

运行命令：

```bash
npm run test:coze-plugin -- \
  --url "https://www.coze.cn/space/7660814090591584275/plugin/7660820108490604607" \
  --tool add_images \
  --payload-file docs/coze_add_images_payload.sample.json
```

## 可选参数

- `--headless true`
  以无头模式运行。首次登录不建议开。

- `--timeout-ms 30000`
  设置页面操作和调试等待超时，默认 `20000`

- `--wait-login false`
  不等待手工登录，适合你已经确定登录态可用时使用

- `--payload-json '{"draft_id":"..."}'`
  直接传内联 JSON，而不是文件

## 当前限制

- 这不是官方 API，而是网页 UI 自动化，所以 Coze 页面结构变动后可能要调脚本
- 当前脚本更适合测试常见表单工具，尤其是：
  - `add_images`
  - `add_captions`
  - `add_audios`
  - `get_draft`
- 如果参数表里有复杂选择器、下拉框、多层数组，可能需要再补定制逻辑

## 建议测试顺序

建议先测这些最小链路：

1. `get_draft`
2. `add_images`
3. `add_captions`
4. `add_audios`
5. `add_effects`

这样可以先确认草稿 ID、插件启用状态和基本写入能力。
