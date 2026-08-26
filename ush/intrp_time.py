#!/usr/bin/env python3

import os
import sys
import re

from datetime import datetime, timedelta, timezone
import netCDF4
import numpy as np

import argparse

########################################################################

def color_text(field, color = 'white', darkness='dark', length=None, ):
    """Return the 'field' in collored terminal form"""

    Term_colors = {
      'black'  : 30,
      'red'    : 31,
      'green'  : 32,
      'yellow' : 33,
      'blue'   : 34,
      'magenta': 35,
      'cyan'   : 36,
      'white'  : 37,
    }

    bgcolor="00"
    if darkness == "light":
        bgcolor="01"

    outfield = field
    if length :
        if len(field) > length :
            outfield = field[:length-4]+' ...'
        else:
            outfield = field.ljust(length)

    if sys.stdout.isatty():    # You're running in a real terminal
        outfield = f'\x1B[{bgcolor};{Term_colors[color]}m{outfield}\x1B[00m'
    #else:                     # You're being piped or redirected

    return outfield

#enddef color_text

########################################################################

def parse_args():
    """ Parse command line arguments
    """
    parser = argparse.ArgumentParser(description='Interpolate two MPAS lbc file linearly in time',
                                     epilog="""        ---- Yunheng Wang (2025-01-23).
                                            """)
                                     #formatter_class=CustomFormatter)

    parser.add_argument('file1',help='MPAS lbc file')
    parser.add_argument('file2',help='MPAS lbc file')
    parser.add_argument('outfile',help='Output file name')

    parser.add_argument('-v','--verbose', help='Verbose output',                                    action="store_true", default=False)
    parser.add_argument('-t','--time'   , help='Desired time string in YYYY-mm-dd_HH:MM:SS',        default=None,        type=str, required=True)

    args = parser.parse_args()

    #
    # Process multiple files
    #
    if not os.path.lexists(args.file1):
        print(f"{color_text('ERROR','red')}: File {color_text(args.file1,'yellow')} not exist.")
        sys.exit(1)

    if not os.path.lexists(args.file2):
        print(f"{color_text('ERROR','red')}: File {color_text(args.file2,'yellow')} not exist.")
        sys.exit(1)

    if os.path.lexists(args.outfile):
        print(f"{color_text('ERROR','red')}: File {color_text(args.outfile,'yellow')} exist.")
        sys.exit(1)

    return args

#@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@
#
# Main function defined to return correct sys.exit() calls
#
#@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@

if __name__ == "__main__":

    rargs = parse_args()

    with netCDF4.Dataset(rargs.file1, 'r') as dataset:
        xtime = dataset.variables["xtime"][0,:].tobytes().decode('utf-8')
        xtime1 = datetime.strptime(xtime.strip(),'%Y-%m-%d_%H:%M:%S')

        time1 = dataset.variables["Time"][:]

        #print(xtime1, time1)

    with netCDF4.Dataset(rargs.file2, 'r') as dataset:
        xtime = dataset.variables["xtime"][0,:].tobytes().decode('utf-8')
        xtime2 = datetime.strptime(xtime.strip(),'%Y-%m-%d_%H:%M:%S')

        time2 = dataset.variables["Time"][:]

        #print(xtime2, time2)

    out_timestr = rargs.time.replace(':','.')
    xtimeo = datetime.strptime(out_timestr,'%Y-%m-%d_%H.%M.%S')
    if xtimeo < xtime1 or xtimeo > xtime2:
        print(f"Times in the two input files are not in the right order. \n\ttime1  = {xtime1}, \n\ttime2  = {xtime2}, \n\tdesired= {xtimeo}.")
        sys.exit(0)

    dtime = (xtime2-xtime1).total_seconds()
    wtime2 = (xtimeo-xtime1).total_seconds()/dtime
    wtime1 = (xtime2-xtimeo).total_seconds()/dtime

    timeo = time1 + int((xtimeo-xtime1).total_seconds())

    print(f"{xtime1}{time1}*{wtime1} + {xtime2}{time2}*{wtime2} -> {rargs.time}{timeo}")

    # Create the new lbc at the desired time
    outfilename = rargs.outfile

    print(f"=> {outfilename}")

    #"ncflint -w 0.75,0.25 wofs_mpas_12.lbc.2024-05-08_15.00.00.nc wofs_mpas_12.lbc.2024-05-08_16.00.00.nc wofs_mpas_12.lbc.2024-05-08_15.15.00.nc"

    #print(sys.argv)

    with netCDF4.Dataset(rargs.file1) as src1, netCDF4.Dataset(rargs.file2) as src2, netCDF4.Dataset(outfilename, "w", format="NETCDF3_CLASSIC") as dst:
        # copy attributes
        for name in src1.ncattrs():
            if name == 'history':
                dst.setncattr(name, ' '.join(sys.argv))
            elif name == 'output_interval':
                dst.setncattr(name, int(time2-timeo)//60)
            else:
                dst.setncattr(name, src1.getncattr(name))
        # copy dimensions
        for name, dimension in src1.dimensions.items():
            if dimension.isunlimited():
                dst.createDimension( name, None)
            else:
                dst.createDimension( name, len(dimension))

        # copy all file data for variables that are included in the toinclude list
        for name, variable in src1.variables.items():
            if name == 'Time':
                dstvar = dst.createVariable(name, variable.datatype, variable.dimensions)
                dst.variables[name][:] = timeo
            elif name == 'xtime':
                dstvar = dst.createVariable(name, variable.datatype, variable.dimensions)
                date_strings = [xtimeo.strftime('%Y-%m-%d_%H:%M:%S').ljust(64),]
                # 1. Ensure your strings are standard Python strings (not bytes)
                # This list comprehension acts as a safety net
                clean_strings = [str(s.decode('utf-8')) if isinstance(s, bytes) else str(s) for s in date_strings]

                # 2. Create a 2D numpy array of single characters
                # We specify 'S1' (1-byte character) as the dtype
                char_array = np.array([list(s) for s in clean_strings], dtype='S1')
                dst.variables[name][:] = char_array

            else:
                var_type = variable.dtype
                if var_type in ('float32', ):
                    dstvar = dst.createVariable(name, variable.datatype, variable.dimensions)
                    dst.variables[name][:] = src1.variables[name][:]*wtime1 + src2.variables[name][:]*wtime2

            dstvar.setncatts(variable.__dict__)

