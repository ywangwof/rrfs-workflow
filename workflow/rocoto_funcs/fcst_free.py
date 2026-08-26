#!/usr/bin/env python
import os
import sys
from rocoto_funcs.base import xml_task, get_cascade_env

# begin of fcst_free --------------------------------------------------------
#
# WoFS free (non-DA) forecast.  Runs on the `free` cycledef for the first
# FREE_FCST_MEMBERS members, starting from each member's DA analysis and
# integrating FREE_FCST_LEN_HRS hours with standard (hourly) output.  Gated by
# EVENT_DATE; only wired in WoFS windowed mode.


def fcst_free(xmlFile, expdir, dcEnsGrpInfo=None):
    meta_id = 'fcst_free'
    cycledefs = 'free'

    extrn_mdl_source = os.getenv('IC_EXTRN_MDL_NAME', 'IC_PREFIX_not_defined')
    physics_suite = os.getenv('PHYSICS_SUITE', 'PHYSICS_SUITE_not_defined')

    dcTaskEnv = {
        'DO_FREE_FCST': 'TRUE',
        'EXTRN_MDL_SOURCE': f'{extrn_mdl_source}',
        'LBC_INTERVAL': os.getenv('LBC_INTERVAL', '3'),
        'FREE_FCST_LEN_HRS': os.getenv('FREE_FCST_LEN_HRS', '6'),
        'FREE_OUTPUT_INTERVAL_MIN': os.getenv('FREE_OUTPUT_INTERVAL_MIN', '5'),
        'RESTART_INTERVAL': os.getenv('RESTART_INTERVAL', 'none'),
        'PHYSICS_SUITE': f'{physics_suite}',
        'LSM_SCHEME': os.getenv('LSM_SCHEME', 'sf_ruc'),
        'NSOIL_LEVELS': os.getenv('NSOIL_LEVELS', '9'),
        'FCST_DT': os.getenv('FCST_DT', 'FCST_DT_not_defined'),
        'FCST_SUBSTEPS': os.getenv('FCST_SUBSTEPS', 'FCST_SUBSTEPS_not_defined'),
        'FCST_RADT': os.getenv('FCST_RADT', 'FCST_RADT_not_defined'),
    }
    if os.getenv('FCST_CONVECTION_SCHEME', 'FALSE').upper() == 'TRUE':
        dcTaskEnv['FCST_CONVECTION_SCHEME'] = "TRUE"
    if os.getenv('FCST_GFL_SUB3D', '') != '':
        dcTaskEnv['FCST_GFL_SUB3D'] = os.getenv('FCST_GFL_SUB3D')

    if dcEnsGrpInfo is None:
        print('dcEnsGrpInfo not set up or incorrect!')
        sys.exit(1)
    ens_indices = dcEnsGrpInfo["ens_indices"]
    dep_xml = dcEnsGrpInfo["dep_xml"]
    group_name = dcEnsGrpInfo["group_name"]
    task_id = f'{meta_id}_m#ens_index#'
    dcTaskEnv['ENS_INDEX'] = "#ens_index#"
    meta_bgn = f'''
<metatask name="{group_name}">
<var name="ens_index">{ens_indices}</var>'''
    meta_end = '</metatask>\n'

    dcTaskEnv['KEEPDATA'] = get_cascade_env(f"KEEPDATA_{task_id}".upper()).upper()

    # dependencies: the member's DA analysis (getkf solver + prep_ic) at the
    # launch cycle plus the member's free-forecast LBCs.
    jedidep = ""
    if os.getenv("DO_JEDI", "FALSE").upper() == "TRUE":
        jedidep = '\n    <taskdep task="getkf_solver"/>'
    prep_ic_dep = '\n    <taskdep task="prep_ic"/>'
    prep_lbc_dep = '\n    <taskdep task="prep_lbc_free_m#ens_index#" cycle_offset="0:00:00"/>'

    dependencies = f'''
  <dependency>
  <and>{prep_lbc_dep}{jedidep}{prep_ic_dep}{dep_xml}
  </and>
  </dependency>'''

    xml_task(xmlFile, expdir, task_id, cycledefs, dcTaskEnv, dependencies,
             True, meta_id, meta_bgn, meta_end, "FCST_FREE")
# end of fcst_free ----------------------------------------------------------
