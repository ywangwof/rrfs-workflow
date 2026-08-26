#!/usr/bin/env bash
# shellcheck disable=SC1091,SC2154,SC2086,SC2068
declare -rx PS4='+${SECONDS}s $(basename ${BASH_SOURCE[0]:-${FUNCNAME[0]:-"Unknown"}})[${LINENO}]: '
set -x
cpreq=${cpreq:-cpreq}

cd "${DATA}" || exit 1
#
#-----------------------------------------------------------------------
#
# Locate the raw GOES CWP observation file for this analysis time.
#
# In WoFS windowed mode the analysis time is CDATE (YYYYmmddHHMM) and the raw
# CWP files live at
#   ${OBS_CWP_DIR}/YYYYmmdd/YYYYmmddHHMM_GOES19_CWP_OBS.nc
# Following run_ioda_cwp, look back up to CWP_LOOKBACK_MIN minutes to find the
# most recent available file at or before the analysis time.
#
#-----------------------------------------------------------------------
#
anlys_eventtime=${CDATE}
lookback=${CWP_LOOKBACK_MIN:-4}

cwpfile=""
for (( j=0; j<=lookback; j++ )); do
  curr_date=$(date -u -d "${CDATE:0:8} ${CDATE:8:2}:${CDATE:10:2} UTC - ${j} minutes" +%Y%m%d)
  curr_datetime=$(date -u -d "${CDATE:0:8} ${CDATE:8:2}:${CDATE:10:2} UTC - ${j} minutes" +%Y%m%d%H%M)
  candidate="${OBS_CWP_DIR}/${curr_date}/${curr_datetime}_GOES19_CWP_OBS.nc"
  echo "Looking for CWP data valid ${curr_datetime} as ${candidate}"
  if [[ -s "${candidate}" ]]; then
    cwpfile="${candidate}"
    echo "Using CWP file ${cwpfile}"
    break
  fi
done

if [[ -z "${cwpfile}" ]]; then
  echo "WARNING: No CWP file found under ${OBS_CWP_DIR} within ${lookback} minutes of ${anlys_eventtime}; skipping CWP ioda generation."
  exit 0
fi
#
#-----------------------------------------------------------------------
#
# Run the ioda converter to generate CWP ioda files.
#
# GOESCWP2ioda.py writes one file per variable phase in the current directory:
#   ioda_cwp_obs.nc  ioda_lwp_obs.nc  ioda_iwp_obs.nc
#   ioda_cwp_night_obs.nc  ioda_lwp_night_obs.nc  ioda_iwp_night_obs.nc
#
#-----------------------------------------------------------------------
#
# pyioda libraries
PYIODALIB=$(echo "${HOMErrfs}"/sorc/RDASApp/build/lib/python3.*)
export PYTHONPATH=${PYIODALIB}:${PYTHONPATH}

"${HOMErrfs}"/ush/GOESCWP2ioda.py -d "${anlys_eventtime}" "${cwpfile}"
export err=$?
err_chk
#
#-----------------------------------------------------------------------
#
# Copy any generated CWP ioda files to COMOUT.
#
#-----------------------------------------------------------------------
#
ncopied=0
for cwpobs in cwp lwp iwp cwp_night lwp_night iwp_night; do
  fname="ioda_${cwpobs}_obs.nc"
  if [[ -s "${fname}" ]]; then
    ${cpreq} "${fname}" "${COMOUT}/ioda_cwp/${WGF}/${fname}"
    ((ncopied+=1))
  fi
done

if (( ncopied == 0 )); then
  echo "WARNING: GOESCWP2ioda.py produced no CWP ioda files for ${anlys_eventtime}."
fi

echo "ioda_cwp generated ${ncopied} CWP ioda file(s)."
