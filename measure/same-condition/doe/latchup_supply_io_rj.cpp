/*
 * latchup_supply_io_rj -- cortex latchup_supply_io with the VT/VH judgment
 * fixed. DOE form of P9K_M_latchup3_rj.
 *
 * MEASUREMENT IS UNCHANGED from latchup_supply_io (= legacy P9K_M_latchup3):
 * supplies parked at VSUP1..4 (legacy bias 0 V), geometric x1.05 force-I
 * ramp on IO_PIN from ISTART*1.05, settle DELAY_S (floor 1E-4 s), V(IO)
 * with range MEAS_RANGE (legacy 0), stop after |I| >= I_END or |V| >= V_COMP,
 * point count (ISTOP-ISTART)/ISTEP + 1.
 *
 * ONLY THE JUDGMENT CHANGES (same as latchup_rejudge.py --rule main):
 * hysteresis snapback detection from FIND_START (drop > max(DV_ABS,
 * DV_REL*|Vpeak|), re-rise > DV_ABS); VT = peak of the main snapback (depth
 * >= MAIN_FRAC x deepest, highest peak V), VH = its valley.
 * Extra outputs: VT1/VH1 first snapback, N_SNAP, LEG_VT/LEG_VH legacy rule.
 */

/****** <BEGIN> INCLUDE FILES *********** DON'T EDIT FROM <BEGIN> TO <END> ***/
#include <stdio.h>
#include <stdlib.h>
#include <math.h>
#include <vector>
#include <tis.h>
#ifdef TDE_ENV
#include <SPECS_.h>
#include <DISPATCHER.h>
#include <PROBER.h>
#endif
/****** <END>   INCLUDE FILES *********** DON'T EDIT FROM <BEGIN> TO <END> ***/

#include "../shared/alg_common.h"
#include "../shared/alg_debug.h"

#define ALG_LATCHUP_RJ_MAX_POINTS 401

using namespace std;

/* ---- judgment (identical in POR and DOE; same rule as latchup_rejudge.py --rule main) ---- */
#ifndef LURJ_JUDGE_DEFINED
#define LURJ_JUDGE_DEFINED
#define LURJ_MAX_SNAPS 64

typedef struct {
	int n_snap;      /* snapbacks found */
	int vt_idx;      /* main snapback peak index, -1 if none */
	int vh_idx;      /* main snapback valley index */
	int order;       /* 1-based position of the main snapback */
	int vt1_idx;     /* first snapback peak, -1 if none */
	int vh1_idx;     /* first snapback valley */
} lurj_result;

/* Hysteresis peak/valley scan on polarity-normalised voltages vp[0..n-1]. */
static int lurj_snapbacks(const double* vp, int n, int start, double dv_abs,
		double dv_rel, int pk[], int vl[], int max_ev) {
	if (start < 0) start = 0;
	if (n - start < 2) return 0;
	int ne = 0;
	int down = 0;
	int imax = start, imin = start, peak = start;
	for (int j = start + 1; j < n; j++) {
		if (!down) {
			if (vp[j] >= vp[imax]) {
				imax = j;
			} else {
				double thr = dv_rel * fabs(vp[imax]);
				if (thr < dv_abs) thr = dv_abs;
				if (vp[imax] - vp[j] > thr) {
					down = 1;
					peak = imax;
					imin = j;
				}
			}
		} else {
			if (vp[j] <= vp[imin]) {
				imin = j;
			} else if (vp[j] - vp[imin] > dv_abs) {
				if (ne < max_ev) { pk[ne] = peak; vl[ne] = imin; ne++; }
				down = 0;
				imax = j;
			}
		}
	}
	if (down && ne < max_ev) { pk[ne] = peak; vl[ne] = imin; ne++; }
	return ne;
}

static lurj_result lurj_judge(const double* v, const double* cur, int n,
		int start, double dv_abs, double dv_rel, double main_frac) {
	lurj_result r;
	r.n_snap = 0; r.vt_idx = -1; r.vh_idx = -1; r.order = 0;
	r.vt1_idx = -1; r.vh1_idx = -1;
	if (n <= 0) return r;

	/* polarity from the injected current (geometric ramp: one sign) */
	double pol = 1.0;
	for (int j = 0; j < n; j++) {
		if (cur[j] != 0.0) { pol = (cur[j] < 0.0) ? -1.0 : 1.0; break; }
	}
	double vp[512];
	if (n > 512) n = 512;
	for (int j = 0; j < n; j++) vp[j] = v[j] * pol;

	int pk[LURJ_MAX_SNAPS], vl[LURJ_MAX_SNAPS];
	const int ne = lurj_snapbacks(vp, n, start, dv_abs, dv_rel, pk, vl, LURJ_MAX_SNAPS);
	r.n_snap = ne;
	if (ne == 0) return r;
	r.vt1_idx = pk[0];
	r.vh1_idx = vl[0];

	double dmax = 0.0;
	for (int k = 0; k < ne; k++) {
		const double d = vp[pk[k]] - vp[vl[k]];
		if (k == 0 || d > dmax) dmax = d;
	}
	int best = -1;
	for (int k = 0; k < ne; k++) {
		const double d = vp[pk[k]] - vp[vl[k]];
		if (d < main_frac * dmax) continue;
		if (best < 0 || vp[pk[k]] > vp[pk[best]]) best = k;
	}
	r.vt_idx = pk[best];
	r.vh_idx = vl[best];
	r.order = best + 1;
	return r;
}

