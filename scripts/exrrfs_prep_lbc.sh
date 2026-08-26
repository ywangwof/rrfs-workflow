#!/usr/bin/env bash
# shellcheck disable=SC1091,SC2153,SC2154
declare -rx PS4='+${SECONDS}s $(basename ${BASH_SOURCE[0]:-${FUNCNAME[0]:-"Unknown"}})[${LINENO}]: '
set -x
cpreq="ln -snf"
cpreq=${cpreq:-cpreq}
#
# WoFS windowed DA cycle: sub-hourly LBC boundaries are time-interpolated from
# the bracketing hourly external-model LBC files (see ush/intrp_time.py).  When
# EVENT_DATE is unset this whole branch is skipped and the legacy hour-granular
# staging below runs unchanged.
#
wofs_da='false'
[[ -n "${EVENT_DATE:-}" ]] && wofs_da='true'
# The free-forecast staging mode (PREP_LBC_MODE=free) reuses the whole-hour
# external boundaries directly and takes precedence over the DA sub-hourly
# interpolation branch even though EVENT_DATE is also set for free forecasts.
[[ "${PREP_LBC_MODE:-da}" == 'free' ]] && wofs_da='false'
# WoFS: the shared lbc/ dir holds only LBC_ENS_SIZE external members; this
# forecast/free member sources its boundaries from mapped member LBC_MEM.
# Legacy (LBC_MEM unset) falls back to MEMDIR, keeping behavior unchanged.
lbc_memsub=${MEMDIR}
[[ -n "${LBC_MEM:-}" ]] && lbc_memsub="/mem${LBC_MEM}"
cdate_ymd=${CDATE:0:8}
cdate_hh=${CDATE:8:2}
cdate_mm=${CDATE:10:2}; cdate_mm=${cdate_mm:-00}

