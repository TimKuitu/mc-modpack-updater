# MC 整合包升级助手（MC Modpack Updater）

面向 Windows 平台（重点适配 **PCL2 / PCL-CE** 启动器与 Minecraft `26.1+` 年份制版本号）的整合包识别、跨版本升级、前置补齐与导出桌面工具。

## 核心功能

- **多格式整合包读取与四级 Mod 识别**
  - 支持 PCL2 版本目录（`.minecraft\versions\<实例名>`，含版本隔离检测）以及 `.mrpack`、CurseForge `.zip`、MCBBS `.zip`、MultiMC/Prism `.zip`、懒人包压缩包。
  - 四级识别流水线：清单文件 → Modrinth SHA-512/SHA-1 批量反查 → CurseForge Murmur2 指纹反查 → Jar 内元数据（`fabric.mod.json` / `quilt.mod.json` / `neoforge.mods.toml` / `mods.toml`）。
- **跨版本兼容性分析（支持 `26.1+` 年份制）**
  - 动态拉取 Minecraft 年份制版本与推荐加载器版本（Fabric / NeoForge / Forge / Quilt）。
  - Modrinth 正式版/测试版两步分流匹配，支持 CurseForge 禁分发 Mod 交叉替代与手动导入校验。
  - 自动递归解析 `required` 前置依赖与 `incompatible` 冲突告警。
- **并发下载与 PCL2 兼容导出**
  - 内置 MCIM 国内镜像加速与 Windows 系统代理穿透，流式并发下载并校验 SHA-512 / SHA-1。
  - 导出可直接拖入 PCL2 / PCL-CE 安装的标准 `.mrpack` 压缩包，并支持一键单独导出原配置备份 `.zip`。
- **精美中文桌面界面**
  - Python 3.11 + Vue 3 + TypeScript + Element Plus + pywebview（WebView2），黑曜石深色毛玻璃主题。

## 本地开发与构建

```powershell
# 1. 前端构建（产物输出到 backend/ui_dist/）
cd frontend
npm install
npm run build

# 2. 后端环境与运行
cd ../backend
python -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[dev]"
.venv\Scripts\python.exe -m pytest tests -v
.venv\Scripts\python.exe -m mc_updater.main
```

更多说明见 [docs/使用说明-v1.0.0.md](docs/使用说明-v1.0.0.md)。
