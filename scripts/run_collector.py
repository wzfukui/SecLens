"""CLI utility to execute collectors manually."""
import argparse
import json
import sys
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.schemas import BulletinCreate
from collectors.aliyun import FetchParams as AliyunFetchParams, run as run_aliyun
from collectors.huawei import FetchParams as HuaweiFetchParams, run as run_huawei


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a SecLens collector")
    parser.add_argument(
        "--source", choices=["aliyun", "huawei"], required=True, help="Collector source slug"
    )
    parser.add_argument("--ingest-url", dest="ingest_url", help="Optional ingest API endpoint")
    parser.add_argument("--token", help="Bearer token for the ingest API")
    parser.add_argument("--page-size", dest="page_size", type=int, default=None)
    parser.add_argument("--page-no", dest="page_no", type=int, default=None)
    parser.add_argument("--page-index", dest="page_index", type=int, default=None)
    parser.add_argument("--sort", type=int, default=None, help="Sort order for Huawei feed")
    parser.add_argument("--sort-field", dest="sort_field", default=None, help="Sort field for Huawei feed")
    parser.add_argument("--keyword", default=None, help="Keyword filter for Huawei feed")
    return parser.parse_args()


def run_collector(args: argparse.Namespace) -> tuple[list[BulletinCreate], dict | None]:
    if args.source == "aliyun":
        defaults = AliyunFetchParams()
        params = AliyunFetchParams(
            page_no=args.page_no or defaults.page_no,
            page_size=args.page_size or defaults.page_size,
        )
        return run_aliyun(args.ingest_url, args.token, params=params)
    if args.source == "huawei":
        defaults = HuaweiFetchParams()
        params = HuaweiFetchParams(
            page_index=args.page_index or defaults.page_index,
            page_size=args.page_size or defaults.page_size,
            sort=args.sort or defaults.sort,
            sort_field=args.sort_field or defaults.sort_field,
            keyword=args.keyword if args.keyword is not None else defaults.keyword,
        )
        return run_huawei(args.ingest_url, args.token, params=params)
    raise ValueError(f"Unsupported source: {args.source}")


def main() -> None:
    args = parse_args()
    bulletins, ingest_result = run_collector(args)
    if args.ingest_url:
        summary = f"[{args.source}] dispatched {len(bulletins)} bulletins"
        if isinstance(ingest_result, dict):
            accepted = ingest_result.get("accepted")
            duplicates = ingest_result.get("duplicates")
            summary += f", accepted={accepted}, duplicates={duplicates}"
        print(summary)
        if ingest_result:
            print(json.dumps(ingest_result, ensure_ascii=False))
    else:
        for bulletin in bulletins:
            print(json.dumps(bulletin.model_dump(mode="json"), ensure_ascii=False))


if __name__ == "__main__":
    main()
