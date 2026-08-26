#!/usr/bin/env python
import os
from rocoto_funcs.base import xml_task, get_cascade_env

# begin of ioda_cwp --------------------------------------------------------


def ioda_cwp(xmlFile, expdir):
    task_id = 'ioda_cwp'
    cycledefs = 'prod'
    if os.getenv("DO_SPINUP", "FALSE").upper() == "TRUE":
        cycledefs = 'prod,spinup'
    OBS_CWP_DIR = os.getenv("OBS_CWP_DIR", 'OBS_CWP_DIR_not_defined')
    CWP_LOOKBACK_MIN = os.getenv("CWP_LOOKBACK_MIN", '4')
    # Task-specific EnVars beyond the task_common_vars
    dcTaskEnv = {
        'OBS_CWP_DIR': f'{OBS_CWP_DIR}',
        'CWP_LOOKBACK_MIN': f'{CWP_LOOKBACK_MIN}',
    }

    dcTaskEnv['KEEPDATA'] = get_cascade_env(f"KEEPDATA_{task_id}".upper()).upper()
    # dependencies
    timedep = ""
    realtime = os.getenv("REALTIME", "false")
    if realtime.upper() == "TRUE":
        starttime = get_cascade_env(f"STARTTIME_{task_id}".upper())
        timedep = f'\n    <timedep><cyclestr offset="{starttime}">@Y@m@d@H@M00</cyclestr></timedep>'
        dependencies = f'''
  <dependency>
    {timedep}
  </dependency>'''
    else:
        dependencies = f' '
    #
    xml_task(xmlFile, expdir, task_id, cycledefs, dcTaskEnv, dependencies)
# end of ioda_cwp --------------------------------------------------------
