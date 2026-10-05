#!/usr/bin/env python3
#
# Convert Oklahoma Mesonet (OKM) MDF surface observations into an IODA-format
# file for assimilation.  Based on the METAR conversion process, it produces:
#   airTemperature (plus an airTemperatureAt2M copy), specificHumidity,
#   stationPressure, windEastward, windNorthward
#
# The pyiodaconv libraries are expected to be on PYTHONPATH (set by the caller,
# e.g. ${HOMErrfs}/sorc/RDASApp/build/lib/python3.*), mirroring GOESCWP2ioda.py.
#
import os
import sys
import argparse
import numpy as np
import pandas as pd
import netCDF4
from collections import defaultdict
from datetime import datetime, timezone

import pyiodaconv.ioda_conv_engines as iconv
from pyiodaconv.orddicts import DefaultOrderedDict

# Ratio of molecular weights of water vapor and dry air (MetPy constants)
EPSILON = 18.015268 / 28.96546


def to_posix_timestamp(time_str: str) -> int:
    # Parse the string into a naive datetime object
    dt = datetime.strptime(time_str, "%Y%m%d%H%M")
    # Treat as UTC and convert to POSIX timestamp (integer seconds)
    return int(dt.replace(tzinfo=timezone.utc).timestamp())


def parse_args():
    parser = argparse.ArgumentParser(
        description="Convert Oklahoma Mesonet MDF observations to IODA format.")
    parser.add_argument("time", help="valid time in YYYYmmddHHMM format")
    parser.add_argument("-i", "--input", dest="input_file", required=True,
                        help="path to the OK Mesonet MDF file")
    parser.add_argument("-g", "--geoinfo", dest="geo_file", required=True,
                        help="path to geoinfo.csv (station lat/lon/elevation)")
    parser.add_argument("-o", "--output", dest="output_file", required=True,
                        help="output IODA netCDF file")
    return parser.parse_args()


