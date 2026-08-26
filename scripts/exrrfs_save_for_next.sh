#!/usr/bin/env bash
# shellcheck disable=SC1091,SC2153,SC2154
declare -rx PS4='+${SECONDS}s $(basename ${BASH_SOURCE[0]:-${FUNCNAME[0]:-"Unknown"}})[${LINENO}]: '
set -x
cpreq=${cpreq:-cpreq}

cd "${DATA}" || exit 1
mpasout_interval=${MPASOUT_INTERVAL:-1}
fcst_hr=${FCST_HR:-1}
#
# WoFS windowed DA cycling: first guess is FCST_MIN minutes after the analysis
# time and the completion marker is DA_MARKER (fcst_da.done); otherwise the
# legacy hourly FCST_HR / fcst_fNNN.done convention is used.
#
wofs_da='false'
[[ -n "${EVENT_DATE:-}" ]] && wofs_da='true'
if [[ "${wofs_da}" == 'true' ]]; then
  cdate_ymd=${CDATE:0:8}
  cdate_hh=${CDATE:8:2}
  cdate_mm=${CDATE:10:2}; cdate_mm=${cdate_mm:-00}
  fcst_min=${FCST_MIN:-${DA_INTERVAL:-15}}
  timestr=$(date -d "${cdate_ymd} ${cdate_hh}:${cdate_mm} ${fcst_min} minutes" +%Y-%m-%d_%H.%M.%S)
else
  CDATEp=$( ${NDATE}  "${fcst_hr}"  "${CDATE}" )
  timestr=$(date -d "${CDATEp:0:8} ${CDATEp:8:2}" +%Y-%m-%d_%H.%M.%S)
fi
#
export CMDFILE="${DATA}/poescript_savefcst"
mkdir -p "$(dirname "${CMDFILE}")"
: > "${CMDFILE}"

# Populate the list for the ensemble members, or deterministic member
if (( "${ENS_SIZE:-0}" > 2 )); then
  mapfile -t mem_list < <(printf "/mem%03d\n" $(seq 1 "${ENS_SIZE}"))
else
  mem_list=("/") # if determinitic
fi

for memdir in "${mem_list[@]}"; do
  # Determine path
  if (( ${#memdir} > 1 )); then
    comoutdir=${COMOUT}/fcst/${WGF}${memdir}
    mpasout_file=${UMBRELLA_FCST_DATA}${memdir}/mpasout.${timestr}.nc
  else
    comoutdir=${COMOUT}/fcst/${WGF}
    mpasout_file=${UMBRELLA_FCST_DATA}/mpasout.${timestr}.nc
  fi

  mkdir -p "${comoutdir}"

#
# save to com
if [[ "${mpasout_interval,,}" != "none"  ]]; then
  mpasout_path=$(realpath "${mpasout_file}")
  echo "${cpreq} ${mpasout_path} ${comoutdir}/." >> "${CMDFILE}"
fi

done

#
# parallel run the serial tasks
#
${cpreq} "${EXECrrfs}"/rank_run.x .
${MPI_RUN_CMD} ./rank_run.x "${CMDFILE}"

# Check for errors
export err=$?
if (( err != 0 )) ; then
  echo "save_for_next failed with error code ${err} "
  err_exit
else
  if [[ "${wofs_da}" == 'true' ]]; then
    touch "${COMOUT}/fcst/${WGF}/${DA_MARKER:-fcst_da.done}"
  else
    touch "${COMOUT}/fcst/${WGF}/fcst_f$(printf "%03d" "${fcst_hr}").done"
  fi
fi

exit 0
