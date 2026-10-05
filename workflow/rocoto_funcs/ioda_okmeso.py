#!/usr/bin/env python
import os
from rocoto_funcs.base import xml_task, get_cascade_env, obs_file_dependency

# begin of ioda_okmeso --------------------------------------------------------


def ioda_okmeso(xmlFile, expdir):
    task_id = 'ioda_okmeso'
    cycledefs = 'prod'
    if os.getenv("DO_SPINUP", "FALSE").upper() == "TRUE":
        cycledefs = 'prod,spinup'
    OKMESO_DIR = os.getenv("OKMESO_DIR", 'OKMESO_DIR_not_defined')
    OKMESO_LOOKBACK_MIN = os.getenv("OKMESO_LOOKBACK_MIN", '4')
    OKMESO_TIMEOUT_SEC = os.getenv("OKMESO_TIMEOUT_SEC", '300')
    # Task-specific EnVars beyond the task_common_vars
    dcTaskEnv = {
        'OKMESO_DIR': f'{OKMESO_DIR}',
        'OKMESO_LOOKBACK_MIN': f'{OKMESO_LOOKBACK_MIN}',
    }

    dcTaskEnv['KEEPDATA'] = get_cascade_env(f"KEEPDATA_{task_id}".upper()).upper()
    # dependencies: wait for the raw OK Mesonet MDF file (any minute within the
    # lookback window), or give up after OKMESO_TIMEOUT_SEC past the cycle time.
    fpath = f'{OKMESO_DIR}/@Y/@m/@d/mesonet.realtime.@Y@m@d@H@M.mdf'
    dependencies = obs_file_dependency(task_id, fpath, OKMESO_LOOKBACK_MIN, OKMESO_TIMEOUT_SEC)
    #
    xml_task(xmlFile, expdir, task_id, cycledefs, dcTaskEnv, dependencies)
# end of ioda_okmeso --------------------------------------------------------
