/* stub AUF.h -- test only. TDE typedefs (same as cortex alg_common.h) and
 * AUF_getTag returning generic placeholder tag values. */
#ifndef STUB_AUF_H
#define STUB_AUF_H
#include <cstring>
#include <string>
typedef double REAL;
typedef int INTEGER;
typedef char STRING[256];
typedef char* STRINGP;
static inline int AUF_getTag(const char*, const char* var, STRING& v) {
    std::string s = std::string("T_") + var;
    std::strncpy(v, s.c_str(), 255);
    v[255] = '\0';
    return 0;
}
static inline int AUF_getTag(const char*, const char*, int& v) { v = 7; return 0; }
#endif