if [[ "${PREP_LBC_MODE:-da}" == 'free' ]]; then
  # WoFS free forecast: stage whole-hour boundaries lbc.<time>.nc for
  # fhr = 0, LBC_INTERVAL, ... FREE_FCST_LEN_HRS from the source lbc/ cycle.
  lbc_interval=$(( 10#${LBC_INTERVAL:-3} ))
  free_len=$(( 10#${FREE_FCST_LEN_HRS:-6} ))
  lbc_hrs=$(( 10#${PREP_LBC_LOOK_BACK_HRS:-6} ))
  cdate10=${CDATE:0:10}

  CDATElbcend=$(${NDATE} "${free_len}" "${cdate10}")
  end_time=$(date -u -d "${CDATElbcend:0:8} ${CDATElbcend:8:2}" +%Y-%m-%d_%H.%M.%S)
  last_bdyfile="lbc.${end_time}.nc"

  srcdir=""
  n=0
  while (( n <= lbc_hrs )); do
    CDATElbc=$(${NDATE} -$((10#${n})) "${cdate10}")
    YYYYMMDDlbc=${CDATElbc:0:8}
    HHlbc=${CDATElbc:8:2}
    trydir=${COMINrrfs}/${RUN}.${YYYYMMDDlbc}/${HHlbc}/lbc/${WGF}${lbc_memsub}
    if [[ -s "${trydir}/${last_bdyfile}" ]]; then
      srcdir=${trydir}
      echo "Found LBC source cycle ${YYYYMMDDlbc}${HHlbc}: ${srcdir}"
      break
    fi
    n=$((n + 1))
  done

  # WoFS: LBCs live in a single per-event lbc/ dir (minute-aware @H@M token).
  if [[ -z "${srcdir}" && -n "${LBC_SRC_YMD:-}" ]]; then
    trydir=${COMINrrfs}/${RUN}.${LBC_SRC_YMD}/${LBC_SRC_HHMM}/lbc/${WGF}${lbc_memsub}
    [[ -s "${trydir}/${last_bdyfile}" ]] && srcdir=${trydir}
    echo "Using fixed LBC source dir ${trydir}"
  fi

  if [[ -z "${srcdir}" ]]; then
    echo "Cannot find free-forecast boundary file: ${last_bdyfile}"
    err_exit
  fi

  mkdir -p "${UMBRELLA_PREP_LBC_DATA}"
  for fhr in $(seq 0 "${lbc_interval}" "${free_len}"); do
    CDATElbc=$(${NDATE} "${fhr}" "${cdate10}")
    string_time=$(date -u -d "${CDATElbc:0:8} ${CDATElbc:8:2}" +%Y-%m-%d_%H.%M.%S)
    out="${UMBRELLA_PREP_LBC_DATA}/lbc.${string_time}.nc"
    [[ -e "${out}" ]] && rm -rf "${out}"
    ${cpreq} "${srcdir}/lbc.${string_time}.nc" "${out}"
  done

  exit 0
fi

if [[ "${wofs_da}" == 'true' ]]; then
  extinvl_sec=$(( ${EXTINVL_HRS:-1} * 3600 ))
  da_fcst_seconds=${DA_FCST_SECONDS:-$(( ${DA_INTERVAL:-15} * 60 ))}

  # cycle valid time and the bracketing whole-hour external boundary times
  isec=$(date -u -d "${cdate_ymd} ${cdate_hh}:${cdate_mm}" +%s)
  isec_nlbc1=$(( isec - isec % extinvl_sec ))          # whole hour at/before cycle
  isec_nlbc2=$(( isec_nlbc1 + extinvl_sec ))           # next whole hour
  isec_elbc=$(( isec + da_fcst_seconds ))              # end of the DA forecast
  while (( isec_elbc > isec_nlbc2 )); do
    (( isec_nlbc2 += extinvl_sec ))
  done
  isec_elbc=${isec_nlbc2}                              # 2nd MPAS boundary time

  mpastime1=$(date -u -d "@${isec}"       +%Y-%m-%d_%H.%M.%S)  # = cycle time
  mpastime2=$(date -u -d "@${isec_elbc}"  +%Y-%m-%d_%H.%M.%S)  # next whole hour
  lbctime1=$(date  -u -d "@${isec_nlbc1}" +%Y-%m-%d_%H.%M.%S)  # hourly src before
  lbctime2=$(date  -u -d "@${isec_nlbc2}" +%Y-%m-%d_%H.%M.%S)  # hourly src after

  # locate a source cycle whose lbc/ directory holds the bracketing hourly files
  lbc_hrs=$(( 10#${PREP_LBC_LOOK_BACK_HRS:-6} ))
  cdate10=${CDATE:0:10}
  srcdir=""
  n=0
  while (( n <= lbc_hrs )); do
    CDATElbc=$(${NDATE} -$((10#${n})) "${cdate10}")
    YYYYMMDDlbc=${CDATElbc:0:8}
    HHlbc=${CDATElbc:8:2}
    trydir=${COMINrrfs}/${RUN}.${YYYYMMDDlbc}/${HHlbc}/lbc/${WGF}${lbc_memsub}
    if [[ -s "${trydir}/lbc.${lbctime2}.nc" ]]; then
      srcdir=${trydir}
      echo "Found LBC source cycle ${YYYYMMDDlbc}${HHlbc}: ${srcdir}"
      break
    fi
    n=$((n + 1))
  done

  # WoFS: LBCs live in a single per-event lbc/ dir (minute-aware @H@M token).
  if [[ -z "${srcdir}" && -n "${LBC_SRC_YMD:-}" ]]; then
    trydir=${COMINrrfs}/${RUN}.${LBC_SRC_YMD}/${LBC_SRC_HHMM}/lbc/${WGF}${lbc_memsub}
    [[ -s "${trydir}/lbc.${lbctime2}.nc" ]] && srcdir=${trydir}
    echo "Using fixed LBC source dir ${trydir}"
  fi

  if [[ -z "${srcdir}" ]]; then
    echo "Cannot find hourly LBC source containing lbc.${lbctime2}.nc"
    err_exit
  fi

  mkdir -p "${UMBRELLA_PREP_LBC_DATA}"

  # --- boundary 1 at the cycle valid time (mpastime1) ---
  out1="${UMBRELLA_PREP_LBC_DATA}/lbc.${mpastime1}.nc"
  [[ -e "${out1}" ]] && rm -rf "${out1}"
  if [[ -s "${srcdir}/lbc.${mpastime1}.nc" ]]; then
    echo "Using hourly lbc.${mpastime1}.nc directly"
    ${cpreq} "${srcdir}/lbc.${mpastime1}.nc" "${out1}"
  else
    echo "Interpolating lbc.${mpastime1}.nc from lbc.${lbctime1}.nc and lbc.${lbctime2}.nc"
    "${USHrrfs}/intrp_time.py" -t "${mpastime1}" \
        "${srcdir}/lbc.${lbctime1}.nc" "${srcdir}/lbc.${lbctime2}.nc" "${out1}"
  fi

  # --- boundary 2 at the next whole external boundary hour (mpastime2) ---
  out2="${UMBRELLA_PREP_LBC_DATA}/lbc.${mpastime2}.nc"
  [[ -e "${out2}" ]] && rm -rf "${out2}"
  if [[ -s "${srcdir}/lbc.${mpastime2}.nc" ]]; then
    echo "Using hourly lbc.${mpastime2}.nc directly"
    ${cpreq} "${srcdir}/lbc.${mpastime2}.nc" "${out2}"
  else
    echo "Interpolating lbc.${mpastime2}.nc from lbc.${lbctime1}.nc and lbc.${lbctime2}.nc"
    "${USHrrfs}/intrp_time.py" -t "${mpastime2}" \
        "${srcdir}/lbc.${lbctime1}.nc" "${srcdir}/lbc.${lbctime2}.nc" "${out2}"
  fi

  exit 0
fi
#
# timestr=$(date -d "${CDATE:0:8} ${CDATE:8:2}" +%Y-%m-%d_%H.%M.%S) 
lbc_interval=${LBC_INTERVAL:-3}
#
# find forecst length for this cycle
#
fcst_len_hrs_cycles=${FCST_LEN_HRS_CYCLES:-"01 01"}
fcst_len_hrs_thiscyc=$( "${USHrrfs}/find_fcst_length.sh"  "${fcst_len_hrs_cycles}" "${cyc}" )
echo "forecast length for this cycle is ${fcst_len_hrs_thiscyc}"
lbc_hrs=$(( 10#${PREP_LBC_LOOK_BACK_HRS} ))
#
# find cycle that has boundary files
#
CDATElbcend=$( ${NDATE} $((10#${fcst_len_hrs_thiscyc})) "${CDATE}")
string_time=$(date -d "${CDATElbcend:0:8} ${CDATElbcend:8:2}" +%Y-%m-%d_%H.%M.%S)
last_bdyfile="lbc.${string_time}.nc"
n=0
while (( n <= lbc_hrs )); do
  CDATElbc=$(${NDATE} -$((10#${n})) "${CDATE}")
  YYYYMMDDlbc=${CDATElbc:0:8}
  HHlbc=${CDATElbc:8:2}
  checkfile=${COMINrrfs}/${RUN}.${YYYYMMDDlbc}/${HHlbc}/lbc/${WGF}${lbc_memsub}/${last_bdyfile}
  if [[ -s "${checkfile}" ]]; then
     echo "Found ${checkfile}; Use it as boundary for forecast "
     break
  else
     n=$((n + 1))
  fi
done

#
# find bdry sequence and copy them to umbrella space
#

fhr_all=$(seq 0 $((10#${lbc_interval})) $((10#${fcst_len_hrs_thiscyc} )) )

if [[ -s "${checkfile}" ]]; then
  for fhr in  ${fhr_all}; do
    CDATElbc=$(${NDATE} "${fhr}" "${CDATE}")
    string_time=$(date -d "${CDATElbc:0:8} ${CDATElbc:8:2}" +%Y-%m-%d_%H.%M.%S)
    ${cpreq} "${COMINrrfs}/${RUN}.${YYYYMMDDlbc}/${HHlbc}/lbc/${WGF}${lbc_memsub}/lbc.${string_time}.nc"  "${UMBRELLA_PREP_LBC_DATA}/."
  done
else
  echo "Cannot find boundary file: ${checkfile}"
  err_exit
fi