/* Legacy P9K_M_latchup3 rule over the full grid vf[0..n_grid-1] (unmeasured
 * tail = 0, as the legacy arrays are): VT = point before the first delta-V
 * sign change from find_start, VH = point before the next one (j > 2). */
static void lurj_legacy(const double* vf, int n_grid, int find_start,
		int* vt_idx, int* vh_idx) {
	*vt_idx = -1;
	*vh_idx = -1;
	int k = 0;
	int start = find_start < 1 ? 1 : find_start;
	for (int j = start; j < n_grid; j++) {
		const double d0 = vf[j] - vf[j - 1];
		const double d1 = (j >= 2) ? vf[j - 1] - vf[j - 2] : 0.0;
		if (d0 * d1 < 0.0) { *vt_idx = j - 1; k = j; break; }
	}
	for (int j = k + 1; j < n_grid; j++) {
		const double d0 = vf[j] - vf[j - 1];
		const double d1 = (j >= 2) ? vf[j - 1] - vf[j - 2] : 0.0;
		if (j > 2 && d0 * d1 < 0.0) { *vh_idx = j - 1; break; }
	}
}
#endif /* LURJ_JUDGE_DEFINED */
/* ---- end judgment ---- */

typedef struct {
    REAL point_count_raw, vt, vh, vt_i, vh_i, vt1, vh1, n_snap, leg_vt, leg_vh;
} lurj_out;

static void latchup_supply_io_rj_one(
    STRINGP token, STRINGP io_pin, const STRINGP sup_pin[4],
    const REAL vsup[4], REAL istart, REAL istep, REAL istop,
    REAL i_end, REAL v_comp, REAL sup_comp, INTEGER find_start,
    REAL meas_range, REAL delay_s, STRINGP integration,
    REAL dv_abs, REAL dv_rel, REAL main_frac, INTEGER debug, lurj_out* o);

void latchup_supply_io_rj(
    const vector<STRINGP>& token,
    const vector<STRINGP>& IO_PIN,
    const vector<STRINGP>& SUPPLY1_PIN,
    const vector<STRINGP>& SUPPLY2_PIN,
    const vector<STRINGP>& SUPPLY3_PIN,
    const vector<STRINGP>& SUPPLY4_PIN,
    const vector<REAL>& VSUP1,
    const vector<REAL>& VSUP2,
    const vector<REAL>& VSUP3,
    const vector<REAL>& VSUP4,
    const vector<REAL>& ISTART,
    const vector<REAL>& ISTEP,
    const vector<REAL>& ISTOP,
    const vector<REAL>& I_END,
    const vector<REAL>& V_COMP,
    const vector<REAL>& SUP_COMP,
    const vector<INTEGER>& FIND_START,
    const vector<REAL>& MEAS_RANGE,
    const vector<REAL>& DELAY_S,
    const vector<STRINGP>& INTEGRATION,
    const vector<REAL>& DV_ABS,
    const vector<REAL>& DV_REL,
    const vector<REAL>& MAIN_FRAC,
    const vector<INTEGER>& DEBUG,
    vector<REAL>& POINT_COUNT_RAW,
    vector<REAL>& VT,
    vector<REAL>& VH,
    vector<REAL>& VT_I,
    vector<REAL>& VH_I,
    vector<REAL>& VT1,
    vector<REAL>& VH1,
    vector<REAL>& N_SNAP,
    vector<REAL>& LEG_VT,
    vector<REAL>& LEG_VH,
    const INTEGER _size) {

    POINT_COUNT_RAW.assign(_size, 0.0);
    VT.assign(_size, 0.0);
    VH.assign(_size, 0.0);
    VT_I.assign(_size, 0.0);
    VH_I.assign(_size, 0.0);
    VT1.assign(_size, 0.0);
    VH1.assign(_size, 0.0);
    N_SNAP.assign(_size, 0.0);
    LEG_VT.assign(_size, 0.0);
    LEG_VH.assign(_size, 0.0);

    for (int __i = 0; __i < _size; __i++) {
        STRINGP sup_pin[4] = { SUPPLY1_PIN[__i], SUPPLY2_PIN[__i],
                               SUPPLY3_PIN[__i], SUPPLY4_PIN[__i] };
        REAL vsup[4] = { VSUP1[__i], VSUP2[__i], VSUP3[__i], VSUP4[__i] };
        lurj_out o = { 0, 0, 0, 0, 0, 0, 0, 0, 0, 0 };
        latchup_supply_io_rj_one(token[__i], IO_PIN[__i], sup_pin, vsup,
            ISTART[__i], ISTEP[__i], ISTOP[__i], I_END[__i], V_COMP[__i],
            SUP_COMP[__i], FIND_START[__i], MEAS_RANGE[__i], DELAY_S[__i],
            INTEGRATION[__i], DV_ABS[__i], DV_REL[__i], MAIN_FRAC[__i],
            DEBUG[__i], &o);
        POINT_COUNT_RAW[__i] = o.point_count_raw;
        VT[__i] = o.vt;
        VH[__i] = o.vh;
        VT_I[__i] = o.vt_i;
        VH_I[__i] = o.vh_i;
        VT1[__i] = o.vt1;
        VH1[__i] = o.vh1;
        N_SNAP[__i] = o.n_snap;
        LEG_VT[__i] = o.leg_vt;
        LEG_VH[__i] = o.leg_vh;
    }

    return;
}

