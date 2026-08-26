#!/usr/bin/env python
#
import os
import stat
from rocoto_funcs.base import header_begin, header_entities, header_end, \
    wflow_begin, wflow_log, wflow_cycledefs, wflow_end, tok_hm, wofs_windowed
from rocoto_funcs.smart_cycledefs import smart_cycledefs
from rocoto_funcs.smart_post_groups import smart_post_groups
from rocoto_funcs.create_domain import create_domain
from rocoto_funcs.ungrib_ic import ungrib_ic
from rocoto_funcs.ungrib_lbc import ungrib_lbc
from rocoto_funcs.ic import ic
from rocoto_funcs.lbc import lbc
from rocoto_funcs.prep_ic import prep_ic
from rocoto_funcs.prep_lbc import prep_lbc
from rocoto_funcs.mpas_blend import mpas_blend
from rocoto_funcs.jedivar import jedivar
from rocoto_funcs.fcst import fcst
from rocoto_funcs.smart_ens_groups import smart_ens_groups
from rocoto_funcs.save_for_next import save_for_next
from rocoto_funcs.prep_lbc_free import prep_lbc_free
from rocoto_funcs.fcst_free import fcst_free
from rocoto_funcs.mpassit_free import mpassit_free
from rocoto_funcs.getkf import getkf
from rocoto_funcs.recenter import recenter
from rocoto_funcs.ensmean import ensmean
from rocoto_funcs.mpassit import mpassit
from rocoto_funcs.upp import upp
from rocoto_funcs.ioda_airnow import ioda_airnow
from rocoto_funcs.ioda_bufr import ioda_bufr
from rocoto_funcs.ioda_mrms_refl import ioda_mrms_refl
from rocoto_funcs.ioda_cwp import ioda_cwp
from rocoto_funcs.nonvar_bufrobs import nonvar_bufrobs
from rocoto_funcs.nonvar_reflobs import nonvar_reflobs
from rocoto_funcs.nonvar_cldana import nonvar_cldana
from rocoto_funcs.prep_chem import prep_chem
from rocoto_funcs.clean import clean
from rocoto_funcs.graphics import graphics
from rocoto_funcs.misc import misc
from rocoto_funcs.hofx import hofx
from rocoto_funcs.pyDAmonitor import pyDAmonitor
from rocoto_funcs.archive import archive

# setup_xml


def setup_xml(HOMErrfs, expdir):
    NET = os.getenv('NET').lower()
    machine = os.getenv('MACHINE').lower()
    MESH_NAME = os.getenv("MESH_NAME")
    do_deterministic = os.getenv('DO_DETERMINISTIC', 'TRUE').upper()
    do_ensemble = os.getenv('DO_ENSEMBLE', 'FALSE').upper()
    do_ensmean_post = os.getenv('DO_ENSMEAN_POST', 'FALSE').upper()
    do_chemistry = os.getenv('DO_CHEMISTRY', 'FALSE').upper()
    #
    # In WoFS windowed mode the "prod" cycledef is the sub-hourly DA cycle.
    # mpassit/upp on every DA cycle is off by default (DO_DA_POST) so that
    # post-processing is reserved for the free forecasts (Phase 3/4).
    wofs_windowed_mode = os.getenv('EVENT_DATE', '').strip() != ''
    do_post = os.getenv("DO_POST", "TRUE").upper() == "TRUE"
    if wofs_windowed_mode:
        post_da_cycles = do_post and os.getenv("DO_DA_POST", "FALSE").upper() == "TRUE"
    else:
        post_da_cycles = do_post
    #
    # create cycledefs smartly
    dcCycledef = smart_cycledefs()
    # create post groups smartly and update dcCycleDef accordingly
    listPostGrpInfo = []
    if post_da_cycles:
        listPostGrpInfo = smart_post_groups(dcCycledef)

    fPath = f"{expdir}/{NET}.xml"
    with open(fPath, 'w') as xmlFile:
        header_begin(xmlFile)
        header_entities(xmlFile, expdir)
        header_end(xmlFile)
        wflow_begin(xmlFile)
        log_fpath = f'&LOGROOT;/&RUN;.@Y@m@d/{tok_hm()}/&WGF;/&RUN;.log'
        wflow_log(xmlFile, log_fpath)
        wflow_cycledefs(xmlFile, dcCycledef)

