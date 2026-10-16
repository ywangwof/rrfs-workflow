#!/usr/bin/env python
import subprocess
import os
import calendar
from datetime import datetime
from dateutil.relativedelta import relativedelta


# --- WoFS windowed sub-hourly cycling helpers (Phase 1) --------------------
# DO_WOFS is the master switch (config.base default FALSE).  When it is TRUE the
# workflow runs in "WoFS windowed" mode and every per-cycle path/label token must
# carry minute resolution (@H@M) so that sub-hourly cycles do not collide.  When
# DO_WOFS is FALSE these helpers return the exact legacy tokens, keeping existing
# experiments byte-identical.  EVENT_DATE remains the event date *value* (YYYYmmdd).
def wofs_windowed():
    return os.getenv('DO_WOFS', 'FALSE').upper() == 'TRUE'


def tok_hm():
    """Cycle hour(+minute) token used in directory names and labels."""
    return '@H@M' if wofs_windowed() else '@H'


def tok_cdate():
    """CDATE token (analysis time)."""
    return '@Y@m@d@H@M' if wofs_windowed() else '@Y@m@d@H'


def tok_reftime():
    """JEDI/obs REFERENCE_TIME token."""
    return '@Y-@m-@dT@H:@M:00Z' if wofs_windowed() else '@Y-@m-@dT@H:00:00Z'


def min_to_offset(total_min):
    """Minutes -> Rocoto '[-]H:MM:SS' style offset magnitude (no sign)."""
    total_min = int(total_min)
    return f'{total_min // 60}:{total_min % 60:02d}:00'


def sec_to_offset(total_sec):
    """Seconds -> Rocoto 'H:MM:SS' style offset magnitude (no sign)."""
    total_sec = int(total_sec)
    return f'{total_sec // 3600}:{(total_sec % 3600) // 60:02d}:{total_sec % 60:02d}'


def obs_file_dependency(task_id, fpath, lookback_min, timeout_sec, age="00:00:30"):
    """Rocoto dependency that waits for a raw obs file, with a timeout fallback.

    The task becomes ready as soon as a file matching `fpath` (a cyclestr
    template) exists for any minute from the cycle time back to `lookback_min`
    minutes earlier (mirroring the ex-script search), or once the wall clock
    passes cycle time + `timeout_sec`, whichever comes first.  On timeout the
    ex-script finds no file and skips gracefully, so the DA is never blocked.
    In realtime mode the task additionally honors STARTTIME_<TASK>.
    """
    datadeps = ''
    for j in range(int(lookback_min) + 1):
        offset = f' offset="-{min_to_offset(j)}"' if j > 0 else ''
        datadeps += f'\n      <datadep age="{age}"><cyclestr{offset}>{fpath}</cyclestr></datadep>'
    timeoutdep = f'\n      <timedep><cyclestr offset="{sec_to_offset(timeout_sec)}">@Y@m@d@H@M00</cyclestr></timedep>'

    starttimedep = ''
    if os.getenv("REALTIME", "false").upper() == "TRUE":
        starttime = get_cascade_env(f"STARTTIME_{task_id}".upper())
        starttimedep = f'\n    <timedep><cyclestr offset="{starttime}">@Y@m@d@H@M00</cyclestr></timedep>'

    return f'''
  <dependency>
  <and>{starttimedep}
    <or>{datadeps}{timeoutdep}
    </or>
  </and>
  </dependency>'''


def mesh_dir():
    """Directory holding the experiment mesh files (<mesh>.static.nc, etc.).

    In WoFS windowed mode create_domain writes the mesh into a per-event
    directory under COM (see MESHrrfs in task_common_vars); otherwise it falls
    back to the shared ${FIXrrfs}/${MESH_NAME}. This mirrors the runtime
    ${MESHrrfs:-${FIXrrfs}/${MESH_NAME}} used by the job scripts so the rocoto
    datadeps gate on the same location create_domain actually produces.
    """
    mesh = os.getenv('MESH_NAME', '')
    if wofs_windowed():
        net = os.getenv('NET', 'rrfs')
        run = net  # so far, RUN = NET
        rrfs_ver = os.getenv('VERSION', 'v2.0.0')
        event_date = os.getenv('EVENT_DATE', '').strip()
        return f'&COMROOT;/{net}/{rrfs_ver}/{run}.{event_date}/domain/{mesh}'
    return f'&HOMErrfs;/fix/{mesh}'


