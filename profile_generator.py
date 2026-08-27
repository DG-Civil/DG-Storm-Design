import os
import sys
import json
import math
import csv
import traceback
from datetime import datetime
import platform
import ezdxf

def run_headless_pipeline(payload_path):
    # Hardcoded error reporting path requested by user
    TARGET_LOG_DIR =  os.path.abspath("Storm-design")
    LOG_FILE_PATH = os.path.join(TARGET_LOG_DIR, "engine_errors.log")

    try:
        print("[CORE ENGINE] Processing layout design vectors out of: " + str(payload_path))
        
        with open(payload_path, "r", encoding="utf-8") as f:
            payload = json.load(f)
            
        start_node = payload["start_node"]
        outfall_node = payload["outfall_node"]
        method = payload["method"]
        user_hgl = payload["user_hgl"]
        cad_format = payload["format"]
        len_method = payload.get("length_method", "Center-to-Center")
        scale_y = float(payload.get("vertical_exaggeration", 5.0))  
        row_idx = payload.get("row_index", 0)
        
        with open(payload["nodes_json"], "r", encoding="utf-8") as f: nodes_list = json.load(f)
        with open(payload["links_json"], "r", encoding="utf-8") as f: links_list = json.load(f)
        with open(payload["pipes_json"], "r", encoding="utf-8") as f: pipes_list = json.load(f)
        with open(payload["inlets_json"], "r", encoding="utf-8") as f: inlets_list = json.load(f)
        with open(payload["ditches_json"], "r", encoding="utf-8") as f: ditches_list = json.load(f)

        all_conduits = pipes_list + ditches_list

        # ==========================================
        # MASTER LIBRARY CSV DATA EXTRACTION
        # ==========================================
        csv_library_path = os.path.abspath(os.path.join("files", "structure-library.csv"))
        library_data = {}
        
        if os.path.exists(csv_library_path):
            try:
                with open(csv_library_path, mode='r', encoding='utf-8-sig') as csvfile:
                    reader = csv.DictReader(csvfile)
                    for row in reader:
                        if row.get('Name'):
                            library_data[str(row['Name']).strip()] = row
            except Exception as e:
                print(f"[LIBRARY ERROR] Failed reading library dataset: {str(e)}")
                
        # --- BOX CULVERT SPECIFICATION TABLE LOADING ---
        csv_box_path = os.path.abspath(os.path.join("files", "Box-pipe.csv"))
        box_library_data = {}
        
        if os.path.exists(csv_box_path):
            try:
                with open(csv_box_path, mode='r', encoding='utf-8-sig') as csvfile:
                    reader = csv.DictReader(csvfile)
                    for row in reader:
                        # Convert CSV values to float first, then int to strip any decimals like 2.0
                        raw_csv_span = row.get('Span_FT', '').strip()
                        raw_csv_depth = row.get('Depth_FT', '').strip()
                        
                        if raw_csv_span and raw_csv_depth:
                            span_key = str(int(float(raw_csv_span)))
                            depth_key = str(int(float(raw_csv_depth)))
                            box_library_data[(span_key, depth_key)] = row
                print(f"[LIBRARY] Successfully cataloged {len(box_library_data)} box culvert profiles.")
            except Exception as e:
                print(f"[LIBRARY ERROR] Failed reading Box-pipe dataset: {str(e)}")
                
        # ==========================================
        # STEP 1: TRACE TOPOLOGICAL CONNECTIONS
        # ==========================================
        next_node_map = {}
        link_name_map = {}
        for row in links_list:
            next_node_map[row['Start Node']] = row['End Node']
            link_name_map[(row['Start Node'], row['End Node'])] = row['Link Name']

        profile_path = [start_node]
        curr = start_node
        safety_counter = 0
        
        while curr != outfall_node and safety_counter < 100:
            safety_counter += 1
            if curr in next_node_map:
                curr = next_node_map[curr]
                profile_path.append(curr)
            else:
                raise ValueError(f"Topology Gap: Reached node '{curr}', but could not find a downstream connection to outfall '{outfall_node}'")

        # ==========================================
        # STEP 2: DIMENSIONAL LOOKUPS
        # ==========================================
        node_geo_map = {} 
        node_types = {}
        node_station_data = {}
        
        for n_name in profile_path:
            n_match = [n for n in nodes_list if n.get('Node Name') == n_name]
            node_record = n_match[0] if (isinstance(n_match, list) and len(n_match) > 0) else {}
            
            n_type = str(node_record.get('Type', 'Manhole')).strip()
            struct_id = str(node_record.get('Structure ID', 'None')).strip()
            
            node_types[n_name] = n_type
            node_station_data[n_name] = node_record  
            
            if n_type in ['Joint', 'Transition', 'Outfall'] or struct_id == 'None' or not struct_id:
                node_geo_map[n_name] = {
                    'width': 0.0, 'wall_thick': 0.0, 'top_thick': 0.0, 'bot_thick': 0.0, 
                    'k_value': 0.0, 'is_line_only': True, 'display_id': struct_id if (struct_id and struct_id != 'None') else n_type
                }
            else:
                w_val, t_wall, t_top, t_bot, k_val = 5.0, 0.5, 0.5, 0.5, 0.2
                if struct_id in library_data:
                    lib_rec = library_data[struct_id]
                    raw_length = lib_rec.get('Length')
                    if raw_length:
                        try: w_val = float(str(raw_length).lower().replace('ft', '').replace('in', '').strip())
                        except ValueError: pass
                    raw_thick = lib_rec.get('Wall_Thickness_IN')
                    if raw_thick:
                        try: t_wall = float(str(raw_thick).lower().replace('in', '').replace('ft', '').strip()) / 12.0
                        except ValueError: pass
                    raw_top_thick = lib_rec.get('Top_Thickness_IN')
                    if raw_top_thick:
                        try: t_top = float(str(raw_top_thick).lower().replace('in', '').replace('ft', '').strip()) / 12.0
                        except ValueError: pass
                    raw_bot_thick = lib_rec.get('Bottom_Thickness_IN')
                    if raw_bot_thick:
                        try: t_bot = float(str(raw_bot_thick).lower().replace('in', '').replace('ft', '').strip()) / 12.0
                        except ValueError: pass
                    raw_k = lib_rec.get('Headloss_K_Value')
                    if raw_k:
                        try: k_val = float(str(raw_k).strip())
                        except ValueError: pass
                            
                node_geo_map[n_name] = {
                    'width': w_val, 'wall_thick': t_wall, 'top_thick': t_top, 'bot_thick': t_bot,
                    'k_value': k_val, 'is_line_only': False, 'display_id': struct_id
                }

        # ==========================================
        # STEP 3: GEOMETRIC STATION ALIGNMENTS
        # ==========================================
        ordered_elements = []
        station = 0.0

        for idx in range(len(profile_path) - 1):
            u_node = profile_path[idx]
            d_node = profile_path[idx+1]
            l_name = link_name_map.get((u_node, d_node)) or f"Link-{u_node}-to-{d_node}"
            
            node_up_match = [n for n in nodes_list if n.get('Node Name') == u_node]
            node_dn_match = [n for n in nodes_list if n.get('Node Name') == d_node]
            n_up_rec = node_up_match[0] if len(node_up_match) > 0 else {}
            n_dn_rec = node_dn_match[0] if len(node_dn_match) > 0 else {}
            
            ground_up = float(n_up_rec.get('Ground Elev (ft)', 650.0))
            ground_down = float(n_dn_rec.get('Ground Elev (ft)', 648.0))
            
            pipe_match = [p for p in pipes_list if p.get('Name') == l_name]
            ditch_match = [d for d in ditches_list if d.get('Name') == l_name]
            is_pipe = True if pipe_match else False
            element_data = pipe_match[0] if (is_pipe and len(pipe_match) > 0) else (ditch_match[0] if len(ditch_match) > 0 else {})
                
            raw_length = float(element_data.get('Length (ft)', 50.0))
            inv_up = float(element_data.get('Upstream Invert (ft)', 640.0))
            inv_down = float(element_data.get('Downstream Invert (ft)', 638.0))
            slope_val = float(element_data.get('Slope (%)', 0.50))
            
            span_str = str(element_data.get('Span/Diameter', '24 in'))
            if is_pipe:
                dia_ft = float(span_str.replace('in', '').strip()) / 12.0 if 'in' in span_str else float(span_str.replace('ft', '').strip())
                height = dia_ft
                pipe_wall_thick = (dia_ft + 1.0) / 12.0
            else:
                height = float(element_data.get('Allowable Depth (ft)', 2.0))
                pipe_wall_thick = 0.1

            def get_calculated_node_invert(node_id):
                matched_inverts = []
                for cond in all_conduits:
                    if cond.get('Start Node') == node_id and cond.get('Upstream Invert (ft)'):
                        matched_inverts.append(float(cond['Upstream Invert (ft)']))
                    if cond.get('End Node') == node_id and cond.get('Downstream Invert (ft)'):
                        matched_inverts.append(float(cond['Downstream Invert (ft)']))
                return min(matched_inverts) if matched_inverts else min(inv_up, inv_down)

            struct_inv_up = get_calculated_node_invert(u_node)
            struct_inv_down = get_calculated_node_invert(d_node)

            w_up, t_up_wall, t_up_top, t_up_bot = node_geo_map[u_node]['width'], node_geo_map[u_node]['wall_thick'], node_geo_map[u_node]['top_thick'], node_geo_map[u_node]['bot_thick']
            w_dn, t_dn_wall, t_dn_top, t_dn_bot = node_geo_map[d_node]['width'], node_geo_map[d_node]['wall_thick'], node_geo_map[d_node]['top_thick'], node_geo_map[d_node]['bot_thick']
            
            if len_method == "Construction (Inner Wall to Inner Wall)":
                box_start_x = station
                p_start_x = station + t_up_wall + w_up
                p_end_x = p_start_x + raw_length
                box_end_x = p_end_x
                next_station = box_end_x + t_dn_wall
            else:
                box_start_x = station
                p_start_x = station + ((w_up + (2 * t_up_wall)) / 2.0)
                p_end_x = station + raw_length + ((w_dn + (2 * t_dn_wall)) / 2.0)
                box_end_x = station + raw_length
                next_station = station + raw_length

            ordered_elements.append({
                'name': l_name, 'up_node': u_node, 'down_node': d_node,
                'length': raw_length, 'height': height, 'is_pipe': is_pipe, 'size_str': span_str,
                'inv_up': inv_up, 'inv_down': inv_down, 'slope': slope_val,
                'struct_inv_up': struct_inv_up, 'struct_inv_down': struct_inv_down,
                'ground_up': ground_up, 'ground_down': ground_down,
                'w_up': w_up, 'w_dn': w_dn,
                't_up_wall': t_up_wall, 't_dn_wall': t_dn_wall,
                't_up_top': t_up_top, 't_up_bot': t_up_bot,
                't_dn_top': t_dn_top, 't_dn_bot': t_dn_bot,
                'type_up': node_types.get(u_node, 'Manhole'), 'type_dn': node_types.get(d_node, 'Manhole'),
                'pipe_wall': pipe_wall_thick, 'p_start_x': p_start_x, 'p_end_x': p_end_x,
                'box_start_x': box_start_x, 'box_end_x': box_end_x
            })
            station = next_station

        # ==========================================
        # STEP 3.5: HYDRAULIC PROFILE SIMULATOR
        # ==========================================
        g_accel = 32.2 
        node_hgl_map = {}
        hgl_profile_points = []
        last_elem = ordered_elements[-1]
        terminal_outfall = last_elem['down_node']
        
        static_pipe_dict_map = {p.get('Name'): p for p in pipes_list if isinstance(p, dict) and p.get('Name')}
        static_ditch_dict_map = {d.get('Name'): d for d in ditches_list if isinstance(d, dict) and d.get('Name')}
        
        is_last_ditch = last_elem['name'] in static_ditch_dict_map
        p_rec = static_ditch_dict_map.get(last_elem['name']) if is_last_ditch else static_pipe_dict_map.get(last_elem['name'], {})
        
        if is_last_ditch:
            starting_hgl = last_elem['inv_down'] + float(p_rec.get('Normal Depth (ft)', 0.5))
        elif method == "User Input":
            starting_hgl = float(user_hgl)
        elif method == "Crown":
            starting_hgl = last_elem['inv_down'] + last_elem['height']
        else:  
            tw_depth = max(float(p_rec.get('Normal Depth (ft)', 0.0)), float(p_rec.get('Critical Depth (ft)', 0.0)))
            starting_hgl = min(last_elem['inv_down'] + tw_depth, last_elem['inv_down'] + last_elem['height'])

        node_hgl_map[terminal_outfall] = starting_hgl
        active_pipe_tailwater = starting_hgl

        # --- EXTRACT LENGTH METHOD FROM YOUR PAYLOAD ---
        # Checks for "Center-to-Center" vs "Inner Wall to Inner Wall"
        len_method_scenario = str(payload.get("length_method", "Inner Wall to Inner Wall")).strip().lower()

        for i, elem in enumerate(reversed(ordered_elements)):
            u_node = elem['up_node']
            is_ditch = elem['name'] in static_ditch_dict_map
            p_rec = static_ditch_dict_map.get(elem['name']) if is_ditch else static_pipe_dict_map.get(elem['name'], {})
            
            norm_depth = float(p_rec.get('Normal Depth (ft)', 0.0))
            velocity = float(p_rec.get('Velocity (ft/s)', 2.0))
            discharge = float(p_rec.get('Discharge (cfs)', 0.0))
            
            if is_ditch:
                hgl_at_p_end = max(active_pipe_tailwater, elem['inv_down'] + norm_depth)
                hgl_at_p_start = max(hgl_at_p_end, elem['inv_up'] + norm_depth)
            else:
                manning_n = float(p_rec.get('Manning n', 0.013))
                area_full = (math.pi * (elem['height'] ** 2)) / 4.0 if elem['is_pipe'] else (float(p_rec.get('Bottom Width (ft)', 2.0)) * elem['height'])
                sf = ((discharge * manning_n) / (1.486 * area_full * ((elem['height']/4.0)**(2.0/3.0)))) ** 2 if discharge > 0 else 0.0
                
                hgl_at_p_end = max(active_pipe_tailwater, elem['inv_down'] + norm_depth)
                hgl_at_p_start = max(hgl_at_p_end + (sf * elem['length']), elem['inv_up'] + norm_depth)

            custom_k = float(node_geo_map[u_node]['k_value'])
            hj_junction_loss = custom_k * ((velocity ** 2) / (2.0 * g_accel)) if (discharge > 0 and custom_k > 0) else 0.0
            hgl_after_junction_loss = hgl_at_p_start + hj_junction_loss
            
            # --- DIVERGENT PROFILE ROUTING ---
            if "center" in len_method_scenario:
                # Center-to-Center Calculation Model:
                # No wall boundaries exist. Pipes clip completely at the center point.
                current_segment_points = [
                    (elem['p_start_x'], hgl_after_junction_loss), # Top of vertical energy drop line
                    (elem['p_start_x'], hgl_at_p_start),          # Bottom of vertical drop line
                    (elem['p_end_x'], hgl_at_p_end)               # Friction slope line to link downstream end
                ]
            else:
                # Construction / Inner Wall to Inner Wall Model (Original Method):
                # Implements structural widths with horizontal step drops inside structure boxes
                mid_struct_x = elem['box_start_x'] + ((elem['p_start_x'] - elem['box_start_x']) / 2.0)
                current_segment_points = [
                    (elem['box_start_x'], hgl_after_junction_loss), (mid_struct_x, hgl_after_junction_loss),        
                    (mid_struct_x, hgl_at_p_start), (elem['p_start_x'], hgl_at_p_start), (elem['p_end_x'], hgl_at_p_end)                  
                ]
                
            hgl_profile_points = current_segment_points + hgl_profile_points
            node_hgl_map[u_node] = hgl_after_junction_loss
            active_pipe_tailwater = hgl_after_junction_loss

        # Close out trailing profile terminus point safely
        if "center" in len_method_scenario:
            hgl_profile_points.append((last_elem['p_end_x'], starting_hgl))
        else:
            hgl_profile_points.append((last_elem['box_end_x'], starting_hgl))
            
            
        # ==========================================
        # STEP 3.55: ENGINEERING GRID MATRIX GENERATION
        # ==========================================
        raw_all_grounds = [elem['ground_up'] for elem in ordered_elements] + [elem['ground_down'] for elem in ordered_elements]
        raw_all_inverts = [elem['inv_up'] for elem in ordered_elements] + [elem['inv_down'] for elem in ordered_elements]
        grid_min_elev = math.floor((min(raw_all_inverts) - 20.0) / 5.0) * 5
        grid_max_elev = math.ceil((max(raw_all_grounds) + 20.0) / 5.0) * 5

        grid_step_x = 5.0 * scale_y
        grid_min_x = ordered_elements[0]['box_start_x'] - (2.0 * grid_step_x)
        grid_max_x = ordered_elements[-1]['box_end_x'] + (2.0 * grid_step_x)

        grid_metadata = {
            'min_elev': grid_min_elev, 'max_elev': grid_max_elev,
            'min_x': grid_min_x, 'max_x': grid_max_x, 'step_x': grid_step_x, 'step_y': 5.0 * scale_y
        }

        # ==========================================
        # STEP 4: VECTOR RENDERING SUB-ROUTINES (ezdxf)
        # ==========================================
        
        doc = ezdxf.new('R2010')
        msp = doc.modelspace()
        
        # Mapping FreeCAD layers and colors to ezdxf standards
        doc.layers.new(name='Ground', dxfattribs={'color': 3})      # Green
        doc.layers.new(name='Hatch', dxfattribs={'color': 8})       # Dark Gray
        doc.layers.new(name='Text', dxfattribs={'color': 7})        # White/Black
        doc.layers.new(name='Pipe', dxfattribs={'color': 5})        # Blue
        doc.layers.new(name='Structure', dxfattribs={'color': 40})  # Orange
        doc.layers.new(name='Joint', dxfattribs={'color': 6})       # Magenta
        doc.layers.new(name='HGL', dxfattribs={'color': 1})         # Red
        doc.layers.new(name='Grid', dxfattribs={'color': 252})      # Light Gray

        drawn_structures = set()

        # Update this line to pull 'Offset' from your data source
        node_data_map = {n.get('Node Name'): {
            'station': str(n.get('Station', '0+00')), 
            'offset': str(n.get('Offset', '0.00')) 
            } for n in nodes_list}

        # OS checking print logic (kept for consistency)
        base_dir = os.path.dirname(os.path.abspath(__file__))
        font_path = os.path.join(base_dir, "fonts", "Arial.ttf")
        #if platform.system() == "Windows":
        #    font_path = "C:/Windows/Fonts/arial.ttf" if os.path.exists("C:/Windows/Fonts/arial.ttf") else "C:/Windows/Fonts/msgothic.ttc"
        #else:
        #    linux_arial = "/usr/share/fonts/truetype/msttcorefonts/Arial.ttf"
        #    linux_fallback = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
        #    font_path = linux_arial if os.path.exists(linux_arial) else linux_fallback
        
        print(f"[FONT SETUP] Active font path selected: {font_path} (Used for reference, ezdxf handles native styles)")

        g_meta = grid_metadata
        scaled_min_y, scaled_max_y = g_meta['min_elev'] * scale_y, g_meta['max_elev'] * scale_y
        raw_origin_x, system_start_x, system_end_x = ordered_elements[0]['box_start_x'], ordered_elements[0]['p_start_x'], ordered_elements[-1]['p_end_x']

        def format_engineering_station(current_x, reference_zero_x):
            delta_feet = current_x - reference_zero_x
            return f"{int(abs(delta_feet) // 100)}+{abs(delta_feet) % 100:05.2f}"

        grid_v_lines_x = []
        curr_grid_x = g_meta['min_x']
        while curr_grid_x <= (g_meta['max_x'] + 0.1):
            grid_v_lines_x.append(curr_grid_x)
            curr_grid_x += g_meta['step_x']

        hgl_text_positions = list(grid_v_lines_x)
        for elem in ordered_elements:
            if not any(abs(pos - elem['p_start_x']) < 0.1 for pos in hgl_text_positions): hgl_text_positions.append(elem['p_start_x'])
            if not any(abs(pos - elem['p_end_x']) < 0.1 for pos in hgl_text_positions): hgl_text_positions.append(elem['p_end_x'])
        hgl_text_positions.sort()

        grid_box_height_scaled = 5.0 * scale_y
        text_font_size = grid_box_height_scaled / 10.0
        clearance_buffer = text_font_size * 0.5

        # Render Grid Stations
        for g_x in grid_v_lines_x:
            msp.add_line((g_x, scaled_min_y), (g_x, scaled_max_y), dxfattribs={'layer': 'Grid'})

            station_string = format_engineering_station(g_x, raw_origin_x)
            text_x = g_x - ((len(station_string) * (text_font_size * 0.65)) / 2.0)
            text_y = scaled_min_y - (text_font_size * 2.5)
            msp.add_text(station_string, dxfattribs={'layer': 'Text', 'height': text_font_size}).set_placement((text_x, text_y))

        # Render HGL Annotations
        for target_x in hgl_text_positions:
            if system_start_x <= target_x <= system_end_x:
                inside_structure = False
                for elem in ordered_elements:
                    if (elem['box_start_x'] <= target_x < elem['p_start_x']) or (elem['p_end_x'] < target_x <= elem['box_end_x']):
                        inside_structure = True
                        break
                if inside_structure: continue

                matched_hgl_elev = None
                for s_idx in range(len(hgl_profile_points) - 1):
                    pt_left, pt_right = hgl_profile_points[s_idx], hgl_profile_points[s_idx + 1]
                    if (pt_left[0] <= target_x <= pt_right[0]) or (pt_right[0] <= target_x <= pt_left[0]):
                        dx = pt_right[0] - pt_left[0]
                        matched_hgl_elev = pt_left[1] + (((target_x - pt_left[0]) / dx) * (pt_right[1] - pt_left[1])) if abs(dx) > 0.0001 else max(pt_left[1], pt_right[1])
                        break
                
                if matched_hgl_elev is None: continue
                    
                hgl_label_text = f"HGL: {matched_hgl_elev:.2f}'"
                text_x = target_x + (text_font_size / 2.0)
                text_y = scaled_min_y + 0.5
                msp.add_text(hgl_label_text, dxfattribs={'layer': 'Text', 'height': text_font_size, 'rotation': 90.0}).set_placement((text_x, text_y))

        # Horizontal Elevation Grids
        curr_elev = g_meta['min_elev']
        while curr_elev <= g_meta['max_elev']:
            current_scaled_y = curr_elev * scale_y
            msp.add_line((g_meta['min_x'], current_scaled_y), (g_meta['max_x'], current_scaled_y), dxfattribs={'layer': 'Grid'})

            text_x = g_meta['min_x'] - (text_font_size * 4.0)
            text_y = current_scaled_y - (text_font_size * 0.4)
            msp.add_text(f"{curr_elev}", dxfattribs={'layer': 'Text', 'height': text_font_size}).set_placement((text_x, text_y))
            curr_elev += 5

        # Structure Rendering Loop
        for elem in ordered_elements:
            g_start_x = elem['box_start_x'] + ((elem['w_up'] + 2*elem['t_up_wall'])/2.0)
            g_start_y = elem['ground_up'] * scale_y
            g_end_x = elem['box_end_x'] + ((elem['w_dn'] + 2*elem['t_dn_wall'])/2.0)
            g_end_y = elem['ground_down'] * scale_y
            msp.add_line((g_start_x, g_start_y), (g_end_x, g_end_y), dxfattribs={'layer': 'Ground'})

            structure_mappings = [
                {
                    'node_name': elem['up_node'], 'w': elem['w_up'], 't_wall': elem['t_up_wall'], 
                    't_top': elem['t_up_top'], 't_bot': elem['t_up_bot'],
                    's_inv': elem['struct_inv_up'], 'ground': elem['ground_up'], 'n_type': elem['type_up'], 'x_pos': elem['box_start_x']
                },
                {
                    'node_name': elem['down_node'], 'w': elem['w_dn'], 't_wall': elem['t_dn_wall'], 
                    't_top': elem['t_dn_top'], 't_bot': elem['t_dn_bot'],
                    's_inv': elem['struct_inv_down'], 'ground': elem['ground_down'], 'n_type': elem['type_dn'], 'x_pos': elem['box_end_x']
                }
            ]

            for s_info in structure_mappings:
                n_name = s_info['node_name']
                if n_name in drawn_structures: continue
                drawn_structures.add(n_name)
                
                w = s_info['w']
                t_wall = s_info['t_wall']
                s_inv_scaled = s_info['s_inv'] * scale_y
                ground_scaled = s_info['ground'] * scale_y
                x_pos = s_info['x_pos']
                
                t_top_scaled_y = s_info['t_top'] * scale_y
                t_bot_scaled_y = s_info['t_bot'] * scale_y
                display_id_label = node_geo_map[n_name]['display_id']

                struct_lines = [
                    f"{n_name}",
                    f"TYPE: {display_id_label}",
                    f"Elev: {s_info['ground']:.2f}'",
                    f"Off: {float(node_data_map.get(n_name, {}).get('offset', '0.00')):.2f}",
                    f"Sta: {node_data_map.get(n_name, {}).get('station', '0+00')}"
                ]
                
                txt_center_x = x_pos + t_wall + (w / 2.0) if w > 0 else x_pos
                txt_center_y = ground_scaled + 2.0
                if node_geo_map[n_name]['is_line_only']:
                    j_start_y = s_inv_scaled
                    j_end_y = ground_scaled
    
                    # SAFEGUARD: Check if the points are identical to prevent rendering errors
                    if abs(j_start_y - j_end_y) < 0.001:
                        j_start_y = s_inv_scaled - (0.01 * scale_y)

                    msp.add_line((x_pos, j_start_y), (x_pos, j_end_y), dxfattribs={'layer': 'Joint'})

                else:
                    xl_out, xl_in = x_pos, x_pos + t_wall
                    xr_in, xr_out = x_pos + t_wall + w, x_pos + (2 * t_wall) + w
                    yb_out, yb_in = s_inv_scaled - t_bot_scaled_y, s_inv_scaled
                    yt_in, yt_out = ground_scaled - t_top_scaled_y, ground_scaled

                    poly_out = [(xl_out, yb_out), (xr_out, yb_out), (xr_out, yt_out), (xl_out, yt_out), (xl_out, yb_out)]
                    poly_in = [(xl_in, yb_in), (xr_in, yb_in), (xr_in, yt_in), (xl_in, yt_in), (xl_in, yb_in)]
                    
                    msp.add_lwpolyline(poly_out, dxfattribs={'layer': 'Structure'})
                    msp.add_lwpolyline(poly_in, dxfattribs={'layer': 'Structure'})

                    h_step = 0.5 / scale_y if scale_y > 1.0 else 0.5
                    zones = [
                        {'x1': xl_out, 'x2': xl_in, 'y1': yb_out, 'y2': yt_out}, {'x1': xr_in, 'x2': xr_out, 'y1': yb_out, 'y2': yt_out},
                        {'x1': xl_in, 'x2': xr_in, 'y1': yb_out, 'y2': yb_in}, {'x1': xl_in, 'x2': xr_in, 'y1': yt_in, 'y2': yt_out}
                    ]
                    for zone in zones:
                        zx1, zx2, zy1, zy2 = zone['x1'], zone['x2'], zone['y1'], zone['y2']
                        offset = -((zx2 - zx1) + (zy2 - zy1))
                        while offset < ((zx2 - zx1) + (zy2 - zy1)):
                            xs_h, xe_h = zx1 + offset, zx1 + offset + (zy2 - zy1)
                            if not (xe_h < zx1 or xs_h > zx2):
                                x1_t = max(zx1, min(zx2, xs_h))
                                y1_t = max(zy1, min(zy2, zy1 + (x1_t - xs_h)))
                                x2_t = max(zx1, min(zx2, xe_h))
                                y2_t = max(zy1, min(zy2, zy2 - (xe_h - x2_t)))
                                if x1_t != x2_t:
                                    msp.add_line((x1_t, y1_t), (x2_t, y2_t), dxfattribs={'layer': 'Hatch'})
                            offset += h_step

                for line_idx, line_text in enumerate(struct_lines):
                    line_offset_x = line_idx * (text_font_size * 1.5)
                    text_x = txt_center_x - line_offset_x + (text_font_size / 2.0)
                    text_y = txt_center_y
                    msp.add_text(line_text, dxfattribs={'layer': 'Text', 'height': text_font_size, 'rotation': 90.0}).set_placement((text_x, text_y))

        # Conduit Rendering Loop
        for elem in ordered_elements:
            xs, xe = elem['p_start_x'], elem['p_end_x']
            iu, idn = elem['inv_up'] * scale_y, elem['inv_down'] * scale_y
            h = elem['height'] * scale_y
            
            is_ditch_element = elem['name'] in static_ditch_dict_map
            p_rec = static_ditch_dict_map.get(elem['name']) if is_ditch_element else static_pipe_dict_map.get(elem['name'], {})
            p_slope = float(p_rec.get('Slope (%)', 0.50))

            # Determine structural classification
            conduit_ui_type = str(p_rec.get('Type', 'Pipe')).strip().lower()
            is_box_conduit = 'box' in conduit_ui_type and not is_ditch_element

            # Assign top and bottom wall thicknesses based on type
            if is_ditch_element:
                raw_allowable_depth = float(p_rec.get('Allowable Depth (ft)', 3.0))
                if raw_allowable_depth <= 0.0: raw_allowable_depth = 3.0
                h = raw_allowable_depth * scale_y
                t_ditch_bot = (2.0 / 12.0) * scale_y  
                t_top = 0.0
                t_bot = t_ditch_bot
                
                p_bot_pts = [(xs, iu - t_bot), (xe, idn - t_bot), (xe, idn), (xs, iu), (xs, iu - t_bot)]
                p_flow_pts = [(xs, iu), (xe, idn), (xe, idn + h), (xs, iu + h), (xs, iu)]
                p_top_pts = [(xs, iu + h), (xe, idn + h)]
                
            elif is_box_conduit:
                # 1. Extract raw strings and clean up units ('ft', 'in')
                raw_span = str(p_rec.get('Span/Diameter', '2.0')).lower().replace('ft','').replace('in','').strip()
                raw_depth = str(p_rec.get('Depth (ft)', '2.0')).lower().replace('ft','').replace('in','').strip()
                
                # 2. Convert to float first, then down to integer string
                try:
                    span_lookup = str(int(float(raw_span)))
                    depth_lookup = str(int(float(raw_depth)))
                except ValueError:
                    span_lookup = raw_span
                    depth_lookup = raw_depth
                
                # 3. Query the database map using clean integer keys
                matched_box = box_library_data.get((span_lookup, depth_lookup))
                
                if matched_box:
                    try:
                        # Extract raw thickness in inches
                        raw_t_top = float(matched_box.get('Top_Thickness_IN', 6.0))
                        raw_t_bot = float(matched_box.get('Bottom_Thickness_IN', 6.0))
                        
                        # SAFEGUARD: Force a absolute minimum floor of 2.0 inches to prevent infinite hatch loops
                        if raw_t_top < 2.0: raw_t_top = 6.0
                        if raw_t_bot < 2.0: raw_t_bot = 6.0
                        
                        t_top = (raw_t_top / 12.0) * scale_y
                        t_bot = (raw_t_bot / 12.0) * scale_y
                    except (ValueError, TypeError):
                        t_top = 0.5 * scale_y
                        t_bot = 0.5 * scale_y
                else:
                    # Fallback default value if size combo isn't found in library mapping
                    t_top = 0.5 * scale_y
                    t_bot = 0.5 * scale_y
                    
                p_bot_pts = [(xs, iu - t_bot), (xe, idn - t_bot), (xe, idn), (xs, iu), (xs, iu - t_bot)]
                p_flow_pts = [(xs, iu), (xe, idn), (xe, idn + h), (xs, iu + h), (xs, iu)]
                p_top_pts = [(xs, iu + h), (xe, idn + h), (xe, idn + h + t_top), (xs, iu + h + t_top), (xs, iu + h)]
            
            else:
                # Standard Round Pipe thickness logic using formula
                t_pipe_calc = elem['pipe_wall'] * scale_y
                t_top = t_pipe_calc
                t_bot = t_pipe_calc
                
                p_bot_pts = [(xs, iu - t_bot), (xe, idn - t_bot), (xe, idn), (xs, iu), (xs, iu - t_bot)]
                p_flow_pts = [(xs, iu), (xe, idn), (xe, idn + h), (xs, iu + h), (xs, iu)]
                p_top_pts = [(xs, iu + h), (xe, idn + h), (xe, idn + h + t_top), (xs, iu + h + t_top), (xs, iu + h)]

            # Core Polyline Additions
            msp.add_lwpolyline(p_bot_pts, dxfattribs={'layer': 'Pipe'})
            if is_ditch_element:
                msp.add_line((xs, iu), (xe, idn), dxfattribs={'layer': 'Pipe'})
                msp.add_line(p_top_pts[0], p_top_pts[1], dxfattribs={'layer': 'Pipe'})
            else:
                msp.add_lwpolyline(p_flow_pts, dxfattribs={'layer': 'Pipe'})
                msp.add_lwpolyline(p_top_pts, dxfattribs={'layer': 'Pipe'})

            # Invert Annotation Placement Adjustments (using t_bot)
            txt_inv_up = f"Inv: {elem['inv_up']:.2f}'"
            adj_base_y_up = (iu - t_bot) - (len(txt_inv_up) * text_font_size * 0.75) - clearance_buffer
            text_x_up = xs + 1.5 + (text_font_size / 2.0)
            msp.add_text(txt_inv_up, dxfattribs={'layer': 'Text', 'height': text_font_size, 'rotation': 90.0}).set_placement((text_x_up, adj_base_y_up))

            txt_inv_dn = f"Inv: {elem['inv_down']:.2f}'"
            adj_base_y_dn = (idn - t_bot) - (len(txt_inv_dn) * text_font_size * 0.75) - clearance_buffer
            text_x_dn = xe - 2.5 + (text_font_size / 2.0)
            msp.add_text(txt_inv_dn, dxfattribs={'layer': 'Text', 'height': text_font_size, 'rotation': 90.0}).set_placement((text_x_dn, adj_base_y_dn))

            # Label generation
            if is_ditch_element:
                ditch_shape_ui = str(p_rec.get('Type', 'Trapezoidal')).strip().lower()
                formatted_size_str = f"{p_rec.get('Left Slope', '3:1')}, {p_rec.get('Right Slope', '3:1')}" if 'tri' in ditch_shape_ui else f"{p_rec.get('Left Slope', '3:1')}, {float(p_rec.get('Bottom Width (ft)', 2.0)):.1f} ft, {p_rec.get('Right Slope', '3:1')}"
            else:
                span_val = str(p_rec.get('Span/Diameter', '24 in')).lower().replace('in','').replace('ft','').strip()
                if is_box_conduit:
                    formatted_size_str = f"{span_val} ft x {str(p_rec.get('Depth (ft)', '2.0')).lower().replace('in','').replace('ft','').strip()} ft"
                else:
                    formatted_size_str = str(p_rec.get('Span/Diameter', '24 in')) + (" in" if 'in' not in str(p_rec.get('Span/Diameter', '24 in')) and 'ft' not in str(p_rec.get('Span/Diameter', '24 in')) else "")
            
            pipe_lines = [f"{elem['name']}", f"L = {elem['length']:.2f} ft", f"Size = {formatted_size_str}", f"S = {p_slope:.2f}%"]
            mid_x = xs + ((xe - xs) / 2.0)
            start_txt_y = (iu + ((idn - iu) / 2.0)) - t_bot - (text_font_size * 2.5)
            
            for line_idx, line_text in enumerate(pipe_lines):
                total_str_len_est = len(line_text) * (text_font_size * 0.55)
                text_x = mid_x - (total_str_len_est / 2.0)
                text_y = start_txt_y - (line_idx * (text_font_size * 1.5))
                msp.add_text(line_text, dxfattribs={'layer': 'Text', 'height': text_font_size}).set_placement((text_x, text_y))

            # Solid Hatch Sub-routines (Refactored to separate t_bot and t_top boundaries)
            p_len = xe - xs
            num_hatches = int(p_len / 0.5)
            if num_hatches > 0:
                for step in range(num_hatches + 1):
                    ratio = step / float(num_hatches)
                    hx, hy = xs + (ratio * p_len), iu + (ratio * (idn - iu))
                    if is_ditch_element:
                        msp.add_line((hx, hy - t_bot), (hx + (t_bot / scale_y), hy), dxfattribs={'layer': 'Hatch'})
                    else:
                        msp.add_line((hx, hy - t_bot), (hx + (t_bot / scale_y), hy), dxfattribs={'layer': 'Hatch'})
                        msp.add_line((hx, hy + h), (hx + (t_top / scale_y), hy + h + t_top), dxfattribs={'layer': 'Hatch'})
                        
        # ==========================================
        # STEP 5: HGL VECTOR ASSEMBLIES & EXPORT
        # ==========================================
        hgl_points = [(pt_x, pt_y * scale_y) for pt_x, pt_y in hgl_profile_points]
        if len(hgl_points) > 1:
            msp.add_lwpolyline(hgl_points, dxfattribs={'layer': 'HGL'})

        run_token, row_idx, cad_format = payload.get("run_token", ""), payload.get("row_index", 0), payload["format"]
        export_filename = f"profile_output_{row_idx}_{run_token}.{cad_format.lower()}" if run_token else f"profile_output_{row_idx}.{cad_format.lower()}"
        export_output_path = os.path.join(os.path.dirname(payload["nodes_json"]), export_filename).replace('\\', '/')
        
        doc.saveas(export_output_path)
        print("SUCCESS: Dynamic Custom Dimension DXF Profile Generated at: " + str(export_output_path))
        
    except Exception as internal_crash:
        error_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        stack_details = traceback.format_exc()
        
        # Force the full traceback directly into the standard output
        print("\n==================================================")
        print(f"BACKGROUND ENGINE PIPELINE CRASH: {error_time}")
        print("==================================================")
        print(f"Exception Message: {str(internal_crash)}\n")
        print("Full Structural Execution Traceback:")
        print(stack_details)
        print("==================================================\n")
        
        # Optional: Still try to write to the log, but don't rely on it
        try:
            if not os.path.exists(TARGET_LOG_DIR):
                os.makedirs(TARGET_LOG_DIR, exist_ok=True)
            with open(LOG_FILE_PATH, "a", encoding="utf-8") as f:
                f.write(f"CRASH AT {error_time}\n{stack_details}\n")
        except:
            pass
            
        # Hard exit to communicate fallback to Streamlit
        sys.exit(1)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        run_headless_pipeline(sys.argv[1])
