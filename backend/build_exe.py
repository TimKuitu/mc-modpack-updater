from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from PIL import Image, ImageDraw


def ensure_app_icon(ico_path: Path) -> None:
    ico_path.parent.mkdir(parents=True, exist_ok=True)
    if ico_path.exists():
        return
    size = 256
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    # 圆角深色底座 + 翡翠绿几何徽章
    draw.rounded_rectangle([12, 12, size - 12, size - 12], radius=48, fill=(15, 23, 42, 255), outline=(16, 185, 129, 255), width=8)
    draw.polygon([(128, 48), (200, 96), (176, 196), (80, 196), (56, 96)], fill=(16, 185, 129, 240))
    draw.polygon([(128, 68), (180, 104), (160, 178), (96, 178), (76, 104)], fill=(52, 211, 153, 255))
    img.save(ico_path, format="ICO", sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)])


def main() -> None:
    backend_dir = Path(__file__).resolve().parent
    repo_dir = backend_dir.parent
    assets_ico = repo_dir / "assets" / "app.ico"
    build_dir = repo_dir / "build" / "pyinstaller"
    outputs_dir = repo_dir / "dist"
    ui_dist = backend_dir / "ui_dist" / "index.html"

    if not ui_dist.is_file():
        raise FileNotFoundError(f"前端构建产物缺失：{ui_dist}，请先运行 npm run build")

    ensure_app_icon(assets_ico)
    build_dir.mkdir(parents=True, exist_ok=True)
    outputs_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--workpath",
        str(build_dir),
        "--distpath",
        str(outputs_dir),
        str(backend_dir / "mc_updater.spec"),
    ]
    print("Running:", " ".join(cmd))
    subprocess.run(cmd, cwd=str(backend_dir), check=True)
    print("Build finished:", outputs_dir / "MC整合包升级助手-v1.0.0.exe")


if __name__ == "__main__":
    main()
