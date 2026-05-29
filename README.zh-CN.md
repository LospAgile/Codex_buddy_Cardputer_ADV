# Codex Buddy Cardputer ADV Alice

[English README](README.md)

Codex Buddy Cardputer ADV Alice 可以把 M5Stack Cardputer ADV 变成一个
Codex 硬件桌宠和审批终端。

它会在设备上显示紧凑的 Codex 会话活动，显示 Alice 桌宠动画，并允许你直接在硬件
上批准或拒绝 Codex 权限请求。它支持 Codex CLI 和 Codex Desktop。默认使用 BLE，
也支持可选的 WiFi 长连接。

这个仓库是面向 Codex 重新实现的项目，不需要 Claude Desktop，不需要 Claude 硬件
权限，也不依赖 Anthropic 的硬件申请流程。

## 功能亮点

- M5Stack Cardputer ADV 上的 Alice 桌宠动画。
- 紧凑会话活动：`user`、`Agent`、`tool`。
- 硬件审批：`Y`、`Enter`、`Space` 批准；`N`、`Del`、`Back` 拒绝。
- Codex CLI 临时 hook 启动模式。
- Codex Desktop managed `PermissionRequest` hook 模式。
- macOS BLE helper，支持设备名过滤和可选配对码。
- 可选 WiFi bridge，支持本地 token。
- macOS 顶部菜单栏 App，面向普通用户启动和配置。
- 固件中英文 UI。
- PET Stats、SFX、LED 反馈、IMU 倾斜互动、自动休眠。
- 支持重新编译你自己的 Codex Desktop 宠物。
- 提供可直接烧录的 Alice release 固件。

## 目录结构

```text
daemon/              Mac 端 Python daemon 和 CLI
firmware/            M5Stack Cardputer ADV PlatformIO 固件
apps/codex-buddy-menu
                     Rust macOS 顶部菜单栏 App
tools/               BLE helper、宠物资源生成、release 检查脚本
examples/pets/alice  默认 Alice 宠物包
release/firmware/    可直接烧录的单个固件 bin
release/apps/        macOS 顶部菜单栏 App zip
docs/                快速开始、Desktop、App、宠物、协议和发布文档
AI_DEPLOYMENT.md     给 AI coding agent 看的部署说明
```

## 傻瓜安装：Alice 固件 + 菜单栏 App

大多数用户直接使用 release 里的两个文件：

```text
release/firmware/codex-buddy-cardputer-adv-v0.3.27-ble-pair-merged.bin
release/apps/CodexBuddyMenu-v0.1.0-macos-arm64.zip
```

这个仓库里的固件 bin 是 Alice 版本：烧录后硬件默认宠物就是 Alice。

1. 把 `codex-buddy-cardputer-adv-v0.3.27-ble-pair-merged.bin` 烧录到 Cardputer ADV。
2. 解压 `CodexBuddyMenu-v0.1.0-macos-arm64.zip`。
3. 当前 App 是未 notarize 的预览版，首次打开前先在命令行清掉 macOS quarantine：

```bash
unzip CodexBuddyMenu-v0.1.0-macos-arm64.zip
xattr -dr com.apple.quarantine CodexBuddyMenu.app
open CodexBuddyMenu.app
```

4. 选择 `连接向导 -> 使用 BLE 快速连接...`，输入设备 `Device` 页显示的配对码；
   或选择 `使用 WiFi 连接说明...` 走局域网模式。
5. 只有需要 Codex Desktop 集成时，才点 `安装 Desktop Hook...`。

如果 macOS 提示“无法验证开发者”或“不允许打开”，通常就是 zip 解压后的隔离标记
还在；对解压出来的 `CodexBuddyMenu.app` 执行上面的 `xattr` 命令一次即可。

`安装 Desktop Hook...` 会把 managed Codex `PermissionRequest` hook 写入
`~/.codex/config.toml`。Codex Desktop 和裸 `codex` CLI 都可能读取同一份配置。
它本身不会启动 heartbeat watcher；要保持菜单栏桥接运行，或者 CLI 直接用
`codex-buddy start` 这条一体化入口。

开发者仍然可以直接使用 Python CLI。

## 傻瓜烧录

使用 merged 固件：

```text
release/firmware/codex-buddy-cardputer-adv-v0.3.27-ble-pair-merged.bin
```

这是 Alice 固件版本。

让 Cardputer ADV 进入下载模式：

1. 顶部电源拨到 OFF。
2. 按住 `G0`。
3. 插 USB-C 到 Mac。
4. 等 1 秒。
5. 松开 `G0`。

