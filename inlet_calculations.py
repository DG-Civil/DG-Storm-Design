import numpy as np

# ==========================================
# CORE HYDRAULIC PROFILE UTILITIES
# ==========================================

def calculate_triangular_gutter_hydraulics(Q_total, Sx, S, n=0.013):
    """
    Calculates uniform spread and depth for a standard triangular gutter (HEC-22).
    """
    S = max(S, 0.0001)
    Sx = max(Sx, 0.001)
    # Izzard's modified Manning's equation for triangular channels (K_g = 0.56 US Customary)
    spread_ft = (Q_total * n / (0.56 * (S**0.5) * (Sx**1.67))) ** 0.375
    depth_ft = spread_ft * Sx
    return spread_ft, depth_ft

def calculate_v_ditch_hydraulics(Q_total, z_left, z_right, S, n=0.030):
    """
    Calculates uniform depth and top-width for a V-shaped ditch/channel.
    z_left and z_right are horizontal-to-vertical side slopes (e.g., 3 for 3:1).
    """
    S = max(S, 0.0001)
    # Geometry variables for V-ditch: Area = 0.5 * (z1 + z2) * d^2; Wetted Perimeter = d * (sqrt(1+z1^2) + sqrt(1+z2^2))
    z_sum = z_left + z_right
    p_factor = np.sqrt(1 + z_left**2) + np.sqrt(1 + z_right**2)
    
    # Iterative Manning's solver for normal depth d
    # Q = (1.486 / n) * A * R^(2/3) * S^0.5
    # Standard numerical iteration for depth
    d = 0.5  # initial guess
    for _ in range(15):
        A = 0.5 * z_sum * (d**2)
        P = d * p_factor
        if P == 0: break
        R = A / P
        Q_calc = (1.486 / n) * A * (R**(2/3)) * (S**0.5)
        d_res = Q_total - Q_calc
        # Derivative approximation to update guess
        d += d_res / ((1.486 / n) * (S**0.5) * 2 * d * z_sum) # simplified gradient step
        d = max(d, 0.001)
        
    spread_ft = d * z_sum
    return spread_ft, d


def calculate_composite_gutter_hydraulics(Q_total, Sx, S, a_in, W_dep_in, n=0.013):
    """FlowMaster Exact Integration (Divided Channel) for composite gutters."""
    S = max(S, 0.0001)
    Sx = max(Sx, 0.001)
    a = a_in / 12.0
    W_dep = W_dep_in / 12.0
    Sw = Sx + (a / W_dep)

    T_low, T_high = 0.001, 100.0
    for _ in range(100):
        T = (T_low + T_high) / 2.0
        if T <= W_dep:
            Q_guess = (0.56 / n) * (S**0.5) * (Sw**1.67) * (T**2.67)
        else:
            Q_road = (0.56 / n) * (S**0.5) * (Sx**1.67) * (T - W_dep)**2.67
            d_curb = (T * Sx) + a
            Tw = d_curb / Sw
            Q_gutter = (0.56 / n) * (S**0.5) * (Sw**1.67) * (Tw**2.67 - (Tw - W_dep)**2.67)
            Q_guess = Q_road + Q_gutter

        if Q_guess < Q_total: T_low = T
        else: T_high = T

    # Se back-calculated for HEC-22 capture capacity
    S_e = ((Q_total * n) / (0.56 * (S**0.5) * (T**2.67))) ** (1 / 1.67) if T > W_dep else Sw
    return S_e

# ==========================================
# INLET CALCULATIONS ON GRADE
# ==========================================

# def curb_inlet_on_grade(Q_total, L, Sx, S, a_in=0.0, W_dep_in=0.0, n=0.013):
#     if Q_total <= 0:
#         return {'captured_cfs': 0.0, 'efficiency': 0.0, 'bypass_cfs': 0.0, 'depth_ft': 0.0, 'depth_in': 0.0, 'spread_ft': 0.0}
    
#     # 1. Approach Hydraulics (Independent of depression)
#     spread_ft, depth_ft = calculate_triangular_gutter_hydraulics(Q_total, Sx, S, n)
    
#     # 2. Capture Efficiency (Uses Equivalent Cross Slope Se)
#     if a_in > 0 and W_dep_in > 0:
#         Se = calculate_composite_gutter_hydraulics(Q_total, Sx, S, a_in, W_dep_in, n)
#     else:
#         Se = Sx
        
#     K_t = 0.6
#     L100 = K_t * (Q_total**0.42) * (S**0.3) * (1 / (n * Se))**0.6
#     efficiency = 1.0 if L >= L100 else 1.0 - (1.0 - L / L100)**1.8
#     Q_captured = Q_total * efficiency
    