def source(bash_file, optional=False):
    """
    Source a Bash file and capture the environment variables
    """
    # check if bash_file exists
    command = f"source {bash_file} && env"
    proc = subprocess.Popen(
        ['bash', '-c', command],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True
    )
    stdout, stderr = proc.communicate()
    if proc.returncode != 0:
        if optional:
            return  # do nothing for optional config files
        else:
            raise Exception(f"Error sourcing bash file: {stderr}")
    env_vars = {}
    for line in stdout.splitlines():
        key, _, value = line.partition("=")
        env_vars[key] = value
    # Update the current environment
    os.environ.update(env_vars)
# end of source(bash_file)

# run_git_command


def run_git_command(cmd):
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if result.returncode == 0:
        return result.stdout.strip()
    else:
        raise RuntimeError(f"Git command failed: {' '.join(cmd)}\n{result.stderr.strip()}")

# head_begin


def header_begin(xmlFile):
    text = """<?xml version="1.0"?>
<!DOCTYPE wflow [
"""
    xmlFile.write(text)

# header_entities_


def header_entities(xmlFile, expdir):
    MACHINE = os.getenv('MACHINE', 'MACHINE_not_defined')
    HOMErrfs = os.getenv('HOMErrfs', 'HOMErrfs_not_defined')
    DATAROOT = os.getenv('DATAROOT', 'DATAROOT_not_defined')
    COMROOT = os.getenv('COMROOT', 'COMROOT_not_defined')
    net = os.getenv('NET', 'rrfs')
    run = os.getenv('NET', 'rrfs')  # so far, RUN = NET
    rrfs_ver = os.getenv('VERSION', 'v2.0.0')
    account = os.getenv('ACCOUNT', 'wrfruc')
    queue = os.getenv('QUEUE', 'batch')
    partition = os.getenv('PARTITION', 'hera')
    reservation = os.getenv('RESERVATION', '')
    mesh_name = os.getenv('MESH_NAME', 'na3km')
    mpi_run_cmd = os.getenv('MPI_RUN_CMD', 'srun')
    wgf = os.getenv('WGF', 'det')
    cyc_interval = os.getenv('CYC_INTERVAL', '3')
    realtime = os.getenv("REALTIME", "false").upper()
    # WoFS windowed mode -> minute-aware per-cycle tokens (byte-identical when off)
    hm = tok_hm()
    cdate_fmt = tok_cdate()
    if wofs_windowed():
        subcyc_envar = '\n<envar><name>subcyc</name><value><cyclestr>@M</cyclestr></value></envar>'
        # WoFS DA-cycle knobs consumed by the job scripts (fcst, prep_lbc, ...)
        # at runtime.  The jobs do not source the experiment config, so these
        # must be carried explicitly in task_common_vars.
        event_date = os.getenv('EVENT_DATE', '').strip()
        da_interval = os.getenv('DA_INTERVAL', '15').strip()
        # The DA-cycle first-guess forecast spans exactly one DA_INTERVAL, so the
        # forecast length (DA_FCST_SECONDS, consumed by the job scripts) is derived
        # directly from DA_INTERVAL - the single source of truth for the cadence.
        da_fcst_seconds = f'{int(da_interval) * 60}'
        extinvl_hrs = os.getenv('EXTINVL_HRS', '1').strip()
        mrms_all_dir = os.getenv('MRMS_ALL_DIR', '').strip()
        mrms_clear_dir = os.getenv('MRMS_CLEAR_DIR', '').strip()
        vr_dir = os.getenv('VR_DIR', '').strip()
        obs_cwp_dir = os.getenv('OBS_CWP_DIR', '').strip()
        okmeso_dir = os.getenv('OKMESO_DIR', '').strip()
        # copy_obs.sh stages okmeso obs whenever OKMESO_DIR is set, so blank it
        # unless DO_MESONET is on.
        if os.getenv('DO_MESONET', 'FALSE').upper() != 'TRUE':
            okmeso_dir = ''
        # Per-event domain directory under COM (Approach A): each WoFS case has
        # its own mesh, so create_domain writes here and every downstream task
        # reads the mesh from here instead of the shared ${FIXrrfs}/${MESH_NAME}.
        # Anchored on EVENT_DATE (not the cycle) so all cycles of the event -
        # including post-midnight ones - resolve the same domain.
        mesh_rrfs = f'&COMROOT;/{net}/{rrfs_ver}/{run}.{event_date}/domain/{mesh_name}'
        wofs_envar = (
            f'\n<envar><name>EVENT_DATE</name><value>{event_date}</value></envar>'
            f'\n<envar><name>DA_INTERVAL</name><value>{da_interval}</value></envar>'
            f'\n<envar><name>DA_FCST_SECONDS</name><value>{da_fcst_seconds}</value></envar>'
            f'\n<envar><name>EXTINVL_HRS</name><value>{extinvl_hrs}</value></envar>'
            f'\n<envar><name>MRMS_ALL_DIR</name><value>{mrms_all_dir}</value></envar>'
            f'\n<envar><name>MRMS_CLEAR_DIR</name><value>{mrms_clear_dir}</value></envar>'
            f'\n<envar><name>VR_DIR</name><value>{vr_dir}</value></envar>'
            f'\n<envar><name>OBS_CWP_DIR</name><value>{obs_cwp_dir}</value></envar>'
            f'\n<envar><name>OKMESO_DIR</name><value>{okmeso_dir}</value></envar>'
            f'\n<envar><name>MESHrrfs</name><value>{mesh_rrfs}</value></envar>'
        )
    else:
        subcyc_envar = ''
        wofs_envar = ''

    if os.getenv('DO_WOFS', 'FALSE').upper() == "TRUE":
        wofs_switch_envar = "\n<envar><name>DO_WOFS</name><value>TRUE</value></envar>"
    else:
        wofs_switch_envar = ""

    if os.getenv('DO_CHEMISTRY', 'FALSE').upper() == "TRUE":
        chem_envar = "\n<envar><name>DO_CHEMISTRY</name><value>TRUE</value></envar>"
    else:
        chem_envar = ""
