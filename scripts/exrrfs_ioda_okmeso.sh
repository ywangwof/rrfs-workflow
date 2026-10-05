#!/usr/bin/env bash
# shellcheck disable=SC1091,SC2154,SC2086,SC2068
declare -rx PS4='+${SECONDS}s $(basename ${BASH_SOURCE[0]:-${FUNCNAME[0]:-"Unknown"}})[${LINENO}]: '
set -x
cpreq=${cpreq:-cpreq}

cd "${DATA}" || exit 1
#
#-----------------------------------------------------------------------
#
# Locate the raw OK Mesonet (OKM) observation file for this analysis time.
#
# In WoFS windowed mode the analysis time is CDATE (YYYYmmddHHMM) and the raw
# Mesonet MDF files live at
#   ${OKMESO_DIR}/YYYY/MM/DD/mesonet.realtime.YYYYmmddHHMM.mdf
# Look back up to OKMESO_LOOKBACK_MIN minutes to find the most recent available
# file at or before the analysis time.
#
#-----------------------------------------------------------------------
#
anlys_eventtime=${CDATE}
lookback=${OKMESO_LOOKBACK_MIN:-4}

okmfile=""
okmtime=""
for (( j=0; j<=lookback; j++ )); do
  curr_datetime=$(date -u -d "${CDATE:0:8} ${CDATE:8:2}:${CDATE:10:2} UTC - ${j} minutes" +%Y%m%d%H%M)
  curr_yyyy=${curr_datetime:0:4}
  curr_mm=${curr_datetime:4:2}
  curr_dd=${curr_datetime:6:2}
  candidate="${OKMESO_DIR}/${curr_yyyy}/${curr_mm}/${curr_dd}/mesonet.realtime.${curr_datetime}.mdf"
  echo "Looking for OK Mesonet data valid ${curr_datetime} as ${candidate}"
  if [[ -s "${candidate}" ]]; then
    okmfile="${candidate}"
    okmtime="${curr_datetime}"
    echo "Using OK Mesonet file ${okmfile}"
    break
  fi
done

if [[ -z "${okmfile}" ]]; then
  echo "WARNING: No OK Mesonet file found under ${OKMESO_DIR} within ${lookback} minutes of ${anlys_eventtime}; skipping OK Mesonet ioda generation."
  exit 0
fi
#
#-----------------------------------------------------------------------
#
# Run the ioda converter to generate the OK Mesonet ioda file.
#
#-----------------------------------------------------------------------
#
# pyioda libraries
PYIODALIB=$(echo "${HOMErrfs}"/sorc/RDASApp/build/lib/python3.*)
export PYTHONPATH=${PYIODALIB}:${PYTHONPATH}

geoinfo="${FIXrrfs}/okmeso/geoinfo.csv"
outfile="ioda_okmeso_obs.nc"

"${HOMErrfs}"/ush/mesonet2ioda.py "${okmtime}" \
  -i "${okmfile}" \
  -g "${geoinfo}" \
  -o "${outfile}"
export err=$?
err_chk
#
# Keep only stations inside the MPAS domain; stations outside the mesh get
# missing GeoVaLs, which makes the SfcCorrected H(x) missing and aborts getkf.
#
if [[ -s "${outfile}" ]]; then
  grid_file="${MESHrrfs:-${FIXrrfs}/${MESH_NAME}}/${MESH_NAME}.static.nc"
  if [[ -s "${grid_file}" ]]; then
    ${cpreq} "${USHrrfs}"/offline_domain_check.py .
    ./offline_domain_check.py -o "${outfile}" -g "${grid_file}" -s 0.005
    export err=$?
    err_chk
    mv "${outfile%.nc}_dc.nc" "${outfile}"
  else
    echo "WARNING: mesh file ${grid_file} not found; skipping the OK Mesonet domain check."
  fi
fi
#
#-----------------------------------------------------------------------
#
# Copy the generated OK Mesonet ioda file to COMOUT.
#
#-----------------------------------------------------------------------
#
if [[ -s "${outfile}" ]]; then
  ${cpreq} "${outfile}" "${COMOUT}/ioda_okmeso/${WGF}/${outfile}"
  echo "ioda_okmeso generated ${outfile}."
else
  echo "WARNING: mesonet2ioda.py produced no OK Mesonet ioda file for ${anlys_eventtime}."
fi