# ---------------------------------------------------------------------------
# one-time domain creation (must precede every other task)
        if os.getenv("DO_CREATE_DOMAIN", "FALSE").upper() == "TRUE":
            create_domain(xmlFile, expdir)

# ---------------------------------------------------------------------------
# assemble tasks for a deterministic experiment
        if do_deterministic == "TRUE" and os.getenv("IC_ONLY", "FALSE").upper() == "TRUE":
            ungrib_ic(xmlFile, expdir)
            ic(xmlFile, expdir)
        elif do_deterministic == "TRUE":
            if os.getenv("DO_IODA", "FALSE").upper() == "TRUE":
                if do_chemistry == "TRUE":
                    ioda_airnow(xmlFile, expdir)
                ioda_bufr(xmlFile, expdir)
            if os.getenv("DO_RADAR_REF", "FALSE").upper() == "TRUE" and not wofs_windowed():
                ioda_mrms_refl(xmlFile, expdir)
            if os.getenv("DO_CWP", "FALSE").upper() == "TRUE":
                ioda_cwp(xmlFile, expdir)
            if os.getenv("DO_NONVAR_CLOUD_ANA", "FALSE").upper() == "TRUE":
                nonvar_bufrobs(xmlFile, expdir)
                nonvar_reflobs(xmlFile, expdir)
            #
            if os.getenv("DO_IC_LBC", "TRUE").upper() == "TRUE":
                ungrib_ic(xmlFile, expdir)
                if "global" not in MESH_NAME:
                    ungrib_lbc(xmlFile, expdir)
                ic(xmlFile, expdir)
                if "global" not in MESH_NAME:
                    lbc(xmlFile, expdir)
            #
            if os.getenv("DO_SPINUP", "FALSE").upper() == "TRUE":
                prep_lbc(xmlFile, expdir)
                # spin up line
                prep_ic(xmlFile, expdir, spinup_mode=1)
                jedivar(xmlFile, expdir, spinup_mode=1)
                if os.getenv("DO_NONVAR_CLOUD_ANA", "FALSE").upper() == "TRUE":
                    nonvar_cldana(xmlFile, expdir, spinup_mode=1)
                fcst(xmlFile, expdir, do_spinup=True)
                # prod line
                prep_ic(xmlFile, expdir, spinup_mode=-1)
                jedivar(xmlFile, expdir, spinup_mode=-1)
                if os.getenv("DO_NONVAR_CLOUD_ANA", "FALSE").upper() == "TRUE":
                    nonvar_cldana(xmlFile, expdir, spinup_mode=-1)
                fcst(xmlFile, expdir)
                save_for_next(xmlFile, expdir)
            elif os.getenv("DO_FCST", "TRUE").upper() == "TRUE":
                prep_ic(xmlFile, expdir)
                if "global" not in MESH_NAME:
                    prep_lbc(xmlFile, expdir)
                if do_chemistry == "TRUE":
                    prep_chem(xmlFile, expdir)
                if os.getenv("DO_BLENDING", "FALSE").upper() == "TRUE":
                    mpas_blend(xmlFile, expdir)
                if os.getenv("DO_JEDI", "FALSE").upper() == "TRUE":
                    jedivar(xmlFile, expdir)
                if os.getenv("DO_NONVAR_CLOUD_ANA", "FALSE").upper() == "TRUE":
                    nonvar_cldana(xmlFile, expdir)
                if os.getenv("DO_PYDAMONITOR", "FALSE").upper() == "TRUE":
                    pyDAmonitor(xmlFile, expdir)
                fcst(xmlFile, expdir)
                if os.getenv('DO_CYC', 'FALSE').upper() == "TRUE" and os.getenv('DO_RTMA', 'FALSE').upper() == 'FALSE':
                    save_for_next(xmlFile, expdir)
            #
            if post_da_cycles:
                for index, dcGrpInfo in enumerate(listPostGrpInfo):
                    mpassit(xmlFile, expdir, index, dcGrpInfo)
                    upp(xmlFile, expdir, index, dcGrpInfo)
            if os.getenv("DO_GRAPHICS", 'FALSE').upper() == "TRUE":
                graphics(xmlFile, expdir)
                if not os.path.exists(f"{HOMErrfs}/workflow/sideload/pygraf"):
                    print("  *** DO_GRAPHICS=true but pygraf not cloned yet!!! ***\n  run `tools/clone_pygraf.sh` first\n")
            if os.getenv("DO_HOFX", "FALSE").upper() == "TRUE":
                hofx(xmlFile, expdir)
            if os.getenv("DO_ARCHIVE", "FALSE").upper() == "TRUE":
                archive(xmlFile, expdir)

