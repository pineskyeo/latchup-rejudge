/* Include-guarded wrapper: the POR and DOE sources are compiled in one test
 * unit, and the cortex stub tis.h is only partly guarded. */
#ifndef LUPIDD_TEST_TIS_WRAPPER_H
#define LUPIDD_TEST_TIS_WRAPPER_H
#include CORTEX_STUB_TIS
#endif