# figure out run period for realtime experiments
    if realtime == 'TRUE':
        now = datetime.now()
        end = now + relativedelta(months=1)  # each realtime deployment, set current month and next month
        startyear = f'''{now.year:04}'''
        startmonth = f'''{now.month:02}'''
        startday = f'''{now.day:02}'''

        endyear = f'''{end.year:04}'''
        endmonth = f'''{end.month:02}'''
        endday = f'''{calendar.monthrange(end.year,end.month)[1]:02}'''  # find the last day of a calendar month
        entities_for_cycledef = f'''\n
<!ENTITY Y1 "{startyear}">
<!ENTITY M1 "{startmonth}">
<!ENTITY D1 "{startday}">

<!ENTITY Y2 "{endyear}">
<!ENTITY M2 "{endmonth}">
<!ENTITY D2 "{endday}">'''
    else:  # retros
        entities_for_cycledef = ''
    #
    if os.getenv('MORE_XML_ENTITIES', 'false').upper() == 'TRUE':
        text = f'''
<!ENTITY ACCOUNT         "{account}">
<!ENTITY QUEUE_DEFAULT   "{queue}">
<!ENTITY PARTITION       "{partition}">
'''
        if reservation != '':
            text = text + f'<!ENTITY RESERVATION     "--reservation={reservation}">\n'
    else:
        text = ''
    #
    text = text + f'''
<!ENTITY MACHINE         "{MACHINE}">
<!ENTITY HOMErrfs        "{HOMErrfs}">
<!ENTITY EXPDIR          "{expdir}">
<!ENTITY DATAROOT        "{DATAROOT}">
<!ENTITY COMROOT         "{COMROOT}">
<!ENTITY LOGROOT         "{COMROOT}/{net}/{rrfs_ver}/logs">

<!ENTITY RUN             "{run}">
<!ENTITY NET             "{net}">
<!ENTITY rrfs_ver        "{rrfs_ver}">
<!ENTITY WGF             "{wgf}">

<!ENTITY task_common_vars
"
<envar><name>MACHINE</name><value>&MACHINE;</value></envar>
<envar><name>HOMErrfs</name><value>&HOMErrfs;</value></envar>
<envar><name>EXPDIR</name><value>&EXPDIR;</value></envar>
<envar><name>COMROOT</name><value>&COMROOT;</value></envar>
<envar><name>DATAROOT</name><value><cyclestr>&DATAROOT;/@Y@m@d</cyclestr></value></envar>
<envar><name>COMINrrfs</name><value>&COMROOT;/{net}/{rrfs_ver}</value></envar>
<envar><name>COMOUT</name><value><cyclestr>&COMROOT;/{net}/{rrfs_ver}/{run}.@Y@m@d/{hm}</cyclestr></value></envar>
<envar><name>CDATE</name><value><cyclestr>{cdate_fmt}</cyclestr></value></envar>
<envar><name>PDY</name><value><cyclestr>@Y@m@d</cyclestr></value></envar>
<envar><name>cyc</name><value><cyclestr>{hm}</cyclestr></value></envar>{subcyc_envar}
<envar><name>NET</name><value>{net}</value></envar>
<envar><name>RUN</name><value>{run}</value></envar>
<envar><name>rrfs_ver</name><value>{rrfs_ver}</value></envar>
<envar><name>MPI_RUN_CMD</name><value>{mpi_run_cmd}</value></envar>
<envar><name>MESH_NAME</name><value>{mesh_name}</value></envar>
<envar><name>WGF</name><value>{wgf}</value></envar>
<envar><name>CYC_INTERVAL</name><value>{cyc_interval}</value></envar>{wofs_switch_envar}{chem_envar}{wofs_envar}
"
>{entities_for_cycledef}
'''
    xmlFile.write(text)