def main():
    args = parse_args()

    input_time = args.time
    valid_time = to_posix_timestamp(input_time)

    file_path = args.input_file       # OK Mesonet observations (MDF)
    geo_file_path = args.geo_file     # station lat/lon/elevation table
    output_file = args.output_file    # IODA output

    # The Oklahoma Mesonet standard MDF format usually has header metadata
    # lines at the top.  Adjust 'skiprows' based on your specific file structure
    # (often 1 or 2 header rows exist before the column names/data).
    df = pd.read_csv(
        file_path,
        skiprows=2,           # Skip top metadata lines; adjust as needed
        sep=r'\s+',
        na_values=["-999", "-999.0", "-998", "-998.0", "-997", "-997.0",
                   "-996", "-996.0", "-995", "-995.0", "-994", "-994.0", " "]
    )

    df_geo = pd.read_csv(
        geo_file_path,
        na_values=["-999", "-999.0", " "]
    )

    merged_df = pd.merge(df, df_geo, left_on='STID', right_on='stid')

    keep_vars = ['STID', 'TIME', 'nlat', 'elon', 'elev', 'RELH', 'TAIR',
                 'WSPD', 'WDIR', 'PRES']

    subset_mdf = merged_df[keep_vars]
    clean_sub = subset_mdf.dropna()

    stations = clean_sub['STID'].values
    time = clean_sub['TIME'].values
    time.fill(valid_time)
    lat = clean_sub['nlat'].values
    lon = 360. + clean_sub['elon'].values
    elev = clean_sub['elev'].values
    relh = clean_sub['RELH'].values
    temp = clean_sub['TAIR'].values + 273.15
    wspd = clean_sub['WSPD'].values
    wdir = clean_sub['WDIR'].values
    pres = 100. * clean_sub['PRES'].values

    # Calculate specific humidity from pressure, temperature and relative humidity.
    # Same formulas as MetPy 1.5 (Bolton 1980 saturation vapor pressure), in
    # plain numpy so the converter runs with the RDASApp python stack.
    es = 611.2 * np.exp(17.67 * (temp - 273.15) / (temp - 29.65))  # Pa
    mixing_ratio = (relh / 100.) * EPSILON * es / (pres - es)
    sphu = mixing_ratio / (1. + mixing_ratio)                        # kg/kg

    # Calculate u-wind and v-wind from wind speed and direction (meteorological)
    wdir_rad = np.deg2rad(wdir)
    u = -wspd * np.sin(wdir_rad)
    v = -wspd * np.cos(wdir_rad)

    # Begin IODA conversion code
    os.environ["TZ"] = "UTC"

    locationKeyList = [("stationICAO", "string", ""),
                       ("latitude", "float", "degrees_north"),
                       ("longitude", "float", "degrees_east"),
                       ("stationElevation", "float", "m"),
                       ("height", "float", "m"),
                       ("dateTime", "long", "seconds since 1970-01-01T00:00:00Z")]

    meta_keys = [m_item[0] for m_item in locationKeyList]

    # 'airTemperature' is the name keyed by the UFO SfcCorrected GSL operator
    # (airTemperature_GSL).  'airTemperatureAt2M' is an auxiliary copy that
    # stationPressure_GSL reads for its hydrostatic correction; it is not
    # simulated in the DA.
    obsvars = ['airTemperature',
               'airTemperatureAt2M',
               'specificHumidity',
               'stationPressure',
               'windEastward',
               'windNorthward']

    obsvars_units = ['K', 'K', 'kg kg-1', 'Pa', 'm s-1', 'm s-1']
    obserrlist = [1.0, 1.0, 0.75E-3, 100.0, 1.0, 1.0]

    AttrData = {'converter': os.path.basename(__file__),
                'ioda_object_version': 2,
                'description': 'OK Mesonet surface observation data converted from MDF',
                'source': 'NSSL OK Mesonet LDM Feed (kknopfmeier)'}

    DimDict = {}

    metaDataName = iconv.MetaDataName()
    obsValName = iconv.OvalName()
    obsErrName = iconv.OerrName()
    qcName = iconv.OqcName()

    float_missing_value = netCDF4.default_fillvals['f4']
    int_missing_value = netCDF4.default_fillvals['i4']
    double_missing_value = netCDF4.default_fillvals['f8']
    long_missing_value = netCDF4.default_fillvals['i8']
    string_missing_value = '_'

    missing_vals = {'string': string_missing_value,
                    'integer': int_missing_value,
                    'long': long_missing_value,
                    'float': float_missing_value,
                    'double': double_missing_value}

    dtypes = {'string': object,
              'integer': np.int32,
              'long': np.int64,
              'float': np.float32,
              'double': np.float64}

    # Initialize
    varDict = defaultdict(lambda: DefaultOrderedDict(dict))
    varAttrs = DefaultOrderedDict(lambda: DefaultOrderedDict(dict))

    obs_data = {}          # The final outputs.
    data = {}              # Before assigning the output types into the above.

    for key in meta_keys:
        data[key] = []

    for key in obsvars:
        data[key] = []

    data['stationICAO'].extend(stations.tolist())
    data['dateTime'].extend(time.tolist())
    data['latitude'].extend(lat.tolist())
    data['longitude'].extend(lon.tolist())
    data['stationElevation'].extend(elev.tolist())
    data['height'].extend(elev.tolist())
    data['stationPressure'].extend(pres.tolist())
    data['airTemperature'].extend(temp.tolist())
    data['airTemperatureAt2M'].extend(temp.tolist())
    data['specificHumidity'].extend(sphu.tolist())
    data['windEastward'].extend(u.tolist())
    data['windNorthward'].extend(v.tolist())

    nlocs = len(data['dateTime'])
    DimDict['Location'] = nlocs

    # Set coordinates and units of the ObsValues.
    for n, iodavar in enumerate(obsvars):
        varDict[iodavar]['valKey'] = iodavar, obsValName
        varDict[iodavar]['errKey'] = iodavar, obsErrName
        varDict[iodavar]['qcKey'] = iodavar, qcName
        varAttrs[iodavar, obsValName]['coordinates'] = 'longitude latitude'
        varAttrs[iodavar, obsErrName]['coordinates'] = 'longitude latitude'
        varAttrs[iodavar, qcName]['coordinates'] = 'longitude latitude'
        varAttrs[iodavar, obsValName]['units'] = obsvars_units[n]
        varAttrs[iodavar, obsErrName]['units'] = obsvars_units[n]

    # Set units of the MetaData variables and all _FillValues.
    for key in meta_keys:
        dtypestr = locationKeyList[meta_keys.index(key)][1]
        varAttrs[(key, metaDataName)]['_FillValue'] = missing_vals[dtypestr]
        this_units = locationKeyList[meta_keys.index(key)][2]
        if this_units:
            varAttrs[(key, metaDataName)]['units'] = this_units
        obs_data[(key, metaDataName)] = np.array(data[key], dtype=dtypes[dtypestr])

    # Transfer from the 1-D data vectors and ensure output data types using numpy.
    for n, iodavar in enumerate(obsvars):
        vals = [x.magnitude if hasattr(x, 'magnitude') else x for x in data[iodavar]]
        obs_data[(iodavar, obsValName)] = np.array(vals, dtype=np.float32)
        obs_data[(iodavar, obsErrName)] = np.full(nlocs, obserrlist[n], dtype=np.float32)
        obs_data[(iodavar, qcName)] = np.full(nlocs, 2, dtype=np.int32)

    VarDims = {}
    for vname in obsvars:
        VarDims[vname] = ['Location']

    # setup the IODA writer
    writer = iconv.IodaWriter(output_file, locationKeyList, DimDict)

    # write everything out
    writer.BuildIoda(obs_data, VarDims, varAttrs, AttrData)
    print(f"Wrote {nlocs} OK Mesonet obs to {output_file}")


if __name__ == "__main__":
    main()
