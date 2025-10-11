"""Python helper mirroring the cnvdb.js prototype."""
from __future__ import annotations

import json
from typing import Any, Dict

from collectors.cnvdb_client import CNVDBClient

_CLIENT = CNVDBClient()


def get_cnv_list(current_page: int = 1, page_size: int = 15) -> Dict[str, Any]:
    """Fetch a paginated CNVDB policy list."""
    return _CLIENT.list_policies(page=current_page, page_size=page_size)


def get_cnv_detail(policy_id: str) -> Dict[str, Any]:
    """Fetch detailed information for a CNVDB policy by identifier."""
    return _CLIENT.get_policy_detail(str(policy_id))


if __name__ == "__main__":
    listing = get_cnv_list()
    print("CNV list:", json.dumps(listing, ensure_ascii=False))
    first_record = listing.get("data", {}).get("records", [{}])[0]
    policy_id = first_record.get("id")
    if policy_id:
        detail = get_cnv_detail(policy_id)
        print("CNV detail:", json.dumps(detail, ensure_ascii=False))
