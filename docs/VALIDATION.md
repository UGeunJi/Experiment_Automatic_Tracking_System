# 검증 기록

이 공개 패키지를 만드는 과정에서 Linux 실행 환경에서 검증했습니다. 사용자 Windows/AI 서버에 배포하거나 실제 Notion에 테스트 행을 쓰지는 않았습니다.

## 통과한 검증

- Python unittest 17개: 오프라인 큐, 재전송, 같은 Run 재사용, 실제 자식 프로세스 종료 코드, 숫자 검증, nnU-Net 경로·결과 변경 감지, 웹 snapshot 중복/상태 회귀 방지.
- Notion worker: RUNNING 제외, 종료 결과 전송, 변경 없는 결과 생략, 지표 변경 시 갱신, 실패 시 캐시 미갱신, RunID 기존 행 수정/새 행 생성, 중복 RunID 거부, 페이지네이션, URL을 ID로 입력했을 때 거부.
- Node 기록기: 동시 요청 분리, 성공·실패, 중복 finish, 민감 필드 제외, 시간 기록, 디스크 오류 격리.
- Python compileall 및 Node integration example 구문 검사.
- README의 상대 문서/이미지 링크와 공개 패키지의 알려진 개인 경로·토큰 패턴 점검.
- PNG 흐름도 5장의 한글·여백·연결선 시각 확인.

## 아직 검증하지 않은 부분

- 실제 Windows의 프로세스 잠금·파일 교체와 운영 웹/GPU 연동.
- 실제 MLflow 3.18.0/Notion 계정에 대한 종단 간 테스트. 새 Notion worker의 네트워크 동작은 API 계약에 맞춰 구현했으며 unit test는 mock 응답을 사용합니다.
- GitHub Actions 원격 실행. workflow 파일은 포함했지만 GitHub에 push하지 않았습니다.
- 수천~수만 Run 규모의 조회 성능, 장기간 보관·정전 복구.

운영 적용 전에 README의 합성 지표 테스트를 한 번 실행하고 MLflow와 Notion에서 같은 RunID가 보이는지 확인하세요.
