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
from resources.aliyun_security.collector import (
    FetchParams as AliyunSecurityFetchParams,
    run as run_aliyun_security,
)
from resources.exploit_db.collector import run as run_exploit_db
from resources.freebuf_community.collector import run as run_freebuf
from resources.oracle_security_alert.collector import run as run_oracle
from resources.huawei_security.collector import (
    FetchParams as HuaweiSecurityFetchParams,
    run as run_huawei_security,
)
from resources.tencent_cloud_security.collector import run as run_tencent_cloud
from resources.ubuntu_security_notice.collector import run as run_ubuntu_security


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a SecLens collector")
    parser.add_argument(
        "--source",
        choices=[
            "aliyun",
            "huawei",
            "aliyun_security",
            "huawei_security",
            "freebuf",
            "tencent_cloud",
            "exploit_db",
            "ubuntu_security",
            "oracle_security_alert",
        ],
        required=True,
        help="Collector source slug",
    )
    parser.add_argument("--ingest-url", dest="ingest_url", help="Optional ingest API endpoint")
    parser.add_argument("--token", help="Bearer token for the ingest API")
    parser.add_argument("--page-size", dest="page_size", type=int, default=None)
    parser.add_argument("--page-no", dest="page_no", type=int, default=None)
    parser.add_argument("--page-index", dest="page_index", type=int, default=None)
    parser.add_argument("--sort", type=int, default=None, help="Sort order for Huawei feed")
    parser.add_argument("--sort-field", dest="sort_field", default=None, help="Sort field for Huawei feed")
    parser.add_argument("--keyword", default=None, help="Keyword filter for Huawei feed")
    parser.add_argument("--bulletin-type", dest="bulletin_type", default=None, help="Aliyun security bulletin type")
    parser.add_argument("--publish-date-from", dest="publish_date_from", default=None, help="Huawei security publish date start (YYYY-MM-DD)")
    parser.add_argument("--publish-date-to", dest="publish_date_to", default=None, help="Huawei security publish date end (YYYY-MM-DD)")
    parser.add_argument("--product-line", dest="product_line", default=None, help="Huawei security product line filter")
    parser.add_argument("--range", dest="range_value", type=int, default=None, help="Huawei security range filter")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of records for supported collectors")
    parser.add_argument("--force", action="store_true", help="Bypass cursor when supported")
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
    if args.source == "aliyun_security":
        defaults = AliyunSecurityFetchParams()
        params = AliyunSecurityFetchParams(
            page_no=args.page_no or defaults.page_no,
            page_size=args.page_size or defaults.page_size,
            bulletin_type=args.bulletin_type or defaults.bulletin_type,
        )
        return run_aliyun_security(args.ingest_url, args.token, params=params)
    if args.source == "huawei_security":
        defaults = HuaweiSecurityFetchParams()
        params = HuaweiSecurityFetchParams(
            page_index=args.page_index or defaults.page_index,
            page_size=args.page_size or defaults.page_size,
            sort=args.sort or defaults.sort,
            sort_field=args.sort_field or defaults.sort_field,
            keyword=args.keyword if args.keyword is not None else defaults.keyword,
            publish_date_from=args.publish_date_from or defaults.publish_date_from,
            publish_date_to=args.publish_date_to or defaults.publish_date_to,
            product_line=args.product_line or defaults.product_line,
            range=args.range_value or defaults.range,
        )
        return run_huawei_security(args.ingest_url, args.token, params=params)
    if args.source == "freebuf":
        bulletins, response = run_freebuf(args.ingest_url, args.token, force=args.force)
        return bulletins, response
    if args.source == "tencent_cloud":
        return run_tencent_cloud(args.ingest_url, args.token, limit=args.limit, force=args.force)
    if args.source == "exploit_db":
        return run_exploit_db(args.ingest_url, args.token, limit=args.limit, force=args.force)
    if args.source == "ubuntu_security":
        return run_ubuntu_security(args.ingest_url, args.token, limit=args.limit, force=args.force)
    if args.source == "oracle_security_alert":
        return run_oracle(args.ingest_url, args.token, limit=args.limit, force=args.force)
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
