#!/usr/bin/env bash
# 사용법: ./set_api_key.sh
set -e
cd "$(dirname "$0")"
read -rsp "NEIS API Key 입력 (입력 내용은 화면에 표시되지 않습니다): " KEY
echo
if [ -z "$KEY" ]; then
  echo "키가 비어있습니다. 종료." >&2
  exit 1
fi
echo "NEIS_API_KEY=$KEY" > .env
chmod 600 .env
echo "✓ .env 저장 완료 (권한 600)"
