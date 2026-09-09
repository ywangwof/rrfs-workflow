#!/usr/bin/env bash
# shellcheck disable=SC1091,SC2153,SC2154,SC2034
declare -rx PS4='+${SECONDS}s $(basename ${BASH_SOURCE[0]:-${FUNCNAME[0]:-"Unknown"}})[${LINENO}]: '
set -x
cpreq=${cpreq:-cpreq}
cd "${DATA}" || exit 1
#
# ---------------------------------------------------------------------------
# Build the MPAS mesh for this experiment:
#   1) project_hexes   -> ${MESH_NAME}.grid.nc + ${MESH_NAME}.graph.info
#   2) gpmetis         -> ${MESH_NAME}.graph.info.part.N (DOMAIN_GRAPH_PARTS)
#   3) init_atmosphere -> ${MESH_NAME}.static.nc + ${MESH_NAME}.ugwp_oro_data.nc
#   4) init_atmosphere -> ${MESH_NAME}.invariant.nc_L<nlevel>_<prefix> (optional,
#      DO_DOMAIN_INVARIANT; ungribs DOMAIN_INVARIANT_GRIB2 for met interpolation)
# The products are installed under ${MESHrrfs} (defaults to ${FIXrrfs}/${MESH_NAME};
# a per-event COM path in WoFS windowed mode) for the ic/lbc/fcst tasks.
# A guard skips the whole build if the mesh already exists.
# ---------------------------------------------------------------------------
#
fixmesh="${MESHrrfs:-${FIXrrfs}/${MESH_NAME}}"
zeta_levels="${EXPDIR}/config/ZETA_LEVELS.txt"
build_static="yes"
if [[ -s "${fixmesh}/${MESH_NAME}.static.nc" && -s "${fixmesh}/${MESH_NAME}.grid.nc" ]]; then
  need_invariant="no"
  if [[ "${DO_DOMAIN_INVARIANT^^}" == "TRUE" ]]; then
    nlevel=$(wc -l < "${zeta_levels}")
    inv_prefix="${DOMAIN_INVARIANT_PREFIX:-RRFSV2x}"
    [[ -s "${fixmesh}/${MESH_NAME}.invariant.nc_L${nlevel}_${inv_prefix}" ]] || need_invariant="yes"
  fi
  if [[ "${need_invariant}" == "no" ]]; then
    echo "NOTE: ${fixmesh}/${MESH_NAME}.static.nc already exists; skipping domain build."
    exit 0
  fi
  echo "NOTE: static mesh exists but invariant is missing; building invariant only."
  build_static="no"
fi
#
# ---------------------------------------------------------------------------
# Render the namelists / streams from the templates in ${PARMrrfs}/new_domain
# ---------------------------------------------------------------------------
#
start_time=$(date -d "${PDY} ${cyc}" +%Y-%m-%d_%H:%M:%S)

if [[ "${build_static}" == "yes" ]]; then
sed -e "s|@DOMAIN_DX_KM@|${DOMAIN_DX_KM}|g" \
    -e "s|@DOMAIN_SIZE_KM@|${DOMAIN_SIZE_KM}|g" \
    -e "s|@DOMAIN_EARTH_RADIUS_KM@|${DOMAIN_EARTH_RADIUS_KM}|g" \
    -e "s|@DOMAIN_CEN_LON@|${DOMAIN_CEN_LON}|g" \
    -e "s|@DOMAIN_CEN_LAT@|${DOMAIN_CEN_LAT}|g" \
    -e "s|@DOMAIN_STD_PAR1@|${DOMAIN_STD_PAR1}|g" \
    -e "s|@DOMAIN_STD_PAR2@|${DOMAIN_STD_PAR2}|g" \
    "${PARMrrfs}/new_domain/namelist.projections" > namelist.projections

sed -e "s|@START_TIME@|${start_time}|g" \
    -e "s|@DOMAIN_GEOG_DATA_PATH@|${DOMAIN_GEOG_DATA_PATH}|g" \
    -e "s|@ZETA_LEVELS@|${zeta_levels}|g" \
    -e "s|@MESH_NAME@|${MESH_NAME}|g" \
    "${PARMrrfs}/new_domain/namelist.init_atmosphere" > namelist.init_atmosphere

