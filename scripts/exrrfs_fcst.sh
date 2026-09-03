#!/usr/bin/env bash
# shellcheck disable=SC1091,SC2153,SC2154,SC2034
declare -rx PS4='+${SECONDS}s $(basename ${BASH_SOURCE[0]:-${FUNCNAME[0]:-"Unknown"}})[${LINENO}]: '
set -x
cpreq=${cpreq:-cpreq}
prefix=${EXTRN_MDL_SOURCE%_NCO} # remove the trailing '_NCO' if any
cd "${DATA}" || exit 1
#
# WoFS windowed sub-hourly DA cycle: detect mode and decompose CDATE robustly
# (CDATE is 12-digit YYYYMMDDHHMM in WoFS mode, 10-digit otherwise).
#
wofs_da='false'
[[ -n "${EVENT_DATE:-}" ]] && wofs_da='true'
# A WoFS free forecast is a standard (hour-granular) forecast started from the
# DA analysis, not a sub-hourly DA cycle, so it uses the legacy hourly semantics
# even though EVENT_DATE is set.
do_free='false'
[[ "${DO_FREE_FCST^^}" == "TRUE" ]] && do_free='true'
[[ "${do_free}" == 'true' ]] && wofs_da='false'
cdate_ymd=${CDATE:0:8}
cdate_hh=${CDATE:8:2}
cdate_mm=${CDATE:10:2}; cdate_mm=${cdate_mm:-00}
da_fcst_seconds=${DA_FCST_SECONDS:-$(( ${DA_INTERVAL:-15} * 60 ))}
# forecast-offset -> MPAS timestamp; offset is minutes in WoFS DA mode, hours otherwise
fcst_timestr() {
  local off=$1
  if [[ "${wofs_da}" == 'true' ]]; then
    date -d "${cdate_ymd} ${cdate_hh}:${cdate_mm} ${off} minutes" +%Y-%m-%d_%H.%M.%S
  elif [[ "${do_free}" == 'true' ]]; then
    date -d "${cdate_ymd} ${cdate_hh}:${cdate_mm} ${off} minutes" +%Y-%m-%d_%H.%M.%S
  else
    local cp; cp=$( ${NDATE} "${off}" "${CDATE}" )
    date -d "${cp:0:8} ${cp:8:2}" +%Y-%m-%d_%H.%M.%S
  fi
}
#
dt=${FCST_DT:-60}
substeps=${FCST_SUBSTEPS:-2}
radt=${FCST_RADT:-30}
config_gfl_sub3d=${FCST_GFL_SUB3D:-0}
#
# find forecst length for this cycle
#
fcst_len_hrs_cycles=${FCST_LEN_HRS_CYCLES:-"01 01"}
fcst_len_hrs_thiscyc=$("${USHrrfs}/find_fcst_length.sh" "${fcst_len_hrs_cycles}" "${cyc}" )
# WoFS free forecast integrates a fixed FREE_FCST_LEN_HRS regardless of cycle
[[ "${do_free}" == 'true' ]] && fcst_len_hrs_thiscyc=$(( 10#${FREE_FCST_LEN_HRS:-6} ))
echo "forecast length for this cycle is ${fcst_len_hrs_thiscyc}"
#
# determine whether to begin new cycles
#
if [[ -r "${UMBRELLA_PREP_IC_DATA}/init.nc" ]]; then
  ln -snf "${UMBRELLA_PREP_IC_DATA}/init.nc" init.nc
  START_TYPE='cold'
  do_DAcycling='false'
else
  timestr=$(date -d "${cdate_ymd} ${cdate_hh}:${cdate_mm}" +%Y-%m-%d_%H.%M.%S)
  ln -snf "${UMBRELLA_PREP_IC_DATA}/mpasout.nc" "${UMBRELLA_FCST_DATA}/mpasout.${timestr}.nc"
  START_TYPE='warm'
  do_DAcycling='true'
fi

#
#  link bdy and fix files
#
ln -snf "${UMBRELLA_PREP_LBC_DATA}"/lbc*.nc .

ln -snf "${FIXrrfs}/physics/${PHYSICS_SUITE}"/* .
ln -snf "${MESHrrfs:-${FIXrrfs}/${MESH_NAME}}/${MESH_NAME}.ugwp_oro_data.nc" ./ugwp_oro_data.nc
zeta_levels=${EXPDIR}/config/ZETA_LEVELS.txt
nlevel=$(wc -l < "${zeta_levels}")
ln -snf "${MESHrrfs:-${FIXrrfs}/${MESH_NAME}}/${MESH_NAME}.invariant.nc_L${nlevel}_${prefix}" ./invariant.nc
mkdir -p graphinfo stream_list
ln -snf "${MESHrrfs:-${FIXrrfs}/${MESH_NAME}}"/graphinfo/* graphinfo/
${cpreq} "${FIXrrfs}/stream_list/${PHYSICS_SUITE}"/* stream_list/

# generate the namelist on the fly
# do_restart already defined in the above
start_time=$(date -d "${cdate_ymd} ${cdate_hh}:${cdate_mm}" +%Y-%m-%d_%H:%M:%S)
if [[ "${wofs_da}" == 'true' ]]; then
  # DA cycle: fixed short forecast of DA_FCST_SECONDS (defaults to DA_INTERVAL)
  run_duration=$(printf '%02d:%02d:%02d' $((da_fcst_seconds/3600)) $(((da_fcst_seconds%3600)/60)) $((da_fcst_seconds%60)))
else
  run_duration=${fcst_len_hrs_thiscyc:-1}:00:00
fi
physics_suite=${PHYSICS_SUITE:-'mesoscale_reference'}
lsm_scheme=${LSM_SCHEME:-'sf_ruc'}
nsoillevels=${NSOIL_LEVELS:-9}
jedi_da=true #true

pio_num_iotasks=${NODES}
pio_stride=${PPN}
file_content=$(< "${PARMrrfs}/${physics_suite}/namelist.atmosphere") # read in all content
eval "echo \"${file_content}\"" > namelist.atmosphere

if [[ "${FCST_CONVECTION_SCHEME^^}" == "TRUE" ]]; then
  sed -i -e "s/    config_physics_suite = 'hrrrv5'/\
    config_physics_suite = 'hrrrv5'\n\
    config_convection_scheme = 'cu_ntiedtke'\n\
    config_gfl_sub3d = 1/" namelist.atmosphere
fi

# generate the streams file on the fly using sed as this file contains "filename_template='lbc.$Y-$M-$D_$h.$m.$s.nc'"
lbc_interval=${LBC_INTERVAL:-3}
restart_interval=${RESTART_INTERVAL:-none}
history_interval=${HISTORY_INTERVAL:-1}
diag_interval=${DIAG_INTERVAL:-${HISTORY_INTERVAL:-1}}
mpasout_interval=${MPASOUT_INTERVAL:-1}
if [[ "${wofs_da}" == 'true' ]]; then
  # WoFS DA cycles: integer output intervals are in MINUTES; by default only
  # the first-guess mpasout (at the DA forecast length) is written and neither
  # history nor diag output is produced.
  history_interval=${HISTORY_INTERVAL_MIN:-none}
  diag_interval=${DIAG_INTERVAL_MIN:-none}
  mpasout_interval=${MPASOUT_INTERVAL_MIN:-$((da_fcst_seconds/60))}
  MPASOUT_TIMELEVELS=""
  min2hms() { printf '%02d:%02d:%02d' $(( 10#$1/60 )) $(( 10#$1%60 )) 0; }
  [[ ${restart_interval} =~ ^[0-9]+$ ]] && restart_interval="$(min2hms "${restart_interval}")"
  [[ ${history_interval} =~ ^[0-9]+$ ]] && history_interval="$(min2hms "${history_interval}")"
  [[ ${diag_interval}    =~ ^[0-9]+$ ]] && diag_interval="$(min2hms "${diag_interval}")"
  [[ ${mpasout_interval} =~ ^[0-9]+$ ]] && mpasout_interval="$(min2hms "${mpasout_interval}")"
elif [[ "${do_free}" == 'true' ]]; then
  # WoFS free forecast: history/diag/mpasout are all written every
  # FREE_OUTPUT_INTERVAL_MIN minutes so MPASSIT can post at that cadence.
  free_out_min=${FREE_OUTPUT_INTERVAL_MIN:-5}
  history_interval=${free_out_min}
  diag_interval=${free_out_min}
  mpasout_interval="7200"
  MPASOUT_TIMELEVELS=""
  min2hms() { printf '%02d:%02d:%02d' $(( 10#$1/60 )) $(( 10#$1%60 )) 0; }
  [[ ${restart_interval} =~ ^[0-9]+$ ]] && restart_interval="$(min2hms "${restart_interval}")"
  [[ ${history_interval} =~ ^[0-9]+$ ]] && history_interval="$(min2hms "${history_interval}")"
  [[ ${diag_interval}    =~ ^[0-9]+$ ]] && diag_interval="$(min2hms "${diag_interval}")"
  [[ ${mpasout_interval} =~ ^[0-9]+$ ]] && mpasout_interval="$(min2hms "${mpasout_interval}")"
else
  [[ ${restart_interval} =~ ^[0-9]+$ ]] && restart_interval="${restart_interval}:00:00"
  [[ ${history_interval} =~ ^[0-9]+$ ]] && history_interval="${history_interval}:00:00"
  [[ ${diag_interval} =~ ^[0-9]+$ ]] && diag_interval="${diag_interval}:00:00"
  [[ ${mpasout_interval} =~ ^[0-9]+$ ]] && mpasout_interval="${mpasout_interval}:00:00"
fi
if [[ "${MPASOUT_TIMELEVELS}" != "" ]]; then # prioritize MPASOUT_TIMELEVELS
  mpasout_replacement="s|output_interval=\"@mpasout_interval@\"|output_timelevels=\"${MPASOUT_TIMELEVELS}\"|"
else
  mpasout_replacement="s/@mpasout_interval@/${mpasout_interval}/"
fi
sed -e "s/@restart_interval@/${restart_interval}/" -e "s/@history_interval@/${history_interval}/" \
    -e "s/@diag_interval@/${diag_interval}/" -e "s/@lbc_interval@/${lbc_interval}/" \
    -e "${mpasout_replacement}"  "${PARMrrfs}"/streams.atmosphere  > streams.atmosphere
#
if [[ "${mpasout_interval,,}" == "none" ]]; then  # remove the da_state stream for coldstart only forecasts
  sed -i '/<stream name="da_state"/,/<\/stream>/d' streams.atmosphere
fi
#
# WoFS DA cycle: the lateral-boundary stream reads the interpolated boundary at
# the cycle valid time and the next whole external boundary hour.  Set the LBC
# input_interval to that per-cycle gap so MPAS interpolates between the two.
if [[ "${wofs_da}" == 'true' ]]; then
  extinvl_sec=$(( ${EXTINVL_HRS:-1} * 3600 ))
  isec=$(date -u -d "${cdate_ymd} ${cdate_hh}:${cdate_mm}" +%s)
  isec_nlbc1=$(( isec - isec % extinvl_sec ))
  isec_nlbc2=$(( isec_nlbc1 + extinvl_sec ))
  isec_elbc=$(( isec + da_fcst_seconds ))
  while (( isec_elbc > isec_nlbc2 )); do
    (( isec_nlbc2 += extinvl_sec ))
  done
  lbc_gap=$(( isec_nlbc2 - isec ))
  lbc_gap_str=$(printf '%02d:%02d:%02d' $((lbc_gap/3600)) $(((lbc_gap%3600)/60)) $((lbc_gap%60)))
  sed -i -e '/name="lbc_in"/,/\/>/ s#input_interval="[^"]*"#input_interval="'"${lbc_gap_str}"'"#' streams.atmosphere
fi
#
# chemistry related processing
if [[ "${DO_CHEMISTRY^^}" == "TRUE" ]]; then
  source "${USHrrfs}"/chem_fcst.sh
fi
#
# forecast length as a plain number: minutes in WoFS DA/free mode, hours otherwise
if [[ "${wofs_da}" == 'true' ]]; then
  fcst_len_num=$(( da_fcst_seconds / 60 ))
elif [[ "${do_free}" == 'true' ]]; then
  fcst_len_num=$(( 10#${fcst_len_hrs_thiscyc} * 60 ))
else
  fcst_len_num=$(( 10#${fcst_len_hrs_thiscyc} ))
fi
#
# prelink the history/diag files to umbrella
if [[ "${history_interval,,}" != "none" ]]; then
  if [[ "${wofs_da}" == 'true' ]]; then hist_step_num=${HISTORY_INTERVAL_MIN:-0}; elif [[ "${do_free}" == 'true' ]]; then hist_step_num=${free_out_min:-0}; else hist_step_num=$(( 10#${history_interval%%:*} )); fi
  if (( hist_step_num > 0 )); then
    history_all=$(seq 0 "${hist_step_num}" "${fcst_len_num}" )
    for fhr in ${history_all}; do
      timestr=$(fcst_timestr "${fhr}")
      if [[ "${DO_SPINUP:-FALSE}" != "TRUE" ]];  then
        ln -snf "${UMBRELLA_FCST_DATA}/history.${timestr}.nc" "${DATA}/"
        ln -snf "${UMBRELLA_FCST_DATA}/history.${timestr}.nc.done" "${DATA}/"
      fi
    done
  fi
fi
if [[ "${diag_interval,,}" != "none" ]]; then
  if [[ "${wofs_da}" == 'true' ]]; then diag_step_num=${DIAG_INTERVAL_MIN:-0}; elif [[ "${do_free}" == 'true' ]]; then diag_step_num=${free_out_min:-0}; else diag_step_num=$(( 10#${diag_interval%%:*} )); fi
  if (( diag_step_num > 0 )); then
    diag_all=$(seq 0 "${diag_step_num}" "${fcst_len_num}" )
    for fhr in ${diag_all}; do
      timestr=$(fcst_timestr "${fhr}")
      if [[ "${DO_SPINUP:-FALSE}" != "TRUE" ]];  then
        ln -snf "${UMBRELLA_FCST_DATA}/diag.${timestr}.nc" "${DATA}/"
        ln -snf "${UMBRELLA_FCST_DATA}/diag.${timestr}.nc.done" "${DATA}/"
      fi
    done
  fi
fi
# prelink the mpasout files to umbrella
if [[ "${MPASOUT_TIMELEVELS}" != "" ]]; then # prioritize MPASOUT_TIMELEVELS
  read -ra mpasout_all <<< "${MPASOUT_TIMELEVELS}"
elif [[ "${mpasout_interval,,}" != "none" ]]; then
  if [[ "${wofs_da}" == 'true' ]]; then mpasout_step_num=${MPASOUT_INTERVAL_MIN:-$(( da_fcst_seconds / 60 ))}; elif [[ "${do_free}" == 'true' ]]; then mpasout_step_num=${free_out_min:-0}; else mpasout_step_num=$(( 10#${mpasout_interval%%:*} )); fi
  if (( mpasout_step_num > 0 )); then
    read -ra mpasout_all <<< "$(seq 0 "${mpasout_step_num}" "${fcst_len_num}" | paste -sd ' ')"
  fi
fi
# shellcheck disable=SC2068
for fhr in ${mpasout_all[@]}; do
  timestr=$(fcst_timestr "${fhr}")
  ln -snf "${UMBRELLA_FCST_DATA}/mpasout.${timestr}.nc" "${DATA}/"
  ln -snf "${UMBRELLA_FCST_DATA}/mpasout.${timestr}.nc.done" "${DATA}/"
done

# run the MPAS model
source prep_step
${cpreq} "${EXECrrfs}"/atmosphere_model.x .
${MPI_RUN_CMD} ./atmosphere_model.x
export err=$?
err_chk
#
# saving log.atmosphere.0000.out
#
[[ -s ./log.atmosphere.0000.out ]] && cat ./log.atmosphere.0000.out
#
# double check status as sometimes atmosphere_model.x exit with 0 but there are still errors (log.atmosphere*err)
#
num_err_log=$(find ./log.atmosphere*.err 2>/dev/null | wc -l)
if (( "${num_err_log}" > 0 )) ; then
  echo "FATAL ERROR: MPAS model run failed"
  # saving err log info from the first err log file
  for f in ./log.atmosphere*.err; do [[ -s "${f}" ]] && echo "--- Saving err info from ${f} ---" && cat "${f}" && break; done
  err_exit
else
  # spinup cycles copy f001 mpasout to com/ directly, don't need the save_for_next task
  if [[ "${DO_SPINUP:-FALSE}" == "TRUE" ]];  then
    CDATEp=$( ${NDATE} 1 "${CDATE}" )
    timestr=$(date -d "${CDATEp:0:8} ${CDATEp:8:2}" +%Y-%m-%d_%H.%M.%S)
    ${cpreq} "${UMBRELLA_FCST_DATA}/mpasout.${timestr}.nc" "${COMOUT}/fcst_spinup/${WGF}${MEMDIR}"
    cp "${DATA}/log.atmosphere.0000.out" "${COMOUT}/fcst_spinup/${WGF}${MEMDIR}"
    cp "${DATA}/namelist.atmosphere" "${COMOUT}/fcst_spinup/${WGF}${MEMDIR}"
    cp "${DATA}/streams.atmosphere" "${COMOUT}/fcst_spinup/${WGF}${MEMDIR}"

  else # prod cycles, cycling mpasout is copied by the save_for_next task so that next cycle can start much earlier; other mpasout files can be copied when fcst completes
    com_fcst_sub="fcst"
    [[ "${do_free}" == 'true' ]] && com_fcst_sub="fcst_free"
    ${cpreq} "${DATA}/log.atmosphere.0000.out" "${COMOUT}/${com_fcst_sub}/${WGF}${MEMDIR}"
    cp "${DATA}/namelist.atmosphere" "${COMOUT}/${com_fcst_sub}/${WGF}${MEMDIR}"
    cp "${DATA}/streams.atmosphere" "${COMOUT}/${com_fcst_sub}/${WGF}${MEMDIR}"
    if [[ "${do_free}" != 'true' ]] && [[ "${mpasout_interval,,}" != "none"  ]] && [[ -n "${MPASOUT_SAVE2COM_HRS}" ]]; then  # copy mpasout based on the $MPASOUT_SAVE2COM_HRS setting
      read -ra array <<< "${MPASOUT_SAVE2COM_HRS}"
      # shellcheck disable=SC2068
      for fhr in ${array[@]}; do
        timestr=$(fcst_timestr "${fhr}")
        mpasout_file=${UMBRELLA_FCST_DATA}/mpasout.${timestr}.nc
        if [[ -s ${mpasout_file} ]]; then
          ${cpreq} "${mpasout_file}" "${COMOUT}/${com_fcst_sub}/${WGF}${MEMDIR}"
        else
          echo "WARNING: mpasout_file not found - ${mpasout_file}"
        fi
      done
    fi
  fi
  exit 0
fi
