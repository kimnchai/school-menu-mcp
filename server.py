"""School Menu MCP server.

NEIS Open API 기반으로 한국 초/중/고 학교 급식 메뉴를 조회합니다.
"""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta
from typing import Any

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import PlainTextResponse

from neis_client import MealItem, NeisClient, NeisError, School

load_dotenv()

MCP_TRANSPORT = os.environ.get("MCP_TRANSPORT", "stdio")
MCP_HOST = os.environ.get("MCP_HOST", "0.0.0.0" if MCP_TRANSPORT != "stdio" else "127.0.0.1")
MCP_PORT = int(os.environ.get("PORT", os.environ.get("MCP_PORT", "8000")))
PLAYMCP_MODE = os.environ.get("PLAYMCP_MODE", "0") == "1"

if PLAYMCP_MODE:
    mcp = FastMCP("school-menu", host=MCP_HOST, port=MCP_PORT, stateless_http=True)
else:
    mcp = FastMCP("school-menu", host=MCP_HOST, port=MCP_PORT)


@mcp.custom_route("/health", methods=["GET"])
async def health(_: Request) -> PlainTextResponse:
    return PlainTextResponse("ok")


@mcp.custom_route("/ready", methods=["GET"])
async def ready(_: Request) -> PlainTextResponse:
    return PlainTextResponse("ok")


def _fmt_date(s: str) -> str:
    """YYYYMMDD → YYYY-MM-DD."""
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:]}"
    return s


def _normalize_date(s: str) -> str:
    """YYYY-MM-DD 또는 YYYYMMDD → YYYYMMDD."""
    s = s.strip().replace("-", "").replace("/", "")
    if len(s) != 8 or not s.isdigit():
        raise ValueError(f"날짜 형식이 올바르지 않습니다: {s} (YYYY-MM-DD 또는 YYYYMMDD)")
    return s


def _school_to_dict(s: School) -> dict[str, Any]:
    return {
        "office_code": s.office_code,
        "school_code": s.school_code,
        "name": s.name,
        "kind": s.kind,
        "address": s.address,
        "office_name": s.office_name,
    }


def _meal_to_dict(m: MealItem, include_allergies: bool) -> dict[str, Any]:
    out: dict[str, Any] = {
        "date": _fmt_date(m.date),
        "meal_type": m.meal_type,
        "dishes": m.dishes,
        "calories": m.calories,
    }
    if include_allergies:
        out["allergies"] = {k: v for k, v in m.allergies.items() if v}
    return out


@mcp.tool()
async def search_school(name: str) -> dict[str, Any]:
    """학교명으로 학교를 검색해 급식 조회에 필요한 코드를 반환합니다.

    Args:
        name: 학교명 (부분 일치 가능, 예: "서울고", "한국과학영재")

    Returns:
        매칭된 학교 목록. 각 항목은 office_code, school_code, name, kind, address, office_name 포함.
        이후 get_meal/get_meals_range 호출 시 office_code + school_code 를 사용하세요.
    """
    async with NeisClient() as client:
        try:
            schools = await client.search_school(name)
        except NeisError as e:
            return {"error": str(e), "schools": []}
    return {"count": len(schools), "schools": [_school_to_dict(s) for s in schools]}


@mcp.tool()
async def get_meal(
    office_code: str,
    school_code: str,
    target_date: str | None = None,
    include_allergies: bool = True,
) -> dict[str, Any]:
    """특정 날짜의 급식 메뉴(조식/중식/석식)를 조회합니다.

    Args:
        office_code: 시도교육청코드 (search_school 결과의 office_code)
        school_code: 표준학교코드 (search_school 결과의 school_code)
        target_date: 조회 날짜 (YYYY-MM-DD 또는 YYYYMMDD). 생략 시 오늘.
        include_allergies: 알레르기 유발 식품 정보 포함 여부

    Returns:
        해당 날짜의 급식 정보. 학교가 그 날 급식을 제공하지 않으면 빈 리스트.
    """
    d = _normalize_date(target_date) if target_date else date.today().strftime("%Y%m%d")
    async with NeisClient() as client:
        try:
            meals = await client.get_meals(office_code, school_code, date=d)
        except NeisError as e:
            return {"error": str(e), "meals": []}
    return {
        "date": _fmt_date(d),
        "count": len(meals),
        "meals": [_meal_to_dict(m, include_allergies) for m in meals],
    }


@mcp.tool()
async def get_meals_range(
    office_code: str,
    school_code: str,
    date_from: str,
    date_to: str,
    include_allergies: bool = False,
) -> dict[str, Any]:
    """기간 내 모든 급식 메뉴를 조회합니다 (주간/월간 메뉴 조회용).

    Args:
        office_code: 시도교육청코드
        school_code: 표준학교코드
        date_from: 시작일 (YYYY-MM-DD)
        date_to: 종료일 (YYYY-MM-DD). NEIS는 최대 약 한 달 범위까지 권장.
        include_allergies: 알레르기 정보 포함 여부 (기간 조회 시 응답이 커질 수 있어 기본 False)

    Returns:
        기간 내 날짜별/끼니별 급식 목록.
    """
    f = _normalize_date(date_from)
    t = _normalize_date(date_to)
    if f > t:
        return {"error": "date_from 이 date_to 보다 늦습니다", "meals": []}

    async with NeisClient() as client:
        try:
            meals = await client.get_meals(
                office_code, school_code, date_from=f, date_to=t
            )
        except NeisError as e:
            return {"error": str(e), "meals": []}
    return {
        "date_from": _fmt_date(f),
        "date_to": _fmt_date(t),
        "count": len(meals),
        "meals": [_meal_to_dict(m, include_allergies) for m in meals],
    }


@mcp.tool()
async def get_weekly_meal(
    office_code: str,
    school_code: str,
    reference_date: str | None = None,
    include_allergies: bool = False,
) -> dict[str, Any]:
    """주어진 날짜가 속한 주(월~금)의 급식을 조회합니다.

    Args:
        office_code: 시도교육청코드
        school_code: 표준학교코드
        reference_date: 기준 날짜 (YYYY-MM-DD). 생략 시 오늘.
        include_allergies: 알레르기 정보 포함 여부
    """
    if reference_date:
        ref = datetime.strptime(_normalize_date(reference_date), "%Y%m%d").date()
    else:
        ref = date.today()
    monday = ref - timedelta(days=ref.weekday())
    friday = monday + timedelta(days=4)
    return await get_meals_range(
        office_code,
        school_code,
        monday.strftime("%Y-%m-%d"),
        friday.strftime("%Y-%m-%d"),
        include_allergies,
    )


if __name__ == "__main__":
    if MCP_TRANSPORT == "streamable-http":
        import uvicorn

        mcp.settings.json_response = os.environ.get("MCP_JSON_RESPONSE", "1") == "1"
        starlette_app = mcp.streamable_http_app()
        final_app = starlette_app
        if PLAYMCP_MODE:
            from playmcp import GlobalRateLimitMiddleware, OriginCheckMiddleware

            final_app = GlobalRateLimitMiddleware(OriginCheckMiddleware(starlette_app))

        uvicorn.run(final_app, host=MCP_HOST, port=MCP_PORT, log_level="info", timeout_keep_alive=int(os.environ.get("MCP_KEEPALIVE", "30")))
    else:
        mcp.run(transport=MCP_TRANSPORT)
