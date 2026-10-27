#!/usr/bin/env python3
"""Radar-echo test for GOES cloud water path obs, from the MRMS IODA files of the same cycle.

Used by GOESCWP2ioda.py (--echo-ioda / --clear-ioda --echo-distance) to write each obs's
distance to the nearest echo column as MetaData/radarEchoDistance for a QC filter in the LETKF
yaml (ush/yaml_finalize, CWP_ECHO_SCREEN_KM). near_echo() gives the same test as a mask.

The WoFS MRMS IODA files put reflectivity >= 15 dBZ (echo file) and 0 dBZ clear-air points
(clear file) on one regular 0.05 degree lattice at several heights. A lattice column counts as
radar-clear only when it has clear-air points, no echo point and, if clear_top_m is set, a
clear-air point at or above clear_top_m (under an anvil of 5-15 dBZ there are clear-air points
only below it); every other column of the lattice (echo, echo at some heights only, or neither,
i.e. 5-15 dBZ or no data) counts as echo.
An obs is radar-clear when no echo column lies within buffer_km; obs outside the lattice count
as echo. The distance to echo uses the same columns and distance formula, so
distance <= buffer_km exactly when near_echo(buffer_km) is True; obs outside the lattice get 0
and obs with no echo column within max_km get max_km. Only numpy and netCDF4 are needed.
"""
import numpy as np
from netCDF4 import Dataset

EARTH_KM = 6371.0


def read_columns(paths):
    """Latitude, longitude (-180..180) and height of every location in the IODA files."""
    lats, lons, hgts = [], [], []
    for path in paths:
        with Dataset(path) as f:
            md = f.groups["MetaData"].variables
            lats.append(np.asarray(md["latitude"][:], np.float64))
            lons.append(np.asarray(md["longitude"][:], np.float64))
            hgts.append(np.asarray(md["height"][:], np.float64))
    lat = np.concatenate(lats) if lats else np.zeros(0)
    lon = np.concatenate(lons) if lons else np.zeros(0)
    hgt = np.concatenate(hgts) if hgts else np.zeros(0)
    return lat, np.where(lon > 180.0, lon - 360.0, lon), hgt


class EchoLattice:
    """Echo / clear status of the MRMS lattice columns."""

    def __init__(self, echo_lat, echo_lon, clear_lat, clear_lon, clear_hgt=None, clear_top_m=None):
        alat = np.concatenate([echo_lat, clear_lat])
        alon = np.concatenate([echo_lon, clear_lon])
        if alat.size == 0:
            raise ValueError("no MRMS locations")
        ulat = np.unique(np.round(alat, 4))
        ulon = np.unique(np.round(alon, 4))
        self.dlat = float(np.median(np.diff(ulat))) if ulat.size > 1 else 0.05
        self.dlon = float(np.median(np.diff(ulon))) if ulon.size > 1 else 0.05
        self.lat0, self.lon0 = float(ulat[0]), float(ulon[0])
        self.ny = int(round((ulat[-1] - self.lat0) / self.dlat)) + 1
        self.nx = int(round((ulon[-1] - self.lon0) / self.dlon)) + 1
        has_echo = np.zeros((self.ny, self.nx), bool)
        has_clear = np.zeros((self.ny, self.nx), bool)
        has_echo[self._index(echo_lat, echo_lon)] = True
        has_clear[self._index(clear_lat, clear_lon)] = True
        self.top_clear = np.full((self.ny, self.nx), -np.inf)
        if clear_hgt is not None:
            np.maximum.at(self.top_clear, self._index(clear_lat, clear_lon), clear_hgt)
        self.has_echo, self.has_clear = has_echo, has_clear
        self.clear = has_clear & ~has_echo
        if clear_top_m is not None:
            self.clear &= self.top_clear >= clear_top_m
        self.echo = ~self.clear

    def _index(self, lat, lon):
        j = np.rint((lat - self.lat0) / self.dlat).astype(int)
        i = np.rint((lon - self.lon0) / self.dlon).astype(int)
        return np.clip(j, 0, self.ny - 1), np.clip(i, 0, self.nx - 1)

    def _search(self, lat, lon, radius_km):
        """Outside-lattice mask and, for each lattice column within radius_km's index stencil,
        (column is echo and inside the lattice, squared distance in km2)."""
        lon = np.where(lon > 180.0, lon - 360.0, lon)
        fj = (lat - self.lat0) / self.dlat
        fi = (lon - self.lon0) / self.dlon
        outside = (fj < -0.5) | (fj > self.ny - 0.5) | (fi < -0.5) | (fi > self.nx - 0.5)
        coslat = np.cos(np.deg2rad(lat))
        nj = int(np.ceil(radius_km / (EARTH_KM * np.deg2rad(self.dlat)))) + 1
        ni = int(np.ceil(radius_km / (EARTH_KM * np.deg2rad(self.dlon) * max(coslat.min(), 0.1)))) + 1
        j0, i0 = np.rint(fj).astype(int), np.rint(fi).astype(int)

        def columns():
            for dj in range(-nj, nj + 1):
                for di in range(-ni, ni + 1):
                    j, i = j0 + dj, i0 + di
                    inside = (j >= 0) & (j < self.ny) & (i >= 0) & (i < self.nx)
                    jc, ic = np.clip(j, 0, self.ny - 1), np.clip(i, 0, self.nx - 1)
                    clat = self.lat0 + jc * self.dlat
                    clon = self.lon0 + ic * self.dlon
                    dy = np.deg2rad(clat - lat) * EARTH_KM
                    dx = np.deg2rad(clon - lon) * EARTH_KM * coslat
                    yield inside & self.echo[jc, ic], dx * dx + dy * dy
        return outside, columns()

    def near_echo(self, lat, lon, buffer_km):
        """True where an echo column lies within buffer_km of (lat, lon), or outside the lattice."""
        outside, columns = self._search(lat, lon, buffer_km)
        near = outside.copy()
        for echo, d2 in columns:
            near |= echo & (d2 <= buffer_km * buffer_km)
        return near

    def distance_km(self, lat, lon, max_km):
        """Distance (km) to the nearest echo column, capped at max_km; 0 outside the lattice."""
        outside, columns = self._search(lat, lon, max_km)
        d2min = np.full(np.shape(lat), max_km * max_km)
        for echo, d2 in columns:
            d2min = np.where(echo & (d2 < d2min), d2, d2min)
        d2min[outside] = 0.0
        return np.sqrt(d2min)


def lattice_from(echo_paths, clear_paths, clear_top_m=None):
    elat, elon, _ = read_columns(echo_paths)
    clat, clon, chgt = read_columns(clear_paths)
    return EchoLattice(elat, elon, clat, clon, chgt, clear_top_m)


def near_echo(lat, lon, echo_paths, clear_paths, buffer_km, clear_top_m=None):
    """Convenience wrapper: True for obs near radar echo, False for radar-clear obs."""
    lattice = lattice_from(echo_paths, clear_paths, clear_top_m)
    return lattice.near_echo(np.asarray(lat, np.float64), np.asarray(lon, np.float64), buffer_km)


def echo_distance(lat, lon, echo_paths, clear_paths, max_km, clear_top_m=None):
    """Convenience wrapper: distance (km) to the nearest echo column, capped at max_km."""
    lattice = lattice_from(echo_paths, clear_paths, clear_top_m)
    return lattice.distance_km(np.asarray(lat, np.float64), np.asarray(lon, np.float64), max_km)
