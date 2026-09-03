#!/usr/bin/env python
import os
import sys
from rocoto_funcs.base import wofs_windowed
from datetime import datetime, timedelta


def _min_to_hms(total_min):
    total_min = int(total_min)
    return f'{total_min // 60:02d}:{total_min % 60:02d}:00'


def _window(event_date, start_hhmm, end_hhmm):
    """Return (start, end) datetimes for an HHMM window anchored on event_date.
    An end time that is <= the start time rolls over to the next day."""
    d0 = datetime.strptime(event_date, '%Y%m%d')
    sh, sm = int(start_hhmm[:2]), int(start_hhmm[2:])
    eh, em = int(end_hhmm[:2]), int(end_hhmm[2:])
    start = d0 + timedelta(hours=sh, minutes=sm)
    end = d0 + timedelta(hours=eh, minutes=em)
    if end <= start:
        end += timedelta(days=1)
    return start, end


def _wofs_windowed_cycledefs():
    """Build cycledefs for WoFS windowed sub-hourly cycling (EVENT_DATE set).

    * prod  : DA cycles every DA_INTERVAL minutes over the DA window
    * ic     : the single cold-start cycle at DA_STARTTIME
    * domain : the one-time mesh-creation cycle (== ic)
    * lbc    : free-forecast launch window (LBCs feed the free forecasts)
    * free   : free-forecast launches every FREE_FCST_INTERVAL_MIN minutes
    * da_nocold : prod window minus the cold-start cycle (starts one DA
                  interval later) so DA is skipped at the cold start.
    """
    event_date = os.getenv('EVENT_DATE').strip()
    da_start_hhmm = os.getenv('DA_STARTTIME', '1500').strip().zfill(4)
    da_end_hhmm = os.getenv('DA_ENDTIME', '0300').strip().zfill(4)
    da_interval = int(os.getenv('DA_INTERVAL', '15'))
    fcst_start_hhmm = os.getenv('FCST_STARTTIME', '1700').strip().zfill(4)
    fcst_end_hhmm = os.getenv('FCST_ENDTIME', '0300').strip().zfill(4)
    free_interval = int(os.getenv('FREE_FCST_INTERVAL_MIN', '60'))

    da_start, da_end = _window(event_date, da_start_hhmm, da_end_hhmm)
    da_stride = _min_to_hms(da_interval)
    da_nocold_start = da_start + timedelta(minutes=da_interval)
    fcst_start, fcst_end = _window(event_date, fcst_start_hhmm, fcst_end_hhmm)
    free_stride = _min_to_hms(free_interval)

    fmt = '%Y%m%d%H%M'
    cycledef_prod = f'{da_start:{fmt}} {da_end:{fmt}} {da_stride}'
    cycledef_ic = f'{da_start:{fmt}} {da_start:{fmt}} 24:00:00'
    cycledef_domain = cycledef_ic
    cycledef_free = f'{fcst_start:{fmt}} {fcst_end:{fmt}} {free_stride}'
    # LBCs are generated ONCE per event into a single shared lbc/ directory
    # (mirroring the reference WoFS run): one cycle anchored at DA_STARTTIME
    # produces all hourly boundary files spanning the DA + free window.  Every
    # sub-hourly prod/free cycle then depends on that fixed cycle via a literal
    # datadep (see prep_lbc.py / prep_lbc_free.py) instead of a whole-hour
    # metataskdep, which is unsatisfiable for sub-hour and pre-window cycles.
    cycledef_lbc = f'{da_start:{fmt}} {da_start:{fmt}} 24:00:00'
    cycledef_nocold = f'{da_nocold_start:{fmt}} {da_end:{fmt}} {da_stride}'

    dcCycledef = {}
    if os.getenv('DO_CREATE_DOMAIN', 'FALSE').upper() == 'TRUE':
        dcCycledef['domain'] = f'{cycledef_domain}'
    if os.getenv('DO_RTMA', 'FALSE').upper() == 'FALSE':
        dcCycledef['ic'] = f'{cycledef_ic}'
        dcCycledef['lbc'] = f'{cycledef_lbc}'
    dcCycledef['prod'] = f'{cycledef_prod}'
    dcCycledef['free'] = f'{cycledef_free}'
    # skip DA at the single cold-start cycle
    do_jedi = os.getenv('DO_JEDI', 'FALSE').upper() == 'TRUE'
    do_nonvar_cld = os.getenv('DO_NONVAR_CLOUD_ANA', 'FALSE').upper() == 'TRUE'
    nocoldda = os.getenv('COLDSTART_CYCS_DO_DA', 'TRUE').upper() == 'FALSE'
    if (do_jedi or do_nonvar_cld) and nocoldda:
        dcCycledef['da_nocold'] = f'{cycledef_nocold}'
    if os.getenv('DO_ARCHIVE', 'FALSE').upper() == 'TRUE':
        dcCycledef['archive'] = f'{cycledef_prod}'
    return dcCycledef


