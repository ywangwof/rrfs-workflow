#!/usr/bin/env python3
"""Radar-echo test for GOES cloud water path obs, from the MRMS IODA files of the same cycle.

Used by GOESCWP2ioda.py (--echo-ioda / --clear-ioda --echo-distance) to write each obs's
distance to the nearest echo column as MetaData/radarEchoDistance for a QC filter in the LETKF
yaml (ush/yaml_finalize, CWP_ECHO_SCREEN_KM). near_echo() gives the same test as a mask.

The WoFS MRMS IODA files put reflectivity >= 15 dBZ (echo file) and 0 dBZ clear-air points
(clear file) at grid columns at several heights. The grid can be a regular lat/lon lattice
(e.g. 0.05 degree) or any other structured grid, such as the Lambert geo_em grid of the
Cressman regrid, since columns are searched with a k-d tree on their true locations.
A column counts as radar-clear only when it has clear-air points, no echo point and, if
clear_top_m is set, a clear-air point at or above clear_top_m (under an anvil of 5-15 dBZ there
are clear-air points only below it); every other column counts as echo. Grid columns with no
point at all (5-15 dBZ or no data) also count as echo: they are found as the grid positions one
step beyond each column (column + (column - neighbour), for its 4 nearest neighbours) that are
not occupied and that lie inside the lat/lon box of the data.
An obs is radar-clear when no echo column lies within buffer_km; obs that are not in any
column's cell (outside the grid, or inside a hole of it) count as echo. distance <= buffer_km
exactly when near_echo(buffer_km) is True; obs not in any cell get 0 and obs with no echo
column within max_km get max_km. Needs numpy, scipy and netCDF4.
"""
import numpy as np
from netCDF4 import Dataset
from scipy.spatial import cKDTree

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


def _xyz(lat, lon):
    """Cartesian coordinates (km) on the sphere; chord distance ~ great-circle distance at < 100 km."""
    la, lo = np.deg2rad(lat), np.deg2rad(lon)
    return EARTH_KM * np.column_stack([np.cos(la) * np.cos(lo), np.cos(la) * np.sin(lo), np.sin(la)])


class EchoColumns:
    """Echo / clear status of the MRMS grid columns."""

    def __init__(self, echo_lat, echo_lon, clear_lat, clear_lon, clear_hgt=None, clear_top_m=None):
        echo_lon = np.where(echo_lon > 180.0, echo_lon - 360.0, echo_lon)
        clear_lon = np.where(clear_lon > 180.0, clear_lon - 360.0, clear_lon)
        alat = np.round(np.concatenate([echo_lat, clear_lat]), 4)
        alon = np.round(np.concatenate([echo_lon, clear_lon]), 4)
        if alat.size == 0:
            raise ValueError("no MRMS locations")
        cols, inv = np.unique(np.column_stack([alat, alon]), axis=0, return_inverse=True)
        inv = inv.ravel()
        ne = np.size(echo_lat)
        has_echo = np.zeros(len(cols), bool)
        has_clear = np.zeros(len(cols), bool)
        has_echo[inv[:ne]] = True
        has_clear[inv[ne:]] = True
        top_clear = np.full(len(cols), -np.inf)
        if clear_hgt is not None and np.size(clear_hgt):
            np.maximum.at(top_clear, inv[ne:], clear_hgt)
        clear = has_clear & ~has_echo
        if clear_top_m is not None:
            clear &= top_clear >= clear_top_m
        self.lat, self.lon = cols[:, 0], cols[:, 1]
        self.has_echo, self.has_clear, self.top_clear = has_echo, has_clear, top_clear
        self.clear = clear
        self.echo = ~clear

        xyz = _xyz(self.lat, self.lon)
        self._tree = cKDTree(xyz)
        k = min(5, len(cols))
        dist, nbr = self._tree.query(xyz, k=k)
        dist, nbr = dist.reshape(len(cols), k), nbr.reshape(len(cols), k)
        # Grid spacing (nearest neighbour) and cell size (4th neighbour: covers the half
        # diagonal of square and rectangular cells)
        self.spacing_km = float(np.median(dist[:, 1])) if k > 1 else 1.0
        self.cell_km = 0.75 * float(np.median(dist[:, -1])) if k > 1 else 1.0

        # Empty grid columns (no MRMS point at all) inside the data's lat/lon box
        holes = np.zeros((0, 3))
        if k > 1:
            hlat = (2.0 * self.lat[:, None] - self.lat[nbr[:, 1:]]).ravel()
            hlon = (2.0 * self.lon[:, None] - self.lon[nbr[:, 1:]]).ravel()
            eps = 1.0e-6
            box = ((hlat >= self.lat.min() - eps) & (hlat <= self.lat.max() + eps) &
                   (hlon >= self.lon.min() - eps) & (hlon <= self.lon.max() + eps))
            hxyz = _xyz(hlat[box], hlon[box])
            if len(hxyz):
                dmin, _ = self._tree.query(hxyz)
                holes = hxyz[dmin > 0.5 * self.spacing_km]
                if len(holes):
                    holes = np.unique(np.round(holes, 3), axis=0)
        self.n_holes = len(holes)
        echo_xyz = np.vstack([xyz[self.echo], holes])
        self._echo_tree = cKDTree(echo_xyz) if len(echo_xyz) else None

    def _query(self, lat, lon, radius_km):
        """Outside-cell mask and distance (km) to the nearest echo location (inf beyond radius_km)."""
        lat = np.asarray(lat, np.float64)
        lon = np.asarray(lon, np.float64)
        lon = np.where(lon > 180.0, lon - 360.0, lon)
        xyz = _xyz(lat.ravel(), lon.ravel())
        dcol, _ = self._tree.query(xyz)
        outside = (dcol > self.cell_km).reshape(lat.shape)
        if self._echo_tree is None:
            d = np.full(lat.shape, np.inf)
        else:
            d, _ = self._echo_tree.query(xyz, distance_upper_bound=radius_km)
            d = d.reshape(lat.shape)
        return outside, d

    def near_echo(self, lat, lon, buffer_km):
        """True where an echo column lies within buffer_km of (lat, lon), or outside the grid."""
        outside, d = self._query(lat, lon, buffer_km * (1.0 + 1.0e-9))
        return outside | (d <= buffer_km)

    def distance_km(self, lat, lon, max_km):
        """Distance (km) to the nearest echo column, capped at max_km; 0 outside the grid."""
        outside, d = self._query(lat, lon, max_km)
        d = np.minimum(d, max_km)
        d[outside] = 0.0
        return d


EchoLattice = EchoColumns   # former name


def lattice_from(echo_paths, clear_paths, clear_top_m=None):
    elat, elon, _ = read_columns(echo_paths)
    clat, clon, chgt = read_columns(clear_paths)
    return EchoColumns(elat, elon, clat, clon, chgt, clear_top_m)


def near_echo(lat, lon, echo_paths, clear_paths, buffer_km, clear_top_m=None):
    """Convenience wrapper: True for obs near radar echo, False for radar-clear obs."""
    lattice = lattice_from(echo_paths, clear_paths, clear_top_m)
    return lattice.near_echo(np.asarray(lat, np.float64), np.asarray(lon, np.float64), buffer_km)


def echo_distance(lat, lon, echo_paths, clear_paths, max_km, clear_top_m=None):
    """Convenience wrapper: distance (km) to the nearest echo column, capped at max_km."""
    lattice = lattice_from(echo_paths, clear_paths, clear_top_m)
    return lattice.distance_km(np.asarray(lat, np.float64), np.asarray(lon, np.float64), max_km)
