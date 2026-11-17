/*
 * P9K_M_latchup_idd -- powered-supply latch-up I-test, POR (legacy P9000) form
 *
 * Same measurement as the DOE algorithm latchup_supply_idd
 * (cortex sdk/algorithms/latchup__supply_idd). Inputs follow the legacy
 * P9K_M_latchup3 naming (I1*, V2..V5, I2Comp..I5Comp, Tdelay, Integ,
 * P1..P5); outputs use the same names as the DOE algorithm so POR and DOE
 * results line up item by item.
 *
 * P9K_M_latchup3 grounds the supplies (legacy.bias V2..V5 = 0) and infers
 * latch from the IO V-I curve shape, so a snapback the device cannot hold
 * looks the same as a real latch. Here latch-up is measured by its
 * definition: supplies powered, trigger current injected into P1 and then
 * REMOVED, supply current measured afterwards.
 *
 * Per site (sites run one after another so each can stop on its own latch):
 *  1. P2..P5 forced to V2..V5 (compliance I2Comp..I5Comp), P1 at 0 A.
 *     Nominal supply current I_nom; threshold per supply
 *     thr = max(|I_nom| + Iabs, Irel * |I_nom|)  (JESD78-style; confirm the
 *     revision your spec cites).
 *  2. Step k: I_trig = I1start * I1ratio^k on P1 for Tpulse, measure V(P1),
 *     P1 back to 0 A, wait Tdelay, measure every supply. Latched when any
 *     |I_post| > thr. Stop on latch, |I_trig| >= I1end or |V| >= V1Comp.
 *  3. On latch, step the powered supply with the largest |I_post|/thr
 *     toward 0 V by Vhstep while |I| - |I_nom| > Ihabs: LU_VH / LU_IH.
 *  4. Power-cycle all supplies (0 V, then V2..V5) and re-measure.
 *
 * STATUS: 0 no latch, 1 latch + recovered, 2 latch + NOT recovered,
 *        -2 thr >= supply compliance (latch undetectable),
 *        -3 every used supply at 0 V (latch cannot be held),
 *        -4 bad config (I1start = 0, I1ratio <= 1, Iabs <= 0).
 *
 * Multi_OUTPUT1 != 0 appends every step to
 * <LUPIDD_LOG_DIR>/<partid>_<lotid>_LUPIDD.log, the same place and switch as
 * the P9K_M_latchup3 LUP log:
 *   EQPID,PCID,PARTID,LOTID,WFID,XAXIS,YAXIS,DCOP,MOD,ITEM,NUM,PHASE,If,V1,VS,I2,I3,I4,I5,LATCH
 *   PHASE NOM  : I2..I5 = nominal supply currents
 *         TRIG : If = trigger, V1 = V(P1) during trigger, I2..I5 after removal
 *         HOLD : VS = level of the swept supply, its current in its I column
 *         REC  : I2..I5 after the power cycle
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

#ifndef LUPIDD_LOG_DIR
#define LUPIDD_LOG_DIR "/users/dc/ETdata/OLD/SHARED_DATA/"
#endif
#define LUPIDD_MAX_STEPS 400
#define LUPIDD_MAX_HOLD  400

using namespace std;

static string lupidd_num(double v) {
	ostringstream o;
	o << v;
	return o.str();
}

/* Supply (0..3 = P2..P5) with the largest |cur|/thr; powered_only skips
 * supplies forced to 0 V, need_over keeps only supplies above thr. */
static int lupidd_pick(const int used[], int nu, const REAL sv[], const REAL cur[],
		const REAL thr[], int powered_only, int need_over) {
	int best = -1;
	REAL best_r = 0.0;
	for (int u = 0; u < nu; u++) {
		const int s = used[u];
		if (powered_only && sv[s] == 0.0) continue;
		if (need_over && !(fabs(cur[s]) > thr[s])) continue;
		const REAL r = fabs(cur[s]) / thr[s];
		if (best < 0 || r > best_r) { best = s; best_r = r; }
	}
	return best;
}

static void lupidd_row(ofstream& f, const string& head, int num, const char* phase,
		const string& If, const string& v1, const string& vs,
		const int used[], int nu, const REAL cur[], int only, int latch) {
	string col[4];
	for (int u = 0; u < nu; u++) {
		const int s = used[u];
		if (only < 0 || only == s) col[s] = lupidd_num(cur[s]);
	}
	f << head << "," << num << "," << phase << "," << If << "," << v1 << "," << vs
	  << "," << col[0] << "," << col[1] << "," << col[2] << "," << col[3]
	  << "," << latch << endl;
}

