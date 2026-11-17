/*
 * P9K_M_latchup3_rj -- P9K_M_latchup3 with the VT/VH judgment fixed.
 *
 * MEASUREMENT IS UNCHANGED from P9K_M_latchup3:
 *  - supplies P2..P5 forced to V2..V5 (legacy bias: 0 V), compliance I2Comp..
 *  - P1 forced with a geometric current ramp If[0] = I1start*1.05,
 *    If[j] = If[j-1]*1.05, settle Tdelay (floor 1E-4 s), V(P1) measured
 *    with range 0; stop after the point where |If| >= I1end or |V| >= V1Comp
 *  - point count from (I1stop - I1start)/I1step + 1, same as legacy
 *  - the same LUP log (<partid>_<lotid>_LUP.log, same columns) when
 *    Multi_OUTPUT1 != 0, so latchup_rejudge.py still reads it
 *
 * ONLY THE JUDGMENT CHANGES. Legacy takes the first delta-V sign change as
 * VT, which on a double-snapback curve is the small 1st snapback. Here
 * (same as latchup_rejudge.py --rule main):
 *  1. snapbacks are found with hysteresis from findStartPoint: a drop must
 *     exceed max(DvAbs, DvRel*|Vpeak|); a re-rise must exceed DvAbs
 *  2. VT = peak of the main snapback: among snapbacks at least
 *     MainFrac x (deepest depth) deep, the one with the highest peak V
 *     VH = valley of that snapback; VTI/VHI = the currents there
 *
 * Outputs VT, VH, VTI, VHI keep their legacy names (new judgment).
 * Extra outputs: VT1/VH1 = first snapback, NSNAP = snapbacks found,
 * LVT/LVH = legacy rule result on the same curve (for comparison).
 */

/****** <BEGIN> INCLUDE FILES *********** DON'T EDIT FROM <BEGIN> TO <END> ***/
#include <stdio.h>
#include <stdlib.h>
#include <math.h>
#include <vector>
#include <string>
#include <sstream>
#include <fstream>
#include <tis.h>
#include <AUF.h>
#ifdef TDE_ENV
#include <SPECS_.h>
#include <DISPATCHER.h>
#include <PROBER.h>
#endif
/****** <END>   INCLUDE FILES *********** DON'T EDIT FROM <BEGIN> TO <END> ***/

#ifndef LUP_LOG_DIR
#define LUP_LOG_DIR "/users/dc/ETdata/OLD/SHARED_DATA/"
#endif
#define LUP3RJ_MAX_POINTS 401

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

