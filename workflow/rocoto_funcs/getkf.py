#!/usr/bin/env python
import os
from rocoto_funcs.base import xml_task, get_cascade_env, tok_hm, tok_reftime

# begin of getkf ---------------------------------------------------------------


def getkf(xmlFile, expdir, taskType):
    nocoldda = os.getenv('COLDSTART_CYCS_DO_DA', 'TRUE').upper() == 'FALSE'
    if nocoldda:
        cycledefs = 'da_nocold'
    else:
        cycledefs = 'prod'
    # Task-specific EnVars beyond the task_common_vars
    extrn_mdl_source = os.getenv('IC_EXTRN_MDL_NAME', 'IC_PREFIX_not_defined')
    physics_suite = os.getenv('PHYSICS_SUITE', 'PHYSICS_SUITE_not_defined')
    lsm_scheme = os.getenv('LSM_SCHEME', 'sf_ruc')
    recenter_cycs = os.getenv('RECENTER_CYCS', '99')
    analysis_variables = os.getenv('ANALYSIS_VARIABLES', '0')
    dcTaskEnv = {
        'EXTRN_MDL_SOURCE': f'{extrn_mdl_source}',
        'PHYSICS_SUITE': f'{physics_suite}',
        'LSM_SCHEME': f'{lsm_scheme}',
        'NSOIL_LEVELS': os.getenv('NSOIL_LEVELS', '9'),
        'REFERENCE_TIME': tok_reftime(),
        'DO_RADAR_REF': os.getenv('DO_RADAR_REF', 'FALSE').upper(),
        'YAML_GEN_METHOD': os.getenv('YAML_GEN_METHOD', '1'),
        'COLDSTART_CYCS_DO_DA': os.getenv('COLDSTART_CYCS_DO_DA', 'TRUE').upper(),
        'SAVE_GETKF_ANL': os.getenv('SAVE_GETKF_ANL', 'FALSE').upper(),
        'ENS_SIZE': os.getenv("ENS_SIZE", '5'),
        'GETKF_TYPE': taskType.lower(),
        'USE_CONV_SAT_INFO': os.getenv('USE_CONV_SAT_INFO', 'TRUE').upper(),
        'SAT_USELIST': os.getenv('SAT_USELIST', ''),
        'EMPTY_OBS_SPACE_ACTION': os.getenv('EMPTY_OBS_SPACE_ACTION', 'skip output'),
        'DA_WINDOW_HALF_MIN': os.getenv('DA_WINDOW_HALF_MIN', '120'),
        'MP_SCHEME': os.getenv('MP_SCHEME', ''),
    }
    if taskType.upper() == "OBSERVER":
        task_id = "getkf_observer"
    elif taskType.upper() == "SOLVER":
        task_id = "getkf_solver"
    elif taskType.upper() == "POST":
        task_id = "getkf_post"
    if analysis_variables != '0':
        dcTaskEnv['ANALYSIS_VARIABLES'] = analysis_variables

    # Optional (WoFS reflectivity DA): compute the posterior H(xa) for refl10cm
    # from the forward forecast's t=0 refl10cm (recomputed from the analyzed
    # hydrometeors by init_reflectivity_diagnostic), instead of the LETKF-updated
    # analysis refl10cm.  Only emitted for getkf_post when enabled, so other
    # experiments/tasks regenerate byte-identical XML.
    refl_from_fcst = os.getenv("GETKF_POST_REFL_FROM_FCST", "FALSE").upper() == "TRUE"
    if refl_from_fcst and taskType.upper() == "POST":
        dcTaskEnv['GETKF_POST_REFL_FROM_FCST'] = 'TRUE'

    # Optional per-experiment override of the mpasjedi_enkf.x executable.
    # Only emitted when ENKF_EXEC is set, so other experiments are unchanged.
    enkf_exec = os.getenv('ENKF_EXEC', '')
    if enkf_exec:
        dcTaskEnv['ENKF_EXEC'] = enkf_exec

    dcTaskEnv['KEEPDATA'] = get_cascade_env(f"KEEPDATA_{task_id}".upper()).upper()
    # dependencies
    timedep = ""
    realtime = os.getenv("REALTIME", "false")
    if realtime.upper() == "TRUE":
        starttime = get_cascade_env(f"STARTTIME_{task_id}".upper())
        timedep = f'\n    <timedep><cyclestr offset="{starttime}">@Y@m@d@H@M00</cyclestr></timedep>'
    if taskType.upper() == "OBSERVER":
        if os.getenv("DO_IODA", "FALSE").upper() == "TRUE":
            iodadep = '<taskdep task="ioda_bufr"/>'
            dcTaskEnv['IODA_BUFR_WGF'] = 'enkf'
        else:
            iodadep = f'<datadep age="00:01:00"><cyclestr>&COMROOT;/&NET;/&rrfs_ver;/&RUN;.@Y@m@d/{tok_hm()}/ioda_bufr/det/ioda_aircar.nc</cyclestr></datadep>'
            dcTaskEnv['IODA_BUFR_WGF'] = 'det'

        cwpdep = ""
        if os.getenv("DO_CWP", "FALSE").upper() == "TRUE":
            cwpdep = '\n    <taskdep task="ioda_cwp"/>'

        okmesodep = ""
        if os.getenv("DO_MESONET", "FALSE").upper() == "TRUE":
            okmesodep = '\n    <taskdep task="ioda_okmeso"/>'

        final_recenterdep = ""
        spaces = " " * 4
        if os.getenv("DO_RECENTER", "FALSE").upper() == "TRUE":
            recenterhrs = recenter_cycs.split(' ')
            recenterdep = f'<taskdep task="recenter"/>'
            streqs_rec = "<or>"
            strneqs_rec = "<and>"
            for hr in recenterhrs:
                hr = f"{int(hr):02d}"
                streqs_rec += '\n' + spaces + f'  <streq><left><cyclestr>@H</cyclestr></left><right>{hr}</right></streq>'
                strneqs_rec += '\n' + spaces + f'  <strneq><left><cyclestr>@H</cyclestr></left><right>{hr}</right></strneq>'
            streqs_rec += '\n      </or>'
            strneqs_rec += '\n    </and>'
            final_recenterdep = f'''
    <or>
    {strneqs_rec}
    <and>
      {streqs_rec}
      {recenterdep}
    </and>
    </or>'''

        dependencies = f'''
  <dependency>
  <and>{timedep}
    <taskdep task="prep_ic"/>
    {iodadep}{cwpdep}{okmesodep}{final_recenterdep}
  </and>
  </dependency>'''
    elif taskType.upper() == "SOLVER":
        dependencies = f'''
  <dependency>
  <and>{timedep}
    <taskdep task="getkf_observer"/>
  </and>
  </dependency>'''
    #
    elif taskType.upper() == "POST":
        # Optionally wait for the forward forecasts so the posterior observer can
        # read each member's t=0 refl10cm (recomputed from the analysis).  The
        # fcst metatask dependency tracks all ensemble groups automatically.
        fcstdep = ""
        if refl_from_fcst:
            from rocoto_funcs.smart_ens_groups import smart_ens_groups
            fcstdep = smart_ens_groups('fcst')["combined_dep_xml"]
        dependencies = f'''
  <dependency>
  <and>{timedep}
    <taskdep task="getkf_solver"/>{fcstdep}
  </and>
  </dependency>'''
    #
    xml_task(xmlFile, expdir, task_id, cycledefs, dcTaskEnv=dcTaskEnv, dependencies=dependencies, command_id="GETKF")
# end of getkf -----------------------------------------------------------------