# header_end


def header_end(xmlFile):
    text = "]>\n"
    xmlFile.write(text)

# wflow_begin


def wflow_begin(xmlFile):
    realtime = os.getenv("REALTIME", "false").upper()
    cyclethrottle = os.getenv("CYCLETHROTTLE", "3")
    taskthrottle = os.getenv("TASKTHROTTLE", "30")
    cyclelifespan = os.getenv("CYCLELIFESPAN", "2")
    machine = os.getenv('MACHINE').lower()
    if machine in ['wcoss2', 'derecho']:
        scheduler = 'pbspro'
    else:
        scheduler = 'slurm'
    if realtime == "TRUE":
        text = f'<workflow realtime="T" scheduler="{scheduler}" cyclethrottle="{cyclethrottle}" cyclelifespan="{cyclelifespan}:00:00:00">'
    else:
        text = f'<workflow realtime="F" scheduler="{scheduler}" cyclethrottle="{cyclethrottle}" taskthrottle="{taskthrottle}">'
    xmlFile.write(f'\n{text}\n')

# wflow_end


def wflow_end(xmlFile):
    xmlFile.write('\n</workflow>\n')

# wflow_log


def wflow_log(xmlFile, log_fpath):
    text = f'  <log verbosity="10"><cyclestr>{log_fpath}</cyclestr></log>'
    xmlFile.write(f'{text}\n')

# wflow_cycledefs