#     return {
#         'captured_cfs': round(Q_captured, 3),
#         'efficiency': round(efficiency * 100, 1),
#         'bypass_cfs': round(Q_total - Q_captured, 3),
#         'depth_ft': round(depth_ft, 3),
#         'depth_in': round(depth_ft * 12, 2),
#         'spread_ft': round(spread_ft, 2)
#     }

def curb_inlet_on_grade(Q_total, L, Sx, S, a_in=0.0, W_dep_in=0.0, n=0.013):
    if Q_total <= 0:
        return {'captured_cfs': 0.0, 'efficiency': 0.0, 'bypass_cfs': 0.0, 'depth_ft': 0.0, 'depth_in': 0.0, 'spread_ft': 0.0}

    # 1. Approach Hydraulics (Spread and Depth use the normal road Cross Slope Sx)
    S_adj = max(S, 0.0001)
    Sx_adj = max(Sx, 0.001)
    
    # Calculate Spread (T) using standard triangular gutter equation
    spread_ft = (Q_total * n / (0.56 * (S_adj**0.5) * (Sx_adj**1.67))) ** 0.375
    depth_ft = spread_ft * Sx_adj

    # 2. Capture Capacity (Use Equivalent Cross Slope Se)
    if a_in > 0 and W_dep_in > 0:
        a = a_in / 12.0
        W_dep = W_dep_in / 12.0
        
        # Calculate Frontal Flow Ratio (E0)
        # If spread < depression width, all flow is in the depression
        if spread_ft <= W_dep:
            E0 = 1.0
        else:
            E0 = 1.0 - (1.0 - (W_dep / spread_ft))**2.67
            
        # Equivalent Cross Slope (Se) calculation
        # Sw' is the depression slope relative to the roadway cross slope
        Sw_prime = a / W_dep
        Se = Sx_adj + (Sw_prime * E0)
    else:
        # No local depression, Se is just the roadway cross slope
        Se = Sx_adj

    # 3. Calculate LT (Length needed to capture all flow)
    # Using Se as the equivalent cross slope in the HEC-22/FlowMaster formula
    K_t = 0.6
    LT = K_t * (Q_total**0.42) * (S_adj**0.3) * (1 / (n * Se))**0.6

    # 4. Efficiency Calculation
    # If L >= LT, efficiency is 100%. Otherwise, use the standard power formula.
    if L >= LT:
        efficiency = 1.0
    else:
        efficiency = 1.0 - (1.0 - L / LT)**1.8
        
    Q_captured = Q_total * efficiency
    
    return {
        'captured_cfs': round(Q_captured, 3),
        'efficiency': round(efficiency * 100, 1),
        'bypass_cfs': round(Q_total - Q_captured, 3),
        'depth_ft': round(depth_ft, 3),
        'depth_in': round(depth_ft * 12, 2),
        'spread_ft': round(spread_ft, 2)
    }



def grate_inlet_on_grade(Q_total, L, W, Sx, S, n=0.013, splash_velocity_file=None):
    """
    Grate Inlet on Grade (HEC-22 Section 4.4.4.1)
    Splits flow into Frontal Flow (E_o) and Side Flow.
    """
    if Q_total <= 0:
        return {'captured_cfs': 0.0, 'efficiency': 0.0, 'bypass_cfs': 0.0, 'depth_ft': 0.0, 'depth_in': 0.0, 'spread_ft': 0.0}

    spread_ft, depth_ft = calculate_triangular_gutter_hydraulics(Q_total, Sx, S, n)
    
    # 1. Ratio of frontal flow to total flow (E_o)
    if spread_ft <= W:
        E_o = 1.0
    else:
        E_o = 1.0 - (1.0 - W / spread_ft)**2.67

    # 2. Velocity profile
    A = 0.5 * Sx * (spread_ft**2)
    V = Q_total / A if A > 0 else 0

    # 3. Frontal Flow Efficiency (R_f) - Accounts for splash-over
    # Simplification of HEC-22 curves (assuming a standard curved vane or P-50 grate profile)
    # In FlowMaster, R_f decreases if velocity exceeds specific thresholds based on grate length L
    V0 = 2.0 + 1.5 * L  # Empirical splash-over threshold velocity
    if V <= V0:
        R_f = 1.0
    else:
        R_f = max(0.0, 1.0 - 0.15 * (V - V0))

    # 4. Side Flow Efficiency (R_s)
    R_s = 1.0 / (1.0 + (0.15 * (V**1.8) / (Sx * (L**2.3))))

    # 5. Total Efficiency (E)
    efficiency = E_o * R_f + (1.0 - E_o) * R_s
    efficiency = min(max(efficiency, 0.0), 1.0)
    
    Q_captured = Q_total * efficiency
    
    return {
        'captured_cfs': round(Q_captured, 3),
        'efficiency': round(efficiency * 100, 1),
        'bypass_cfs': round(Q_total - Q_captured, 3),
        'depth_ft': round(depth_ft, 3),
        'depth_in': round(depth_ft * 12, 2),
        'spread_ft': round(spread_ft, 2)
    }


