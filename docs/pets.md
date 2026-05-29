# 宠物资源与互动设计

## 目标

Codex Buddy 开源发布时默认使用 `Alice` 宠物资源，同时必须让使用者能替换成
自己的 Codex Desktop 宠物资源。

宠物功能继续复用 Codex Desktop 的资源语义和动画状态，不另做一套独立宠物
系统。Mac 端 daemon 只发送宠物元数据和 Codex 状态，固件端负责把内置
spritesheet 帧数组渲染到 M5 Cardputer ADV 屏幕上。

## 发布边界

- 默认宠物：`Alice`。
- 默认资源来源：`examples/pets/alice/spritesheet.webp`。
- 当前固件资源：由 `tools/generate_pet_sprite_asset.py` 生成到
  `firmware/include/CodexPetSprite.h` 和 `firmware/src/CodexPetSprite.cpp`。
- 当前默认资源共 `57` 帧，固件端尺寸为 `72x78`，并按 M5GFX 当前
  `pushImage` 路径需要的 `swap565` 字节序输出。
- 默认资源配套预览图为 `tools/alice-firmware-contact-sheet.png`。
- 公开默认宠物包位于 `examples/pets/alice/`，包含
  Codex Desktop 兼容的 `pet.json` 和 `1536x1872` `spritesheet.webp`。
- `Codex Placeholder` 仍保留在 `examples/pets/codex-placeholder/`，作为无版权
  风险的替代测试资源。
- 不要把个人本机路径、临时生成目录或未确认授权的图片资源提交到公开仓库。

## 自定义宠物目录

用户自己的宠物建议沿用 Codex Desktop 自定义宠物目录：

```text
~/.codex/pets/<pet-id>/
├── pet.json
└── spritesheet.webp
```

`pet.json` 最小示例：

```json
{
  "id": "my-pet",
  "displayName": "My Pet",
  "spritesheetPath": "spritesheet.webp"
}
```

字段说明：

- `id`：稳定资源 id，建议只用小写字母、数字和短横线。
- `displayName`：设备状态页显示的名称，daemon 会裁剪到协议允许的长度。
- `spritesheetPath`：相对当前宠物目录的 spritesheet 文件名；缺省时按
  `spritesheet.webp` 读取。

daemon 选择宠物的规则：

1. 如果 Codex Desktop 当前选择了 `custom:<pet-id>`，daemon 读取对应目录。
2. 如果没有选择自定义宠物，但 `~/.codex/pets` 下只有一个 `pet.json`，daemon
   把它作为调试兜底。
3. 如果没有可判断的唯一宠物，daemon 不发送 `pet` 字段，设备显示 `Pet: -`。

## spritesheet 规格

当前固件生成脚本只接受 Codex Desktop 兼容的 `8 x 9` atlas：

- atlas 尺寸：`1536x1872`。
- 网格规格：`8 x 9`。
- 单格尺寸：`192x208`。
- 输出帧尺寸：`72x78`。
- 输出格式：C++ `uint16_t` PROGMEM 数组，像素为 `swap565` 字节序。
- 透明色：脚本内置 `0x1FF8`，透明像素由 alpha 阈值转换。

动作行和帧数约定：

1. `idle`：6 帧。
2. `running-right`：8 帧。
3. `running-left`：8 帧。
4. `waving`：4 帧。
5. `jumping`：5 帧。
6. `failed`：8 帧。
7. `waiting`：6 帧。
8. `running`：6 帧。
9. `review`：6 帧。

## 准备宠物资源

推荐路径：

1. 在 Codex Desktop 中使用或生成自己的自定义宠物。
2. 确认本机存在 `~/.codex/pets/<pet-id>/pet.json` 和 `spritesheet.webp`。
3. 如果是通过 Codex pet 生成流程产出的资源，直接使用最终 package 目录。
4. 不要把个人本机路径、临时生成目录或未确认授权的图片资源写进开源仓库。

最小检查：

```bash
sips -g pixelWidth -g pixelHeight ~/.codex/pets/<pet-id>/spritesheet.webp
PYTHONPATH=daemon/src python3 -m codex_buddy.cli pet
PYTHONPATH=daemon/src python3 -m codex_buddy.cli pet \
  --pet-dir ~/.codex/pets/<pet-id> \
  --json
```

期望输出要点：

```text
pixelWidth: 1536
pixelHeight: 1872
id: <pet-id>
displayName: <Pet Name>
size: 1536x1872
valid: yes
```

`--pet-dir` 不依赖 Codex Desktop 当前选择的宠物，适合在生成固件资源前先检查
某个包。校验内容包括：

- `pet.json` 是否存在且可解析。
- `id` 是否只包含小写字母、数字和短横线。
- `spritesheet.webp` 是否存在且能读取尺寸。
- atlas 尺寸是否为 `1536x1872`。

