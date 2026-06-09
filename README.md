# school-menu-mcp

한국 NEIS Open API 기반 학교 급식 메뉴 조회 MCP 서버.

## 기능

| 도구 | 설명 |
|---|---|
| `search_school` | 학교명으로 검색 → 급식 조회에 필요한 코드 반환 |
| `get_meal` | 특정 날짜의 조식/중식/석식 조회 (알레르기 정보 포함) |
| `get_meals_range` | 기간 내 모든 급식 조회 |
| `get_weekly_meal` | 기준일이 속한 주(월~금) 급식 조회 |

## 설치

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## NEIS API 키 설정

키 없이도 동작하지만 일일 1,000회 제한이 있습니다. 발급받으려면:

1. https://open.neis.go.kr/portal/mainPage.do 접속 후 회원가입/로그인
2. **인증키 신청** 메뉴 → 활용 사유 입력 후 발급 (즉시)

저장 방법 (셋 중 하나):

```bash
# (a) 대화형 스크립트 — 가장 안전
./set_api_key.sh

# (b) 직접 작성
cp .env.example .env
# .env 파일 열고 NEIS_API_KEY=... 채우기

# (c) 환경 변수
export NEIS_API_KEY=...
```

`.env` 파일은 `.gitignore`에 포함되어 커밋되지 않습니다.

## 실행

```bash
source venv/bin/activate
python server.py
```

### Claude Desktop / Claude Code 등록

`~/.config/claude/claude_desktop_config.json` (또는 Claude Code MCP 설정)에 추가:

```json
{
  "mcpServers": {
    "school-menu": {
      "command": "/home/icj74/school-menu-mcp/venv/bin/python",
      "args": ["/home/icj74/school-menu-mcp/server.py"],
      "env": {
        "NEIS_API_KEY": "선택사항"
      }
    }
  }
}
```

## 사용 예

1. 학교 검색
   ```
   search_school(name="서울고등학교")
   → office_code="B10", school_code="7010083"
   ```
2. 오늘 급식 조회
   ```
   get_meal(office_code="B10", school_code="7010083")
   ```
3. 이번 주 급식
   ```
   get_weekly_meal(office_code="B10", school_code="7010083")
   ```

## 참고

- NEIS Open API 가이드: https://open.neis.go.kr/portal/data/service/selectServicePage.do
- 알레르기 코드 19종(난류/우유/메밀/땅콩/대두/밀/...)을 자동 라벨링.
