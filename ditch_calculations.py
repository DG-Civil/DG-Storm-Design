# -*- coding: utf-8 -*-
"""
Created on Fri May 22 10:34:21 2026

@author: Dawit.Ghebreyesus
"""

import numpy as np
from scipy.optimize import fsolve

def manning_ditch_normal_depth(Q, bottom_width, z_left, z_right, n, S, max_depth):
    """Normal depth for Trapezoidal ditch"""
    if Q <= 0 or S <= 0:
        return 0.0
    
    def objective(y):
        y = max(0.01, min(y, max_depth))
        area = (bottom_width + y * (z_left + z_right) / 2) * y
        perimeter = bottom_width + y * np.sqrt(1 + z_left**2) + y * np.sqrt(1 + z_right**2)
        r_h = area / perimeter if perimeter > 0 else 0.01
        Q_calc = (1.486 / n) * area * r_h**(2/3) * S**0.5
        return Q_calc - Q
    
    y_guess = min(max_depth * 0.6, Q * 0.4)
    y_sol = fsolve(objective, y_guess)
    return round(max(0.01, min(float(y_sol[0]), max_depth)), 3)


def calculate_ditch_velocity(Q, bottom_width, z_left, z_right, normal_depth):
    area = (bottom_width + normal_depth * (z_left + z_right) / 2) * normal_depth
    return round(Q / area, 2) if area > 0 else 0.0


def calculate_ditch_full_capacity(bottom_width, z_left, z_right, n, S, allowable_depth):
    area = (bottom_width + allowable_depth * (z_left + z_right) / 2) * allowable_depth
    perimeter = bottom_width + allowable_depth * np.sqrt(1 + z_left**2) + allowable_depth * np.sqrt(1 + z_right**2)
    r_h = area / perimeter if perimeter > 0 else 0.01
    capacity = (1.486 / n) * area * r_h**(2/3) * S**0.5
    return round(capacity, 3)


def get_ditch_hydraulics(row):
    try:
        Q = float(row.get('Discharge (cfs)', 0))
        n = float(row.get('Manning n', 0.013))
        L = float(row.get('Length (ft)', 100))
        up_inv = float(row.get('Upstream Invert (ft)', 640))
        down_inv = float(row.get('Downstream Invert (ft)', 638))
        slope = max(0.0001, (up_inv - down_inv) / L)
        
        typ = row.get('Type', 'Trapezoidal')
        bottom = float(row.get('Bottom Width (ft)', 2.0))
        z_left = float(str(row.get('Left Slope', '3:1')).split(':')[0])
        z_right = float(str(row.get('Right Slope', '3:1')).split(':')[0])
        max_d = float(row.get('Allowable Depth (ft)', 1.0))
        
        normal_d = manning_ditch_normal_depth(Q, bottom, z_left, z_right, n, slope, max_d)
        velocity = calculate_ditch_velocity(Q, bottom, z_left, z_right, normal_d)
        capacity = calculate_ditch_full_capacity(bottom, z_left, z_right, n, slope, max_d)
        percent_full = min(100.0, (Q / capacity * 100)) if capacity > 0 else 0.0
        
        area = (bottom + normal_d * (z_left + z_right) / 2) * normal_d
        
        return {
            'Slope (%)': round(slope * 100, 3),
            'Normal Depth (ft)': normal_d,
            'Flow Area (ft²)': round(area, 3),
            'Velocity (ft/s)': velocity,
            'Full Capacity (cfs)': capacity,
            '% Full': round(percent_full, 1)
        }
    except:
        return {
            'Slope (%)': 0.0, 'Normal Depth (ft)': 0.0, 'Flow Area (ft²)': 0.0,
            'Velocity (ft/s)': 0.0, 'Full Capacity (cfs)': 0.0, '% Full': 0.0
        }