# ---------------------------------------------------------------------------
# assemble tasks for an ensemble experiment
        if do_ensemble == "TRUE" and os.getenv("IC_ONLY", "FALSE").upper() == "TRUE":
            ungrib_ic(xmlFile, expdir, do_ensemble=True)
            ic(xmlFile, expdir, do_ensemble=True)
        elif do_ensemble == "TRUE":
            if os.getenv("DO_IODA", "FALSE").upper() == "TRUE":
                if do_chemistry == "TRUE":
                    ioda_airnow(xmlFile, expdir)
                ioda_bufr(xmlFile, expdir)
            if os.getenv("DO_RADAR_REF", "FALSE").upper() == "TRUE" and not wofs_windowed():
                ioda_mrms_refl(xmlFile, expdir)
            if os.getenv("DO_CWP", "FALSE").upper() == "TRUE":
                ioda_cwp(xmlFile, expdir)
            if os.getenv("DO_NONVAR_CLOUD_ANA", "FALSE").upper() == "TRUE":
                nonvar_bufrobs(xmlFile, expdir)
                nonvar_reflobs(xmlFile, expdir)
            ungrib_ic(xmlFile, expdir, do_ensemble=True)
            if "global" not in MESH_NAME:
                ungrib_lbc(xmlFile, expdir, do_ensemble=True)
            ic(xmlFile, expdir, do_ensemble=True)
            if "global" not in MESH_NAME:
                lbc(xmlFile, expdir, do_ensemble=True)
            prep_ic(xmlFile, expdir, do_ensemble=True)
            if "global" not in MESH_NAME:
                prep_lbc(xmlFile, expdir, do_ensemble=True)
            if os.getenv("DO_RECENTER", "FALSE").upper() == "TRUE":
                recenter(xmlFile, expdir)
            if os.getenv("DO_JEDI", "FALSE").upper() == "TRUE":
                getkf(xmlFile, expdir, 'OBSERVER')
                getkf(xmlFile, expdir, 'SOLVER')
                if os.getenv("DO_GETKF_POST", "TRUE").upper() == "TRUE":
                    getkf(xmlFile, expdir, 'POST')
            if os.getenv("DO_NONVAR_CLOUD_ANA", "FALSE").upper() == "TRUE":
                nonvar_cldana(xmlFile, expdir, do_ensemble=True)
            if os.getenv("DO_PYDAMONITOR", "FALSE").upper() == "TRUE":
                pyDAmonitor(xmlFile, expdir)
            listEnsGrpInfo = smart_ens_groups('fcst')
            for dcEnsGrpInfo in listEnsGrpInfo["group_list"]:
                fcst(xmlFile, expdir, do_ensemble=True, dcEnsGrpInfo=dcEnsGrpInfo)
            if os.getenv('DO_CYC', 'FALSE').upper() == "TRUE":
                save_for_next(xmlFile, expdir, do_ensemble=True)
            # WoFS windowed mode: hourly free (non-DA) forecasts launched from
            # the DA analysis, with their own free-forecast LBC staging task.
            if wofs_windowed() and "global" not in MESH_NAME:
                prep_lbc_free(xmlFile, expdir)
                free_members = int(os.getenv('FREE_FCST_MEMBERS', os.getenv('ENS_SIZE', '2')))
                listFreeGrpInfo = smart_ens_groups('fcst_free', ens_size=free_members)
                for dcEnsGrpInfo in listFreeGrpInfo["group_list"]:
                    fcst_free(xmlFile, expdir, dcEnsGrpInfo=dcEnsGrpInfo)
                # Phase 4: post-process the free forecasts with MPASSIT only
                if os.getenv('DO_FREE_POST', 'TRUE').upper() == "TRUE":
                    listFreePostGrpInfo = smart_ens_groups('mpassit_free', ens_size=free_members)
                    for dcEnsGrpInfo in listFreePostGrpInfo["group_list"]:
                        mpassit_free(xmlFile, expdir, dcEnsGrpInfo=dcEnsGrpInfo)
            if post_da_cycles:
                for index, dcGrpInfo in enumerate(listPostGrpInfo):
                    mpassit(xmlFile, expdir, index, dcGrpInfo, do_ensemble=True)
                    upp(xmlFile, expdir, index, dcGrpInfo, do_ensemble=True)
            if do_ensmean_post == "TRUE":
                fcst_dep = listEnsGrpInfo["combined_dep_xml"]
                ensmean(xmlFile, fcst_dep, expdir)
                for index, dcGrpInfo in enumerate(listPostGrpInfo):
                    mpassit(xmlFile, expdir, index, dcGrpInfo, do_ensemble=True, do_ensmean_post=True)
                    upp(xmlFile, expdir, index, dcGrpInfo, do_ensemble=True, do_ensmean_post=True)

