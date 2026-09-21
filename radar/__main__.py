from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .service import Radar, BusyError, write_json
from .profiles import PRESET_IDS


def main():
    parser = argparse.ArgumentParser(description="arXiv 研究雷达")
    subs = parser.add_subparsers(dest="command", required=True)
    scan = subs.add_parser("scan", help="扫描并归档 arXiv 官方数据")
    scan.add_argument("--days", type=int)
    serve = subs.add_parser("serve", help="打开本地研究雷达")
    serve.add_argument("--port", type=int, default=8765)
    queue = subs.add_parser("review-queue", help="导出待解读的真实摘要")
    queue.add_argument("--output", type=Path)
    reviews = subs.add_parser("import-reviews", help="校验证据并导入摘要解读")
    reviews.add_argument("file", type=Path)
    delivery = subs.add_parser("delivery-plan", help="列出尚未通知的新记录与版本变化")
    delivery.add_argument("--output", type=Path)
    ack = subs.add_parser("acknowledge", help="记录本次通知摘要已准备发送的范围")
    ack.add_argument("file", type=Path)
    digest = subs.add_parser("digest", help="生成最新日报")
    status = subs.add_parser("status", help="查看扫描状态")
    candidates = subs.add_parser("export-candidates", help="Export stored metadata, including unrecommended papers, for profile tuning")
    candidates.add_argument("--output", type=Path)
    for command in (scan, serve, queue, reviews, delivery, ack, digest, status, candidates):
        command.add_argument("--profile", type=Path, help="Research profile; relative paths use the repository root")
        command.add_argument("--data-dir", type=Path, help="Separate state directory; relative paths use the repository root")
    subs.add_parser("profiles", help="List editable starter research profiles")
    initialize = subs.add_parser("init-profile", help="Create a profile without overwriting an existing file")
    initialize.add_argument("--preset", required=True, choices=PRESET_IDS)
    initialize.add_argument("--output", type=Path, default=Path("config/profile.local.json"))
    initialize.add_argument("--name")
    initialize.add_argument("--timezone")
    validate = subs.add_parser("validate-profile", help="Validate any research profile without opening a database")
    validate.add_argument("file", type=Path)
    evaluation = subs.add_parser("evaluate", help="Offline evaluation against labeled relevance cases")
    evaluation.add_argument("dataset", type=Path)
    evaluation.add_argument("--profile", type=Path, help="Profile to evaluate; defaults to the active profile")
    evaluation.add_argument("--k", type=int, default=5)
    evaluation.add_argument("--output", type=Path)
    preview = subs.add_parser("preview-profile", help="Preview a profile on a fixed metadata pool without changing research state")
    preview.add_argument("file", type=Path)
    preview.add_argument("--profile", type=Path, required=True)
    preview.add_argument("--baseline", type=Path)
    preview.add_argument("--limit", type=int, default=10)
    preview.add_argument("--format", choices=("json", "markdown"), default="json")
    preview.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "profiles":
            from .profiles import list_presets
            print(json.dumps({"presets": list_presets(), "custom_profiles_supported": True}, ensure_ascii=False, indent=2))
            return 0
        if args.command == "init-profile":
            from .profiles import init_profile
            print(json.dumps(init_profile(args.preset, args.output, name=args.name, timezone=args.timezone), ensure_ascii=False, indent=2))
            return 0
        if args.command == "validate-profile":
            from .config import load_profile
            path = args.file.expanduser().absolute()
            print(json.dumps({"valid": True, "path": str(path), "profile": load_profile(path)}, ensure_ascii=False, indent=2))
            return 0
        if args.command == "evaluate":
            from .config import load_profile, profile_path
            from .evaluation import evaluate
            from .service import ROOT
            result = evaluate(json.loads(args.dataset.read_text(encoding="utf-8")),
                              load_profile(profile_path(ROOT, args.profile)), args.k)
            if args.output:
                write_json(args.output, result)
                print(str(args.output.resolve()))
            else:
                print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        if args.command == "preview-profile":
            from .config import load_profile, profile_path
            from .preview import preview_profile, render_preview
            from .service import ROOT
            selected_path = profile_path(ROOT, args.profile)
            baseline_path = profile_path(ROOT, args.baseline) if args.baseline is not None else None
            source_path = args.file.expanduser().resolve()
            protected = {source_path, selected_path.resolve()}
            if baseline_path is not None:
                protected.add(baseline_path.resolve())
            if args.output is not None:
                output_path = args.output.expanduser().resolve()
                same_input = output_path in protected
                if not same_input and output_path.exists():
                    # Different path strings can still name the same inode.
                    # In particular, Markdown writes would truncate a hardlinked input.
                    same_input = any(path.exists() and output_path.samefile(path) for path in protected)
                if same_input:
                    raise ValueError("Preview output must not overwrite the candidates or either profile")
            result = preview_profile(json.loads(source_path.read_text(encoding="utf-8")),
                                     load_profile(selected_path),
                                     baseline=load_profile(baseline_path) if baseline_path is not None else None,
                                     limit=args.limit)
            if args.format == "markdown":
                rendered = render_preview(result)
                if args.output:
                    output = args.output.expanduser().resolve()
                    output.parent.mkdir(parents=True, exist_ok=True)
                    output.write_text(rendered, encoding="utf-8")
                    print(str(output))
                else:
                    print(rendered)
            elif args.output:
                write_json(args.output.expanduser(), result)
                print(str(args.output.expanduser().resolve()))
            else:
                print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        radar = Radar(profile=args.profile, data_dir=args.data_dir)
        if args.command == "serve":
            from .server import serve
            return serve(args.port, radar=radar)
        if args.command == "scan":
            if args.days is not None and not 1 <= args.days <= 90:
                parser.error("--days 须在 1 至 90 之间")
            run = radar.scan(args.days)
            print(json.dumps(run, ensure_ascii=False, indent=2))
            return 2 if run["status"] == "failed" else 0
        if args.command == "review-queue":
            result = radar.review_queue()
            if args.output:
                write_json(args.output, result)
                print(str(args.output.resolve()))
            else:
                print(json.dumps(result, ensure_ascii=False, indent=2))
        elif args.command == "import-reviews":
            count = radar.import_reviews(json.loads(args.file.read_text(encoding="utf-8")))
            print(f"已导入 {count} 篇经摘要引文校验的解读。")
        elif args.command == "digest":
            print(radar.digest()["markdown"])
        elif args.command == "delivery-plan":
            result = radar.delivery_plan()
            if args.output:
                write_json(args.output, result)
                print(str(args.output.resolve()))
            else:
                print(json.dumps(result, ensure_ascii=False, indent=2))
        elif args.command == "acknowledge":
            radar.acknowledge(json.loads(args.file.read_text(encoding="utf-8")))
            print("已记录通知范围；此记录不代表外部消息平台投递回执。")
        elif args.command == "status":
            print(json.dumps(radar.state(), ensure_ascii=False, indent=2))
        elif args.command == "export-candidates":
            result = {"source": "Stored metadata snapshot, including unrecommended candidates; not a complete arXiv collection",
                      "papers": [{key: paper.get(key, [] if key in ("authors", "categories") else "")
                                  for key in ("id", "title", "abstract", "authors", "categories")}
                                 for paper in radar.store.papers()]}
            if args.output:
                write_json(args.output, result)
                print(str(args.output.resolve()))
            else:
                print(json.dumps(result, ensure_ascii=False, indent=2))
    except BusyError:
        print(json.dumps({"status": "busy", "message": "已有扫描正在运行"}, ensure_ascii=False))
        return 3
    except (ValueError, OSError) as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
