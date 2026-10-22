"""Điểm cuối của vòng phản hồi: hàng đợi duyệt, nhận định của Reviewer, thống kê đồng thuận, xuất tập phản hồi."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse, Response

from rfcv.api import reviews
from rfcv.api.auth import User

if TYPE_CHECKING:
    from rfcv.api.server import Api


async def _json(request: Request) -> None:
    from rfcv.api.server import _require_json  # type: ignore[reportPrivateUsage]

    await _require_json(request)


def register(app: FastAPI, api: Api, writable: Callable[[], None], current: Callable[[Request], User]) -> None:
    m = api.m

    @app.get("/api/reviews/meta")
    def meta() -> dict[str, Any]:
        return {
            "causes": reviews.CAUSES,
            "evidence_flags": reviews.EVIDENCE_FLAGS,
            "labels": list(reviews.LABELS),
            "sample_percent": reviews.SAMPLE_PERCENT,
        }

    @app.get("/api/reviews/queue")
    def queue() -> dict[str, Any]:
        return {"items": reviews.queue(m)}

    @app.get("/api/reviews/summary")
    def summary() -> dict[str, Any]:
        return reviews.summary(m)

    @app.get("/api/reviews/digest")
    def digest() -> PlainTextResponse:
        return PlainTextResponse(reviews.markdown_digest(reviews.summary(m)), media_type="text/markdown; charset=utf-8")

    @app.get("/api/reviews/export")
    def export() -> Response:
        return Response(
            reviews.export_jsonl(m),
            media_type="application/x-ndjson",
            headers={"Content-Disposition": 'attachment; filename="phan-hoi.jsonl"'},
        )

    @app.get("/api/runs/{run_id}/reviews")
    def run_reviews(run_id: str) -> JSONResponse:
        d = m.run_dir(run_id)
        if d is None:
            return JSONResponse({"error": "không có lần chạy này"}, status_code=404)
        rv = reviews.read_reviews(d)
        return JSONResponse(
            {
                "reviews": rv,
                "states": {
                    rid: reviews.state_of([x for x in rv if x["requirement_id"] == rid])
                    for rid in {x["requirement_id"] for x in rv}
                },
            }
        )

    @app.post("/api/runs/{run_id}/reviews", dependencies=[Depends(_json), Depends(writable)])
    def submit(run_id: str, body: reviews.ReviewIn, user: User = Depends(current)) -> JSONResponse:
        if api.auth is not None:  # đã đăng nhập: người duyệt là tài khoản của phiên, tên do máy khách gửi bị bỏ qua
            body = body.model_copy(update={"reviewer": user.username})
        try:
            saved = reviews.submit(m, run_id, body)
        except reviews.ReviewError as exc:
            return JSONResponse({"error": exc.message}, status_code=exc.status)
        return JSONResponse({"review": saved}, status_code=201)