def smart_cycledefs():
    # If users set CYCLEDEF_* variables explicitly in exp.setup, then just use it
    # otherwise calculate cycledef smartly

    cycledef_ic = os.getenv('CYCLEDEF_IC', 'not_defined')
    recenter = os.getenv('DO_RECENTER', 'FALSE').upper() == "TRUE"
    spinup = os.getenv('DO_SPINUP', 'FALSE').upper() == "TRUE"
    if cycledef_ic != 'not_defined':
        cycledef_lbc = os.getenv('CYCLEDEF_LBC', 'not_defined')
        cycledef_prod = os.getenv('CYCLEDEF_PROD', 'not_defined')
        cycledef_spinup = os.getenv('CYCLEDEF_SPINUP', 'not_defined')
        cycledef_recenter = os.getenv('CYCLEDEF_RECENTER', 'not_defined')
        cycledef_domain = os.getenv('CYCLEDEF_DOMAIN', 'not_defined')
    else:  # compute cycledef automatically if no CYCLEDEF_* environment variables
        # WoFS windowed sub-hourly mode is fully self-contained
        if wofs_windowed():
            return _wofs_windowed_cycledefs()
        lbc_cycs = os.getenv('LBC_CYCS', '00 12').strip().split()
        lbc_step = str(int(24 / len(lbc_cycs)))
        cyc_interval = os.getenv('CYC_INTERVAL', '3')
        cold_cycs = os.getenv('COLDSTART_CYCS', '03 15').strip().split()
        ic_step = str(int(24 / len(cold_cycs)))
        if os.getenv('DO_CYC', 'FALSE').upper() == "FALSE":
            cyc_interval = ic_step
            os.environ["CYC_INTERVAL"] = cyc_interval  # assign a pseudo "CYC_INTERVAL" for coldstart_only
        if recenter:
            recenter_cycs = os.getenv('RECENTER_CYCS', '03 15').strip().split()
            recenter_step = str(int(24 / len(recenter_cycs)))
        prodswitch_cycs = os.getenv('PRODSWITCH_CYCS', '09 21').strip().split()
        # compute spinup_hrs (usually coldstart at 03 or 15)
        spinup_hrs = list(range(int(cold_cycs[0]), int(prodswitch_cycs[0])))
        if len(cold_cycs) > 1:
            spinup_hrs.extend(list(range(int(cold_cycs[1]), int(prodswitch_cycs[1]))))
        #
        realtime = os.getenv('REALTIME', 'FALSE').upper() == "TRUE"
        if realtime:
            cycledef_ic = f'  &Y1;&M1;&D1;{cold_cycs[0]}00 &Y2;&M2;&D2;2300 {ic_step.zfill(2)}:00:00'
            cycledef_lbc = f' &Y1;&M1;&D1;{lbc_cycs[0]}00 &Y2;&M2;&D2;2300 {lbc_step.zfill(2)}:00:00'
            cycledef_prod = f'&Y1;&M1;&D1;0000 &Y2;&M2;&D2;2300 {cyc_interval.zfill(2)}:00:00'
            cycledef_recenter = cycledef_ic
            cycledef_spinup = cycledef_prod
            # single-cycle cycledef for the one-time domain-creation task
            cycledef_domain = f'&Y1;&M1;&D1;{cold_cycs[0]}00 &Y1;&M1;&D1;{cold_cycs[0]}00 24:00:00'
        # ~~~~~
        # retros write out cycledefs explicitly without referencing XML entities
        else:
            retrodates = os.getenv('RETRO_PERIOD', '2225010100-2225010800').split("-")
            hour1 = int(retrodates[0][8:10])
            if len(cold_cycs) > 1:
                index = 0 if hour1 < 12 else 1
            else:
                index = 0
            cold_cyc1 = cold_cycs[index]
            lbc_cyc1 = lbc_cycs[index]
            prod_cyc1 = cold_cyc1
            if spinup:  # if spinup, the first prod_cyc is from prodswitch_cycs
                prod_cyc1 = prodswitch_cycs[index]
            if recenter:
                if len(recenter_cycs) > 1:
                    recenter_index = 0 if hour1 < 12 else 1
                else:
                    recenter_index = 0
                recenter_cyc1 = recenter_cycs[recenter_index]
            #
            cycledef_ic = f'  {retrodates[0][0:8]}{cold_cyc1}00 {retrodates[1]}00 {ic_step.zfill(2)}:00:00'
            cycledef_lbc = f' {retrodates[0][0:8]}{lbc_cyc1}00 {retrodates[1]}00 {lbc_step.zfill(2)}:00:00'
            cycledef_prod = f'{retrodates[0][0:8]}{prod_cyc1}00 {retrodates[1]}00 {cyc_interval.zfill(2)}:00:00'
            # single-cycle cycledef for the one-time domain-creation task
            cycledef_domain = f'{retrodates[0][0:8]}{cold_cyc1}00 {retrodates[0][0:8]}{cold_cyc1}00 24:00:00'
            if recenter:
                cycledef_recenter = f'{retrodates[0][0:8]}{recenter_cyc1}00 {retrodates[1]}00 {recenter_step.zfill(2)}:00:00'
            if spinup:
                cycledef_spinup = f'{retrodates[0][0:8]}{cold_cyc1}00 {retrodates[1]}00 {cyc_interval.zfill(2)}:00:00'
    #
    # fill in the Cycledef dictionary
    dcCycledef = {}
    if os.getenv('DO_CREATE_DOMAIN', 'FALSE').upper() == "TRUE":
        dcCycledef['domain'] = f'{cycledef_domain}'
    if os.getenv('DO_RTMA', 'FALSE').upper() == 'FALSE':
        dcCycledef['ic'] = f'{cycledef_ic}'
        dcCycledef['lbc'] = f'{cycledef_lbc}'
    #
    exclude_str = os.getenv('CYCLEDEF_PROD_EXCLUDE', '')
    if exclude_str:
        dcCycledef['prod'] = {'exclude_hours': f'{exclude_str}', "cycledef": f'{cycledef_prod}'}
    else:
        dcCycledef['prod'] = f'{cycledef_prod}'
    #
    if recenter:
        dcCycledef['recenter'] = f'{cycledef_recenter}'
    #
    if spinup:
        valid_str = " ".join(f"{i}" for i in spinup_hrs)
        dcCycledef['spinup'] = {'valid_hours': f'{valid_str}', "cycledef": f'{cycledef_spinup}'}
    #
    # if we don't do DA at cold start cycles, let's exclude cold_cycs
    do_jedi = os.getenv('DO_JEDI', 'FALSE').upper() == 'TRUE'
    do_nonvar_cld = os.getenv('DO_NONVAR_CLOUD_ANA', 'FALSE').upper() == 'TRUE'
    nocoldda = os.getenv('COLDSTART_CYCS_DO_DA', 'TRUE').upper() == 'FALSE'
    if (do_jedi or do_nonvar_cld) and nocoldda:
        if spinup:  # if spinup, coldda only happens at spinup cycles
            spinup_hrs2 = [item for item in spinup_hrs if item not in list(map(int, cold_cycs))]
            valid_str = " ".join(f"{i}" for i in spinup_hrs2)
            dcCycledef['da_nocold'] = {'valid_hours': f'{valid_str}', "cycledef": f'{cycledef_spinup}'}
        else:
            exclude_cycs = list(map(int, os.getenv('CYCLEDEF_PROD_EXCLUDE', '').strip().split()))
            exclude_cycs.extend(list(map(int, cold_cycs)))
            exclude_cycs = sorted(set(exclude_cycs))  # uniq and sort
            exclude_str = " ".join(f"{i}" for i in exclude_cycs)
            dcCycledef['da_nocold'] = {'exclude_hours': f'{exclude_str}', "cycledef": f'{cycledef_prod}'}
    # ~~~~~~~
    if os.getenv('DO_ARCHIVE', 'FALSE').upper() == 'TRUE':
        archive_interval = int(os.getenv('ARCHIVE_INTERVAL', '1'))
        if archive_interval == 1:
            dcCycledef['archive'] = cycledef_prod
        else:
            if 24 % archive_interval != 0:
                print(f'24 cannot be divided by ARCHIVE_INTERVAL={archive_interval}, stop...')
                sys.exit()
            # determine the archive cycledef
            valid_list = list(range(archive_interval - 1, 25, archive_interval))
            valid_str = " ".join(f"{i}" for i in valid_list)
            dcCycledef['archive'] = {'valid_hours': f'{valid_str}', "cycledef": f'{cycledef_prod}'}
    # ~~~~~~~~
    return dcCycledef
