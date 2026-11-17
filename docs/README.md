# 설명 페이지 (HTML)

브라우저로 바로 열면 된다 (외부 라이브러리 없음, 파일 하나로 동작).

| 파일 | 내용 |
|---|---|
| [`latchup.html`](latchup.html) | 래치업 동작 원리: 기생 PNPN(SCR) 구조와 PNP/NPN 턴온 |
| [`latchup-steps.html`](latchup-steps.html) | 소자 단면 애니메이션: 01 지금 측정(1차 → 풀림 → 2차), 02 왜 VDD를 인가하나(VDD 0 V vs 인가, IO 뺀 뒤 비교), 03 신규 전원 인가형 알고리즘 순서(①~⑦), 04 force-I vs force-V |
| [`latchup-judge.html`](latchup-judge.html) | 측정 그대로 판정만 개선한 VT·VH 판정 조건 (`measure/same-condition/`): 곡선 훑기 → 깊이 비교 → 결과 |
| [`forcei-vs-forcev.html`](forcei-vs-forcev.html) | force-I vs force-V: X = 스윕 값, Y = 측정 값, 스텝당 전력, 소자 손상 관점 |

곡선 수치는 ITEM#2 형태를 본뜬 모델 값이다 (실측 아님).
