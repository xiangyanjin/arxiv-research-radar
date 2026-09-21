from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .service import Radar, BusyError, write_json


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
    subs.add_parser("digest", help="生成最新日报")
    subs.add_parser("status", help="查看扫描状态")
    evaluation = subs.add_parser("evaluate", help="Offline evaluation against labeled relevance cases")
    evaluation.add_argument("dataset", type=Path)
    evaluation.add_argument("--profile", type=Path, help="Profile to evaluate; defaults to the active profile")
    evaluation.add_argument("--k", type=int, default=5)
    evaluation.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
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
        radar = Radar()
        if args.command == "serve":
            from .server import serve
            return serve(args.port)
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
    except BusyError:
        print(json.dumps({"status": "busy", "message": "已有扫描正在运行"}, ensure_ascii=False))
        return 3
    except (ValueError, OSError) as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
