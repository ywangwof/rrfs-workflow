#!/usr/bin/env python3

import argparse
import netCDF4 as nc
from datetime import datetime
import numpy as np
from multiprocessing import Pool
from multiprocessing.pool import ThreadPool
import os
import sys
import contextlib

import pyiodaconv.ioda_conv_engines as iconv
from pyiodaconv.orddicts import DefaultOrderedDict

os.environ["TZ"] = "UTC"

##%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
class GOESConverter:
    """Handles the logic for reading and transforming GOES netCDF data."""

    def __init__(self, config):
        self.config = config
        self.locationKeyList = [
            ("latitude", "float"),
            ("longitude", "float"),
            ("dateTime", "long"),
        ]

    ############################################################################
    def get_output_var_name(self, target_phase):
        """Maps the integer phase to the IODA variable name."""
        mapping = {
            0: "CloudWaterPath_Zero",
            1: "LiquidWaterPath",
            2: "IceWaterPath",
            3: "CloudWaterPath_Zero_Night",
            4: "LiquidWaterPath_Night",
            5: "IceWaterPath_Night",
            6: "LiquidWaterPath_Zero",
            7: "LiquidWaterPath_Zero_Night"
        }
        return [mapping.get(int(target_phase), "Unknown_Path_Variable")]

    ############################################################################
    def read_input(self, input_file):
        """Reads/converts a single input file into an observation dictionary."""
        target_phase = int(self.config['goesvar'])
        output_var_names = self.get_output_var_name(target_phase)

        if self.config.get('verbose'):
            print(f"Reading {input_file} for {output_var_names[0]}")

        ncd = nc.Dataset(input_file, 'r')

        # Extract global attributes
        global_attrs = {}
        attrib_map = {'satellite': 'platformCommonName', 'grid_spacing': 'gridSpacing_km'}
        for src, dest in attrib_map.items():
            global_attrs[dest] = ncd.getncattr(src)

        # Apply phase masking
        phase = ncd.variables['phase'][:]
        mask_phase = (phase == target_phase)

        # Extract and convert Metadata
        lats = ncd.variables['lat'][mask_phase].astype(np.float32)
        lons = ncd.variables['lon'][mask_phase].astype(np.float32)
        prs = ncd.variables['pressure'][mask_phase].astype(np.float32) * 100.
        ctp = ncd.variables['ctp'][mask_phase].astype(np.float32) * 100.
        cbp = ncd.variables['cbp'][mask_phase].astype(np.float32) * 100.

        # Assign hgt depending pressure (from pyiodaconv/meteo_utils.py)
        hgt = 44307.692 * (1.0 - ((prs/100.)/1013.25)**0.190)

        # Retrieve observed variables and errors
        cwp = ncd.variables['cwp'][mask_phase].astype(np.float32)
        cwp_err = ncd.variables['cwp_err'][mask_phase].astype(np.float32)

        ncd.close()

        # Apply random thinning
        np.random.seed(int((self.config['date'] - datetime(1970, 1, 1)).total_seconds()))
        thin_mask = np.random.uniform(size=len(lons)) > self.config['thin']

        # Package data into IODA dictionary format
        obs_data = {}
        v_name = output_var_names[0]

        obs_data[('latitude', 'MetaData')] = lats[thin_mask]
        obs_data[('longitude', 'MetaData')] = lons[thin_mask]
        obs_data[('dateTime', 'MetaData')] = np.zeros(len(lons[thin_mask]), dtype=np.int64)
        obs_data[('pressure', 'MetaData')] = prs[thin_mask]
        obs_data[('height', 'MetaData')] = hgt[thin_mask]
        obs_data[('satcbp', 'MetaData')] = cbp[thin_mask]
        obs_data[('satctp', 'MetaData')] = ctp[thin_mask]

        obs_data[(v_name, self.config['oval_name'])] = cwp[thin_mask]
        obs_data[(v_name, self.config['oerr_name'])] = cwp_err[thin_mask]
        obs_data[(v_name, self.config['opqc_name'])] = np.zeros(len(lons[thin_mask]), dtype=np.int32)

        return obs_data, self.config['date'], global_attrs, output_var_names

