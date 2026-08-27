import numpy as np
from scipy.optimize import fsolve

def manning_pipe_normal_depth(Q, D, n, S):
    """Calculate normal depth in circular pipe using Manning's equation (iterative solver)"""
    if Q <= 0 or D <= 0 or S <= 0:
        return 0.0
    
    def partial_flow(theta):
        r = D / 2
        area = r**2 * (theta - np.sin(theta)) / 2
        perimeter = r * theta
        r_h = area / perimeter if perimeter > 0 else 0.01
        Q_calc = (1.486 / n) * area * r_h**(2/3) * S**0.5
        return Q_calc - Q
    
    # Initial guess
    d_guess = min(D * 0.5, Q * n / (1.486 * S**0.5 * (D/4)**(2/3)) * 0.8)
    d_guess = max(0.01, min(d_guess, D * 0.95))
    
    def find_theta(d):
        if d >= D:
            return 2 * np.pi
        r = D / 2
        return 2 * np.arccos(1 - 2 * d / D)
    
    def objective(d):
        theta = find_theta(d)
        return partial_flow(theta)
    
    d_sol = fsolve(objective, d_guess)
    normal_depth = max(0.01, min(float(d_sol[0]), D))
    return round(normal_depth, 3)


def manning_box_normal_depth(Q, width, height, n, S):
    """Calculate normal depth in rectangular box using Manning's"""
    if Q <= 0 or width <= 0 or height <= 0 or S <= 0:
        return 0.0
    
    def objective(d):
        d = min(max(d, 0.01), height * 0.99)
        area = width * d
        perimeter = width + 2 * d
        r_h = area / perimeter
        Q_calc = (1.486 / n) * area * r_h**(2/3) * S**0.5
        return Q_calc - Q
    
    d_guess = min(height * 0.6, Q * n / (1.486 * S**0.5 * (width*height / (width + 2*height))**(2/3)))
    d_sol = fsolve(objective, d_guess)
    normal_depth = max(0.01, min(float(d_sol[0]), height))
    return round(normal_depth, 3)


def calculate_full_capacity_pipe(D, n, S):
    """Full flow capacity for circular pipe"""
    if D <= 0 or S <= 0:
        return 0.0
    area = np.pi * (D/2)**2
    r_h = D/4
    return (1.486 / n) * area * r_h**(2/3) * S**0.5


def calculate_full_capacity_box(width, height, n, S):
    """Full flow capacity for box"""
    if width <= 0 or height <= 0 or S <= 0:
        return 0.0
    area = width * height
    perimeter = 2 * (width + height)
    r_h = area / perimeter
    return (1.486 / n) * area * r_h**(2/3) * S**0.5


def get_pipe_hydraulics(row):
    try:
        Q = float(row.get('Discharge (cfs)', 0))
        n = float(row.get('Manning n', 0.013))
        L = float(row.get('Length (ft)', 100))
        up_inv = float(row.get('Upstream Invert (ft)', 640))
        down_inv = float(row.get('Downstream Invert (ft)', 638))
        slope = max(0.0001, (up_inv - down_inv) / L)
        
        size_str = str(row.get('Span/Diameter', '24 in'))
        typ = row.get('Type', 'Pipe')
        
        if typ == 'Pipe':
            D_in = float(size_str.replace(' in', '').strip())
            D = D_in / 12.0
            capacity = calculate_full_capacity_pipe(D, n, slope)
            normal_d = manning_pipe_normal_depth(Q, D, n, slope)
            
            # More accurate wetted area for circular pipe
            if normal_d >= D:
                flow_area = np.pi * (D/2)**2
            else:
                r = D / 2
                theta = 2 * np.arccos(1 - 2 * normal_d / D)
                flow_area = r**2 * (theta - np.sin(theta)) / 2
            
            velocity = Q / flow_area if flow_area > 0 else 0
            area_full = np.pi * (D/2)**2
            
        else:  # Box
            width = float(size_str.replace(' ft', '').strip())
            height = float(row.get('Depth (ft)', width))
            capacity = calculate_full_capacity_box(width, height, n, slope)
            normal_d = manning_box_normal_depth(Q, width, height, n, slope)
            flow_area = width * normal_d
            area_full = width * height
            velocity = Q / flow_area if flow_area > 0 else 0

        percent_full = min(100.0, (Q / capacity * 100)) if capacity > 0 else 0.0

        return {
            'Slope (%)': round(slope * 100, 3),
            'Normal Depth (ft)': normal_d,
            'Flow Area (ft²)': round(flow_area, 3),
            'Velocity (ft/s)': round(velocity, 2),
            'Full Capacity (cfs)': round(capacity, 3),
            '% Full': round(percent_full, 1)
        }
    except Exception:
        return {
            'Slope (%)': 0.0,
            'Normal Depth (ft)': 0.0,
            'Flow Area (ft²)': 0.0,
            'Velocity (ft/s)': 0.0,
            'Full Capacity (cfs)': 0.0,
            '% Full': 0.0
        }