void P9K_M_latchup3_rj_sub(const vector<REAL>& I1start, const vector<REAL>& I1step, const vector<REAL>& I1stop, const vector<REAL>& I1end, const vector<REAL>& V2, const vector<REAL>& V3, const vector<REAL>& V4, const vector<REAL>& V5, const vector<REAL>& V1Comp, const vector<REAL>& I2Comp, const vector<REAL>& I3Comp, const vector<REAL>& I4Comp, const vector<REAL>& I5Comp, const vector<REAL>& Tdelay, const vector<REAL>& findStartPoint, const vector<STRINGP>& Integ, const vector<STRINGP>& P1, const vector<STRINGP>& P2, const vector<STRINGP>& P3, const vector<STRINGP>& P4, const vector<STRINGP>& P5,
        const vector<REAL>& Multi_OUTPUT1, const vector<REAL>& Multi_OUTPUT2, const vector<REAL>& Multi_OUTPUT3, const vector<REAL>& Multi_OUTPUT4, const vector<REAL>& Multi_OUTPUT5, const vector<STRINGP>& OutputName,
        const vector<REAL>& DvAbs, const vector<REAL>& DvRel, const vector<REAL>& MainFrac,
        vector<REAL>& PLOT, vector<REAL>& VT, vector<REAL>& VH, vector<REAL>& VTI, vector<REAL>& VHI,
        vector<REAL>& VT1, vector<REAL>& VH1, vector<REAL>& NSNAP, vector<REAL>& LVT, vector<REAL>& LVH,
        const INTEGER _size)
{
	(void)Multi_OUTPUT2; (void)Multi_OUTPUT3; (void)Multi_OUTPUT4; (void)Multi_OUTPUT5;

	STRING lotid, dcop, mod, partid, eqpid, pcardid;
	int tmp_waferid = 0, tmp_xaxis = 0, tmp_yaxis = 0;
	stringstream waferid, xaxis, yaxis;

	AUF_getTag("SYSTEM","EQPID", eqpid);
	AUF_getTag("SYSTEM","PROBECARD", pcardid);
	AUF_getTag("SYSTEM","TST_RCP_LOTID", lotid);
	AUF_getTag("SYSTEM","TST_SLOT_CURRENT", tmp_waferid);
	AUF_getTag("SYSTEM","DCOP", dcop);
	AUF_getTag("SYSTEM","TST_DIE_LASTX", tmp_xaxis);
	AUF_getTag("SYSTEM","TST_DIE_LASTY", tmp_yaxis);
	AUF_getTag("SYSTEM","TST_MOD_LAST", mod);
	AUF_getTag("SYSTEM","SEC_PARTID", partid);

	waferid << tmp_waferid; xaxis << tmp_xaxis; yaxis << tmp_yaxis;

	vector<INTEGER> integTime(_size);
	vector<REAL> tDelay(_size);
	for (int __i = 0; __i < _size; ++__i) {
		// Parse integration time
		std::string str;
		str = Integ[__i];
		if (str.compare("SHORT") == 0) {
			integTime[__i] = INTEG_SHORT;
		} else if (str.compare("MEDIUM") == 0) {
			integTime[__i] = INTEG_MEDIUM;
		} else if (str.compare("LONG") == 0) {
			integTime[__i] = INTEG_LONG;
		} else {
			integTime[__i] = INTEG_MEDIUM;
		}
		tDelay[__i] = (Tdelay[__i] < 1.0E-4) ? 1.0E-4 : Tdelay[__i];
	}

	PLOT.assign(_size, 0.0);
	VT.assign(_size, 0.0);
	VH.assign(_size, 0.0);
	VTI.assign(_size, 0.0);
	VHI.assign(_size, 0.0);
	VT1.assign(_size, 0.0);
	VH1.assign(_size, 0.0);
	NSNAP.assign(_size, 0.0);
	LVT.assign(_size, 0.0);
	LVH.assign(_size, 0.0);

	// Multi_OUTPUT1=0 means PLOT is not included in DCOP: no LUP log
	const int do_log = (_size > 0 && Multi_OUTPUT1[0] != 0);
	string logpath = string(LUP_LOG_DIR) + partid + "_" + lotid + "_LUP.log";
	ofstream writeFile;
	if (do_log) writeFile.open(logpath.c_str(), ios::app);

	for (int i = 0; i < _size; i++) {
		STRINGP sp[4] = { P2[i], P3[i], P4[i], P5[i] };
		REAL sv[4] = { V2[i], V3[i], V4[i], V5[i] };
		REAL sc[4] = { I2Comp[i], I3Comp[i], I4Comp[i], I5Comp[i] };

		// legacy point count (the +1 is inside fabs)
		int n = 1;
		if (I1step[i] != 0.0) {
			n = (int)fabs((I1stop[i] - I1start[i]) / I1step[i] + 1);
			if (n < 1) n = 1;
			if (n > LUP3RJ_MAX_POINTS) n = LUP3RJ_MAX_POINTS;
		}

		// same setup as P9K_M_latchup3
		for (int s = 0; s < 4; s++) {
			if (sp[s] == NULL || sp[s][0] == '\0') continue;
			connect_pin(PSMU, sp[s]);
		}
		connect_pin(PSMU, P1[i]);
		psmu_set_adc(P1[i], integTime[i], 1.0);
		for (int s = 0; s < 4; s++) {
			if (sp[s] == NULL || sp[s][0] == '\0') continue;
			force_v(sp[s], sv[s], sv[s], sc[s]);
		}

		// same geometric force-I ramp; unmeasured tail stays 0 like legacy
		double If[LUP3RJ_MAX_POINTS], Vf[LUP3RJ_MAX_POINTS];
		for (int j = 0; j < n; j++) { If[j] = 0.0; Vf[j] = 0.0; }
		int m = 0;
		for (int j = 0; j < n; j++) {
			If[j] = (j == 0) ? I1start[i] * 1.05 : If[j - 1] * 1.05;
			force_i(P1[i], If[j], If[j], V1Comp[i]);
			wait_th(tDelay[i]);
			double v = 0.0;
			measure_v(P1[i], &v, 0);
			Vf[j] = v;
			m = j + 1;

			if (do_log) {
				writeFile << eqpid << "," << pcardid << "," << partid << "," << lotid << "," << waferid.str() << ","
						<< xaxis.str() << "," << yaxis.str() << "," << dcop << "," << mod << "," << OutputName[i] << ","
						<< j + 1 << "," << If[j] << "," << Vf[j] << endl;
			}

			if (fabs(If[j]) >= I1end[i]) break;
			if (fabs(Vf[j]) >= V1Comp[i]) break;
		}
		PLOT[i] = m;

		disable_port_all();
		disconnect_all();

		// new judgment on the measured points only
		const lurj_result r = lurj_judge(Vf, If, m, (int)findStartPoint[i],
				DvAbs[i], DvRel[i], MainFrac[i]);
		NSNAP[i] = r.n_snap;
		if (r.vt_idx >= 0) {
			VT[i] = Vf[r.vt_idx];
			VTI[i] = If[r.vt_idx];
			VH[i] = Vf[r.vh_idx];
			VHI[i] = If[r.vh_idx];
			VT1[i] = Vf[r.vt1_idx];
			VH1[i] = Vf[r.vh1_idx];
		}

		// legacy rule on the same curve, full grid as legacy scans it
		int lt = -1, lh = -1;
		lurj_legacy(Vf, n, (int)findStartPoint[i], &lt, &lh);
		if (lt >= 0) LVT[i] = Vf[lt];
		if (lh >= 0) LVH[i] = Vf[lh];
	}

	sync_th(0);
}