可以用 M5Burner、ESP 烧录工具，或者命令行烧录：

```bash
python3 -m pip install esptool
esptool.py --chip esp32s3 --port /dev/cu.usbmodemXXXX --baud 1500000 \
  write_flash 0x0 release/firmware/codex-buddy-cardputer-adv-v0.3.27-ble-pair-merged.bin
```

正常启动：

1. 拔掉 USB-C。
2. 顶部电源拨到 ON。
3. 不按 `G0`。
4. 重新插 USB-C。

## 从源码安装

```bash
python3 -m venv .venv
./.venv/bin/python -m pip install -e daemon -r requirements-dev.txt
tools/build_ble_bridge_app.sh
tools/build_menu_bar_app.sh
```

编译固件：

```bash
./.venv/bin/python -m pip install platformio
./.venv/bin/pio run -d firmware -e cardputer-adv
```

烧录源码固件：

```bash
./.venv/bin/pio run -d firmware -e cardputer-adv -t upload \
  --upload-port /dev/cu.usbmodemXXXX
```

## 用 GitHub Actions 构建 Release

仓库里包含 GitHub Actions 工作流：

```text
.github/workflows/release-artifacts.yml
```

你可以在 GitHub Actions 页面手动运行，也可以推送 `v*` tag 触发。它会构建 Alice
固件、构建 macOS 菜单栏 App、上传 `dist/release`，并在 tag 构建时把产物附加到
GitHub Release。

## Codex CLI 模式

如果使用菜单栏 App，可以先在 App 里选择连接模式并启动桥接。下面的 CLI 流程主要
面向开发和调试。

CLI 用户有两种模式：

- `codex-buddy start`：启动 Codex CLI、临时注入审批 hook，并启动 heartbeat 同步；
  不会修改 `~/.codex/config.toml`。
- 裸 `codex`：可以使用 `安装 Desktop Hook...` 写入的持久 hook，因为 Codex Desktop
  和 CLI 共享 Codex hook 配置。若还想让硬件持续显示当前会话，需要菜单栏桥接或
  单独的 watcher 持续运行。

先检查硬件链路：

```bash
PYTHONPATH=daemon/src ./.venv/bin/python -m codex_buddy.cli doctor --timeout 8
```

启动带硬件审批 hook 的 Codex CLI：

```bash
PYTHONPATH=daemon/src ./.venv/bin/python -m codex_buddy.cli start \
  --transport ble-socket
```

设备 WiFi 配置完成后，也可以使用 auto transport：

```bash
PYTHONPATH=daemon/src ./.venv/bin/python -m codex_buddy.cli start \
  --transport auto
```

`auto` 会优先尝试 WiFi，WiFi 不可用时回退 BLE。

### BLE 配对码

`0.3.27-ble-pair` 以及之后的固件会在设备 `Device` 页面显示六位配对码。
菜单栏 App 的 BLE 向导会提示输入它。CLI 用户也可以手动传入：

```bash
PYTHONPATH=daemon/src ./.venv/bin/python -m codex_buddy.cli doctor \
  --transport ble-socket \
  --ble-device-name Codex-Buddy \
  --ble-pair-code 123456
```

只有旧固件没有显示配对码时，才保持这个参数为空。

## Desktop 和裸 CLI 共用的持久 Codex Hook

这个模式会在 `~/.codex/config.toml` 中写入 managed Codex `PermissionRequest`
hook。菜单里叫 `Desktop Hook` 是因为最常见场景是接入 Codex Desktop，但这份配置
本质上是 Codex hook 配置，Codex Desktop 和裸 `codex` CLI 都可以读取。

先预览将写入的配置块：

```bash
PYTHONPATH=daemon/src ./.venv/bin/python -m codex_buddy.cli desktop print \
  --python "$PWD/.venv/bin/python" \
  --transport ble-socket
```

确认后安装：

```bash
PYTHONPATH=daemon/src ./.venv/bin/python -m codex_buddy.cli desktop install \
  --python "$PWD/.venv/bin/python" \
  --transport ble-socket
```

安装器只会写入下面这个托管块：

```text
# BEGIN CODEX BUDDY DESKTOP HOOK
# END CODEX BUDDY DESKTOP HOOK
```

同时会在 `~/.codex/config.toml` 旁边生成带时间戳的备份。

安装后重启 Codex Desktop。Desktop 触发权限请求时，硬件会显示审批卡片。审批 hook
会记录当前 Desktop session id，后续 heartbeat 会优先显示同一条 Desktop 会话的
活动摘要。

