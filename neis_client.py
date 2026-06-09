"""NEIS Open API client for school meal data.

Docs: https://open.neis.go.kr/portal/data/service/selectServicePage.do
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import httpx

BASE_URL = "https://open.neis.go.kr/hub"

MEAL_CODE = {"1": "조식", "2": "중식", "3": "석식"}


class NeisError(Exception):
    pass


@dataclass
class School:
    office_code: str  # ATPT_OFCDC_SC_CODE — 시도교육청코드
    school_code: str  # SD_SCHUL_CODE — 표준학교코드
    name: str
    kind: str  # 초/중/고/특수학교
    address: str
    office_name: str


@dataclass
class MealItem:
    date: str  # YYYYMMDD
    meal_type: str  # 조식/중식/석식
    dishes: list[str]  # 메뉴 항목
    allergies: dict[str, list[str]]  # {메뉴명: [알레르기 코드들]}
    calories: str
    nutrients: str


class NeisClient:
    def __init__(self, api_key: str | None = None, timeout: float = 10.0):
        self.api_key = api_key or os.environ.get("NEIS_API_KEY")
        self._client = httpx.AsyncClient(timeout=timeout)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "NeisClient":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.aclose()

    async def _request(self, endpoint: str, params: dict[str, Any]) -> dict[str, Any]:
        params = {"Type": "json", "pIndex": 1, "pSize": 100, **params}
        if self.api_key:
            params["KEY"] = self.api_key
        resp = await self._client.get(f"{BASE_URL}/{endpoint}", params=params)
        resp.raise_for_status()
        data = resp.json()
        # NEIS returns either {endpoint: [...]} on success or {RESULT: {CODE, MESSAGE}} on error
        if "RESULT" in data:
            code = data["RESULT"].get("CODE", "")
            msg = data["RESULT"].get("MESSAGE", "")
            if code == "INFO-200":  # 데이터 없음
                return {}
            raise NeisError(f"NEIS {code}: {msg}")
        return data.get(endpoint, [{}, {}])

    async def search_school(self, name: str) -> list[School]:
        """학교명으로 학교 검색."""
        result = await self._request("schoolInfo", {"SCHUL_NM": name})
        if not result:
            return []
        rows = self._extract_rows(result)
        return [
            School(
                office_code=r["ATPT_OFCDC_SC_CODE"],
                school_code=r["SD_SCHUL_CODE"],
                name=r["SCHUL_NM"],
                kind=r.get("SCHUL_KND_SC_NM", ""),
                address=r.get("ORG_RDNMA", ""),
                office_name=r.get("ATPT_OFCDC_SC_NM", ""),
            )
            for r in rows
        ]

    async def get_meals(
        self,
        office_code: str,
        school_code: str,
        date: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> list[MealItem]:
        """급식 식단 조회. date 또는 date_from+date_to 중 하나 사용."""
        params: dict[str, Any] = {
            "ATPT_OFCDC_SC_CODE": office_code,
            "SD_SCHUL_CODE": school_code,
        }
        if date:
            params["MLSV_YMD"] = date
        elif date_from and date_to:
            params["MLSV_FROM_YMD"] = date_from
            params["MLSV_TO_YMD"] = date_to
        else:
            raise ValueError("date 또는 date_from+date_to 가 필요합니다")

        result = await self._request("mealServiceDietInfo", params)
        if not result:
            return []
        rows = self._extract_rows(result)
        return [self._parse_meal(r) for r in rows]

    @staticmethod
    def _extract_rows(payload: Any) -> list[dict[str, Any]]:
        # NEIS 응답: [{"head": [...]}, {"row": [...]}]
        if not isinstance(payload, list):
            return []
        for chunk in payload:
            if isinstance(chunk, dict) and "row" in chunk:
                return chunk["row"]
        return []

    @staticmethod
    def _parse_meal(row: dict[str, Any]) -> MealItem:
        raw_dish = row.get("DDISH_NM", "")
        dishes, allergies = _parse_dishes(raw_dish)
        return MealItem(
            date=row.get("MLSV_YMD", ""),
            meal_type=row.get("MMEAL_SC_NM", ""),
            dishes=dishes,
            allergies=allergies,
            calories=row.get("CAL_INFO", ""),
            nutrients=row.get("NTR_INFO", "").replace("<br/>", "\n"),
        )


# 알레르기 코드 (NEIS 식품정보)
ALLERGY_LABELS = {
    "1": "난류", "2": "우유", "3": "메밀", "4": "땅콩", "5": "대두",
    "6": "밀", "7": "고등어", "8": "게", "9": "새우", "10": "돼지고기",
    "11": "복숭아", "12": "토마토", "13": "아황산류", "14": "호두",
    "15": "닭고기", "16": "쇠고기", "17": "오징어", "18": "조개류",
    "19": "잣",
}


def _parse_dishes(raw: str) -> tuple[list[str], dict[str, list[str]]]:
    """DDISH_NM 파싱: '백미밥<br/>김치찌개 (5.6.)<br/>...' → 메뉴 리스트 + 알레르기 매핑."""
    import re

    if not raw:
        return [], {}
    parts = [p.strip() for p in raw.split("<br/>") if p.strip()]
    dishes: list[str] = []
    allergies: dict[str, list[str]] = {}
    for part in parts:
        m = re.search(r"\(([\d\.\s]+)\)\s*$", part)
        if m:
            name = part[: m.start()].strip()
            codes = [c for c in re.split(r"[.\s]+", m.group(1).strip()) if c]
            dishes.append(name)
            allergies[name] = [ALLERGY_LABELS.get(c, c) for c in codes]
        else:
            dishes.append(part)
    return dishes, allergies