void P9K_M_latchup_idd_sub(const vector<REAL>& I1start, const vector<REAL>& I1ratio, const vector<REAL>& I1end, const vector<REAL>& V2, const vector<REAL>& V3, const vector<REAL>& V4, const vector<REAL>& V5, const vector<REAL>& V1Comp, const vector<REAL>& I2Comp, const vector<REAL>& I3Comp, const vector<REAL>& I4Comp, const vector<REAL>& I5Comp, const vector<REAL>& Iabs, const vector<REAL>& Irel, const vector<REAL>& Tpulse, const vector<REAL>& Tdelay, const vector<REAL>& Vhstep, const vector<REAL>& Ihabs, const vector<STRINGP>& Integ, const vector<STRINGP>& P1, const vector<STRINGP>& P2, const vector<STRINGP>& P3, const vector<STRINGP>& P4, const vector<STRINGP>& P5,
        const vector<REAL>& Multi_OUTPUT1, const vector<STRINGP>& OutputName,
        vector<REAL>& STATUS, vector<REAL>& STEP_COUNT, vector<REAL>& I_NOM, vector<REAL>& LU_IT, vector<REAL>& LU_VT, vector<REAL>& LU_SUP, vector<REAL>& I_LATCH, vector<REAL>& LU_VH, vector<REAL>& LU_IH, vector<REAL>& I_RECOVER,
        const INTEGER _size)
{
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
	vector<REAL> tDelay(_size), tPulse(_size);

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
		// legacy 1E-4 s settle floor (P9K_M_latchup3)
		tDelay[__i] = (Tdelay[__i] < 1.0E-4) ? 1.0E-4 : Tdelay[__i];
		tPulse[__i] = (Tpulse[__i] < 1.0E-4) ? 1.0E-4 : Tpulse[__i];
	}

	STATUS.assign(_size, 0.0);
	STEP_COUNT.assign(_size, 0.0);
	I_NOM.assign(_size, 0.0);
	LU_IT.assign(_size, 0.0);
	LU_VT.assign(_size, 0.0);
	LU_SUP.assign(_size, 0.0);
	I_LATCH.assign(_size, 0.0);
	LU_VH.assign(_size, 0.0);
	LU_IH.assign(_size, 0.0);
	I_RECOVER.assign(_size, 0.0);

	// Multi_OUTPUT1=0 means no plot logging (same switch as the LUP log)
	const int do_log = (_size > 0 && Multi_OUTPUT1[0] != 0);
	string logpath = string(LUPIDD_LOG_DIR) + partid + "_" + lotid + "_LUPIDD.log";
	ofstream writeFile;
	if (do_log) {
		ifstream probe(logpath.c_str());
		const bool exists = probe.good();
		probe.close();
		writeFile.open(logpath.c_str(), ios::app);
		if (!exists) {
			writeFile << "EQPID,PCID,PARTID,LOTID,WFID,XAXIS,YAXIS,DCOP,MOD,ITEM,NUM,PHASE,If,V1,VS,I2,I3,I4,I5,LATCH" << endl;
		}
	}

	for (int i = 0; i < _size; i++) {
		STRINGP sp[4] = { P2[i], P3[i], P4[i], P5[i] };
		REAL sv[4] = { V2[i], V3[i], V4[i], V5[i] };
		REAL sc[4] = { I2Comp[i], I3Comp[i], I4Comp[i], I5Comp[i] };
		int used[4];
		int nu = 0, powered = 0;
		for (int s = 0; s < 4; s++) {
			if (sp[s] == NULL || sp[s][0] == '\0') continue;
			used[nu++] = s;
			if (sv[s] != 0.0) powered = 1;
		}

		if (I1start[i] == 0.0 || !(I1ratio[i] > 1.0) || !(Iabs[i] > 0.0)) {
			STATUS[i] = -4.0;
			continue;
		}
		if (!powered) {
			STATUS[i] = -3.0;
			continue;
		}

		const string head = string(eqpid) + "," + pcardid + "," + partid + "," + lotid + ","
				+ waferid.str() + "," + xaxis.str() + "," + yaxis.str() + "," + dcop + ","
				+ mod + "," + OutputName[i];

		// 1. power up, P1 at rest, nominal supply current
		for (int u = 0; u < nu; u++) connect_pin(PSMU, sp[used[u]]);
		connect_pin(PSMU, P1[i]);
		psmu_set_adc(P1[i], integTime[i], 1.0);
		for (int u = 0; u < nu; u++) psmu_set_adc(sp[used[u]], integTime[i], 1.0);
		for (int u = 0; u < nu; u++) {
			const int s = used[u];
			force_v(sp[s], sv[s], sv[s], sc[s]);
		}
		force_i(P1[i], 0.0, I1start[i], V1Comp[i]);
		wait_th(tDelay[i]);

		REAL inom[4] = { 0.0, 0.0, 0.0, 0.0 };
		REAL thr[4] = { 1.0, 1.0, 1.0, 1.0 };
		REAL ipost[4] = { 0.0, 0.0, 0.0, 0.0 };
		REAL irec[4] = { 0.0, 0.0, 0.0, 0.0 };
		int undetectable = 0;
		for (int u = 0; u < nu; u++) {
			const int s = used[u];
			double m = 0.0;
			measure_i(sp[s], &m, 0.0);
			inom[s] = m;
			const REAL a = fabs(inom[s]) + Iabs[i];
			const REAL r = Irel[i] * fabs(inom[s]);
			thr[s] = (a > r) ? a : r;
			if (thr[s] >= sc[s]) undetectable = 1;
		}
		if (do_log) lupidd_row(writeFile, head, 0, "NOM", "", "", "", used, nu, inom, -1, 0);
		if (undetectable) {
			STATUS[i] = -2.0;
			disable_port_all();
			disconnect_all();
			continue;
		}

		// 2. trigger -> remove -> judge by supply current
		REAL itrig = I1start[i];
		int latched = -1;
		for (int k = 0; k < LUPIDD_MAX_STEPS; k++) {
			if (k > 0) itrig *= I1ratio[i];
			force_i(P1[i], itrig, itrig, V1Comp[i]);
			wait_th(tPulse[i]);
			double vio = 0.0;
			measure_v(P1[i], &vio, 0.0);
			force_i(P1[i], 0.0, itrig, V1Comp[i]);
			wait_th(tDelay[i]);
			for (int u = 0; u < nu; u++) {
				const int s = used[u];
				double m = 0.0;
				measure_i(sp[s], &m, 0.0);
				ipost[s] = m;
			}
			STEP_COUNT[i] = (REAL)(k + 1);
			latched = lupidd_pick(used, nu, sv, ipost, thr, 0, 1);
			if (do_log) lupidd_row(writeFile, head, k + 1, "TRIG", lupidd_num(itrig),
					lupidd_num(vio), "", used, nu, ipost, -1, latched >= 0 ? 1 : 0);
			if (latched >= 0) {
				LU_IT[i] = itrig;
				LU_VT[i] = vio;
				break;
			}
			if (fabs(itrig) >= fabs(I1end[i])) break;
			if (fabs(vio) >= fabs(V1Comp[i])) break;
		}
		if (latched < 0) {
			STATUS[i] = 0.0;
			disable_port_all();
			disconnect_all();
			continue;
		}

		LU_SUP[i] = (REAL)(latched + 1);   // 1..4 = P2..P5 (DOE SUPPLY1..4)
		I_NOM[i] = inom[latched];
		I_LATCH[i] = ipost[latched];

		// 3. hold point: lower one powered supply until the latch releases
		const int hs = lupidd_pick(used, nu, sv, ipost, thr, 1, 0);
		LU_VH[i] = sv[hs];
		LU_IH[i] = ipost[hs];
		if (Vhstep[i] > 0.0) {
			const REAL v0 = sv[hs];
			const REAL dir = (v0 > 0.0) ? -1.0 : 1.0;
			for (int h = 1; h <= LUPIDD_MAX_HOLD; h++) {
				REAL vs = v0 + dir * (REAL)h * Vhstep[i];
				if ((v0 > 0.0 && vs < 0.0) || (v0 < 0.0 && vs > 0.0)) vs = 0.0;
				force_v(sp[hs], vs, v0, sc[hs]);
				wait_th(tDelay[i]);
				double ih = 0.0;
				measure_i(sp[hs], &ih, 0.0);
				const int held = (fabs(ih) - fabs(inom[hs])) > Ihabs[i];
				REAL cur[4] = { 0.0, 0.0, 0.0, 0.0 };
				cur[hs] = ih;
				if (do_log) lupidd_row(writeFile, head, h, "HOLD", "", "", lupidd_num(vs),
						used, nu, cur, hs, held);
				if (!held) break;
				LU_VH[i] = vs;
				LU_IH[i] = ih;
				if (vs == 0.0) break;
			}
		}

		// 4. power cycle, then check the device returned to nominal
		for (int u = 0; u < nu; u++) {
			const int s = used[u];
			force_v(sp[s], 0.0, sv[s], sc[s]);
		}
		wait_th(tDelay[i]);
		for (int u = 0; u < nu; u++) {
			const int s = used[u];
			force_v(sp[s], sv[s], sv[s], sc[s]);
		}
		wait_th(tDelay[i]);
		for (int u = 0; u < nu; u++) {
			const int s = used[u];
			double m = 0.0;
			measure_i(sp[s], &m, 0.0);
			irec[s] = m;
		}
		I_RECOVER[i] = irec[latched];
		const int stuck = lupidd_pick(used, nu, sv, irec, thr, 0, 1);
		STATUS[i] = (stuck >= 0) ? 2.0 : 1.0;
		if (do_log) lupidd_row(writeFile, head, 0, "REC", "", "", "", used, nu, irec, -1,
				stuck >= 0 ? 1 : 0);

		disable_port_all();
		disconnect_all();
	}

	if (do_log) writeFile.close();

	sync_th(0);
	stop_tis_log();
	return;
}
