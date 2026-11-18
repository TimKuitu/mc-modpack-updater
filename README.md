# MC 整合包升级助手（MC Modpack Updater）

<p align="left">
  <img src="https://img.shields.io/badge/Version-v1.0.0-10b981?style=flat-square" alt="Version" />
  <img src="https://img.shields.io/badge/Platform-Windows%2010%2F11-0ea5e9?style=flat-square" alt="Platform" />
  <img src="https://img.shields.io/badge/Minecraft-26.1%2B%20%26%201.x-34d399?style=flat-square" alt="Minecraft" />
  <img src="https://img.shields.io/badge/Launcher-PCL2%20%2F%20PCL--CE-6366f1?style=flat-square" alt="Launcher" />
</p>

面向 Windows 平台（重点适配 **PCL2 / PCL-CE** 启动器与 Minecraft **`26.1+` 年份制版本号**）的整合包升级桌面工具——自动识别旧包内的 Mod、检测目标版本兼容性、补齐前置依赖，并将升级后的 Mod 与原配置文件一键打包为可直接拖入 PCL2 安装的 `.mrpack` 整合包。

---

## 为什么需要它？

手动把一个整合包升到新版本，往往需要逐个打开 Modrinth / CurseForge 核对版本号（尤其是 `26.1`、`26.2` 等年份制新版本）、手动补齐漏掉的前置库，还要小心翼翼地搬运 `config/`、`kubejs/`、`options.txt` 等原配置。

**MC 整合包升级助手**把这套繁琐流程压缩为 4 步：

```
① 导入旧包（PCL2 目录 / .mrpack / CF zip）
   ↓
② 选择目标 MC 版本与加载器 → 输出兼容性报告 + 自动补齐前置
   ↓
③ 并发下载校验（支持 MCIM 加速）+ 勾选保留原配置文件
   ↓
④ 导出可直接拖入 PCL2 的 .mrpack + 原配置备份 .zip
```

---

## 核心特性

### 1. 多格式整合包识别（四级流水线）
- **支持输入**：PCL2 版本目录（`.minecraft\versions\<实例名>`，自动进行三级版本隔离判定）、`.mrpack`、CurseForge `.zip`、MCBBS `.zip`、MultiMC/Prism `.zip` 与散装懒人包。
- **四级 Mod 识别**：清单文件 → Modrinth `SHA-512 / SHA-1` 批量反查 → CurseForge `Murmur2` 指纹反查（需填写 API Key）→ Jar 内部元数据兜底（`fabric.mod.json` / `quilt.mod.json` / `neoforge.mods.toml` / `mods.toml`），同时保留 `.jar.disabled` 禁用状态。

### 2. 精准兼容性分析与前置解析
- **适配 `26.1+` 年份制版本**：动态拉取 Modrinth 版本列表与官方加载器推荐版本（Fabric / NeoForge / Forge / Quilt），严格以平台 `game_versions` 为准，不被 `>=1.21` 开放区间误导。
- **四类状态清晰分类**：可升级（正式版）、仅测试版（避免测试版覆盖正式版）、需手动下载（CurseForge 禁分发）、暂无新版；支持逐个切换候选版本、跳过或保留原版。
- **自动前置与冲突提示**：递归解析 `required` 前置依赖并自动补全，发现 `incompatible` 冲突时发出告警。

### 3. 国内网络优化与安全下载
- 默认启用 **MCIM 镜像加速**（失败自动回退官方源），支持自动读取 Windows 系统代理或自定义 HTTP / SOCKS5 代理。
- 并发流式下载并边下边算 `SHA-512 / SHA-1` 哈希校验，原子落盘防损坏。
- CurseForge API Key 采用 Windows **DPAPI** 加密存储于本地配置目录。

### 4. PCL2 友好导出
- **`.mrpack` 导出**：Modrinth / GitHub / GitLab 白名单直链写入 `modrinth.index.json`；CurseForge、禁分发本地导入与保留原版的 jar 以及勾选的配置目录（`config/`、`defaultconfigs/`、`kubejs/`、`scripts/`、`options.txt`、`resourcepacks/`、`shaderpacks/` 等）统一写入 `overrides/`，拖入 PCL2 / PCL-CE 即可安装。
- **原配置备份 `.zip`**：支持一键单独打包备份原整合包配置。

---

## 普通玩家快速上手

1. 前往本仓库右侧 [**Releases**](https://github.com/TimKuitu/mc-modpack-updater/releases) 下载最新版的 `MC整合包升级助手-v1.0.0.exe`（单文件免安装，无需配置 Python 或 Node 环境）。
2. 双击运行：
   - **第 1 步**：拖入 `.mrpack` / `.zip` 压缩包，或点击「选择 PCL2 版本目录」。
   - **第 2 步**：选择目标 MC 版本与加载器，点击「开始检测兼容性」。
   - **第 3 步**：点击「开始下载 Mod」，并勾选需要保留的原配置目录。
   - **第 4 步**：导出 `.mrpack`，直接拖入 PCL2 / PCL-CE 窗口即可开始安装。

> **常见提示**：
> - 若拖入文件到 PCL2 没反应，通常是因为 PCL2 以「管理员身份」运行触发了 Windows 权限隔离（UIPI），取消管理员运行或在 PCL2 内选择本地整合包安装即可。
> - 完整排查说明见 [docs/使用说明-v1.0.0.md](docs/使用说明-v1.0.0.md)。

---

## 开发者指南与项目结构

```text
mc_modpack_updater/
├── backend/                # Python 3.11 后端核心（识别、匹配、下载、导出、pywebview 桥接）
│   ├── mc_updater/
│   ├── tests/              # pytest 单元测试
│   ├── build_exe.py        # PyInstaller 单文件打包脚本
│   └── pyproject.toml
├── frontend/               # Vue 3 + Vite + TypeScript + Element Plus 深色毛玻璃 UI
├── assets/                 # 应用图标 (app.ico)
└── docs/                   # 使用说明与测试体检报告
```

### 本地运行与打包

```powershell
# 1. 构建前端（输出至 backend/ui_dist/）
cd frontend
npm install
npm run build

# 2. 运行后端测试与桌面程序
cd ../backend
python -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[dev]"
.venv\Scripts\python.exe -m pytest tests -v
.venv\Scripts\python.exe -m mc_updater.main

# 3. 打包单文件 exe（产物输出至 dist/）
.venv\Scripts\python.exe build_exe.py
```

---

## 边界与免责说明

- 跨 Minecraft 大版本升级时，工具仅负责 Mod 版本对齐、前置补齐与配置迁移，**无法保证旧存档或所有 Mod 之间 100% 不发生玩法/配置结构冲突**，升级前建议先单独备份存档。
- 若导出包内包含 CurseForge 作者禁止第三方分发的 Mod（通过「手动下载并导入」打入 `overrides/mods/`），**仅限个人本地游玩，请勿公开分发该压缩包**。