sed -e "s|@MESH_NAME@|${MESH_NAME}|g" \
    "${PARMrrfs}/new_domain/streams.init_atmosphere" > streams.init_atmosphere
#
# ---------------------------------------------------------------------------
# Step 1: project_hexes (needs the SMIOL build; run in a subshell so the module
#         swap does not disturb the init_atmosphere environment loaded already)
# ---------------------------------------------------------------------------
#
(
  set -x
  source /etc/profile.d/modules.sh 2>/dev/null || true
  if [[ -n "${DOMAIN_PROJECT_MODULE}" ]]; then
    module purge
    [[ -n "${DOMAIN_PROJECT_MODULE_USE}" ]] && module use "${DOMAIN_PROJECT_MODULE_USE}"
    module load "${DOMAIN_PROJECT_MODULE}"
    module list
  fi
  ulimit -s unlimited
  srun -n 1 "${EXECrrfs}/project_hexes"
)
if [[ ! -s './mpas_hex_mesh.nc' || ! -s './graph.info' ]]; then
  echo "FATAL ERROR: project_hexes failed to produce mpas_hex_mesh.nc / graph.info"
  err_exit
fi
mv mpas_hex_mesh.nc "${MESH_NAME}.grid.nc"
mv graph.info "${MESH_NAME}.graph.info"
#
# ---------------------------------------------------------------------------
# Step 2: gpmetis partitions (always include the static-step task count)
# ---------------------------------------------------------------------------
#
parts="${DOMAIN_GRAPH_PARTS} ${DOMAIN_STATIC_NTASKS}"
parts=$(echo "${parts}" | tr ' ' '\n' | sort -un | tr '\n' ' ')
# gpmetis links against shared libraries co-located with the binary
# (../lib relative to its bin/ directory); make them resolvable at run time.
gpmetis_libdir="$(cd "$(dirname "${GPMETIS}")/../lib" 2>/dev/null && pwd)"
[[ -n "${gpmetis_libdir}" ]] && export LD_LIBRARY_PATH="${gpmetis_libdir}:${LD_LIBRARY_PATH}"
for n in ${parts}; do
  [[ "${n}" -le 1 ]] && continue
  "${GPMETIS}" -minconn -contig -niter=200 "${MESH_NAME}.graph.info" "${n}" > "gpmetis.out${n}" 2>&1
  if [[ ! -s "${MESH_NAME}.graph.info.part.${n}" ]]; then
    echo "FATAL ERROR: gpmetis failed to produce ${MESH_NAME}.graph.info.part.${n}"
    cat "gpmetis.out${n}"
    err_exit
  fi
done
#
# ---------------------------------------------------------------------------
# Step 3: init_atmosphere_model.x -> static.nc + ugwp_oro_data.nc
# ---------------------------------------------------------------------------
#
source prep_step
${cpreq} "${EXECrrfs}/init_atmosphere_model.x" .
ulimit -s unlimited
srun -n "${DOMAIN_STATIC_NTASKS}" ./init_atmosphere_model.x
export err=$?; err_chk
if [[ ! -s "./${MESH_NAME}.static.nc" ]]; then
  echo "FATAL ERROR: init_atmosphere failed to generate ${MESH_NAME}.static.nc"
  err_exit
fi
else
  #
  # Reuse the previously installed static mesh so only the invariant is built.
  #
  ${cpreq} "${fixmesh}/${MESH_NAME}.static.nc" "${MESH_NAME}.static.nc"
  ${cpreq} "${fixmesh}/graphinfo/${MESH_NAME}.graph.info.part.${DOMAIN_STATIC_NTASKS}" .
