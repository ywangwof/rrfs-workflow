#!/usr/bin/env python
import os
from rocoto_funcs.base import xml_task, get_cascade_env

# begin of prep_lbc_free ----------------------------------------------------
#
# WoFS free-forecast LBC staging.  Runs on the `free` cycledef and stages the
# full hourly/3-hourly LBC sequence (0 .. FREE_FCST_LEN_HRS at LBC_INTERVAL)
# into a dedicated `_free` umbrella, so it never collides with the sub-hourly
# DA-cycle prep_lbc that shares the same launch minute.


def prep_lbc_free(xmlFile, expdir):
    meta_id = 'prep_lbc_free'
    cycledefs = 'free'
    prep_lbc_look_back_hrs = int(os.getenv("PREP_LBC_LOOK_BACK_HRS", "6"))
    free_fcst_len_hrs = os.getenv('FREE_FCST_LEN_HRS', '6')
    free_members = int(os.getenv('FREE_FCST_MEMBERS', os.getenv('ENS_SIZE', '2')))

    # Task-specific EnVars beyond the task_common_vars
    dcTaskEnv = {
        'PREP_LBC_MODE': 'free',
        'LBC_INTERVAL': os.getenv('LBC_INTERVAL', '3'),
        'FREE_FCST_LEN_HRS': f'{free_fcst_len_hrs}',
        'PREP_LBC_LOOK_BACK_HRS': f'{prep_lbc_look_back_hrs}',
        'ENS_INDEX': "#ens_index#",
    }

    ens_indices = ''.join(f'{i:03d} ' for i in range(1, free_members + 1)).strip()
    # WoFS: free member N sources its LBCs from external lbc member
    # ((N-1) mod LBC_ENS_SIZE)+1 (round-robin); only LBC_ENS_SIZE lbc members
    # are generated (see lbc.py).
    lbc_ens_size = int(os.getenv('LBC_ENS_SIZE', os.getenv('EXTRN_LBC_MEMBERS', '10')))
    lbc_mems = ''.join(f'{((i - 1) % lbc_ens_size) + 1:03d} ' for i in range(1, free_members + 1)).strip()
    meta_bgn = f'''
<metatask name="{meta_id}">
<var name="ens_index">{ens_indices}</var>
<var name="lbc_mem">{lbc_mems}</var>'''
    meta_end = '</metatask>\n'
    ensindexstr = "_m#ens_index#"
    task_id = f'{meta_id}_m#ens_index#'

    dcTaskEnv['KEEPDATA'] = get_cascade_env(f"KEEPDATA_{task_id}".upper()).upper()

    # dependencies: LBCs come from the single per-event lbc cycle at
    # DA_STARTTIME.  Each free launch (whole hour T) needs boundaries valid
    # T .. T+FREE_FCST_LEN_HRS; depend on the first and last of those hourly
    # files in the fixed shared lbc/ dir.  The dir is a literal event-anchored
    # path while the filename valid time is a cyclestr of this free cycle.
    event_date = os.getenv('EVENT_DATE', '').strip()
    da_start_hhmm = os.getenv('DA_STARTTIME', '1500').strip().zfill(4)
    free_len = int(free_fcst_len_hrs)
    dcTaskEnv['LBC_SRC_YMD'] = event_date
    dcTaskEnv['LBC_SRC_HHMM'] = da_start_hhmm
    dcTaskEnv['LBC_MEM'] = "#lbc_mem#"
    lbc_dir = f'&COMROOT;/&NET;/&rrfs_ver;/&RUN;.{event_date}/{da_start_hhmm}/lbc/&WGF;/mem#lbc_mem#'
    datadep = (
        f'\n     <datadep age="00:00:05">{lbc_dir}/lbc.'
        f'<cyclestr>@Y-@m-@d_@H.00.00</cyclestr>.nc</datadep>'
        f'\n     <datadep age="00:00:05">{lbc_dir}/lbc.'
        f'<cyclestr offset="{free_len}:00:00">@Y-@m-@d_@H.00.00</cyclestr>.nc</datadep>')

    dependencies = f'''
  <dependency>
  <and>{datadep}
  </and>
  </dependency>'''

    xml_task(xmlFile, expdir, task_id, cycledefs, dcTaskEnv, dependencies,
             True, meta_id, meta_bgn, meta_end, "PREP_LBC_FREE")
# end of prep_lbc_free ------------------------------------------------------
