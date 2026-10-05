#!/usr/bin/env python
import os
from rocoto_funcs.base import xml_task, get_cascade_env, obs_file_dependency

# begin of ioda_cwp --------------------------------------------------------


def ioda_cwp(xmlFile, expdir):
    task_id = 'ioda_cwp'
    cycledefs = 'prod'
    if os.getenv("DO_SPINUP", "FALSE").upper() == "TRUE":
        cycledefs = 'prod,spinup'
    OBS_CWP_DIR = os.getenv("OBS_CWP_DIR", 'OBS_CWP_DIR_not_defined')
    CWP_LOOKBACK_MIN = os.getenv("CWP_LOOKBACK_MIN", '4')
    CWP_TIMEOUT_SEC = os.getenv("CWP_TIMEOUT_SEC", '300')
    # Task-specific EnVars beyond the task_common_vars
    dcTaskEnv = {
        'OBS_CWP_DIR': f'{OBS_CWP_DIR}',
        'CWP_LOOKBACK_MIN': f'{CWP_LOOKBACK_MIN}',
    }

    dcTaskEnv['KEEPDATA'] = get_cascade_env(f"KEEPDATA_{task_id}".upper()).upper()
    # dependencies: wait for the raw GOES CWP file (any minute within the
    # lookback window), or give up after CWP_TIMEOUT_SEC past the cycle time.
    fpath = f'{OBS_CWP_DIR}/@Y@m@d/@Y@m@d@H@M_GOES19_CWP_OBS.nc'
    dependencies = obs_file_dependency(task_id, fpath, CWP_LOOKBACK_MIN, CWP_TIMEOUT_SEC)
    #
    xml_task(xmlFile, expdir, task_id, cycledefs, dcTaskEnv, dependencies)
# end of ioda_cwp --------------------------------------------------------