static void latchup_supply_io_rj_one(
    STRINGP token, STRINGP io_pin, const STRINGP sup_pin[4],
    const REAL vsup[4], REAL istart, REAL istep, REAL istop,
    REAL i_end, REAL v_comp, REAL sup_comp, INTEGER find_start,
    REAL meas_range, REAL delay_s, STRINGP integration,
    REAL dv_abs, REAL dv_rel, REAL main_frac, INTEGER debug, lurj_out* o)
{
    alg_log_t lg = alg_log_begin(debug, token);
    alg_log_line(lg, 1, "latchup_rj io=%s i=%g..%g step=%g vcomp=%g",
                 io_pin, (double)istart, (double)istop, (double)istep,
                 (double)v_comp);

    const INTEGER integ = alg_integ_code(integration);
    REAL settle = delay_s;
    if (settle < 1.0E-4) settle = 1.0E-4;

    int n = 1;
    if (istep != 0.0) {
        n = (int)fabs((double)((istop - istart) / istep) + 1.0);
        if (n < 1) n = 1;
        if (n > ALG_LATCHUP_RJ_MAX_POINTS) n = ALG_LATCHUP_RJ_MAX_POINTS;
    }

    for (int s = 0; s < 4; ++s) {
        const string pin(sup_pin[s]);
        if (pin.empty()) continue;
        ALG_TIS(lg, connect_pin(PSMU, sup_pin[s]));
    }
    ALG_TIS(lg, connect_pin(PSMU, io_pin));
    ALG_TIS(lg, psmu_set_adc(io_pin, integ, 1.0));
    for (int s = 0; s < 4; ++s) {
        const string pin(sup_pin[s]);
        if (pin.empty()) continue;
        ALG_TIS(lg, force_v(sup_pin[s], vsup[s], vsup[s], sup_comp));
    }

    double vf[ALG_LATCHUP_RJ_MAX_POINTS];
    double ii[ALG_LATCHUP_RJ_MAX_POINTS];
    for (int j = 0; j < n; ++j) { vf[j] = 0.0; ii[j] = 0.0; }
    int m = 0;
    for (int j = 0; j < n; ++j) {
        const REAL cur = (j == 0) ? istart * 1.05 : ii[j - 1] * 1.05;
        ii[j] = cur;
        ALG_TIS(lg, force_i(io_pin, cur, cur, v_comp));
        ALG_TIS(lg, wait_th(settle));
        double v = 0.0;
        ALG_TIS(lg, measure_v(io_pin, &v, meas_range));
        vf[j] = v;
        m = j + 1;
        if (fabs((double)cur) >= i_end) break;
        if (fabs(v) >= v_comp) break;
    }
    o->point_count_raw = (REAL)m;

    const lurj_result r = lurj_judge(vf, ii, m, (int)find_start,
                                     dv_abs, dv_rel, main_frac);
    o->n_snap = r.n_snap;
    if (r.vt_idx >= 0) {
        o->vt = vf[r.vt_idx];
        o->vt_i = ii[r.vt_idx];
        o->vh = vf[r.vh_idx];
        o->vh_i = ii[r.vh_idx];
        o->vt1 = vf[r.vt1_idx];
        o->vh1 = vf[r.vh1_idx];
    }
    int lt = -1, lh = -1;
    lurj_legacy(vf, n, (int)find_start, &lt, &lh);
    if (lt >= 0) o->leg_vt = vf[lt];
    if (lh >= 0) o->leg_vh = vf[lh];

    alg_log_line(lg, 1, "points=%d snaps=%d vt=%.6e vh=%.6e legacy vt=%.6e vh=%.6e",
                 m, r.n_snap, (double)o->vt, (double)o->vh,
                 (double)o->leg_vt, (double)o->leg_vh);

    disable_port_all();
    disconnect_all();
    sync_th(0);
    alg_log_end(lg);
}