################################################################################
def process_variable(args_tuple):
    """Worker function to process a specific GOES variable using ThreadPool."""
    v_id, args, name_map = args_tuple

    config = {
        'date': datetime.strptime(args.date, '%Y%m%d%H%M'),
        'thin': args.thin,
        'goesvar': v_id,
        'verbose': args.verbose,
        'oval_name': iconv.OvalName(),
        'oerr_name': iconv.OerrName(),
        'opqc_name': iconv.OqcName()
    }

    converter = GOESConverter(config)

    # Inner Parallelism: Use threads to read input files concurrently
    with ThreadPool(args.threads) as thread_pool:
        results = thread_pool.map(converter.read_input, args.input)

    # Concatenate results
    obs_data, basetime, global_attrs, out_names = results[0]
    for i in range(1, len(results)):
        for key in obs_data.keys():
            obs_data[key] = np.concatenate((obs_data[key], results[i][0][key]))

    nlocs = len(obs_data[('longitude', 'MetaData')])
    if nlocs <= 0:
        return f"Skipped {v_id}: No observations." if args.verbose else None

    # Setup IODA structure
    dim_dict = {'Location': nlocs}
    var_attrs = DefaultOrderedDict(lambda: DefaultOrderedDict(dict))
    var_dims = {out_names[0]: ['Location']}

    date_str = basetime.strftime("%Y-%m-%dT%H:%M:%SZ")
    var_attrs['dateTime', 'MetaData']['units'] = f'seconds since {date_str}'

    for suffix in [config['oval_name'], config['oerr_name']]:
        var_attrs[out_names[0], suffix]['units'] = 'kg m-2'
        var_attrs[out_names[0], suffix]['_FillValue'] = -32767.

    global_attrs['datetimeReference'] = date_str
    global_attrs['thinning'] = np.float32(args.thin)
    global_attrs['converter'] = os.path.basename(__file__)

    # Filename Logic
    if args.output is not None:
        out_file = f"{name_map.get(v_id, v_id)}_{args.output}" if args.goesvar is None else args.output
    else:
        out_file = f"ioda_{name_map.get(v_id, v_id)}_obs.nc"

    writer = iconv.IodaWriter(out_file, converter.locationKeyList, dim_dict)
    writer.BuildIoda(obs_data, var_dims, var_attrs, global_attrs)

    return f"Finished {out_names[0]}: nlocs = {nlocs}" if args.verbose else None

################################################################################
def parse_args():
    """Defines and handles the command line argument parser."""
    parser = argparse.ArgumentParser(description='Converts NSSL netCDF to IODA.')

    parser.add_argument('input', nargs='+', help="Input netCDF file(s)")

    required = parser.add_argument_group(title='required arguments')
    required.add_argument('-d', '--date', required=True, help="Date YYYYMMDDHHMM")

    optional = parser.add_argument_group(title='optional arguments')
    optional.add_argument('-o', '--output', default=None, help="Output IODA file")
    optional.add_argument('-g', '--goesvar', default=None, help="Variable ID (0-5)")
    optional.add_argument('-t', '--thin', type=float, default=0.0, help="Thinning (0-1)")
    optional.add_argument('--threads', type=int, default=1, help="Threads per process")
    optional.add_argument('-v', '--verbose', action='store_true', help="Enable verbose output")

    return parser.parse_args()

################################################################################
def main():
    """Outer Parallelism: Use processes to handle each variable."""
    args = parse_args()

    # Context manager to silence output if verbose is False
    with contextlib.redirect_stdout(None if not args.verbose else sys.stdout):
        with contextlib.redirect_stderr(None if not args.verbose else sys.stderr):

            name_map = {0: "cwp", 1: "lwp", 2: "iwp", 3: "cwp_night", 4: "lwp_night", 5: "iwp_night"}
            var_ids = [int(args.goesvar)] if args.goesvar is not None else range(6)
            pool_inputs = [(v_id, args, name_map) for v_id in var_ids]

            with Pool(len(var_ids)) as process_pool:
                log_messages = process_pool.map(process_variable, pool_inputs)

            if args.verbose:
                for msg in log_messages:
                    if msg: print(msg)

################################################################################
if __name__ == '__main__':
    main()