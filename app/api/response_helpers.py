import math
from typing import Any, Dict, Iterable

from app.utils.mongo_utils import public_document


def pagination_metadata(page: int, page_size: int, total: int) -> Dict[str, Any]:
    total_pages = math.ceil(total / page_size) if total else 0
    return {
        "page": page,
        "pageSize": page_size,
        "totalRecords": total,
        "totalPages": total_pages,
        "hasNext": page < total_pages,
        "hasPrevious": page > 1 and total_pages > 0,
    }


def list_response(documents: Iterable[Dict[str, Any]], page: int, page_size: int, total: int):
    return {
        "data": [public_document(document) for document in documents],
        "pagination": pagination_metadata(page, page_size, total),
    }
