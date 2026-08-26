#!/usr/bin/env python
import os
from rocoto_funcs.base import xml_task, get_cascade_env

# begin of create_domain ----------------------------------------------------
#
# One-time (non-cycled) task that builds the MPAS mesh for the experiment:
#   1) project_hexes  -> <mesh>.grid.nc + <mesh>.graph.info
#   2) gpmetis        -> <mesh>.graph.info.part.N (for each DOMAIN_GRAPH_PARTS)
#   3) init_atmosphere-> <mesh>.static.nc + <mesh>.ugwp_oro_data.nc
# The products are installed under ${FIXrrfs}/${MESH_NAME}/ so that the regular
# ic/lbc/fcst tasks find them exactly where they expect the fix mesh files.
# The task runs on the single-cycle 'domain' cycledef (see smart_cycledefs.py).


def create_domain(xmlFile, expdir):
    task_id = 'create_domain'
    cycledefs = 'domain'
    # Task-specific EnVars beyond the task_common_vars
    dcTaskEnv = {
        'DOMAIN_CEN_LAT': os.getenv('DOMAIN_CEN_LAT', 'DOMAIN_CEN_LAT_not_defined'),
        'DOMAIN_CEN_LON': os.getenv('DOMAIN_CEN_LON', 'DOMAIN_CEN_LON_not_defined'),
        'DOMAIN_SIZE_KM': os.getenv('DOMAIN_SIZE_KM', '900'),
        'DOMAIN_DX_KM': os.getenv('DOMAIN_DX_KM', '3'),
        'DOMAIN_STD_PAR1': os.getenv('DOMAIN_STD_PAR1', '30.0'),
        'DOMAIN_STD_PAR2': os.getenv('DOMAIN_STD_PAR2', '60.0'),
        'DOMAIN_EARTH_RADIUS_KM': os.getenv('DOMAIN_EARTH_RADIUS_KM', '6378.14'),
        'DOMAIN_STATIC_NTASKS': os.getenv('DOMAIN_STATIC_NTASKS', '96'),
        'DOMAIN_GRAPH_PARTS': os.getenv('DOMAIN_GRAPH_PARTS', '96'),
        'DOMAIN_GEOG_DATA_PATH': os.getenv('DOMAIN_GEOG_DATA_PATH', 'DOMAIN_GEOG_DATA_PATH_not_defined'),
        'GPMETIS': os.getenv('GPMETIS', 'gpmetis'),
        'DOMAIN_PROJECT_MODULE_USE': os.getenv('DOMAIN_PROJECT_MODULE_USE', ''),
        'DOMAIN_PROJECT_MODULE': os.getenv('DOMAIN_PROJECT_MODULE', ''),
        # Invariant stage (optional): ungribs an external GRIB2 record and runs
        # init_atmosphere with met interpolation to build
        # <mesh>.invariant.nc_L<nlevel>_<prefix> for the JEDI/fcst/MPASSIT tasks.
        'DO_DOMAIN_INVARIANT': os.getenv('DO_DOMAIN_INVARIANT', 'false'),
        'DOMAIN_INVARIANT_PREFIX': os.getenv('DOMAIN_INVARIANT_PREFIX', 'RRFSv2X'),
        'DOMAIN_INVARIANT_GRIB2': os.getenv('DOMAIN_INVARIANT_GRIB2', ''),
        'DOMAIN_INVARIANT_VTABLE': os.getenv('DOMAIN_INVARIANT_VTABLE', 'RRFSv2X'),
        'DOMAIN_INVARIANT_TIME': os.getenv('DOMAIN_INVARIANT_TIME', ''),
        'DOMAIN_INVARIANT_FG_INTERVAL': os.getenv('DOMAIN_INVARIANT_FG_INTERVAL', '3600'),
        'DOMAIN_INVARIANT_NFGLEVELS': os.getenv('DOMAIN_INVARIANT_NFGLEVELS', '66'),
        'DOMAIN_INVARIANT_NFGSOILLEVELS': os.getenv('DOMAIN_INVARIANT_NFGSOILLEVELS', '9'),
        'DOMAIN_INVARIANT_LINK_PREFIXES': os.getenv('DOMAIN_INVARIANT_LINK_PREFIXES', ''),
        'NSOIL_LEVELS': os.getenv('NSOIL_LEVELS', '9'),
    }

    dcTaskEnv['KEEPDATA'] = get_cascade_env(f"KEEPDATA_{task_id}".upper()).upper()
    # dependencies: none -- create_domain is the very first task in the workflow
    dependencies = ' '
    #
    xml_task(xmlFile, expdir, task_id, cycledefs, dcTaskEnv, dependencies)
# end of create_domain ------------------------------------------------------
