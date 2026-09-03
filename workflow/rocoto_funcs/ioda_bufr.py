#!/usr/bin/env python
import os
from rocoto_funcs.base import xml_task, get_cascade_env, wofs_windowed

# begin of ioda_bufr --------------------------------------------------------


def ioda_bufr(xmlFile, expdir):
    task_id = 'ioda_bufr'
    cycledefs = 'prod'
    if os.getenv("DO_SPINUP", "FALSE").upper() == "TRUE":
        cycledefs = 'prod,spinup'
    # WoFS: no DA runs at the cold start, so obs prep is unnecessary there; run
    # on the da_nocold cycledef (which skips DA_STARTTIME) like the getkf tasks.
    if wofs_windowed() and os.getenv('COLDSTART_CYCS_DO_DA', 'TRUE').upper() == 'FALSE':
        cycledefs = 'da_nocold'
    OBSPATH = os.getenv("OBSPATH", 'OBSPATH_not_defined')
    # Task-specific EnVars beyond the task_common_vars
    dcTaskEnv = {
        'REFERENCE_TIME': '@Y-@m-@dT@H:00:00Z',
        'YAML_GEN_METHOD': os.getenv('YAML_GEN_METHOD', '1'),
        'OBSPATH': f'{OBSPATH}'
    }

    dcTaskEnv['KEEPDATA'] = get_cascade_env(f"KEEPDATA_{task_id}".upper()).upper()
    # dependencies: in WoFS windowed mode the sub-hourly prepbufr comes from a
    # dated PREPBUFR_DIR with an rtma_ru, minute-stamped filename.
    if wofs_windowed():
        prepbufr_dir = os.getenv("PREPBUFR_DIR", 'PREPBUFR_DIR_not_defined')
        dcTaskEnv['PREPBUFR_DIR'] = f'{prepbufr_dir}'
        fpath = f'{prepbufr_dir}/@Y@m@d/@Y@m@d@H.rtma_ru.t@H@Mz.prepbufr.tm00'
    else:
        fpath = f'{OBSPATH}/@Y@m@d@H.rap.t@Hz.prepbufr.tm00'

    timedep = ""
    realtime = os.getenv("REALTIME", "false")
    if realtime.upper() == "TRUE":
        starttime = get_cascade_env(f"STARTTIME_{task_id}".upper())
        timedep = f'\n    <timedep><cyclestr offset="{starttime}">@Y@m@d@H@M00</cyclestr></timedep>'
    #
    dependencies = f'''
  <dependency>
  <and>{timedep}
    <datadep age="00:02:00"><cyclestr>{fpath}</cyclestr></datadep>
  </and>
  </dependency>'''
    #
    xml_task(xmlFile, expdir, task_id, cycledefs, dcTaskEnv, dependencies)
# end of ioda_bufr --------------------------------------------------------