菜单栏 App 也可以安装和卸载同一个 managed hook。它会使用 App 内置的 daemon
helper，普通用户不需要自己定位 Python 入口。

卸载：

```bash
PYTHONPATH=daemon/src ./.venv/bin/python -m codex_buddy.cli desktop uninstall
```

## WiFi 模式

在设备 WiFi 页设置：

- SSID 和密码。
- Mac 的局域网 IP 作为 `Host`。
- `47392` 作为 `Port`。
- 可选 token。

Mac 端启动 bridge：

```bash
PYTHONPATH=daemon/src ./.venv/bin/python -m codex_buddy.cli wifi-bridge \
  --wifi-host 0.0.0.0 \
  --wifi-port 47392
```

如果要让 Codex Desktop 走 WiFi 审批，需要保持 `wifi-bridge` 常驻，并用
`--transport local-bridge` 安装 Desktop hook。不要把 Desktop hook 直接安装成
`--transport wifi-server`。

## 自定义宠物

硬件上的宠物资源会编译进固件，不是运行时动态下载。

你的 Codex Desktop 宠物包应符合：

```text
~/.codex/pets/<pet-id>/pet.json
~/.codex/pets/<pet-id>/spritesheet.webp
```

当前固件资源规则：

- `spritesheet.webp`：`1536x1872`。
- 图集：`8 x 9`。
- 单格：`192x208`。
- 固件输出帧：`72x78`。
- 固件帧数：`57`。
- 预期动作行：idle、running-right、running-left、waving、jumping、failed、
  waiting、running、review。

检查宠物：

```bash
PYTHONPATH=daemon/src ./.venv/bin/python -m codex_buddy.cli pet \
  --pet-dir ~/.codex/pets/<pet-id> \
  --json
```

生成固件数组：

```bash
./.venv/bin/python tools/generate_pet_sprite_asset.py \
  --spritesheet ~/.codex/pets/<pet-id>/spritesheet.webp \
  --label "<Pet Name>" \
  --contact-sheet tools/<pet-id>-firmware-contact-sheet.png
```

然后重新编译并烧录固件。

## 给 AI Coding Agent

请看 [AI_DEPLOYMENT.md](AI_DEPLOYMENT.md)。

这份文件是给 AI coding agent 写的操作部署指南。如果用户把这个仓库丢给 Codex 并说
“帮我部署”，应优先从那里开始。

## 开发检查

```bash
PYTHONPATH=daemon/src ./.venv/bin/python -m unittest discover daemon/tests
PYTHONPATH=daemon/src ./.venv/bin/python tools/release_check.py --skip-firmware
./.venv/bin/pio run -d firmware -e cardputer-adv
```

## 为什么默认宠物是 Alice

Alice 是 [洛小山](https://luoxiaoshan.cn/) 的作品，是一个桌面 AI Agent。它不是
单纯的工具型 Agent，而是带有人格、记忆和一组 Agent 伙伴设定的桌面陪伴型产品，可以
帮用户做海报、学 AI、写汇报，也可以组织多 Agent 分析。

Alice 官网：[alice.miyang.cn](https://alice.miyang.cn/)

这个仓库选择 Alice 作为默认宠物，不是为了放一个随便的示例 mascot，而是想展示：一个
真正有个性、有来源的桌面 Agent，也可以变成桌面上的实体硬件伙伴。

如果你想使用自己的宠物，可以把 Alice 替换成你自己的 Codex Desktop 宠物包，然后重新
编译固件。

## License

MIT. See [LICENSE](LICENSE).

## Friendship Link 友情链接

Thanks for the support and feedback from the friends at
[LINUX DO](https://linux.do/).

感谢 [LINUX DO](https://linux.do/) 朋友们的支持和反馈。

友情链接：

- [Anthropic Claude Desktop Buddy](https://github.com/anthropics/claude-desktop-buddy)
- [y88huang 的 claude-desktop-buddy-cardputer](https://github.com/y88huang/claude-desktop-buddy-cardputer)
- [M5Burner 文档](https://docs.m5stack.com/en/uiflow/m5burner/intro)
- [M5Stack UIFlow MicroPython](https://github.com/m5stack/uiflow-micropython)

“用硬件桌宠承载 coding agent 审批”这个思路，明显受 Claude Desktop Buddy 启发。
本项目保留了这个好用的硬件审批交互模式，但围绕 Codex 和 Codex Desktop 桌宠模型
重新实现了固件、daemon、协议和 Desktop 集成。

本项目不隶属于 Anthropic、OpenAI 或 M5Stack。