fi
#
# ---------------------------------------------------------------------------
# Step 4 (optional): build the invariant file used by the JEDI/fcst/MPASSIT
#   tasks. Unlike the static step this stage interpolates a real met field
#   (config_met_interp=true) so it must ungrib an external GRIB2 record first.
#   Products: ${MESH_NAME}.invariant.nc_L<nlevel>_<prefix>
#   Gated on DO_DOMAIN_INVARIANT so plain static-only meshes are unaffected.
# ---------------------------------------------------------------------------
#
if [[ "${DO_DOMAIN_INVARIANT^^}" == "TRUE" ]]; then
  nlevel=$(wc -l < "${zeta_levels}")
  inv_prefix="${DOMAIN_INVARIANT_PREFIX:-RRFSV2x}"
  invariant_out="${fixmesh}/${MESH_NAME}.invariant.nc_L${nlevel}_${inv_prefix}"
  if [[ -s "${invariant_out}" ]]; then
    echo "NOTE: ${invariant_out} already exists; skipping invariant build."
  else
    if [[ ! -s "${DOMAIN_INVARIANT_GRIB2}" ]]; then
      echo "FATAL ERROR: DOMAIN_INVARIANT_GRIB2='${DOMAIN_INVARIANT_GRIB2}' not found"
      err_exit
    fi
    #
    # Determine the valid time of the GRIB2 record. Prefer the explicit knob;
    # otherwise derive it from the RRFS-style path rrfs.YYYYMMDD/CC/.../f0HH.
    #
    if [[ -n "${DOMAIN_INVARIANT_TIME}" ]]; then
      inv_start_time="${DOMAIN_INVARIANT_TIME}"
    else
      grib_pdy=$(echo "${DOMAIN_INVARIANT_GRIB2}" | sed -n 's|.*rrfs\.\([0-9]\{8\}\)/\([0-9]\{2\}\)/.*|\1\2|p')
      grib_fhr=$(echo "${DOMAIN_INVARIANT_GRIB2}" | sed -n 's|.*\.f\([0-9]\{3\}\)\..*|\1|p')
      if [[ -z "${grib_pdy}" || -z "${grib_fhr}" ]]; then
        echo "FATAL ERROR: cannot derive valid time from ${DOMAIN_INVARIANT_GRIB2}; set DOMAIN_INVARIANT_TIME"
        err_exit
      fi
      grib_valid=$(${NDATE} "$((10#${grib_fhr}))" "${grib_pdy}")
      inv_start_time=$(date -d "${grib_valid:0:8} ${grib_valid:8:2}" +%Y-%m-%d_%H:%M:%S)
    fi
    #
    # Ungrib the GRIB2 into a WPS intermediate file named '${inv_prefix}:YYYY-MM-DD_HH'
    #
    inv_vtable="${DOMAIN_INVARIANT_VTABLE:-RRFSV2x}"
    if [[ -s "${PARMrrfs}/new_domain/Vtable.${inv_vtable}" ]]; then
      ${cpreq} "${PARMrrfs}/new_domain/Vtable.${inv_vtable}" Vtable
    else
      ${cpreq} "${FIXrrfs}/ungrib/Vtable.${inv_vtable}" Vtable
    fi
    gribfile_local=$( "${USHrrfs}/num_to_GRIBFILE.XXX.sh" 1 )
    ln -snf "${DOMAIN_INVARIANT_GRIB2}" "${gribfile_local}"
    fg_interval="${DOMAIN_INVARIANT_FG_INTERVAL:-3600}"
    sed -e "s/@start_time@/${inv_start_time}/" -e "s/@end_time@/${inv_start_time}/" \
        -e "s/@interval_seconds@/${fg_interval}/" -e "s/@prefix@/${inv_prefix}/" \
        "${PARMrrfs}/namelist.wps" > namelist.wps
    source prep_step
    ${cpreq} "${EXECrrfs}/ungrib.x" .
    ./ungrib.x
    export err=$?; err_chk
    inv_intermediate="${inv_prefix}:${inv_start_time:0:13}"
    if [[ ! -s "${inv_intermediate}" ]]; then
      echo "FATAL ERROR: ungrib failed to produce ${inv_intermediate}"
      err_exit
    fi
    #
    # Render the invariant namelist / streams and run init_atmosphere with met interp.
    #
    ztop=$(tail -1 "${zeta_levels}")
    nvertlevels=$(( nlevel - 1 ))
    nsoillevels="${NSOIL_LEVELS:-9}"
    nfglevels="${DOMAIN_INVARIANT_NFGLEVELS:-66}"
    nfgsoillevels="${DOMAIN_INVARIANT_NFGSOILLEVELS:-9}"
    fg_interval_str=$(printf '%02d:00:00' $(( fg_interval/3600 )))
    sed -e "s|@START_TIME@|${inv_start_time}|g" \
        -e "s|@NVERTLEVELS@|${nvertlevels}|g" \
        -e "s|@NSOILLEVELS@|${nsoillevels}|g" \
        -e "s|@NFGLEVELS@|${nfglevels}|g" \
        -e "s|@NFGSOILLEVELS@|${nfgsoillevels}|g" \
        -e "s|@DOMAIN_GEOG_DATA_PATH@|${DOMAIN_GEOG_DATA_PATH}|g" \
        -e "s|@MET_PREFIX@|${inv_prefix}|g" \
        -e "s|@FG_INTERVAL@|${fg_interval}|g" \
        -e "s|@ZTOP@|${ztop}|g" \
        -e "s|@ZETA_LEVELS@|${zeta_levels}|g" \
        -e "s|@MESH_NAME@|${MESH_NAME}|g" \
        "${PARMrrfs}/new_domain/namelist.init_atmosphere.invariant" > namelist.init_atmosphere
    sed -e "s|@MESH_NAME@|${MESH_NAME}|g" \
        -e "s|@FG_INTERVAL_STR@|${fg_interval_str}|g" \
        "${PARMrrfs}/new_domain/streams.init_atmosphere.invariant" > streams.init_atmosphere
    #
    # init_atmosphere is MPI and reads the graph partition produced in Step 2.
    #
    ln -snf "${MESH_NAME}.graph.info.part.${DOMAIN_STATIC_NTASKS}" .
    source prep_step
    ${cpreq} "${EXECrrfs}/init_atmosphere_model.x" .
    ulimit -s unlimited
    srun -n "${DOMAIN_STATIC_NTASKS}" ./init_atmosphere_model.x
    export err=$?; err_chk
    if [[ ! -s "./${MESH_NAME}.init.nc" ]]; then
      echo "FATAL ERROR: init_atmosphere failed to generate ${MESH_NAME}.init.nc (invariant)"
      err_exit
    fi
    mkdir -p "${fixmesh}"
    ${cpreq} "${MESH_NAME}.init.nc" "${invariant_out}"
    #
    # The fcst/getkf/jedivar/mpassit/lbc tasks build the invariant filename from
    # the cycle's EXTRN_MDL_SOURCE prefix; add symlinks so they resolve to the
    # RRFSV2x-built file when a different IC/LBC source name is in use.
    #
    for link_prefix in ${DOMAIN_INVARIANT_LINK_PREFIXES}; do
      [[ "${link_prefix}" == "${inv_prefix}" ]] && continue
      ln -snf "${MESH_NAME}.invariant.nc_L${nlevel}_${inv_prefix}" \
              "${fixmesh}/${MESH_NAME}.invariant.nc_L${nlevel}_${link_prefix}"
    done
    echo "new_domain: invariant '${invariant_out}' installed"
  fi
fi
#
# ---------------------------------------------------------------------------
# Install the mesh into ${fixmesh} (${MESHrrfs} or ${FIXrrfs}/${MESH_NAME})
# ---------------------------------------------------------------------------
#
if [[ "${build_static}" == "yes" ]]; then
mkdir -p "${fixmesh}/graphinfo"
${cpreq} "${MESH_NAME}.grid.nc"           "${fixmesh}/"
${cpreq} "${MESH_NAME}.static.nc"         "${fixmesh}/"
${cpreq} "${MESH_NAME}.graph.info"        "${fixmesh}/"
[[ -s "${MESH_NAME}.ugwp_oro_data.nc" ]] && ${cpreq} "${MESH_NAME}.ugwp_oro_data.nc" "${fixmesh}/"
${cpreq} "${MESH_NAME}".graph.info.part.* "${fixmesh}/graphinfo/"
fi
#
date
echo "new_domain: mesh '${MESH_NAME}' installed under ${fixmesh}"
exit 0
