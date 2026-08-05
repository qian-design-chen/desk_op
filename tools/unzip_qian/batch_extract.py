#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
batch_extract.py  —— 解压指定目录下所有压缩包，支持大文件（1 GB+）

用法：
    python batch_extract.py [目录路径] [选项]

如果不指定路径，默认解压当前工作目录。
支持格式：.zip .tar .tar.gz .tgz .tar.bz2 .tbz .tbz2 .tar.xz .txz .gz .bz2 .xz
"""

import os
import sys
import io
import traceback
import zipfile
import tarfile
import gzip
import bz2
import lzma
import shutil
import argparse
from pathlib import Path


# ── 日志 ────────────────────────────────────────────────
def log(msg: str, indent: int = 0):
    prefix = "  " * indent
    print(f"{prefix}{msg}")


def log_error(msg: str, exc: BaseException):
    """打印简洁错误消息（异常类型 + 原因，不含完整堆栈）"""
    lines = traceback.format_exception_only(type(exc), exc)
    cause = "".join(lines).strip()
    log(f"  [!] {msg}", indent=1)
    if cause:
        log(f"      {cause}", indent=1)


def format_size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / 1024 / 1024:.1f} MB"


# ── 后缀解析 ────────────────────────────────────────────
# 注意：resolve_ext 不读写文件内容，只解析文件名，与文件大小无关

_DOUBLE_MAP = {
    ".tar.gz":  ("tar", "gz"),
    ".tar.bz2": ("tar", "bz2"),
    ".tar.xz":  ("tar", "xz"),
    ".tgz":     ("tar", "gz"),
    ".tbz":     ("tar", "bz2"),
    ".tbz2":    ("tar", "bz2"),
    ".txz":     ("tar", "xz"),
}


def resolve_ext(path: Path) -> list[str]:
    name = path.name.lower()
    for double_sfx, parts in _DOUBLE_MAP.items():
        if name.endswith(double_sfx):
            return list(parts)
    suffix = path.suffix.lower().lstrip(".")
    return [suffix] if suffix else []


def supports_format(suffixes: list[str]) -> bool:
    return bool(suffixes) and suffixes[0] in ("zip", "tar", "gz", "bz2", "xz")


# ── 各类解压实现 ────────────────────────────────────────
# 要点：对单文件 gz/bz2/xz 使用分块写入，不将解压后的全部数据读入内存

_CHUNK = 16 * 1024 * 1024  # 16 MB 读写缓冲


def extract_zip(path: Path, dest: Path) -> bool:
    try:
        with zipfile.ZipFile(path, "r", allowZip64=True) as zf:
            zf.extractall(dest)
        return True
    except MemoryError:
        log_error("zip 文件过大，系统内存不足",
                  MemoryError("请确保有足够的可用内存"))
        return False
    except zipfile.BadZipFile as e:
        log_error("损坏的 zip 或不支持的大文件格式", e)
        return False
    except Exception as e:
        log_error("zip 解压异常", e)
        return False


def extract_tar(path: Path, dest: Path, mode: str = "r") -> bool:
    try:
        with tarfile.open(path, mode) as tf:
            tf.extractall(dest)
        return True
    except MemoryError:
        log_error("tar 文件过大，系统内存不足",
                  MemoryError("请确保有足够的可用内存"))
        return False
    except (tarfile.TarError, EOFError) as e:
        log_error("tar 解压失败", e)
        return False
    except Exception as e:
        log_error("tar 解压异常", e)
        return False


def extract_single_gz(path: Path, dest: Path) -> bool:
    """解压单个 .gz 文件（非 tar.gz），分块写入磁盘"""
    try:
        out_path = dest / path.stem
        with gzip.open(path, "rb") as fin, open(out_path, "wb") as fout:
            shutil.copyfileobj(fin, fout, _CHUNK)
        return True
    except MemoryError:
        log_error("gzip 文件过大，内存不足", MemoryError())
        return False
    except Exception as e:
        log_error("gzip 解压失败", e)
        return False


def extract_single_bz2(path: Path, dest: Path) -> bool:
    """
    解压单个 .bz2 文件（非 tar.bz2）。
    注意：bz2.BZ2Decompressor 不支持 seek，shutil.copyfileobj
    内部依赖 read()，可以正常工作。
    """
    try:
        out_name = path.name[:-4] if path.name.lower().endswith(".bz2") else path.stem
        out_path = dest / out_name
        with bz2.open(path, "rb") as fin, open(out_path, "wb") as fout:
            shutil.copyfileobj(fin, fout, _CHUNK)
        return True
    except MemoryError:
        log_error("bzip2 文件过大，内存不足", MemoryError())
        return False
    except Exception as e:
        log_error("bzip2 解压失败", e)
        return False


def extract_single_xz(path: Path, dest: Path) -> bool:
    """解压单个 .xz 文件（非 tar.xz），分块写入"""
    try:
        out_name = path.name[:-3] if path.name.lower().endswith(".xz") else path.stem
        out_path = dest / out_name
        with lzma.open(path, "rb") as fin, open(out_path, "wb") as fout:
            shutil.copyfileobj(fin, fout, _CHUNK)
        return True
    except MemoryError:
        log_error("xz 文件过大，内存不足", MemoryError())
        return False
    except Exception as e:
        log_error("xz 解压失败", e)
        return False


# ── 统一入口 ────────────────────────────────────────────

def extract_archive(path: Path, dest_dir: Path) -> bool:
    ext_parts = resolve_ext(path)
    if not ext_parts or not supports_format(ext_parts):
        return False

    fsize = format_size(path.stat().st_size)
    log(f"    格式：{'.'.join(ext_parts)}，大小：{fsize}", indent=1)

    try:
        if ext_parts[0] == "zip":
            return extract_zip(path, dest_dir)
        if ext_parts[0] == "tar":
            if len(ext_parts) == 1:
                return extract_tar(path, dest_dir, "r:")
            mode = {"gz": "r:gz", "bz2": "r:bz2", "xz": "r:xz"}.get(ext_parts[1])
            if mode is None:
                log(f"    [!] 不支持的 tar 压缩类型：{ext_parts[1]}", indent=1)
                return False
            return extract_tar(path, dest_dir, mode)
        if ext_parts[0] == "gz":
            return extract_single_gz(path, dest_dir)
        if ext_parts[0] == "bz2":
            return extract_single_bz2(path, dest_dir)
        if ext_parts[0] == "xz":
            return extract_single_xz(path, dest_dir)
    except MemoryError:
        log_error("文件过大，系统内存不足",
                  MemoryError("请确保有足够可用内存（建议至少为压缩包大小的 3 倍）"))
        return False
    except Exception as e:
        log_error("解压过程发生未知错误", e)
        return False
    return False


# ── 辅助 ────────────────────────────────────────────────

def ensure_output_dir(base_dir: Path, archive_path: Path) -> Path:
    stem = archive_path.name
    for _ in range(3):
        p = Path(stem)
        if p.suffix:
            stem = p.stem
        else:
            break
    if not stem:
        stem = archive_path.stem

    candidate = base_dir / stem
    if not candidate.exists():
        candidate.mkdir(parents=True, exist_ok=True)
        return candidate

    counter = 1
    while True:
        candidate = base_dir / f"{stem}_{counter}"
        if not candidate.exists():
            candidate.mkdir(parents=True, exist_ok=True)
            return candidate
        counter += 1


def check_disk_space(archives: list[Path], dest_root: Path) -> tuple[bool, str]:
    """
    粗略估算所需磁盘空间。
    保守估计解压后大小为压缩包大小的 3 倍。
    返回 (是否足够, 消息)
    """
    total_compressed = sum(p.stat().st_size for p in archives)
    estimated_need = total_compressed * 3
    try:
        usage = shutil.disk_usage(dest_root)
        if usage.free < estimated_need:
            need_gb = estimated_need / (1024**3)
            free_gb = usage.free / (1024**3)
            return (False,
                    f"磁盘空间可能不足：估计需要 {need_gb:.1f} GB，"
                    f"可用 {free_gb:.1f} GB（{dest_root}）")
    except Exception:
        pass
    return (True, "")


def scan_archives(root: Path) -> list[Path]:
    """扫描单层目录"""
    archives = []
    for entry in root.iterdir():
        if not entry.is_file():
            continue
        if supports_format(resolve_ext(entry)):
            archives.append(entry)
    archives.sort(key=lambda p: p.stat().st_size)
    return archives


# ── CLI ──────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="批量解压指定目录下的所有压缩包"
    )
    parser.add_argument(
        "directory", nargs="?", default=".",
        help="要扫描的目录路径（默认当前目录）"
    )
    parser.add_argument(
        "--no-recurse", action="store_true",
        help="不解压子目录中的压缩包（默认递归扫描所有子目录）"
    )
    parser.add_argument(
        "--output", "-o", default=None,
        help="解压输出根目录（默认为压缩包所在目录）"
    )
    parser.add_argument(
        "--force", action="store_true",
        help="跳过磁盘空间检查"
    )
    parser.add_argument(
        "--skip-size", type=float, default=0,
        help="跳过大于指定 MB 的压缩包（例如 --skip-size 2048）"
    )
    args = parser.parse_args()

    root = Path(args.directory).resolve()
    if not root.is_dir():
        log(f"错误：目录不存在或不是文件夹 — {root}")
        sys.exit(1)

    if args.no_recurse:
        archives = scan_archives(root)
    else:
        archives = [
            p for p in root.rglob("*")
            if p.is_file() and supports_format(resolve_ext(p))
        ]
    archives.sort(key=lambda p: p.stat().st_size)

    if not archives:
        log(f"在 {root} 中未发现支持的压缩包。")
        log("支持格式：.zip .tar .tar.gz .tgz .tar.bz2 .tbz .tbz2 .tar.xz .txz .gz .bz2 .xz")
        return

    # 可选：按大小过滤跳过超大文件
    if args.skip_size > 0:
        before = len(archives)
        skip_bytes = args.skip_size * 1024 * 1024
        archives = [a for a in archives if a.stat().st_size <= skip_bytes]
        if before - len(archives) > 0:
            log(f"跳过 {before - len(archives)} 个超过 {args.skip_size:.0f} MB 的压缩包")

    # 磁盘空间检查（仅警告）
    if not args.force:
        dest_root = Path(args.output) if args.output else root
        enough, msg = check_disk_space(archives, dest_root)
        if not enough:
            log(f"警告：{msg}")
            log("可通过 --force 跳过此检查")

    summary = {"ok": 0, "fail": 0, "skip": 0}
    for idx, arch in enumerate(archives, start=1):
        rel = arch.relative_to(root)
        size_mb = arch.stat().st_size / (1024 * 1024)
        log(f"[{idx}/{len(archives)}] {rel}  ({size_mb:.1f} MB)")

        if args.output:
            out_root = Path(args.output)
            if arch.parent != root:
                out_root = out_root / arch.parent.relative_to(root)
        else:
            out_root = arch.parent

        dest = ensure_output_dir(out_root, arch)
        log(f"    -> {dest}", indent=1)

        ok = extract_archive(arch, dest)
        if ok:
            summary["ok"] += 1
        else:
            ext_parts = resolve_ext(arch)
            if ext_parts and ext_parts[0] in ("rar", "7z"):
                log(f"    [!] 格式 {ext_parts[0]} 需额外安装：pip install patool py7zr rarfile",
                    indent=1)
                summary["skip"] += 1
            else:
                summary["fail"] += 1

    print()
    log("=" * 40)
    log(f"完成！成功：{summary['ok']}，失败：{summary['fail']}，跳过：{summary['skip']}")


if __name__ == "__main__":
    main()
