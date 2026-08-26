#!/usr/bin/env bash
# copy ioda observation files from com/ to the run directory
#
# shellcheck disable=SC2154
if [[ "$1" == "jedivar" ]]; then
  jedivar=true
else
  jedivar=false
fi

declare -A mappings  # Declare an associative array

if ${jedivar}; then
  obspath="${COMOUT}/ioda_bufr/${WGF}"
else # getkf
  obspath="${COMOUT}/ioda_bufr/${IODA_BUFR_WGF}"
fi
mappings["ioda_adpsfc.nc"]="${obspath}/ioda_adpsfc.nc"
mappings["ioda_adpupa.nc"]="${obspath}/ioda_adpupa.nc"
mappings["ioda_aircar.nc"]="${obspath}/ioda_aircar.nc"
mappings["ioda_aircft.nc"]="${obspath}/ioda_aircft.nc"
mappings["ioda_ascatw.nc"]="${obspath}/ioda_ascatw.nc"
mappings["ioda_msonet.nc"]="${obspath}/ioda_msonet.nc"
mappings["ioda_proflr.nc"]="${obspath}/ioda_proflr.nc"
mappings["ioda_rassda.nc"]="${obspath}/ioda_rassda.nc"
mappings["ioda_sfcshp.nc"]="${obspath}/ioda_sfcshp.nc"
mappings["ioda_vadwnd.nc"]="${obspath}/ioda_vadwnd.nc"
mappings["ioda_gnss_ztd.nc"]="${obspath}/ioda_gnss_ztd.nc"
mappings["ioda_satwnd.abi_goes-16.nc"]="${obspath}/ioda_satwnd.abi_goes-16.nc"
mappings["ioda_satwnd.abi_goes-18.nc"]="${obspath}/ioda_satwnd.abi_goes-18.nc"
# satellite observations
mappings["ioda_abi_g16.nc"]="${obspath}/ioda_abi_g16.nc"
mappings["ioda_abi_g18.nc"]="${obspath}/ioda_abi_g18.nc"
mappings["ioda_atms_npp.nc"]="${obspath}/ioda_atms_npp.nc"
mappings["ioda_atms_n20.nc"]="${obspath}/ioda_atms_n20.nc"
mappings["ioda_atms_n21.nc"]="${obspath}/ioda_atms_n21.nc"
mappings["ioda_crisf4_n20.nc"]="${obspath}/ioda_crisf4_n20.nc"
mappings["ioda_crisf4_n21.nc"]="${obspath}/ioda_crisf4_n21.nc"
mappings["ioda_mtiasi_metop-b.nc"]="${obspath}/ioda_mtiasi_metop-b.nc"
mappings["ioda_mtiasi_metop-c.nc"]="${obspath}/ioda_mtiasi_metop-c.nc"

if [[ "${DO_RADAR_REF^^}" == "TRUE" ]]; then
  if [[ -n "${EVENT_DATE:-}" ]]; then
    # WoFS windowed mode: the ioda_mrms_refl task is not run; use the
    # pre-staged IODA MRMS file for the analysis time YYYYmmddHHMM from
    #   ${MRMS_ALL_DIR}/YYYYmmdd/ioda_mrms_YYYYmmdd_HHMM.nc4
    mappings["ioda_mrms_refl.nc"]="${MRMS_ALL_DIR}/${CDATE:0:8}/ioda_mrms_${CDATE:0:8}_${cyc}.nc4"
    # WoFS clear-sky reflectivity (refl10cm_clear obs space), pre-staged at
    #   ${MRMS_CLEAR_DIR}/YYYYmmdd/ioda_mrms_YYYYmmdd_HHMM_clear.nc4
    mappings["ioda_mrms_clear.nc"]="${MRMS_CLEAR_DIR}/${CDATE:0:8}/ioda_mrms_${CDATE:0:8}_${cyc}_clear.nc4"
  else
    if ${jedivar}; then
      obspath="${COMOUT}/ioda_mrms_refl/${WGF}"
    else # getkf
      obspath="${COMOUT}/ioda_mrms_refl/${IODA_BUFR_WGF}"
    fi
    mappings["ioda_mrms_refl.nc"]="${obspath}/ioda_mrms_${CDATE}_${time_min}.nc4"
  fi
fi

# WoFS radial velocity (rw obs space): pre-staged IODA VR file for the analysis
# time YYYYmmddHHMM at ${VR_DIR}/YYYYmmdd/ioda_VR_YYYYmmdd_HHMM.nc4
if [[ -n "${EVENT_DATE:-}" ]]; then
  mappings["ioda_rw_obs.nc"]="${VR_DIR}/${CDATE:0:8}/ioda_VR_${CDATE:0:8}_${cyc}.nc4"
fi

# GOES cloud-water-path obs (cwp/lwp/iwp and their _night variants).  These are
# produced by the ioda_cwp task into ${COMOUT}/ioda_cwp/${WGF}; stage whichever
# variables were generated for this cycle.
if [[ -n "${OBS_CWP_DIR:-}" ]]; then
  if ${jedivar}; then
    cwppath="${COMOUT}/ioda_cwp/${WGF}"
  else # getkf
    cwppath="${COMOUT}/ioda_cwp/${IODA_BUFR_WGF}"
  fi
  for cwpobs in cwp lwp iwp cwp_night lwp_night iwp_night; do
    mappings["ioda_${cwpobs}_obs.nc"]="${cwppath}/ioda_${cwpobs}_obs.nc"
  done
fi

# loop through and copy files
for dst_file in "${!mappings[@]}"; do
  src_file=${mappings[${dst_file}]}
  if [[ -s "${src_file}" ]]; then
    cp "${src_file}"  "obs/${dst_file}"
  else
    echo "WARNING: ${src_file} does not exist!"
  fi
done
