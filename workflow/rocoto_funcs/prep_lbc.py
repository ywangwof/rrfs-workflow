#!/usr/bin/env python
import os
from datetime import datetime, timedelta
from rocoto_funcs.base import xml_task, get_cascade_env

# begin of prep_lbc --------------------------------------------------------


def prep_lbc(xmlFile, expdir, do_ensemble=False):
    meta_id = 'prep_lbc'
    cycledefs = 'prod'
    if os.getenv("DO_SPINUP", "FALSE").upper() == "TRUE":
        cycledefs = 'prod,spinup'
    prep_lbc_look_back_hrs = int(os.getenv("PREP_LBC_LOOK_BACK_HRS", "6"))

    # Task-specific EnVars beyond the task_common_vars
    dcTaskEnv = {
        'LBC_INTERVAL': os.getenv('LBC_INTERVAL', '3'),
        'FCST_LEN_HRS_CYCLES': os.getenv('FCST_LEN_HRS_CYCLES', '03 03'),
        'PREP_LBC_LOOK_BACK_HRS': f'{prep_lbc_look_back_hrs}',
    }

    if not do_ensemble:
        metatask = False
        task_id = f'{meta_id}'
        meta_bgn = ""
        meta_end = ""
        ensindexstr = ""
    else:
        metatask = True
        task_id = f'{meta_id}_m#ens_index#'
        dcTaskEnv['ENS_INDEX'] = "#ens_index#"
        meta_bgn = ""
        meta_end = ""
        ens_size = int(os.getenv('ENS_SIZE', '2'))
        ens_indices = ''.join(f'{i:03d} ' for i in range(1, int(ens_size) + 1)).strip()
        # WoFS: forecast member N sources its LBCs from external lbc member
        # ((N-1) mod LBC_ENS_SIZE)+1 (round-robin), exposed as #lbc_mem# so
        # only LBC_ENS_SIZE lbc members are generated (see lbc.py).
        lbc_mem_var = ''
        if os.getenv('EVENT_DATE', '').strip():
            lbc_ens_size = int(os.getenv('LBC_ENS_SIZE', os.getenv('EXTRN_LBC_MEMBERS', '10')))
            lbc_mems = ''.join(f'{((i - 1) % lbc_ens_size) + 1:03d} ' for i in range(1, int(ens_size) + 1)).strip()
            lbc_mem_var = f'\n<var name="lbc_mem">{lbc_mems}</var>'
            dcTaskEnv['LBC_MEM'] = "#lbc_mem#"
        meta_bgn = f'''
<metatask name="{meta_id}">
<var name="ens_index">{ens_indices}</var>{lbc_mem_var}'''
        meta_end = f'\
</metatask>\n'
        ensindexstr = "_m#ens_index#"

    dcTaskEnv['KEEPDATA'] = get_cascade_env(f"KEEPDATA_{task_id}".upper()).upper()
    # dependencies
    timedep = ""
    realtime = os.getenv("REALTIME", "false")
    if realtime.upper() == "TRUE":
        starttime = get_cascade_env(f"STARTTIME_{task_id}".upper())
        timedep = f'\n   <timedep><cyclestr offset="{starttime}">@Y@m@d@H@M00</cyclestr></timedep>'

    event_date = os.getenv('EVENT_DATE', '').strip()
    if event_date:
        # WoFS windowed mode: LBCs come from a SINGLE per-event lbc cycle at
        # DA_STARTTIME.  Depend on the first and last hourly boundary files in
        # that fixed shared lbc/ dir (a literal path, unambiguous across
        # midnight).  Both existing implies both lbc groups finished.
        da_start_hhmm = os.getenv('DA_STARTTIME', '1500').strip().zfill(4)
        lbc_length = int(os.getenv('LBC_LENGTH', '18'))
        d0 = datetime.strptime(event_date, '%Y%m%d') + timedelta(
            hours=int(da_start_hhmm[:2]), minutes=int(da_start_hhmm[2:]))
        first_valid = d0.strftime('%Y-%m-%d_%H.%M.%S')
        last_valid = (d0 + timedelta(hours=lbc_length)).strftime('%Y-%m-%d_%H.%M.%S')
        memsub = '/mem#lbc_mem#' if do_ensemble else ''
        lbc_dir = f'&COMROOT;/&NET;/&rrfs_ver;/&RUN;.{event_date}/{da_start_hhmm}/lbc/&WGF;{memsub}'
        dcTaskEnv['LBC_SRC_YMD'] = event_date
        dcTaskEnv['LBC_SRC_HHMM'] = da_start_hhmm
        datadep = (f'\n     <datadep age="00:00:05">{lbc_dir}/lbc.{first_valid}.nc</datadep>'
                   f'\n     <datadep age="00:00:05">{lbc_dir}/lbc.{last_valid}.nc</datadep>')
        dependencies = f'''
  <dependency>
  <and>{timedep}{datadep}
  </and>
  </dependency>'''
        xml_task(xmlFile, expdir, task_id, cycledefs, dcTaskEnv, dependencies,
                 metatask, meta_id, meta_bgn, meta_end, "PREP_LBC")
        return

    taskdep = ""
    for hr in range(0, int(prep_lbc_look_back_hrs) + 1):
        taskdep = taskdep + f'\n     <metataskdep metatask="lbc{ensindexstr}" cycle_offset="-{hr}:00:00" />'
    if os.getenv('DO_RTMA', 'FALSE').upper() == 'TRUE':
        taskdep = f'\n     <taskdep task="prep_ic"/>'

    dependencies = ""
    if os.getenv('DO_IC_LBC', 'TRUE').upper() == "TRUE" or os.getenv('DO_RTMA', 'FALSE').upper() == 'TRUE':
        dependencies = f'''
  <dependency>
  <and>{timedep}
   <or>{taskdep}
   </or>
  </and>
  </dependency>'''
    #
    xml_task(xmlFile, expdir, task_id, cycledefs, dcTaskEnv, dependencies,
             metatask, meta_id, meta_bgn, meta_end, "PREP_LBC")
# end of prep_lbc  --------------------------------------------------------