def wflow_cycledefs(xmlFile, dcCycledef):
    text = ""
    for key, value in dcCycledef.items():
        if isinstance(value, dict):  # a dictionary value containing "valid_hours" or "exclude_hours"
            if "valid_hours" in value:
                valid_hours = value["valid_hours"]
                mycycledef = value["cycledef"]
                text = text + f'\n  <cycledef group="{key}" valid_hours="{valid_hours}">{mycycledef}</cycledef>'
            else:
                exclude_hours = value["exclude_hours"]
                mycycledef = value["cycledef"]
                text = text + f'\n  <cycledef group="{key}" exclude_hours="{exclude_hours}">{mycycledef}</cycledef>'
        else:
            text = text + f'\n  <cycledef group="{key}">{value}</cycledef>'
    xmlFile.write(f'{text}\n')

# objTask


class objTask:
    def __init__(self, task_id, cycledefs, maxtries, dcTaskRes, realtime=False, deadline="", dcTaskEnv={}, dependencies=""):
        self.task_id = task_id
        self.cycledefs = cycledefs
        self.maxtries = maxtries
        self.dcTaskRes = dcTaskRes
        self.realtime = realtime
        self.deadline = deadline
        self.dcTaskEnv = dcTaskEnv
        self.dependencies = dependencies

    def wflow_task_divider(self, xmlFile):
        text = f'\n<!--\n'
        text = text + f'************************************************************************************\n'
        text = text + f'************************************************************************************'
        text = text + f'\n-->\n'
        xmlFile.write(text)

    def wflow_task_begin(self, xmlFile):
        text = f'\n<task name="{self.task_id}" cycledefs="{self.cycledefs}" maxtries="{self.maxtries}">\n'
        xmlFile.write(text)

    def wflow_task_part1(self, xmlFile):  # write out part1 which excludes dependencies
        text = f'  <command>{self.dcTaskRes["command"]}</command>\n'
        text = text + f'  <join><cyclestr>{self.dcTaskRes["join"]}</cyclestr></join>\n'
        text = text + f'\n  <jobname><cyclestr>{self.dcTaskRes["jobname"]}</cyclestr></jobname>\n'
        if os.getenv('MORE_XML_ENTITIES', 'false').upper() == 'TRUE':
            text = text + f'  <account>&ACCOUNT;</account>\n'
            text = text + f'  <queue>&QUEUE_DEFAULT;</queue>\n'
            if self.dcTaskRes["partition"] != "":
                text = text + f'  <partition>&PARTITION;</partition>\n'
        else:
            text = text + f'  <account>{self.dcTaskRes["account"]}</account>\n'
            text = text + f'  <queue>{self.dcTaskRes["queue"]}</queue>\n'
            if self.dcTaskRes["partition"] != "":
                text = text + f'  <partition>{self.dcTaskRes["partition"]}</partition>\n'
        text = text + f'  <walltime>{self.dcTaskRes["walltime"]}</walltime>\n'
        text = text + f'  {self.dcTaskRes["nodes"]}\n'  # note: xml tag self included, no need to add <nodes> </nodes>
        #
        native_text = ''
        if self.dcTaskRes["reservation"] != "":
            if os.getenv('MORE_XML_ENTITIES', 'false').upper() == 'TRUE':
                native_text = native_text + f'&RESERVATION; '
            else:
                native_text = native_text + f'--reservation={self.dcTaskRes["reservation"]} '
        if self.dcTaskRes["cluster"] != "":
            native_text = native_text + f'--cluster={self.dcTaskRes["cluster"]} '
        if self.dcTaskRes["native"] != "":
            native_text = native_text + self.dcTaskRes["native"]
        if native_text != "":
            text = text + f'  <native>{native_text.strip()}</native>\n'
        #
        if self.realtime:
            text = text + f'  <deadline><cyclestr offset="{self.deadline}">@Y@m@d@H@M</cyclestr></deadline>\n'
        #
        text = text + "  &task_common_vars;\n"  # add an empty line before the <envar> block for readability
        for key, value in self.dcTaskEnv.items():
            text = text + f'  <envar><name>{key}</name><value>{value}</value></envar>\n'
        xmlFile.write(text)

    def wflow_task_end(self, xmlFile):
        xmlFile.write("</task>\n")

    def wflow_task_dependencies(self, xmlFile):
        xmlFile.write(f"{self.dependencies}\n")