def ditch_inlet_on_grade(Q_total, L, W, z_left, z_right, S, n=0.030):
    """
    Ditch Inlet on Grade supporting asymmetrical geometry.
    Strictly caps values at 100% to protect against software/empirical calculation overflows.
    """
    if Q_total <= 0:
        return {'captured_cfs': 0.0, 'efficiency': 0.0, 'bypass_cfs': 0.0, 'depth_ft': 0.0, 'depth_in': 0.0, 'spread_ft': 0.0}

    spread_ft, depth_ft = calculate_v_ditch_hydraulics(Q_total, z_left, z_right, S, n)
    A_total = 0.5 * (z_left + z_right) * (depth_ft**2)
    V_avg = Q_total / A_total if A_total > 0 else 0

    W_half = W / 2.0
    spread_left = depth_ft * z_left
    spread_right = depth_ft * z_right

    # Left-wing area calculation
    if spread_left <= W_half:
        A_outside_left = 0.0
    else:
        A_outside_left = 0.5 * z_left * (((spread_left - W_half) / z_left) ** 2)

    # Right-wing area calculation
    if spread_right <= W_half:
        A_outside_right = 0.0
    else:
        A_outside_right = 0.5 * z_right * (((spread_right - W_half) / z_right) ** 2)

    A_frontal = max(0.0, A_total - (A_outside_left + A_outside_right))
    E_o = min(max(A_frontal / A_total if A_total > 0 else 1.0, 0.0), 1.0)

    # Splashover Velocity Checks
    V_o = 2.0 + 1.2 * L  
    R_f = 1.0 if V_avg <= V_o else min(max(1.0 - 0.15 * (V_avg - V_o), 0.0), 1.0)

    # Side Flow Efficiency
    Sx_equivalent = 2.0 / (z_left + z_right) if (z_left + z_right) > 0 else 0.01
    R_s = 1.0 / (1.0 + (0.15 * (V_avg**1.8) / (Sx_equivalent * (L**2.3))))

    # Final Combined System Efficiency (Strictly capped at 1.0 / 100%)
    efficiency = min(max(E_o * R_f + (1.0 - E_o) * R_s, 0.0), 1.0)
    Q_captured = Q_total * efficiency

    return {
        'captured_cfs': round(Q_captured, 3),
        'efficiency': round(efficiency * 100, 1),
        'bypass_cfs': round(Q_total - Q_captured, 3),
        'depth_ft': round(depth_ft, 3),
        'depth_in': round(depth_ft * 12, 2),
        'spread_ft': round(spread_ft, 2)
    }


# ==========================================
# INLET CALCULATIONS IN SAG (PONDING CONDITIONS)
# ==========================================

def curb_inlet_on_sag(Q_total, L, h_throat, Sx, a_in=0.0, W_dep_in=0.0):
    """
    Curb Inlet in Sag (HEC-22 Section 4.4.5.2)
    Dynamically applies depressed weir equations if local depression exists.
    """
    if Q_total <= 0:
        return {'captured_cfs': 0.0, 'efficiency': 100.0, 'bypass_cfs': 0.0, 'depth_ft': 0.0, 'depth_in': 0.0, 'spread_ft': 0.0}

    a = a_in / 12.0
    W_dep = W_dep_in / 12.0

    # Weir Flow
    if a > 0 and W_dep > 0:
        # HEC-22 Depressed Curb Inlet (Cw = 2.3, Effective Length includes sides)
        Cw = 2.3
        L_eff = L + 1.8 * W_dep
        d_weir_lip = (Q_total / (Cw * L_eff)) ** (2/3)
        d_weir = d_weir_lip + a  # Total depth at curb
    else:
        # Standard Undepressed Weir (Cw = 3.0)
        Cw = 3.0
        d_weir = (Q_total / (Cw * L)) ** (2/3)

    # Orifice Flow Equation (Uses total depth at the curb opening)
    Co = 0.67
    A_throat = L * h_throat
    d_orifice = (Q_total / (Co * A_throat * np.sqrt(2 * 32.2)))**2 + (h_throat / 2)

    transition_h = h_throat + a

    # Transition routing rule used by FlowMaster
    if d_weir <= transition_h:
        depth_ft = d_weir
    elif d_orifice > 1.4 * transition_h:
        depth_ft = d_orifice
    else:
        # Linear transition in the indefinite zone
        w_weight = (1.4 * transition_h - d_weir) / (0.4 * transition_h)
        w_weight = min(max(w_weight, 0.0), 1.0)
        depth_ft = (w_weight * d_weir) + ((1.0 - w_weight) * d_orifice)

    # Spread is mapped from the normal cross slope line
    spread_ft = (depth_ft - a) / Sx if (depth_ft - a) > 0 else 0.0
    depth_ft= depth_ft - a  # this is to make sure the depth is only above the local depression.
    
    return {
        'captured_cfs': round(Q_total, 3),
        'efficiency': 100.0,
        'bypass_cfs': 0.0,
        'depth_ft': round(depth_ft, 3),
        'depth_in': round(depth_ft * 12, 2),
        'spread_ft': round(spread_ft, 2)
    }

