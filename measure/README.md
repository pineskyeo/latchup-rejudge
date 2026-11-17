# 전원 인가형 latch-up 측정 알고리즘 (POR / DOE)

`latchup_rejudge.py`는 이미 측정된 force-I 곡선을 다시 판정하는 보정이다.
이 폴더의 알고리즘은 측정 방법 자체를 바꾼다: 트리거를 넣었다가 **뺀 뒤에도 전원 전류가 남으면** 래치로 판정한다.
1차 snapback처럼 트리거를 빼면 꺼지는 현상은 래치로 잡히지 않는다.

| 구분 | 파일 | 함수 |
|---|---|---|
| POR (legacy P9000) | `por/P9K_M_latchup_idd.cpp`, `.alg` | `P9K_M_latchup_idd_sub` |
| DOE (cortex) | `doe/latchup_supply_idd.cpp`, `.alg` | `latchup_supply_idd` |

두 버전은 측정 순서와 출력 이름이 같다.

## 무엇이 바뀌었나

| 항목 | 기존 (`P9K_M_latchup3`) | 신규 (`P9K_M_latchup_idd`) |
|---|---|---|
| 전원 핀 P2~P5 | 0 V 고정 | **VDD_max 인가** (V2~V5, 최소 하나는 0 V가 아님) |
| IO 전류 | 100 nA → 50 mA 계속 증가 | 단계마다 **주입 → 제거** |
| 판정 근거 | IO 전압 곡선의 ΔV 부호 변화 | **트리거 제거 후 전원 전류 I_DD** |
| VT | 첫 ΔV 부호 변화 (1차 snapback에 걸림) | 처음으로 래치가 남은 트리거의 IO 전압 |
| VH | 다음 ΔV 부호 변화 (곡선의 골) | 전원 전압을 내리며 래치가 풀리기 직전 전압 |
| 사후 확인 | 없음 | 전원 OFF → ON 후 정상 전류 복귀 확인 |

기존 방식은 전원이 0 V라 "트리거를 뺀 뒤에도 유지되는가"를 원리적으로 볼 수 없었다.

## 측정 순서 (사이트별)

1. **정상 전류**: P2~P5에 V2~V5 인가, P1(IO) 0 A → 전원별 `I_nom` 측정.
   판정 기준 `thr = max(I_nom + Iabs, Irel × I_nom)` (기본 Iabs 10 mA, Irel 1.4, JESD78 방식. 적용 규격 버전 확인 필요)
2. **트리거 → 제거 → 판정** (k = 0, 1, 2 …)
   - IO에 `I_trig = I1start × I1ratio^k`를 `Tpulse` 동안 주입, IO 전압 측정
   - IO를 0 A로 되돌리고 `Tdelay` 대기, 전원 전류 측정
   - 어느 전원이든 `|I| > thr` → **래치**. 이때 `I_trig` = `LU_IT`, IO 전압 = **`LU_VT` (VT)**
   - 래치 없이 `I1end` 또는 `V1Comp`에 도달하면 종료 (STATUS 0)
3. **Hold**: 래치된 전원을 `Vhstep`(기본 0.05 V)씩 낮추며 `|I| − |I_nom| > Ihabs`(기본 100 µA)인지 확인.
   풀리기 직전 전압 = **`LU_VH` (VH)**, 그때 전류 = `LU_IH`
4. **복구 확인**: 전원 0 V → 재인가 후 전류가 thr 이하인지 (`I_RECOVER`)

## 출력

| 출력 | 의미 |
|---|---|
| `STATUS` | 0 래치 없음 / 1 래치 후 복구 / 2 래치 후 복구 안 됨(손상 의심) / -2 thr ≥ compliance(판정 불가) / -3 전원 전부 0 V / -4 설정 오류 |
| `LU_VT`, `LU_IT` | 래치를 일으킨 트리거의 IO 전압·전류 |
| `LU_VH`, `LU_IH` | 전원을 내리며 찾은 hold 전압·전류 |
| `LU_SUP` | 래치 전류가 가장 크게 보인 전원 (1~4 = P2~P5 = DOE SUPPLY1~4) |
| `I_NOM`, `I_LATCH`, `I_RECOVER` | 정상 / 트리거 제거 후 / 전원 재인가 후 전류 |
| `STEP_COUNT` | 실행한 트리거 단계 수 |

POR은 `Multi_OUTPUT1 ≠ 0`이면 기존 LUP 로그와 같은 위치에 `<partid>_<lotid>_LUPIDD.log`를 남긴다.

```
EQPID,PCID,PARTID,LOTID,WFID,XAXIS,YAXIS,DCOP,MOD,ITEM,NUM,PHASE,If,V1,VS,I2,I3,I4,I5,LATCH
```

`PHASE`: `NOM` 정상 전류 / `TRIG` 트리거 단계 (If, V1, 제거 후 I2..I5) / `HOLD` 전원 내림 (VS, 해당 전원 I) / `REC` 전원 재인가 후.

## 입력 대응 (POR ↔ DOE)

| POR | DOE | 의미 | 기본값 |
|---|---|---|---|
| `P1` | `IO_PIN` | 트리거 IO 핀 | |
| `P2..P5` | `SUPPLY1..4_PIN` | 전원/접지 탭 (`""` = 미사용) | `""` |
| `V2..V5` | `VSUP1..4` | 전원 전압 | 0 |
| `I2Comp..I5Comp` | `SUP_COMP` | 전원 compliance | 0.1 A |
| `I1start`, `I1ratio`, `I1end` | `ISTART`, `RATIO`, `I_END` | 트리거 시작, 배율, 최대 | –, 1.05, – |
| `V1Comp` | `V_COMP` | IO 전압 compliance | |
| `Iabs`, `Irel` | `IDD_ABS`, `IDD_REL` | 판정 기준 | 10 mA, 1.4 |
| `Tpulse`, `Tdelay` | `PULSE_S`, `SETTLE_S` | 트리거 시간, 제거 후 대기 | 1 ms, 1 ms |
| `Vhstep`, `Ihabs` | `HOLD_STEP`, `HOLD_ABS` | hold 측정 간격, 판정 전류 | 0.05 V, 100 µA |
| `Integ` | `INTEGRATION` | 적분 시간 | |

## bias 설정 주의

- V2(전원)에 VDD_max를 넣어야 한다. 기존 bias처럼 0 V면 STATUS -3.
- `I2Comp..I5Comp`는 thr보다 커야 한다. 아니면 STATUS -2.
- Iabs 10 mA / compliance 0.1 A 기본값은 JESD78 수준이라 TEG에 맞게 조정 필요.

## 검증 상태

- stub(가짜 장비 API)로 검증: POR과 DOE가 9개 시나리오에서 출력 10개와 장비 호출 순서가 같음, 다중 사이트와 로그 형식 확인.
- 실제 P9000 장비 컴파일·측정은 아직 안 함. `AUF_getTag`와 단일 핀 `force_v`/`measure_i`/`psmu_set_adc` 형태는 장비 컴파일로 확인 필요.