# ---------------------------------------------------------------------------
        if os.getenv("DO_CLEAN", 'FALSE').upper() == "TRUE":  # write out the clean task if needed, usually for realtime runs
            clean(xmlFile, expdir)
        if os.getenv("DO_MISC", 'FALSE').upper() == "TRUE":
            misc(xmlFile, expdir)
        #
        wflow_end(xmlFile)
# ---------------------------------------------------------------------------

    fPath = f"{expdir}/run_rocoto.sh"
    extra = ""
    if machine in ['orion']:
        extra = "\nmodule use /work/noaa/zrtrr/gge/rocoto/modulefiles"
    elif machine in ['hercules']:
        extra = "\nmodule use /work/noaa/zrtrr/gge/hercules/rocoto/modulefiles"
    elif machine in ['gaeac6']:
        extra = "\nmodule use /gpfs/f6/arfs-gsl/world-shared/gge/rocoto/modulefiles"
    elif machine in ['ursa']:
        extra = "\nmodule use /scratch4/BMC/zrtrr/gge/rocoto/modulefiles"
    elif machine in ['hera']:
        extra = "\nmodule use /scratch4/BMC/zrtrr/gge/rocoto_hera/modulefiles"
    elif machine in ['jet']:
        extra = "\nmodule use /lfs5/BMC/nrtrr/gge/rocoto/modulefiles"
    elif machine in ['wcoss2']:
        extra = "\nmodule use /apps/ops/test/nco/modulefiles/core"
    elif machine in ['derecho']:
        extra = "\nsource /etc/profile.d/z00_modules.sh\nmodule use /glade/work/geguo/rocoto/modulefiles"
    with open(fPath, 'w') as rocotoFile:
        text = \
            f'''#!/usr/bin/env bash
## Example crontab entry (use "crontab -e" to modify crontab):
## */5 * * * * {fPath}

source /etc/profile{extra}
module load rocoto/1.3.7g
cd {expdir}
rocotorun -w {NET}.xml -d {NET}.db
'''
        rocotoFile.write(text)

    # set run_rocoto.sh to be executable
    st = os.stat(fPath)
    os.chmod(fPath, st.st_mode | stat.S_IEXEC)

    print(f'{NET}.xml and run_rocoto.sh created at:\n  {expdir}')
# end of setup_xml
