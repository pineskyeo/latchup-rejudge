# 측정 그대로, 판정만 개선 (POR / DOE)

`P9K_M_latchup3` / cortex `latchup_supply_io`와 **장비 동작이 완전히 같다**:
전원 V2~V5 (bias 그대로 0 V), IO에 100 nA부터 ×1.05 force-I sweep, 같은 측정점, 같은 LUP 로그.
바뀌는 것은 측정이 끝난 곡선에서 VT/VH를 고르는 규칙뿐이다 (`latchup_rejudge.py --rule main`과 같음).

| 구분 | 파일 | 함수 |
|---|---|---|
| POR (legacy P9000) | `por/P9K_M_latchup3_rj.{cpp,alg}` | `P9K_M_latchup3_rj_sub` |
| DOE (cortex) | `doe/latchup_supply_io_rj.{cpp,alg}` | `latchup_supply_io_rj` |

## 판정

1. **snapback 찾기**: `findStartPoint`(기본 6)부터, 꼭대기에서 `max(DvAbs, DvRel × |V|)` (기본 50 mV, 3%) 넘게 떨어지면 snapback 1개. 골 이후 `DvAbs` 넘게 다시 오르면 그 snapback 종료. 작은 흔들림은 무시.
2. **깊이 비교**: 깊이 = 꼭대기 − 골. 가장 깊은 것의 `MainFrac`(0.7) 이상인 snapback만 후보.
3. **선택**: 후보 중 꼭대기 전압이 가장 높은 것. 그 꼭대기 = **VT**, 그 골 = **VH**.

음의 방향 주입은 −V로 판정하고 원래 부호로 출력한다.

## 출력

| POR | DOE | 의미 |
|---|---|---|
| `PLOT` | `POINT_COUNT_RAW` | 측정 점 수 |
| `VT`, `VTI` | `VT`, `VT_I` | 새 판정 trigger 전압·전류 (이름은 기존과 같음) |
| `VH`, `VHI` | `VH`, `VH_I` | 새 판정 hold 전압·전류 |
| `VT1`, `VH1` | `VT1`, `VH1` | 첫 번째 snapback (참고) |
| `NSNAP` | `N_SNAP` | 찾은 snapback 수 |
| `LVT`, `LVH` | `LEG_VT`, `LEG_VH` | 같은 곡선에 기존 규칙을 적용한 값 (기존 데이터와 비교용) |

## bias 적용

- POR: 알고리즘 이름만 `P9K_M_latchup3` → `P9K_M_latchup3_rj`. 새 파라미터 `DvAbs / DvRel / MainFrac`은 DEVICE 쪽에 기본값(0.05 / 0.03 / 0.7)이 있다. INPUT 줄은 기존과 같다.
- DOE: `latchup_supply_io` → `latchup_supply_io_rj`, `DV_ABS / DV_REL / MAIN_FRAC` 기본값 동일.
- 출력이 5개 늘어나므로 DCOP 출력 항목 등록은 확인 필요.

## 검증

```bash
test/run_tests.sh      # CORTEX=<cortex 경로> 로 바꿀 수 있음
```

stub(가짜 장비 API)으로 확인한 것:
- 원본 cortex `latchup_supply_io`와 장비 호출 순서가 완전히 같고, `LEG_VT/LEG_VH`가 원본의 VT/VH와 같다 (= 측정 동일, 기존 값 재현).
- 샘플 곡선 11개(단일/이중/노이즈/음극성/조기 종료/snapback 없음)에서 VT·VH·VT1·VH1·NSNAP·LVT·LVH가 `latchup_rejudge.py`와 같다.
- POR과 DOE의 출력과 장비 호출이 같다. 두 파일에 들어 있는 판정 코드 블록이 글자 단위로 같다.
- POR LUP 로그를 `latchup_rejudge.py`가 다시 읽을 수 있다.

실제 P9000 장비 컴파일·측정은 아직 안 함 (`AUF_getTag`, 단일 핀 `force_v`/`measure_v`/`psmu_set_adc` 형태 확인 필요).