def calculate_grate_sag_capacity(d_curb, L, W, Sx):
    """
    Computes the exact mathematical flow capacity (Q) of a grate in sag 
    matching FlowMaster's HEC-22 multi-depth weir/orifice profile.
    """
    if d_curb <= 0:
        return 0.0

    # 1. FLOWMASTER/HEC-22 MULTI-DEPTH WEIR CAP (Eq 5.78)
    Cw = 3.0
    
    # d1 = Flow depth at middle of grate
    d1 = max(0.0, d_curb - (W / 2.0) * Sx)
    
    # d2 = Flow depth at side of grate opposite the curb
    d2 = max(0.0, d_curb - W * Sx)
    
    # Combined weir capacity across varying depth boundaries
    Q_weir = (Cw * L * (d1 ** 1.5)) + (2.0 * Cw * W * (d2 ** 1.5))

    # 2. ORIFICE CAPACITY (Eq 5.79)
    A_grate = L * W
    d_avg = max(0.0, d_curb - (W / 2.0) * Sx) # Average depth over grate footprint
    Q_orifice = 0.67 * A_grate * np.sqrt(2.0 * 32.2 * d_avg)

    # FlowMaster conservatively uses the lesser of weir or orifice capacity
    return min(Q_weir, Q_orifice)


def grate_inlet_on_sag(Q_total, L, W, Sx):
    """
    Grate Inlet in Sag - Solves for depth inversely to match FlowMaster.
    Accurately accounts for cross-slope depth drops to match 10.4 ft spread benchmarks.
    """
    if Q_total <= 0:
        return {'captured_cfs': 0.0, 'efficiency': 100.0, 'bypass_cfs': 0.0, 'depth_ft': 0.0, 'depth_in': 0.0, 'spread_ft': 0.0}

    # Inverse root finder (Secant Method) to isolate exact depth required
    d_guess = 0.5
    d_prev = 0.4
    
    for _ in range(40):
        q_guess = calculate_grate_sag_capacity(d_guess, L, W, Sx)
        q_prev = calculate_grate_sag_capacity(d_prev, L, W, Sx)
        
        diff_q = q_guess - q_prev
        if abs(diff_q) < 1e-6:
            break
            
        d_new = d_guess - (q_guess - Q_total) * (d_guess - d_prev) / diff_q
        d_prev = d_guess
        d_guess = max(0.001, d_new)
        
        if abs(q_guess - Q_total) < 1e-5:
            break

    depth_ft = d_guess
    spread_ft = depth_ft / Sx

    return {
        'captured_cfs': round(Q_total, 3),
        'efficiency': 100.0,
        'bypass_cfs': 0.0,
        'depth_ft': round(depth_ft, 3),
        'depth_in': round(depth_ft * 12, 2),
        'spread_ft': round(spread_ft, 2)
    }


def ditch_inlet_on_sag(Q_total, L, W, z_left, z_right):
    """
    Ditch Inlet in Sag (Grate in a ditch bottom functioning under ponded conditions)
    Perimeter includes all 4 sides because it sits freely in the valley floor center.
    """
    if Q_total <= 0:
        return {'captured_cfs': 0.0, 'efficiency': 100.0, 'bypass_cfs': 0.0, 'depth_ft': 0.0, 'depth_in': 0.0, 'spread_ft': 0.0}

    P = 2 * L + 2 * W  # 4 open sides
    A_grate = L * W

    d_weir = (Q_total / (3.0 * P)) ** (2/3)
    d_orifice = (Q_total / (0.67 * A_grate * np.sqrt(2 * 32.2))) ** 2

    depth_ft = d_weir if d_weir <= 0.4 else max(d_weir, d_orifice)
    
    # Spread uses full open top horizontal width of V-ditch profile
    spread_ft = depth_ft * (z_left + z_right)

    return {
        'captured_cfs': round(Q_total, 3),
        'efficiency': 100.0,
        'bypass_cfs': 0.0,
        'depth_ft': round(depth_ft, 3),
        'depth_in': round(depth_ft * 12, 2),
        'spread_ft': round(spread_ft, 2)
    }