如果只想验证工具链，可以先使用仓库自带的示例包：

```bash
PYTHONPATH=daemon/src python3 -m codex_buddy.cli pet \
  --pet-dir examples/pets/alice \
  --json
```

如果 `codex-buddy pet` 显示 `No custom Codex pet selected.`，先确认 Codex
Desktop 是否已选择自定义宠物，或者临时只保留一个 `~/.codex/pets/<pet-id>`
目录用于调试。

## 生成固件资源

生成命令需要在仓库根目录执行。读取 WebP spritesheet 或输出 contact sheet
需要 Pillow。如果本地环境缺少 Pillow，
先安装到当前 Python 环境：

```bash
python3 -m pip install Pillow
```

生成仓库默认 Alice 资源：

```bash
python3 tools/generate_pet_sprite_asset.py \
  --spritesheet examples/pets/alice/spritesheet.webp \
  --label Alice \
  --contact-sheet tools/alice-firmware-contact-sheet.png
```

如果只想生成无版权风险的程序化占位资源：

```bash
python3 tools/generate_pet_sprite_asset.py --placeholder
```

重新生成公开示例宠物包：

```bash
python3 tools/generate_example_pet_package.py
```

生成自己的宠物资源：

```bash
python3 tools/generate_pet_sprite_asset.py \
  --spritesheet ~/.codex/pets/<pet-id>/spritesheet.webp
```

默认会覆盖：

- `firmware/include/CodexPetSprite.h`
- `firmware/src/CodexPetSprite.cpp`

如果只想试生成到临时路径，使用显式输出参数，避免改动固件源码：

```bash
python3 tools/generate_pet_sprite_asset.py \
  --spritesheet ~/.codex/pets/<pet-id>/spritesheet.webp \
  --include /tmp/CodexPetSprite.h \
  --source /tmp/CodexPetSprite.cpp
```

生成后需要人工确认：

- 脚本输出帧数为 `57`。
- 输入 atlas 尺寸必须是 `1536x1872`；尺寸不匹配时脚本会直接失败，不会生成
  半成品。
- `CodexPetSprite.h` 中 `kCodexPetFrameWidth` 为 `72`，`kCodexPetFrameHeight`
  为 `78`。
- `kCodexPetFrameCount` 为 `57`。
- 每行动作帧序列和上面的动作行约定一致。
- `codex-buddy pet --pet-dir ~/.codex/pets/<pet-id> --json` 返回
  `"valid": true`。

## 编译和烧录

重新生成固件资源后，按现有 PlatformIO 流程编译：

```bash
cd firmware
../.venv/bin/pio run -e cardputer-adv
```

连接 M5 Cardputer ADV 后烧录：

```bash
../.venv/bin/pio run -e cardputer-adv -t upload --upload-port /dev/cu.usbmodem1101
```

如果设备端口不同，先用下面命令查看候选串口：

```bash
PYTHONPATH=daemon/src python3 -m codex_buddy.cli ports
```

烧录后做最小回归：

```bash
PYTHONPATH=daemon/src python3 -m codex_buddy.cli once --transport ble-socket
```

设备状态页应继续显示宠物动画，并在 `Pet:` 后显示当前宠物名称。如果 BLE helper
重新构建过，macOS 可能再次要求蓝牙权限，需要在系统设置里允许
`Codex Buddy Bridge`。

## 设备显示

当前协议只把宠物元数据放进 heartbeat：

```json
{
  "pet": {
    "id": "my-pet",
    "displayName": "My Pet"
  }
}
```

注意：

- 协议不会下发 spritesheet 路径或图片数据。
- 固件运行时播放的是已经编译进固件的 `CodexPetSprite` 帧数组。
- `pet.displayName` 只用于状态页展示，不能代表固件已经动态切换图片资源。
- 如果要切换实际图像，必须重新生成 `CodexPetSprite.*` 并重新编译烧录。

## 硬件互动设计

M5 Cardputer ADV 的基础 IMU 互动已经在 `0.3.6-sleep-motion` 后实机验收：
左倾 / 右倾方向正确，黑屏后 IMU 运动可唤醒。它只作为本地动画调制，不改变
Codex 任务状态。

基础映射：

- 水平放置：正常站立，使用 `idle` 或 daemon 下发的当前默认动作。
- 向左倾斜：触发 `running-left`，表现为宠物向左走。
- 向右倾斜：触发 `running-right`，表现为宠物向右走。
- 摇一摇：可按需要扩展为一次性特殊动作，建议优先复用 `jumping`。

实现约束：

- 倾斜动作是 UI 层 overlay；Codex `state` 仍由 daemon heartbeat 决定。
- 等待审批时，IMU 动作不应遮挡审批提示。
- 失败状态、待查看状态和审批等待状态优先级高于普通倾斜互动。
- 需要设置开关，允许关闭 IMU 互动。
