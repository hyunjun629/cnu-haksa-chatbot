# 디버깅 기록

| # | 시점 | 현상 | 원인 | 수정 | 확인 |
|---|---|---|---|---|---|
| 1 | 2주차 배포 | CloudShell 배포 출력의 스택 Outputs 설명이 `?? ???`로 깨짐 | CloudShell 기본 언어 설정(로캘)에서 SAM CLI가 템플릿의 한글을 UTF-8로 처리하지 못함 | `scripts/deploy.sh`에 `export LANG=C.UTF-8 LC_ALL=C.UTF-8 PYTHONIOENCODING=utf-8` 추가 | 3주차 배포 출력에서 한글 설명 확인 |
| 2 | 3주차 개발 (화면 확인) | 출처 카드 미리보기에 `## 2.`, `-` 같은 마크다운 기호가 그대로 표시됨 | 문서가 마크다운(.md)이라 검색된 청크 원문에 제목·목록 기호가 포함됨 | `clean_snippet()`으로 제목(#)·목록(-, *)·표(\|) 기호 제거 | 미리보기 화면에서 기호 제거 확인 |
| 3 | 3주차 개발 (단위 테스트) | `test_snippet_hides_markdown` 실패 — 줄 끝의 `\|`가 남음 | 정규식이 기호 뒤에 공백이 있을 때만 제거하도록 작성됨 | 조건을 "뒤에 공백 또는 문자열 끝"(`(?=\s\|$)`)으로 변경 | 단위 테스트 13개 통과 |
| 4 | 3주차 개발 (모델 준비) | Bedrock 플레이그라운드에서 Claude Haiku 5.5 호출 시 `AccessDeniedException: anthropic.claude-haiku-5-5 is not available for this account` (사용 사례 양식도 뜨지 않음) | 최신 모델에 대한 계정 단위 제한. IAM이나 모델 접근 설정으로는 해제되지 않음 | 생성 모델을 템플릿 파라미터(`GenerationModelName`)로 분리하고 기본값을 Claude Haiku 4.5(`global.anthropic.claude-haiku-4-5-20251001-v1:0`)로 변경, Anthropic 사용 사례 양식 제출 | 플레이그라운드에서 Haiku 4.5 응답 확인 (입력 11·출력 29토큰, 1,098ms) |
