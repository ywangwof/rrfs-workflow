#!/usr/bin/env bash
# shellcheck disable=SC2153,SC1091,SC2154
declare -rx PS4='+${SECONDS}s $(basename ${BASH_SOURCE[0]:-${FUNCNAME[0]:-"Unknown"}})[${LINENO}]: '
set -x

cpreq=${cpreq:-cpreq}
prefix=${EXTRN_MDL_SOURCE%_NCO} # remove the trailing '_NCO' if any
cd "${DATA}"  || exit 1
#
#  link the executable (atomic install: symlink avoids ETXTBSY "Text file
#  busy" when many mpassit member tasks stage the shared exe concurrently)
#
ln -sf "${EXECrrfs}/mpassit.x" ./mpassit.x

# Use a physics-suite-specific set of field lists when available, otherwise
# fall back to the shared defaults (keeps all other WGFs unchanged).
mpassit_fix="${FIXrrfs}/mpassit"
if [[ -n "${PHYSICS_SUITE:-}" && -d "${FIXrrfs}/mpassit/${PHYSICS_SUITE}" ]]; then
  mpassit_fix="${FIXrrfs}/mpassit/${PHYSICS_SUITE}"
fi
${cpreq} "${mpassit_fix}"/diaglist                       diaglist
${cpreq} "${mpassit_fix}"/histlist_2d                    histlist_2d
${cpreq} "${mpassit_fix}"/histlist_3d                    histlist_3d
${cpreq} "${mpassit_fix}"/histlist_soil                  histlist_soil
if [[ "${LSM_SCHEME}" == *noah* ]]; then
  sed -i '/^snowfallac/d' histlist_2d  # sf_noah, sf_noahmp does not output variable density snowfall accumulation
fi
#
if [[ "${DO_CHEMISTRY^^}" == "TRUE" ]]; then
  source "${USHrrfs}"/chem_mpassit.sh
fi
#
nx=${MPASSIT_NX:-480}
ny=${MPASSIT_NY:-280}
dx=${MPASSIT_DX:-12000.0}
ref_lat=${MPASSIT_REF_LAT:-"39.0"}
ref_lon=${MPASSIT_REF_LON:-"-97.5"}
#
zeta_levels=${EXPDIR}/config/ZETA_LEVELS.txt
nlevel=$(wc -l < "${zeta_levels}")
ln -snf "${MESHrrfs:-${FIXrrfs}/${MESH_NAME}}/${MESH_NAME}.invariant.nc_L${nlevel}_${prefix}" ./invariant.nc
#
# find forecst length for this cycle
#
fcst_len_hrs_cycles=${FCST_LEN_HRS_CYCLES:-"01 01"}
if [[ "${DO_FREE_FCST^^}" != "TRUE" ]]; then
  fcst_len_hrs_thiscyc=$("${USHrrfs}/find_fcst_length.sh" "${fcst_len_hrs_cycles}" "${cyc}" )
  echo "forecast length for this cycle is ${fcst_len_hrs_thiscyc}"
fi
#
# loop through forecast history files for this group.  In WoFS free-forecast
# mode the lead times are MINUTES (GROUP_MINUTES) and timestamps are computed
# from the minute-aware cycle valid time; otherwise they are hours.
#
if [[ "${DO_FREE_FCST^^}" == "TRUE" ]]; then
  read -ra fhr_all <<< "${GROUP_MINUTES}"
  free_len_min=$(( 10#${FREE_FCST_LEN_HRS:-6} * 60 ))
  cdate_ymd=${CDATE:0:8}
  cdate_hh=${CDATE:8:2}
  cdate_mm=${CDATE:10:2}; cdate_mm=${cdate_mm:-00}
else
  read -ra fhr_all <<< "${GROUP_HOURS}"  # convert string to array
fi
for fhr in "${fhr_all[@]}"; do
    if [[ "${DO_FREE_FCST^^}" == "TRUE" ]]; then
      if (( 10#${fhr} > free_len_min )); then
        break
      fi
      timestr=$(date -d "${cdate_ymd} ${cdate_hh}:${cdate_mm} ${fhr} minutes" +%Y-%m-%d_%H.%M.%S)
    else
      if (( 10#${fhr} > 10#${fcst_len_hrs_thiscyc} )); then
        break
      fi
      # get forecast hour and string
      CDATEp=$(${NDATE} "${fhr}" "${CDATE}" )
      timestr=$(date -d "${CDATEp:0:8} ${CDATEp:8:2}" +%Y-%m-%d_%H.%M.%S)
    fi
    # decide the history files   
    history_file=${UMBRELLA_FCST_DATA}/history.${timestr}.nc
    diag_file=${UMBRELLA_FCST_DATA}/diag.${timestr}.nc
    # wait for file available 
    for (( j=0; j < 20; j=j+1)); do
      if [[ -s ${diag_file} ]]; then
        break
      fi
      sleep 60s
    done
    # run mpassit
    if [[ -s "${history_file}" ]] && [[ -s "${diag_file}" ]]; then
      ln -sfn "${history_file}" .
      ln -sfn "${diag_file}" .

      # generate the naemlist on fly
      sed -e "s/@timestr@/${timestr}/" -e "s/@nx@/${nx}/" -e "s/@ny@/${ny}/" -e "s/@dx@/${dx}/" \
          -e "s/@ref_lat@/${ref_lat}/" -e "s/@ref_lon@/${ref_lon}/" "${PARMrrfs}/namelist.mpassit" > namelist.mpassit

      # run the executable
      source prep_step
      ${MPI_RUN_CMD} ./mpassit.x namelist.mpassit
      # check the status, copy output to UMBRELLA_MPASSIT_DATA
      if [[ -s "./mpassit.${timestr}.nc" ]] && (( $(stat -c%s "./mpassit.${timestr}.nc") > 104857600 )); then
        mv "./mpassit.${timestr}.nc" "${UMBRELLA_MPASSIT_DATA}/."
        mv namelist.mpassit "namelist.mpassit_${fhr}"
      else
        echo "FATAL ERROR: failed to generate mpassit.${timestr}.nc"
        err_exit
      fi
    else
      echo "FATAL ERROR: cannot find history file at ${timestr}"
      err_exit
    fi
done
