"""Rebuild precise documentation diagrams with Graphviz (dot on PATH)."""
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parent
STYLE = '''digraph G {
 graph [bgcolor="#F5F7FB", pad="0.45", nodesep="0.35", ranksep="0.48", fontname="Noto Sans CJK KR", fontsize=22, fontcolor="#142D4E", labelloc=t];
 node [shape=box, style="rounded,filled", fillcolor="#FFFFFF", color="#CAD5E5", penwidth=1.3, fontname="Noto Sans CJK KR", fontsize=14, fontcolor="#142D4E", margin="0.22,0.16"];
 edge [color="#55769F", penwidth=1.5, arrowsize=0.7, fontname="Noto Sans CJK KR", fontsize=11, fontcolor="#48617E"];
'''
DIAGRAMS = {
'01-architecture': '''label="EXPERIMENT HUB  /  전체 구조";
 subgraph cluster_sources {label="실행 환경 · VS Code는 접속 도구"; fontsize=15; color="#D4DEEB"; style=rounded;
 service [label="service\nWindows · 웹 Auto Seg 버튼",fillcolor="#E3F5EF"];
 local [label="local\nWSL Linux · tracker.py run"];
 ai1 [label="ai-1\nSSH 원격 서버 · tracker.py run"];
 ai2 [label="ai-2\nSSH 원격 서버 · tracker.py run"];
 }
 outbox [label="웹 요청별 JSON outbox\nservice_worker.py → SQLite",fillcolor="#E3F5EF"];
 queues [label="각 환경의 로컬 SQLite 큐\n실행 중 전송 + sync worker 재시도",fillcolor="#E8EEFF"];
 hub [label="Windows 중앙 PC · MLflow\nRUNNING / FINISHED / FAILED / KILLED",fillcolor="#DCE9FF"];
 sync [label="sync_notion.py · 30초 간격\n종료 결과만 선택 · RunID로 갱신",fillcolor="#FFF0D5"];
 notion [label="Notion · AI 실험 기록\nEnv / Project / Dice / 소요 시간",fillcolor="#FFF0D5"];
 service -> outbox; local -> queues; ai1 -> queues; ai2 -> queues;
 outbox -> hub; queues -> hub; hub -> sync; sync -> notion;
''',
'02-setup': '''label="SETUP  /  처음 한 번 설정";
 a [label="01  Windows 중앙 저장소 준비\n코드 배치 · Python 가상환경 · MLflow"];
 b [label="02  네트워크 확인\n서버 → Windows:5000 /health"];
 c [label="03  Notion 표 + 내부 연결\n14개 속성 · 페이지 사용 권한"];
 d [label="04  중앙 PC .env\nMLflow 주소 · 토큰 · 데이터베이스 ID"];
 e [label="05  각 실행 환경 init\nlocal / ai-1 / ai-2 각각 구분"];
 f [label="06  지속 worker 실행\ntracker sync · service worker · Notion sync"];
 g [label="07  테스트 후 실제 실험\nMLflow RUNNING → 종료 → Notion",fillcolor="#DDF4EB"];
 a -> b -> c -> d -> e -> f -> g;
''',
'03-lifecycle': '''label="RUN LIFECYCLE  /  Notion에 언제 나타날까?";
 a [label="tracker.py run 또는 웹 버튼"];
 b [label="RUNNING\n로컬 보관 → MLflow",fillcolor="#E8EEFF"];
 c [label="실험 프로세스 / 웹 작업 종료",shape=diamond,style=filled];
 ok [label="FINISHED",fillcolor="#DDF4EB"];
 fail [label="FAILED / KILLED\n잡을 수 있는 오류·중단",fillcolor="#FFE4E5"];
 n [label="종료 결과를 Notion 행으로 반영\nRunID 검색 → 생성 또는 수정",fillcolor="#FFF0D5"];
 crash [label="강제 종료·정전\nRUNNING이 남을 수 있음",fillcolor="#F0E9FA"];
 a -> b -> c; c -> ok [label="성공"]; c -> fail [label="실패 / 중단"];
 ok -> n; fail -> n; b -> crash [style=dashed,label="종료 처리 불가"];
''',
'04-web-timing': '''label="WEB TIMING  /  시간의 의미를 구분";
 a [label="Auto Seg 요청 승인\nrecord.start",fillcolor="#E3F5EF"];
 b [label="입력 준비 + GPU 큐 대기\nbefore_pipeline_sec"];
 c [label="Python 프로세스 시작\npipelineStart()",fillcolor="#DCE9FF"];
 d [label="전처리 → 모델 → 후처리\n순수 모델 시간은 별도 측정 필요",fillcolor="#DCE9FF"];
 e [label="Python 완료\npython_pipeline_sec → Pipeline_s",fillcolor="#DCE9FF"];
 f [label="결과 생성 후 finish\npipeline_total_sec → Total_s",fillcolor="#E3F5EF"];
 a -> b -> c -> d -> e -> f;
 note [label="업로드 이전 시간은 Total_s에 포함하지 않음\nDice는 정답 비교값이 있을 때만 기록",shape=note,fillcolor="#FFF0D5"];
 f -> note [style=dashed,arrowhead=none];
''',
'05-troubleshooting': '''label="CHECK  /  Notion에 기록이 없을 때";
 a [label="MLflow에 해당 Run이 있는가?",shape=diamond,style=filled];
 b [label="서버에서 tracker.py status\nnohup 로그의 Output log 확인\n/health 연결과 init 주소 확인"];
 c [label="상태가 RUNNING인가?",shape=diamond,style=filled];
 d [label="현재 동작이 정상일 수 있음\nNotion에는 종료 후 반영",fillcolor="#E8EEFF"];
 e [label="중앙 PC sync_notion.py 확인\n토큰 · 사용 권한 · 열 이름/타입\nworker 오류와 중복 RunID 확인",fillcolor="#FFF0D5"];
 a -> b [label="없음"]; a -> c [label="있음"]; c -> d [label="예"]; c -> e [label="종료됨"];
''',
}
for name, body in DIAGRAMS.items():
    source = ROOT / 'diagrams' / (name + '.dot')
    source.write_text(STYLE + body + '}\n', encoding='utf-8')
    for ext in ('svg', 'png'):
        subprocess.run(['dot', '-T'+ext, '-Gdpi=150', str(source), '-o', str(ROOT/'images'/(name+'.'+ext))], check=True)
print('Rendered', len(DIAGRAMS), 'SVG + PNG diagrams')
