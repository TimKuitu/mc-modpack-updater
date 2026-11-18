# MC 整合包升级助手 · 测试与构建体检报告

## 1. 单元测试（`pytest`）
- 执行命令：`work\venv\Scripts\python.exe -m pytest tests -v`
- 结果：**8 passed in 0.36s**
  - `test_hashing.py`（2 项）：CurseForge Murmur2 去除空白向量（`b"test" == 2667173943`）与流式哈希一致性。
  - `test_versioning.py`（3 项）：`26.1+` 年份制版本识别、非字典序排序、`VersionPredicateParser`（`~`、`^`、`x`、`>=26.1-` 等）。
  - `test_parsers.py`（2 项）：模拟 PCL2 隔离/非隔离目录、`inheritsFrom` 嵌套、`Setup.ini`、`.jar.disabled`、四级识别流水线。
  - `test_resolver_and_export.py`（1 项）：两步分流升级匹配、递归前置依赖补全、Mock 流式并发下载校验、原配置备份 `.zip` 与 PCL2 兼容 `.mrpack` 导出及结构自检。

## 2. 前端类型检查与生产构建
- 执行命令：`npm --prefix work\frontend run build`（`vue-tsc --noEmit && vite build`）
- 结果：**0 错误**，9.38s 完成，产物落入 `work\backend\ui_dist\`。

## 3. 真实整合包联网实测（`26.2红石包.zip`）
- 执行脚本：`work\qa\live_test_pack.py`
- 结果：
  - 成功识别 `MC 26.2` + `Fabric 0.19.3`、扫描 `66` 个 Mod、`4` 项配置目录（`config/`、`options.txt`、`servers.dat`、`saves/`）。
  - 启用 MCIM 镜像加速批量反查 Modrinth 哈希：**62/66 命中**。
  - 动态拉取 Modrinth 年份制正式版：`['26.3', '26.2', '26.1.2', '26.1.1', '26.1']`。
  - 兼容性统计：`upgradable: 61`，`beta_only: 2`，`unavailable: 3`。

## 4. 单文件 exe 打包与冒烟测试
- 产物：`outputs\MC整合包升级助手-v1.0.0.exe`（27,157,284 字节，约 25.9 MB）。
- 冒烟测试：`MC_UPDATER_SMOKE_TEST=1` 启动 `MC整合包升级助手-v1.0.0.exe` 成功起窗并正常退出（退出码 `0`）。

## 5. 测试边界说明
- CurseForge 在线接口未在无 Key 环境下做真实外网请求，已通过 `httpx.MockTransport` 完整覆盖指纹反查、文件过滤、`allowModDistribution=false` 流程。
- 拖放与文件选择对话框依赖人工交互桌面操作，未自动化触发系统弹窗。
