# 기존 설치에서 이전

**GitHub 업로드만 하려면 운영 파일을 교체할 필요가 없습니다.** 별도 폴더에 압축을 풀어 올리세요.

## 변경점

- tracker.py: 기존 큐 형식 유지. 기본 URI localhost, 결과/로그 경로 태그 제거.
- service JS와 worker: 기존 outbox/큐 형식 유지.
- sync_notion.py: 공개용 독립 구현. 종료 Run만 처리, RunID로 upsert, 로컬 digest 캐시. 기존 notion_sync_marker는 사용하지 않음.
- 비공개 회사 라우트와 자동 패치 대신 범용 integration_example.js 제공.

## 운영 파일 교체 순서

1. 진행 중 학습·추론은 그대로 완료시킵니다. 기록을 위해 재실행하지 않습니다.
2. 기존 코드와 .env를 안전한 로컬 위치에 백업합니다. GitHub에 .env를 올리지 않습니다.
3. MLflow는 기존 명령과 **기존 DB/아티팩트 경로**를 유지합니다. 신규 설치용 DB를 열지 않습니다.
4. 기존 Notion worker만 Ctrl+C로 중지합니다. 새 worker와 동시에 실행하지 않습니다.
5. 공개 소스를 별도 폴더에 두고 기존 .env를 지정해 검증합니다.

```powershell
C:\experiment-hub\.venv\Scripts\python.exe C:\experiment-hub-public\sync_notion.py --env-file C:\experiment-hub\.env --check
```

6. 누락된 열을 추가한 후 한 번 동기화합니다.

```powershell
C:\experiment-hub\.venv\Scripts\python.exe -u C:\experiment-hub-public\sync_notion.py --env-file C:\experiment-hub\.env --once
```

7. 모든 활성 실험의 종료 Run을 조회합니다. 기존 RunID 행은 갱신합니다. 코드가 관리하는 14개 열은 MLflow 값으로 갱신되며 사용자 메모 등 나머지 열은 건드리지 않습니다.
8. 정상이라면 --once 없이 실행합니다. 기존 worker는 켜지 않습니다.
9. CLI tracker는 다음 새 실험부터 교체합니다. 기존 큐 폴더를 삭제하지 않습니다. 동일 HOME/URI이면 대기 큐를 재사용합니다.
10. 이미 비공개 웹 패치를 적용했다면 공개 예제를 중복 삽입하지 않습니다.

실패하면 새 worker를 종료하고 기존 worker로 돌아갑니다. 새 digest 캐시는 기존 MLflow/Notion 데이터를 삭제하지 않습니다.

## 과거 결과

MLflow에 있는 종료 Run은 수집할 수 있습니다. 기록기 없이 실행된 과거 학습은 별도 import가 필요하며 임의 결과 폴더를 자동 스캔하지 않습니다. 과거 노출된 토큰은 재발급 후 로컬 .env만 갱신합니다.
