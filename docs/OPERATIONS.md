# 운영과 복구

## 계속 켜둘 프로그램

| 위치 | 프로세스 | 역할 |
|---|---|---|
| 중앙 Windows | 기존 MLflow server | 중앙 저장소와 UI |
| 중앙 Windows | sync_notion.py | 종료 결과 전송 |
| 웹 실행 Windows 계정 | service_worker.py | 웹 outbox 전송 |
| 각 CLI 환경 | tracker.py sync | 종료 후 미전송 큐 재시도 |

Windows에서 CLI 실험을 직접 실행하지 않는다면 Windows tracker.py sync는 웹 전송에 필수는 아닙니다. 웹은 service_worker.py의 별도 큐를 사용합니다. WSL과 SSH 원격 서버는 다른 환경입니다.

재부팅 후 수동 재시작합니다. Windows 작업 스케줄러/systemd 등록은 별도입니다. 같은 대상으로 Notion worker를 여러 개 돌리지 않습니다.

## 네트워크

1. Windows localhost /health 확인.
2. Windows LAN IP /health 확인.
3. WSL, ai-1, ai-2 각각 /health 확인.
4. 연결 거부: 서버 실행·바인딩·포트 확인. 시간 초과: 방화벽·라우팅 확인. HTTP 403: allowed-hosts 확인.
5. 방화벽 허용은 회사 정책에 맞게 필요한 원격 주소와 5000 포트로 제한합니다. 방화벽 전체를 끄지 않습니다.
6. 다른 네트워크의 AI 서버에서 사설 IP에 접근할 수 없다면 승인된 VPN/터널 등 라우팅이 필요합니다.

Notion의 MLflow 링크는 PC가 켜져 있고 네트워크 연결이 되는 곳에서만 열립니다. Notion 요약 행은 중앙 PC가 꺼져도 볼 수 있습니다.

## 로컬 저장 위치

| 기본 위치 | 내용 |
|---|---|
| ~/.experiment-tracker/ | CLI 설정, 큐, 실행 로그 |
| %USERPROFILE%\.service-tracker-outbox\ | 웹 최신 JSON snapshot |
| %USERPROFILE%\.service-tracker-state\ | 웹 전송 큐 |
| ~/.experiment-notion-sync/ | Notion digest 캐시, 잠금 파일 |

Node와 worker를 다른 사용자로 실행하면 outbox가 다릅니다. 두 프로세스 모두 SERVICE_TRACKER_OUTBOX를 같은 절대 경로로 지정하세요. SERVICE_TRACKER_STATE는 웹 큐 위치, NOTION_SYNC_STATE는 Notion 캐시 위치입니다.

## 재전송

```bash
python3 ~/experiment-hub/tracker.py status
python3 ~/experiment-hub/tracker.py sync --once
```

PENDING은 최신 revision이 중앙에 반영되지 않았다는 뜻입니다. 큐를 지우지 마세요. tracker_id로 Run을 재사용하나 응답 유실 후 metric history 값이 중복될 수 있습니다.

Notion에서 행을 수동 삭제/수정해도 MLflow 속성이 그대로면 digest 캐시 때문에 바로 복원되지 않습니다. 전체 재동기화가 필요하면 **worker 중지 후 캐시 DB를 백업·이름 변경**하고 재시작합니다. 같은 RunID 행은 갱신합니다.

HTTP 401은 토큰, 403은 권한, 404는 대상 ID/페이지 공유를 확인합니다. --check로 열 이름과 타입을 확인하세요. 429는 대기 후 다음 주기에 재시도합니다.

## 백업과 장애 범위

Git 코드 백업과 운영 데이터 백업은 별개입니다. MLflow DB/아티팩트, 로컬 큐와 설정을 백업합니다. SQLite는 writer를 중지한 뒤 복사하거나 backup API를 사용합니다. 자동 보존 기간/정리는 없습니다.

- SIGKILL/정전: RUNNING이 남을 수 있습니다.
- Node 비동기 쓰기 직전 종료: 마지막 상태 유실 가능.
- 로컬 디스크 오류: CLI는 예외, 웹은 경고 후 원래 요청 계속.
- 다른 머신의 Notion worker 중복 실행: RunID 고유 제약이 없어 생성 경쟁 가능.
- 인증: 기본 MLflow stdlib API에 인증 헤더/인증 프록시 지원은 미구현.
- 학습 성공과 지표 수집 성공은 다릅니다. metric_warning을 확인합니다.