# end of objTask

# get_required_env


def get_required_env(env_name):
    env_value = os.getenv(env_name)
    if env_value is None:
        print(f'env variable "{env_name}" not found')
        exit()
    else:
        return env_value

# get_cascade_env


def get_cascade_env(env_name):
    seperator = "_"  # underscore
    revStr = env_name[::-1]  # reverse the string
    env_value = os.getenv(env_name)
    if env_value is not None:
        return env_value

    while seperator in revStr:
        ra, rb = revStr.split(seperator, 1)  # only split once
        new_name = rb[::-1]
        env_value = os.getenv(new_name)
        if env_value is not None:
            return env_value
        else:
            revStr = rb

    # if no env variable is defined in the cascasde
    return f'the cascade env {env_name} not defined'
# end of get_cascade_env(env_name)

# get_yes_or_no


def get_yes_or_no(prompt):
    while True:
        user_input = input(prompt).strip().lower()
        if user_input in ['yes', 'no', 'y', 'n']:
            return user_input
        else:
            print("Please enter 'yes','y','no',or 'n'.")
# end of get_yes_or_no

# xml_task


def xml_task(
        xmlFile, expdir, task_id, cycledefs, dcTaskEnv={}, dependencies="",
        metatask=False, meta_id='', meta_bgn="", meta_end="", command_id=""):
    # for non-meta tasks, task_id=meta_id; for meta tasks, task_id=${meta_id}_xxx
    # metatask is a group of tasks who share a very similar functionality
    #     at the same cycle, for example, post_f01, post_f02, ensembles, etc
    WGF = os.getenv('WGF', 'WGF_not_defined')
    TAG = os.getenv('TAG', 'TAG_not_defined')
    RUN = os.getenv('NET', 'RUN_not_defined')  # so far, RUN = NET
    realtime = os.getenv('REALTIME', 'false')
    deadline = get_cascade_env(f'DEADLINE_{task_id}'.upper())
    if metatask is False:
        meta_id = task_id
    if command_id == "":
        command_id = meta_id
    dcTaskRes = {
        'command': f'&HOMErrfs;/workflow/sideload/launch.sh JRRFS_' + f'{command_id}'.upper(),
        'join': f'&LOGROOT;/{RUN}.@Y@m@d/{tok_hm()}/{WGF}/{RUN}_{task_id}_{TAG}_{tok_cdate()}.log',
        'jobname': f'{TAG}_{task_id}_c{tok_hm()}',
        'account': get_cascade_env(f'ACCOUNT_{task_id}'.upper()),
        'queue': get_cascade_env(f'QUEUE_{task_id}'.upper()),
        'partition': get_cascade_env(f"PARTITION_{task_id}".upper()),
        'walltime': get_cascade_env(f"WALLTIME_{task_id}".upper()),
        'nodes': get_cascade_env(f"NODES_{task_id}".upper()),
        'reservation': get_cascade_env(f"RESERVATION_{task_id}".upper()),
        'cluster': get_cascade_env(f"CLUSTER_{task_id}".upper()),
        'native': get_cascade_env(f"NATIVE_{task_id}".upper())
    }

    myObjTask = objTask(
        task_id=task_id,
        cycledefs=cycledefs,
        maxtries=get_cascade_env(f"MAXTRIES_{task_id}".upper()),
        dcTaskRes=dcTaskRes,
        realtime=realtime.upper() == "TRUE",
        deadline=deadline,
        dcTaskEnv=dcTaskEnv,
        dependencies=dependencies)
    myObjTask.wflow_task_divider(xmlFile)
    if metatask is True:
        xmlFile.write(meta_bgn)
    myObjTask.wflow_task_begin(xmlFile)
    myObjTask.wflow_task_part1(xmlFile)
    myObjTask.wflow_task_dependencies(xmlFile)
    myObjTask.wflow_task_end(xmlFile)
    if metatask is True:
        xmlFile.write(meta_end)
# end of xml_task
