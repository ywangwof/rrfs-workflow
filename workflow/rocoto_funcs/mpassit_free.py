#!/usr/bin/env python
import os
from rocoto_funcs.base import xml_task, get_cascade_env, tok_hm

# begin of mpassit_free -----------------------------------------------------
#
# WoFS Phase 4 post-processing: run MPASSIT on the free-forecast history/diag
# output at the FREE_OUTPUT_INTERVAL_MIN (minute) cadence.  Runs on the `free`
# cycledef for the FREE_FCST_MEMBERS subset and reads the dedicated `_free`
# forecast umbrella.  Gated by EVENT_DATE (only wired in WoFS windowed mode).


def mpassit_free(xmlFile, expdir, dcEnsGrpInfo=None):
    meta_id = 'mpassit_free'
    cycledefs = 'free'

    free_fcst_len_hrs = int(os.getenv('FREE_FCST_LEN_HRS', '6'))
    free_out_min = int(os.getenv('FREE_OUTPUT_INTERVAL_MIN', '5'))
    free_len_min = free_fcst_len_hrs * 60
    # minute lead times processed by this task (0, step, ... free_len_min)
    group_minutes = ' '.join(str(m) for m in range(0, free_len_min + free_out_min, free_out_min))

    extrn_mdl_source = os.getenv('IC_EXTRN_MDL_NAME', 'IC_PREFIX_not_defined')
    dcTaskEnv = {
        'DO_FREE_FCST': 'TRUE',
        'GROUP_MINUTES': f'{group_minutes}',
        'FREE_FCST_LEN_HRS': f'{free_fcst_len_hrs}',
        'FREE_OUTPUT_INTERVAL_MIN': f'{free_out_min}',
        'MPASSIT_NX': os.getenv('MPASSIT_NX', 'MPASSIT_NX_not_defined'),
        'MPASSIT_NY': os.getenv('MPASSIT_NY', 'MPASSIT_NY_not_defined'),
        'MPASSIT_DX': os.getenv('MPASSIT_DX', 'MPASSIT_DX_not_defined'),
        'MPASSIT_REF_LAT': os.getenv('MPASSIT_REF_LAT', 'MPASSIT_REF_LAT_not_defined'),
        'MPASSIT_REF_LON': os.getenv('MPASSIT_REF_LON', 'MPASSIT_REF_LON_not_defined'),
        'EXTRN_MDL_SOURCE': f'{extrn_mdl_source}',
        'LSM_SCHEME': os.getenv('LSM_SCHEME', 'sf_ruc'),
        'PHYSICS_SUITE': os.getenv('PHYSICS_SUITE', 'PHYSICS_SUITE_not_defined'),
    }
    # only set for meshes that define them (e.g. wofs_mpas) to keep other XMLs unchanged
    for key in ('MPASSIT_TRUELAT1', 'MPASSIT_TRUELAT2'):
        if os.getenv(key):
            dcTaskEnv[key] = os.getenv(key)

    if dcEnsGrpInfo is None:
        free_members = int(os.getenv('FREE_FCST_MEMBERS', os.getenv('ENS_SIZE', '2')))
        ens_indices = ''.join(f'{i:03d} ' for i in range(1, free_members + 1)).strip()
        dep_xml = ""
        group_name = meta_id
    else:
        ens_indices = dcEnsGrpInfo["ens_indices"]
        dep_xml = dcEnsGrpInfo["dep_xml"]
        group_name = dcEnsGrpInfo["group_name"]

    task_id = f'{meta_id}_m#ens_index#'
    dcTaskEnv['ENS_INDEX'] = "#ens_index#"
    memdir = "/mem#ens_index#"
    dcTaskEnv['MEMDIR'] = f'{memdir}'
    meta_bgn = f'''
<metatask name="{group_name}">
<var name="ens_index">{ens_indices}</var>'''
    meta_end = '</metatask>\n'

    dcTaskEnv['KEEPDATA'] = get_cascade_env(f"KEEPDATA_{task_id}".upper()).upper()

    # dependencies: the member's free forecast must have produced (at least) the
    # final-lead history/diag, or the fcst_free task itself must be complete.
    extra_dep = f'''
    <or>
      <datadep age="00:00:10"><cyclestr>&DATAROOT;/@Y@m@d/&RUN;_fcst_free_{tok_hm()}_&rrfs_ver;/&WGF;{memdir}</cyclestr><cyclestr offset="{free_fcst_len_hrs}:00:00">/history.@Y-@m-@d_@H.@M.@S.nc.done</cyclestr></datadep>
      <datadep age="00:00:10"><cyclestr>&DATAROOT;/@Y@m@d/&RUN;_fcst_free_{tok_hm()}_&rrfs_ver;/&WGF;{memdir}</cyclestr><cyclestr offset="{free_fcst_len_hrs}:00:00">/diag.@Y-@m-@d_@H.@M.@S.nc.done</cyclestr></datadep>
      <taskdep task="fcst_free_m#ens_index#"/>
    </or>'''

    dependencies = f'''
  <dependency>
  <and>{extra_dep}{dep_xml}
  </and>
  </dependency>'''

    xml_task(xmlFile, expdir, task_id, cycledefs, dcTaskEnv, dependencies,
             True, meta_id, meta_bgn, meta_end, "MPASSIT_FREE")
# end of mpassit_free -------------------------------------------------------
