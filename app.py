# -*- coding: utf-8 -*-
# =========================================================
# ðﾟﾎﾨ FORCE HEADLESS MATPLOTLIB (AVOIDS THREAD COLLISION)
# =========================================================
import matplotlib
matplotlib.use('Agg')  # Must run BEFORE importing pyplot

import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
import ezdxf
from ezdxf.addons.drawing import RenderContext, Frontend
from ezdxf.addons.drawing.matplotlib import MatplotlibBackend
from ezdxf.addons.drawing.config import Configuration, TextPolicy
import math
import io
import tempfile
import uuid
import subprocess
import sys
import time

import streamlit as st
import pandas as pd
import numpy as np
from inlet_calculations import ditch_inlet_on_sag, grate_inlet_on_sag, curb_inlet_on_sag, ditch_inlet_on_grade, grate_inlet_on_grade, curb_inlet_on_grade
from pipe_calculations import get_pipe_hydraulics
from ditch_calculations import get_ditch_hydraulics
import profile_generator
import os
import traceback
from datetime import datetime
import platform

st.set_page_config(page_title="Storm Drainage Design Tool", layout="wide")

# ====================== EXTRACTION OF STRUCTURE ID LIBRARY ======================
#csv_library_path = os.path.abspath("files/structure-library.csv") 
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
csv_library_path = os.path.join(BASE_DIR, "files", "structure-library.csv")
structure_options = [None]  # Base default fallback option

if os.path.exists(csv_library_path):
    try:
        lib_df = pd.read_csv(csv_library_path)
        if "Name" in lib_df.columns:
            extracted_names = sorted(lib_df["Name"].dropna().astype(str).unique().tolist())
            structure_options.extend(extracted_names)
    except Exception as e:
        st.warning(f"⚠️ Could not parse structure library file: {e}")
else:
    st.error(f"❌ Structural CSV library file not found at path: {csv_library_path}")

# ====================== TITLE + EXPORT ======================
col_title, col_export = st.columns([7, 2])
with col_title:
    st.title("ðﾟﾌﾧ️ Storm Drainage Design Tool")
    st.markdown("*Developed by Dawit Ghebreyesus*")

with col_export:
    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("ðﾟﾓﾥ Export All to Excel", use_container_width=True):
        output_buffer = io.BytesIO()
        with pd.ExcelWriter(output_buffer, engine='openpyxl') as output:
            st.session_state.nodes.to_excel(output, sheet_name="Nodes", index=False)
            st.session_state.links.to_excel(output, sheet_name="Links", index=False)
            if not st.session_state.drainage_main.empty:
                st.session_state.drainage_main.to_excel(output, sheet_name="Drainage_Areas", index=False)
            if not st.session_state.inlets.empty:
                st.session_state.inlets.to_excel(output, sheet_name="Inlets", index=False)
            if 'pipes' in st.session_state and not st.session_state.pipes.empty:
                st.session_state.pipes.to_excel(output, sheet_name="Pipe_Design", index=False)
            if 'ditches' in st.session_state and not st.session_state.ditches.empty:
                st.session_state.ditches.to_excel(output, sheet_name="Ditch_Design", index=False)
        
        output_buffer.seek(0)
        st.download_button(
            label="⬇️ Download Excel File",
            data=output_buffer,
            file_name=f"Stormwater_Design_Export_{pd.Timestamp.now().strftime('%Y%m%d_%H%M')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="export_download"
        )
        st.success("✅ Export ready!")

    st.markdown("---")
    uploaded_file = st.file_uploader("Upload Excel File", key="Import_Excel_file", type=["xlsx"])

    if uploaded_file is not None:
        if st.button("ðﾟﾚﾀ Load Data to Tables", key="load_file"):
            try:
                data = pd.read_excel(uploaded_file, sheet_name=None)
                
                if "Nodes" in data: st.session_state.nodes = data["Nodes"]
                if "Links" in data: st.session_state.links = data["Links"]
                if "Drainage_Areas" in data: st.session_state.drainage_main = data["Drainage_Areas"]
                if "Inlets" in data: st.session_state.inlets = data["Inlets"]
                if "Pipe_Design" in data: st.session_state.pipes = data["Pipe_Design"]
                if "Ditch_Design" in data: st.session_state.ditches = data["Ditch_Design"]
                
                st.success("✅ Data imported successfully!")
                st.rerun()
            except Exception as e:
                st.error(f"Error importing file: {e}")

# ====================== SESSION STATE ======================
if 'nodes' not in st.session_state:
    st.session_state.nodes = pd.DataFrame({
        'Node Name': ['Node-A-001', 'Node-A-002', 'Node-A-003', 'Node-A-004', 'Node-A-005', 'Node-B-001'],
        'X': [3194726.64, 3194690.50, 3194691.70, 3194703.13, 3194669.53, 3194744.98],
        'Y': [10139284.99, 10139248.92, 10139214.42, 10139201.57, 10139186.18, 10139260.90],
        'Station': ['102+69.82', '102+20.83', '101+91.07', '101+85.23', '101+55.69', '102+57.21'],
        'Offset': [-4.97, -19.68, -2.18, 14.00, -8.20, 22.55],
        'Ground Elev (ft)': [648.50, 650.00, 649.00, 648.00, 647.50, 649.50],
        'Type': ['Outfall', 'Inlet', 'Manhole', 'Inlet', 'Inlet', 'Outfall'],
        'Structure ID': [None, None, None, None, None, None]
    })

if 'links' not in st.session_state:
    st.session_state.links = pd.DataFrame({
        'Link Name': ['Link-A-007', 'Link-A-002', 'Link-A-003', 'Link-B-002', 'Link-C-002'],
        'Start Node': ['Node-A-007', 'Node-A-002', 'Node-A-003', 'Node-B-002', 'Node-C-002'],
        'End Node': ['Node-A-002', 'Node-A-001', 'Node-A-002', 'Node-B-001', 'Node-C-001'],
        'Length (ft)': [30.38, 51.06, 34.52, 29.84, 28.18],
        'Type': ['Conduit', 'Conduit', 'Conduit', 'Conduit', 'Conduit']
    })

if 'drainage_main' not in st.session_state:
    st.session_state.drainage_main = pd.DataFrame()
    st.session_state.drainage_initialized = False

if 'inlets' not in st.session_state:
    st.session_state.inlets = pd.DataFrame()
    st.session_state.inlets_initialized = False

if 'pipes' not in st.session_state:
    st.session_state.pipes = pd.DataFrame()
    st.session_state.pipes_initialized = False

if 'ditches' not in st.session_state:
    st.session_state.ditches = pd.DataFrame()
    st.session_state.ditches_initialized = False

if 'idf' not in st.session_state:
    st.session_state.idf = pd.DataFrame({
        'Parameter': ['a', 'b', 'c'],
        '001-YR': [47.9309357, 10.48557697, 0.78944906],
        '005-YR': [60.34175068, 10.57304525, 0.78112764], 
        '010-YR': [69.53366856, 10.65667484, 0.776002509],
        '025-YR': [81.30564353, 10.80027831, 0.769648907],
        '050-YR': [89.86973529,  10.92562422, 0.765114872],
        '100-YR': [98.16816479, 11.08956674, 0.760028916], 
        '500-YR': [116.8626863,  11.58008019, 0.746366099],
    })

if 'runoff_coeff' not in st.session_state:
    st.session_state.runoff_coeff = pd.DataFrame({
        'Land Cover': ['Paved', 'Grassed ROW slope', 'Rolling Pasture', 'Commercial', 'Residential','OFF-PFLUG' , 'Pave-PFLUG'],
        '001-YR': [0.9, 0.7, 0.4, 0.95, 0.6, 0.73,0.88],
        '005-YR': [0.9, 0.7, 0.4, 0.95, 0.6, 0.73,0.88],
        '010-YR': [0.9, 0.7, 0.4, 0.95, 0.6, 0.73,0.88],
        '025-YR': [0.9, 0.7, 0.3, 0.95, 0.6, 0.73,0.88],
        '050-YR': [0.9, 0.7, 0.4, 0.95, 0.6, 0.73,0.88],
        '100-YR': [0.9, 0.7, 0.4, 0.95, 0.6, 0.73,0.88],
        '500-YR': [0.9, 0.7, 0.4, 0.95, 0.6, 0.73,0.88]
    })

if 'profile_generated' not in st.session_state:
    st.session_state.profile_generated = False
if 'profile_file_path' not in st.session_state:
    st.session_state.profile_file_path = None
if 'profile_filename' not in st.session_state:
    st.session_state.profile_filename = ""

tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs(["ðﾟﾓﾍ Nodes", "ðﾟﾔﾗ Links", "ðﾟﾌﾊ Drainage Area", "ðﾟﾚﾪ Inlets", "ðﾟﾓﾏ Pipe Design", "ðﾟﾚﾧ Ditch Design", "ðﾟﾓﾊ Profiles"])

# ====================== NODES ======================
with tab1:
    st.header("Nodes")
    node_config = {
        "Type": st.column_config.SelectboxColumn("Type", options=["Inlet", "Manhole", "Outfall", "Joint", "Transition", "Other"]),
        "Structure ID": st.column_config.SelectboxColumn("Structure ID", options=structure_options, help="Match design schema to library records")
    }
    edited_nodes = st.data_editor(
        st.session_state.nodes, 
        num_rows="dynamic", 
        use_container_width=True, 
        column_config=node_config,
        key="nodes_editor_stable"
    )
    if st.button("ðﾟﾒﾾ Save Node Configurations", key="save_button_nodes", use_container_width=False):
        if "nodes_editor_stable" in st.session_state:
            st.session_state.nodes = pd.DataFrame(edited_nodes)
            st.success("✅ Nodes configurations successfully saved to server state memory!")
            st.rerun()

# ====================== LINKS ======================
with tab2:
    st.header("Links")
    node_list = [""] + list(st.session_state.nodes['Node Name'].astype(str).unique())
    link_config = {
        "Link Name": st.column_config.TextColumn("Link Name"),
        "Start Node": st.column_config.SelectboxColumn("Start Node", options=node_list),
        "End Node": st.column_config.SelectboxColumn("End Node", options=node_list),
        "Type": st.column_config.SelectboxColumn("Type", options=["Conduit", "Ditch"]),
        "Length (ft)": st.column_config.NumberColumn(format="%.2f")
    }
    edited_links = st.data_editor(
        st.session_state.links, 
        num_rows="dynamic", 
        use_container_width=True, 
        column_config=link_config, 
        key="links_editor_stable"
    )
    if st.button("ðﾟﾒﾾ Save Link Configurations", key="save_button_links", use_container_width=False):
        if "links_editor_stable" in st.session_state:
            st.session_state.links = pd.DataFrame(edited_links)
            st.success("✅ Links configurations successfully saved to server state memory!")
            st.rerun()

# ====================== DRAINAGE AREA ======================
with tab3:
    st.header("ðﾟﾌﾊ Drainage Area Analysis")
    sub1, sub2, sub3 = st.tabs(["ðﾟﾓﾊ Main Analysis", "ðﾟﾓﾈ IDF Parameters", "ðﾟﾌ﾿ Runoff Coefficients"])
    
    with sub1:
        st.subheader("Main Drainage Area Analysis")
        inlet_nodes = st.session_state.nodes[
            st.session_state.nodes['Type'].isin(['Inlet', 'Transition'])
        ]['Node Name'].astype(str).str.strip().tolist()

        if not st.session_state.drainage_initialized or set(st.session_state.drainage_main['Node'].astype(str).str.strip() if not st.session_state.drainage_main.empty else []) != set(inlet_nodes):
            old_df = (
                st.session_state.drainage_main.copy() 
                if 'drainage_main' in st.session_state and not st.session_state.drainage_main.empty 
                else pd.DataFrame()
            )

            def get_default_drainage_row(node_name, node_type):
                return {
                    'Node': str(node_name).strip(),
                    'Node Type': str(node_type).strip(),
                    'Design Year': '025-YR',
                    'Tc (min)': 5.0,
                    'Area 1 Type': 'Paved', 
                    'Area 1 (ac)': 1.0, 
                    'C1': 0.0,
                    'Area 2 Type': '', 
                    'Area 2 (ac)': 0.0, 
                    'C2': 0.0,
                    'Area 3 Type': '', 
                    'Area 3 (ac)': 0.0, 
                    'C3': 0.0,
                    'Area 4 Type': '', 
                    'Area 4 (ac)': 0.0, 
                    'C4': 0.0,
                    'Total Area (ac)': 0.0,
                    'Weighted C': 0.0,
                    'Intensity (in/hr)': 9.72,
                    'Discharge (cfs)': 0.0
                }

            new_rows_list = []
            for target_node in inlet_nodes:
                node_clean = str(target_node).strip()
                fresh_type = st.session_state.nodes.loc[
                    st.session_state.nodes['Node Name'].astype(str).str.strip() == node_clean, 'Type'
                ].iloc[0]

                is_exact_match = False
                existing_record = None

                if not old_df.empty and 'Node' in old_df.columns:
                    match_records = old_df[old_df['Node'].astype(str).str.strip() == node_clean]
                    if not match_records.empty:
                        is_exact_match = True
                        existing_record = match_records.iloc[0].to_dict()

                if is_exact_match:
                    final_row = existing_record
                    final_row['Node Type'] = fresh_type
                else:
                    final_row = get_default_drainage_row(node_clean, fresh_type)

                new_rows_list.append(final_row)

            if new_rows_list:
                merged_df = pd.DataFrame(new_rows_list)
                numeric_cols = [
                    'Tc (min)', 'Area 1 (ac)', 'C1', 'Area 2 (ac)', 'C2', 
                    'Area 3 (ac)', 'C3', 'Area 4 (ac)', 'C4', 
                    'Total Area (ac)', 'Weighted C', 'Intensity (in/hr)', 'Discharge (cfs)'
                ]
                for col in numeric_cols:
                    if col in merged_df.columns:
                        merged_df[col] = pd.to_numeric(merged_df[col], errors='coerce').fillna(0.0)

                st.session_state.drainage_main = merged_df
            else:
                st.session_state.drainage_main = pd.DataFrame()
                
            st.session_state.drainage_initialized = True

        main_config = {
            "Node": st.column_config.TextColumn("Node", disabled=True),
            "Node Type": st.column_config.TextColumn("Node Type", disabled=True),
            "Design Year": st.column_config.SelectboxColumn("Design Year", options=["001-YR","005-YR","010-YR","025-YR","050-YR","100-YR","500-YR"]),
            "Tc (min)": st.column_config.NumberColumn(format="%.1f"),
            "Area 1 Type": st.column_config.SelectboxColumn("Area 1 Type", options=st.session_state.runoff_coeff['Land Cover'].tolist()),
            "Area 1 (ac)": st.column_config.NumberColumn(format="%.3f"),
            "C1": st.column_config.NumberColumn(format="%.3f", disabled=True),
            "Area 2 Type": st.column_config.SelectboxColumn("Area 2 Type", options=st.session_state.runoff_coeff['Land Cover'].tolist()),
            "Area 2 (ac)": st.column_config.NumberColumn(format="%.3f"),
            "C2": st.column_config.NumberColumn(format="%.3f", disabled=True),
            "Area 3 Type": st.column_config.SelectboxColumn("Area 3 Type", options=st.session_state.runoff_coeff['Land Cover'].tolist()),
            "Area 3 (ac)": st.column_config.NumberColumn(format="%.3f"),
            "C3": st.column_config.NumberColumn(format="%.3f", disabled=True),
            "Area 4 Type": st.column_config.SelectboxColumn("Area 4 Type", options=st.session_state.runoff_coeff['Land Cover'].tolist()),
            "Area 4 (ac)": st.column_config.NumberColumn(format="%.3f"),
            "C4": st.column_config.NumberColumn(format="%.3f", disabled=True),
            "Total Area (ac)": st.column_config.NumberColumn(format="%.3f", disabled=True),
            "Weighted C": st.column_config.NumberColumn(format="%.3f", disabled=True),
            "Intensity (in/hr)": st.column_config.NumberColumn(format="%.3f", disabled=True),
            "Discharge (cfs)": st.column_config.NumberColumn(format="%.3f", disabled=True),
        }

        edited_df = st.data_editor(
            st.session_state.drainage_main, 
            num_rows="fixed", 
            use_container_width=True, 
            column_config=main_config, 
            key="drainage_editor"
        )

        if st.button("ðﾟﾔﾄ Calculate Drainage Areas Flows"):
            df = edited_df.copy()
            coeff_dict = {}
            for _, row in st.session_state.runoff_coeff.iterrows():
                for yr in ['001-YR','005-YR','010-YR','025-YR','050-YR','100-YR','500-YR']:
                    coeff_dict[(row['Land Cover'], yr)] = row[yr]

            for i, row in df.iterrows():
                design_yr = row['Design Year']
                tc = float(row.get('Tc (min)', 5.0))
                total_area = 0.0
                weighted_sum = 0.0

                for n in range(1, 5):
                    atype = row.get(f'Area {n} Type')
                    area_val = float(row.get(f'Area {n} (ac)', 0.0)) if pd.notna(row.get(f'Area {n} (ac)')) else 0.0
                    c_val = coeff_dict.get((atype, design_yr), 0.0) if pd.notna(atype) else 0.0
                    
                    df.at[i, f'C{n}'] = c_val
                    total_area += area_val
                    weighted_sum += (c_val * area_val)

                try:
                    a = float(st.session_state.idf.loc[st.session_state.idf['Parameter']=='a', design_yr].iloc[0])
                    b = float(st.session_state.idf.loc[st.session_state.idf['Parameter']=='b', design_yr].iloc[0])
                    c = float(st.session_state.idf.loc[st.session_state.idf['Parameter']=='c', design_yr].iloc[0])
                    intensity = round(a / (tc + b) ** c, 3)
                except:
                    intensity = 9.72
                    
                df.at[i, 'Intensity (in/hr)'] = intensity
                weighted_c = round(weighted_sum / total_area, 3) if total_area > 0 else 0.0
                discharge = round(weighted_c * intensity * total_area, 3) if total_area > 0 else 0.0

                df.at[i, 'Total Area (ac)'] = round(total_area, 3)
                df.at[i, 'Weighted C'] = weighted_c
                df.at[i, 'Discharge (cfs)'] = discharge

            st.session_state.drainage_main = df
            st.success("✅ All drainage calculations parsed and processed successfully!")
            st.rerun()

    with sub2:
        st.subheader("IDF Parameters (a, b, c)")
        edited_idf = st.data_editor(st.session_state.idf, num_rows="fixed", use_container_width=True, key="idf_editor_key")
        col1, col2 = st.columns([1, 5])
        with col1:
            if st.button("ðﾟﾒﾾ Update IDF", key="btn_update_idf"):
                st.session_state.idf = edited_idf
                st.success("IDF parameters updated!")
                st.rerun()
        with col2:
            if st.button("ðﾟﾔﾄ Reset IDF", key="btn_reset_idf"):
                st.session_state.idf = pd.DataFrame({
                    'Parameter': ['a', 'b', 'c'],
                    '001-YR': [47.9309357, 10.48557697, 0.78944906],
                    '005-YR': [60.34175068, 10.57304525, 0.78112764], 
                    '010-YR': [69.53366856, 10.65667484, 0.776002509],
                    '025-YR': [81.30564353, 10.80027831, 0.769648907],
                    '050-YR': [89.86973529, 10.92562422, 0.765114872],
                    '100-YR': [98.16816479, 11.08956674, 0.760028916], 
                    '500-YR': [116.8626863, 11.58008019, 0.746366099],
                })
                st.info("IDF parameters restored to defaults.")
                st.rerun()

    with sub3:
        st.subheader("Runoff Coefficients")
        edited_runoff = st.data_editor(st.session_state.runoff_coeff, num_rows="dynamic", use_container_width=True, key="runoff_editor_key")
        col3, col4 = st.columns([1, 4])
        with col3:
            if st.button("ðﾟﾒﾾ Update Coefficients", key="btn_update_runoff"):
                st.session_state.runoff_coeff = edited_runoff
                st.success("Runoff coefficients updated!")
                st.rerun()
        with col4:
            if st.button("ðﾟﾔﾄ Reset Coefficients", key="btn_reset_runoff"):
                st.session_state.runoff_coeff = pd.DataFrame({
                    'Land Cover': ['Paved', 'Grassed ROW slope', 'Rolling Pasture', 'Commercial', 'Residential','OFF-PFLUG' , 'Pave-PFLUG'],
                    '001-YR': [0.9, 0.7, 0.4, 0.95, 0.6, 0.73,0.88],
                    '005-YR': [0.9, 0.7, 0.4, 0.95, 0.6, 0.73,0.88],
                    '010-YR': [0.9, 0.7, 0.4, 0.95, 0.6, 0.73,0.88],
                    '025-YR': [0.9, 0.7, 0.3, 0.95, 0.6, 0.73,0.88],
                    '050-YR': [0.9, 0.7, 0.4, 0.95, 0.6, 0.73,0.88],
                    '100-YR': [0.9, 0.7, 0.4, 0.95, 0.6, 0.73,0.88],
                    '500-YR': [0.9, 0.7, 0.4, 0.95, 0.6, 0.73,0.88]
                })

                st.info("Runoff coefficients restored to defaults.")
                st.rerun()

# ====================== INLETS ======================
with tab4:
    st.header("ðﾟﾚﾪ Inlet Analysis")
    if st.button("ðﾟﾔﾄ Sync Incoming Flows (From Drainage & Ditches)", key="btn_sync_flows"):
        master_inlet_nodes = st.session_state.nodes[
            st.session_state.nodes['Type'] == 'Inlet'
        ]['Node Name'].astype(str).str.strip().tolist()
        
        st.session_state.cached_bypass_targets = [''] + list(st.session_state.nodes[
            st.session_state.nodes['Type'].isin(['Inlet', 'Outfall'])
        ]['Node Name'].unique())

        old_df = (
            st.session_state.inlets.copy() 
            if 'inlets' in st.session_state and not st.session_state.inlets.empty 
            else pd.DataFrame()
        )

        def get_default_inlet_row(node_name, incoming_flow=0.0):
            return {
                'Node Name': str(node_name).strip(),
                'Inlet Type': 'Grate',
                'Location': 'Grade',
                'Length (ft)': 4.0,
                'Width/Height (ft)': 2.0,
                'Roadway Cross Slope (%)': 2.0,
                'Roadway Longitudinal Slope (%)': 0.5,
                'Local Depression (in)': 4.0,
                'Local Depression Width (in)': 16.0,
                "Manning's n": 0.013,
                'Incoming Flow (cfs)': float(incoming_flow),
                'Incoming Bypass (cfs)': 0.0,
                'Total Flow (cfs)': 0.0,
                'Captured Flow (cfs)': 0.0,
                'Depth (ft)': 0.0,
                'Depth (in)': 0.0,
                'Spread (ft)': 0.0,
                'Bypass To': '',
                'Bypass Flow (cfs)': 0.0,
                'Left Side Slope': '3:1',
                'Right Side Slope': '3:1'
            }

        new_rows_list = []
        if master_inlet_nodes:
            for fresh_node in master_inlet_nodes:
                node_clean = str(fresh_node).strip()
                drainage_flow = 0.0
                if 'drainage_main' in st.session_state and not st.session_state.drainage_main.empty:
                    match = st.session_state.drainage_main[st.session_state.drainage_main['Node'].astype(str).str.strip() == node_clean]
                    if not match.empty:
                        drainage_flow = float(match['Discharge (cfs)'].iloc[0] or 0.0)

                ditch_flow = 0.0
                if 'ditches' in st.session_state and not st.session_state.ditches.empty:
                    upstream_ditches = st.session_state.ditches[st.session_state.ditches['End Node'].astype(str).str.strip() == node_clean]
                    ditch_flow = float(upstream_ditches['Discharge (cfs)'].sum() or 0.0)

                live_flow = round(drainage_flow + ditch_flow, 3)
                is_exact_match = False
                existing_record = None

                if not old_df.empty and 'Node Name' in old_df.columns:
                    match_records = old_df[old_df['Node Name'].astype(str).str.strip() == node_clean]
                    if not match_records.empty:
                        is_exact_match = True
                        existing_record = match_records.iloc[0].to_dict()

                if is_exact_match:
                    final_row = existing_record
                    final_row['Incoming Flow (cfs)'] = float(live_flow)
                    final_row['Node Name'] = node_clean
                else:
                    final_row = get_default_inlet_row(node_clean, live_flow)

                new_rows_list.append(final_row)

            merged_df = pd.DataFrame(new_rows_list)
            numeric_cols = [
                'Length (ft)', 'Width/Height (ft)', 'Roadway Cross Slope (%)', 'Roadway Longitudinal Slope (%)',
                'Local Depression (in)', 'Local Depression Width (in)',
                "Manning's n", 'Incoming Flow (cfs)', 'Incoming Bypass (cfs)', 'Total Flow (cfs)',
                'Captured Flow (cfs)', 'Depth (ft)', 'Depth (in)', 'Spread (ft)', 'Bypass Flow (cfs)'
            ]
            string_cols = ['Node Name', 'Inlet Type', 'Location', 'Bypass To', 'Left Side Slope', 'Right Side Slope']

            for col in numeric_cols:
                if col in merged_df.columns:
                    merged_df[col] = pd.to_numeric(merged_df[col], errors='coerce').fillna(0.0)

            for col in string_cols:
                if col in merged_df.columns:
                    merged_df[col] = merged_df[col].astype(str).str.strip()

            st.session_state.cached_inlet_nodes = master_inlet_nodes
            st.session_state.inlets = merged_df
            st.session_state.inlets_initialized = True
            st.success("✅ Inlet sync complete!")
        else:
            st.session_state.inlets = pd.DataFrame()
            st.session_state.cached_inlet_nodes = []
            st.warning("Sync processed: No Inlet nodes found in the master table.")
        st.rerun()
        
    if 'cached_inlet_nodes' not in st.session_state:
        st.session_state.cached_inlet_nodes = st.session_state.nodes[
            st.session_state.nodes['Type'] == 'Inlet'
        ]['Node Name'].tolist()
        
        st.session_state.cached_bypass_targets = [''] + list(st.session_state.nodes[
            st.session_state.nodes['Type'].isin(['Inlet', 'Outfall'])
        ]['Node Name'].unique())

    inlet_nodes = st.session_state.cached_inlet_nodes
    bypass_targets = st.session_state.cached_bypass_targets

    if 'inlets_initialized' not in st.session_state or 'inlets' not in st.session_state or st.session_state.inlets.empty or len(st.session_state.inlets) != len(inlet_nodes):
        if inlet_nodes:
            st.session_state.inlets = pd.DataFrame({
                'Node Name': inlet_nodes,
                'Inlet Type': ['Grate'] * len(inlet_nodes),
                'Location': ['Grade'] * len(inlet_nodes),
                'Length (ft)': [4.0] * len(inlet_nodes),
                'Width/Height (ft)': [2.0] * len(inlet_nodes),
                'Roadway Cross Slope (%)': [2.0] * len(inlet_nodes),
                'Roadway Longitudinal Slope (%)': [0.5] * len(inlet_nodes),
                'Local Depression (in)': [4.0] * len(inlet_nodes),
                'Local Depression Width (in)': [16.0] * len(inlet_nodes),
                "Manning's n": [0.013] * len(inlet_nodes),
                'Incoming Flow (cfs)': [0.0] * len(inlet_nodes),
                'Incoming Bypass (cfs)': [0.0] * len(inlet_nodes),
                'Total Flow (cfs)': [0.0] * len(inlet_nodes),
                'Captured Flow (cfs)': [0.0] * len(inlet_nodes),
                'Depth (ft)': [0.0] * len(inlet_nodes),
                'Depth (in)': [0.0] * len(inlet_nodes),
                'Spread (ft)': [0.0] * len(inlet_nodes),
                'Bypass To': [''] * len(inlet_nodes),
                'Bypass Flow (cfs)': [0.0] * len(inlet_nodes),
                'Left Side Slope': ['3:1'] * len(inlet_nodes),
                'Right Side Slope': ['3:1'] * len(inlet_nodes)
            })
            st.session_state.inlets_initialized = True
        else:
            st.session_state.inlets = pd.DataFrame()

    if 'inlets' in st.session_state and st.session_state.inlets.empty:
        st.warning("No Inlets found in Nodes tab. Please add nodes with Type = 'Inlet' and click Sync above.")
    else:
        inlet_config = {
            "Node Name": st.column_config.TextColumn("Node Name", disabled=True),
            "Inlet Type": st.column_config.SelectboxColumn("Inlet Type", options=['Curb', 'Grate', 'Ditch']),
            "Location": st.column_config.SelectboxColumn("Location", options=['Sag', 'Grade']),
            "Length (ft)": st.column_config.NumberColumn(format="%.2f"),
            "Width/Height (ft)": st.column_config.NumberColumn(format="%.2f"),
            "Roadway Cross Slope (%)": st.column_config.NumberColumn(format="%.2f"),
            "Roadway Longitudinal Slope (%)": st.column_config.NumberColumn(format="%.2f"),
            "Local Depression (in)": st.column_config.NumberColumn(format="%.2f"),
            "Local Depression Width (in)": st.column_config.NumberColumn(format="%.2f"),
            "Manning's n": st.column_config.NumberColumn(format="%.3f"),
            "Incoming Flow (cfs)": st.column_config.NumberColumn(format="%.3f", disabled=True),
            "Incoming Bypass (cfs)": st.column_config.NumberColumn(format="%.3f", disabled=True),
            "Total Flow (cfs)": st.column_config.NumberColumn(format="%.3f", disabled=True),
            "Captured Flow (cfs)": st.column_config.NumberColumn(format="%.3f", disabled=True),
            "Depth (ft)": st.column_config.NumberColumn(format="%.3f", disabled=True),
            "Depth (in)": st.column_config.NumberColumn(format="%.2f", disabled=True),
            "Spread (ft)": st.column_config.NumberColumn(format="%.2f", disabled=True),
            "Bypass To": st.column_config.SelectboxColumn("Bypass To", options=bypass_targets),
            "Bypass Flow (cfs)": st.column_config.NumberColumn(format="%.3f", disabled=True),
            "Left Side Slope": st.column_config.SelectboxColumn(options=[f"{i}:1" for i in range(1,11)]),
            "Right Side Slope": st.column_config.SelectboxColumn(options=[f"{i}:1" for i in range(1,11)]),
        }

        edited_inlets = st.data_editor(
            st.session_state.inlets, 
            num_rows="fixed",
            use_container_width=True, 
            column_config=inlet_config, 
            key="inlets_editor_unique"
        )

        if st.button("ðﾟﾚﾀ Calculate All Inlet Hydraulics"):
            df = edited_inlets.copy()
            for i, row in df.iterrows():
                node = row['Node Name']
                drainage_flow = 0.0
                match = st.session_state.drainage_main[st.session_state.drainage_main['Node'] == node]
                if not match.empty:
                    drainage_flow = float(match['Discharge (cfs)'].iloc[0])

                ditch_flow = 0.0
                if 'ditches' in st.session_state and not st.session_state.ditches.empty:
                    upstream_ditches = st.session_state.ditches[st.session_state.ditches['End Node'] == node]
                    ditch_flow = upstream_ditches['Discharge (cfs)'].sum()

                df.at[i, 'Incoming Flow (cfs)'] = round(drainage_flow + ditch_flow, 3)

            for i, row in df.iterrows():
                Q_total = float(df.at[i, 'Incoming Flow (cfs)']) + float(row.get('Incoming Bypass (cfs)', 0))
                loc = row['Location']
                itype = row['Inlet Type']
                L = float(row.get('Length (ft)', 4.0))
                W = float(row.get('Width/Height (ft)', 2.0))
                Sx = float(row.get('Roadway Cross Slope (%)', 2.0)) / 100
                S = float(row.get('Roadway Longitudinal Slope (%)', 0.5)) / 100
                n = float(row.get("Manning's n", 0.013))
                a_in = float(row.get('Local Depression (in)', 0.0))
                w_dep_in = float(row.get('Local Depression Width (in)', 0.0))

                if loc == "Sag":
                    if itype == "Ditch":
                        z_left = float(str(row.get('Left Side Slope', '3:1')).split(':')[0])
                        z_right = float(str(row.get('Right Side Slope', '3:1')).split(':')[0])
                        result = ditch_inlet_on_sag(Q_total, L, W, z_left, z_right)
                    elif itype == "Curb":
                        result = curb_inlet_on_sag(Q_total, L, W, Sx, a_in, w_dep_in)
                    else:
                        result = grate_inlet_on_sag(Q_total, L, W, Sx) if itype == "Grate" else curb_inlet_on_sag(Q_total, L, 0.5, Sx, a_in, w_dep_in)
                else:
                    if itype == "Curb":
                        result = curb_inlet_on_grade(Q_total, L, Sx, S, a_in, w_dep_in, n)
                    elif itype == "Grate":
                        result = grate_inlet_on_grade(Q_total, L, W, Sx, S, n)
                    elif itype == "Ditch":
                        z_left = float(str(row.get('Left Side Slope', '3:1')).split(':')[0])
                        z_right = float(str(row.get('Right Side Slope', '3:1')).split(':')[0])
                        result = ditch_inlet_on_grade(Q_total, L, W, z_left, z_right, S, n)
                    else:
                        result = {'captured_cfs': Q_total, 'bypass_cfs': 0.0, 'depth_ft': 0.0, 'depth_in': 0.0, 'spread_ft': 0.0}

                df.at[i, 'Total Flow (cfs)'] = round(Q_total, 3)
                df.at[i, 'Captured Flow (cfs)'] = result.get('captured_cfs', 0)
                df.at[i, 'Bypass Flow (cfs)'] = result.get('bypass_cfs', 0)
                df.at[i, 'Depth (ft)'] = result.get('depth_ft', 0)
                df.at[i, 'Depth (in)'] = result.get('depth_in', 0)
                df.at[i, 'Spread (ft)'] = result.get('spread_ft', 0)

            bypass_totals = df.groupby('Bypass To')['Bypass Flow (cfs)'].sum()
            df['Incoming Bypass (cfs)'] = df['Node Name'].map(bypass_totals).fillna(0).round(3)

            st.session_state.inlets = df
            st.success("✅ All calculations finished and saved successfully!")
            st.rerun()

# ====================== PIPE DESIGN ======================
with tab5:
    st.header("ðﾟﾓﾏ Pipe Design")
    if st.button("ðﾟﾔﾄ Sync Incoming Flows (From Drainage & Inlets)", key="btn_sync_network_pipes"):
        st.session_state.cached_conduits = st.session_state.links[
            st.session_state.links['Type'].astype(str).str.contains('Conduit', case=False, na=False)
        ].copy()
        
        conduits_sync = st.session_state.cached_conduits
        current_names_sync = set(conduits_sync['Link Name'].values)
        st.session_state.pipes_conduit_names = current_names_sync

        def get_upstream_discharge_sync(start_node, links_df, inlets_df, visited=None):
            if visited is None: visited = set()
            lookup_node = str(start_node).strip()
            if lookup_node in visited: return 0.0
            visited.add(lookup_node)

            total = float(inlets_df[inlets_df['Node Name'].astype(str).str.strip() == lookup_node]['Captured Flow (cfs)'].sum() or 0)
            upstream = links_df[links_df['End Node'].astype(str).str.strip() == lookup_node]
            for _, link in upstream.iterrows():
                total += get_upstream_discharge_sync(link['Start Node'], links_df, inlets_df, visited.copy())
            return round(total, 3)

        def calculate_min_inverts_sync(df):
            df = df.copy()
            nodes = pd.concat([df['Start Node'].astype(str).str.strip(), df['End Node'].astype(str).str.strip()]).unique()
            for node in nodes:
                incoming = df[df['End Node'].astype(str).str.strip() == node]
                if not incoming.empty:
                    val = incoming['Downstream Invert (ft)'].min()
                    df.loc[df['Start Node'].astype(str).str.strip() == node, 'Min Up Invert (ft)'] = f"{val:.2f}" if pd.notna(val) and val != 0 else "-"
                else:
                    df.loc[df['Start Node'].astype(str).str.strip() == node, 'Min Up Invert (ft)'] = "-"

                outgoing = df[df['Start Node'].astype(str).str.strip() == node]
                if not outgoing.empty:
                    val = outgoing['Upstream Invert (ft)'].min()
                    df.loc[df['End Node'].astype(str).str.strip() == node, 'Min Down Invert (ft)'] = f"{val:.2f}" if pd.notna(val) and val != 0 else "-"
                else:
                    df.loc[df['End Node'].astype(str).str.strip() == node, 'Min Down Invert (ft)'] = "-"
            return df

        def get_default_pipe_row(name, start, end, length, flow):
            return {
                'Name': str(name).strip(), 
                'Start Node': str(start).strip(), 
                'End Node': str(end).strip(), 
                'Length (ft)': float(length), 
                'Discharge (cfs)': float(flow),
                'Manning n': 0.013, 
                'Type': 'Pipe', 
                'Span/Diameter': '24 in', 
                'Depth (ft)': 2.0, 
                'Upstream Invert (ft)': 640.00, 
                'Downstream Invert (ft)': 638.00, 
                'Min Up Invert (ft)': "-", 
                'Min Down Invert (ft)': "-", 
                'Slope (%)': 0.50, 
                'Normal Depth (ft)': 0.0, 
                'Flow Area (ft²)': 0.0, 
                'Velocity (ft/s)': 0.0, 
                'Full Capacity (cfs)': 0.0, 
                'Visual': ''
            }

        old_df = (
            st.session_state.pipes.copy() 
            if 'pipes' in st.session_state and not st.session_state.pipes.empty 
            else pd.DataFrame()
        )

        new_rows_list = []
        for _, fresh_link in conduits_sync.iterrows():
            fresh_name = str(fresh_link['Link Name']).strip()
            fresh_start = str(fresh_link['Start Node']).strip()
            fresh_end = str(fresh_link['End Node']).strip()
            fresh_length = round(float(fresh_link['Length (ft)']), 2)
            live_flow = get_upstream_discharge_sync(fresh_start, st.session_state.links, st.session_state.inlets)

            is_exact_match = False
            existing_record = None

            if not old_df.empty and 'Name' in old_df.columns:
                match_records = old_df[old_df['Name'].astype(str).str.strip() == fresh_name]
                if not match_records.empty:
                    old_row = match_records.iloc[0]
                    old_start = str(old_row['Start Node']).strip()
                    old_end = str(old_row['End Node']).strip()
                    try:
                        old_length = round(float(old_row['Length (ft)']), 2)
                    except (ValueError, TypeError):
                        old_length = -1.0

                    if old_start == fresh_start and old_end == fresh_end and old_length == fresh_length:
                        is_exact_match = True
                        existing_record = old_row.to_dict()

            if is_exact_match:
                final_row = existing_record
                final_row['Discharge (cfs)'] = float(live_flow)
                final_row['Name'] = fresh_name
                final_row['Start Node'] = fresh_start
                final_row['End Node'] = fresh_end
                final_row['Length (ft)'] = fresh_length
            else:
                final_row = get_default_pipe_row(fresh_name, fresh_start, fresh_end, fresh_length, live_flow)

            new_rows_list.append(final_row)

        if new_rows_list:
            merged_df = pd.DataFrame(new_rows_list)
            merged_df = calculate_min_inverts_sync(merged_df)
            
            numeric_cols = [
                'Length (ft)', 'Discharge (cfs)', 'Manning n', 'Depth (ft)', 
                'Upstream Invert (ft)', 'Downstream Invert (ft)', 'Slope (%)', 
                'Normal Depth (ft)', 'Flow Area (ft²)', 'Velocity (ft/s)', 'Full Capacity (cfs)'
            ]
            string_cols = ['Name', 'Start Node', 'End Node', 'Type', 'Span/Diameter', 'Min Up Invert (ft)', 'Min Down Invert (ft)', 'Visual']
            
            for col in numeric_cols:
                if col in merged_df.columns:
                    merged_df[col] = pd.to_numeric(merged_df[col], errors='coerce').fillna(0.0)
                    
            for col in string_cols:
                if col in merged_df.columns:
                    merged_df[col] = merged_df[col].astype(str).str.strip()

            target_order = [
                'Name', 'Start Node', 'End Node', 'Length (ft)', 
                'Discharge (cfs)', 'Manning n', 'Type', 'Span/Diameter', 'Depth (ft)', 
                'Upstream Invert (ft)', 'Downstream Invert (ft)', 
                'Min Up Invert (ft)', 'Min Down Invert (ft)', 'Slope (%)', 
                'Normal Depth (ft)', 'Flow Area (ft²)', 'Velocity (ft/s)', 
                'Full Capacity (cfs)', 'Visual'
            ]
            existing_cols = [col for col in target_order if col in merged_df.columns]
            st.session_state.pipes = merged_df[existing_cols]
            st.session_state.pipes_initialized = True
            st.success("✅ Pipes row-by-row layout check and flow updates completed successfully!")
        else:
            st.session_state.pipes = pd.DataFrame()
            st.warning("Sync processed, but zero links matched Type = 'Conduit'.")
        st.rerun()        

    if 'cached_conduits' not in st.session_state:
        st.session_state.cached_conduits = st.session_state.links[
            st.session_state.links['Type'].astype(str).str.contains('Conduit', case=False, na=False)
        ].copy()

    conduits = st.session_state.cached_conduits

    if conduits.empty:
        st.warning("No Conduits found in Links tab. Please add links with Type = 'Conduit' and click Sync above.")
    else:
        if 'pipes_conduit_names' not in st.session_state:
            st.session_state.pipes_conduit_names = set(conduits['Link Name'].values)

        current_names = st.session_state.pipes_conduit_names

        if 'pipes_initialized' not in st.session_state or 'pipes' not in st.session_state or st.session_state.pipes.empty or set(st.session_state.pipes.get('Name', [])) != current_names:
            pipe_df = pd.DataFrame({
                'Name': conduits['Link Name'].values,
                'Start Node': conduits['Start Node'].values,
                'End Node': conduits['End Node'].values,
                'Length (ft)': conduits['Length (ft)'].values.round(2),
            })

            pipe_df['Discharge (cfs)'] = 0.0
            pipe_df['Manning n'] = 0.013
            pipe_df['Type'] = 'Pipe'
            pipe_df['Span/Diameter'] = '24 in'
            pipe_df['Depth (ft)'] = 2.0
            pipe_df['Upstream Invert (ft)'] = 640.00
            pipe_df['Downstream Invert (ft)'] = 638.00
            pipe_df['Min Up Invert (ft)'] = "-"
            pipe_df['Min Down Invert (ft)'] = "-"
            pipe_df['Slope (%)'] = 0.50
            pipe_df['Normal Depth (ft)'] = 0.0
            pipe_df['Flow Area (ft²)'] = 0.0
            pipe_df['Velocity (ft/s)'] = 0.0
            pipe_df['Full Capacity (cfs)'] = 0.0
            pipe_df['Visual'] = ''

            st.session_state.pipes = pipe_df.copy()
            st.session_state.pipes_initialized = True

        def get_upstream_discharge(start_node, links, inlets_df, visited=None):
            if visited is None: visited = set()
            if start_node in visited: return 0.0
            visited.add(start_node)
            total = float(inlets_df[inlets_df['Node Name'] == start_node]['Captured Flow (cfs)'].sum() or 0)
            upstream = links[links['End Node'] == start_node]
            for _, link in upstream.iterrows():
                total += get_upstream_discharge(link['Start Node'], links, inlets_df, visited.copy())
            return round(total, 3)

        def calculate_min_inverts(df):
            df = df.copy()
            nodes = pd.concat([df['Start Node'], df['End Node']]).unique()
            for node in nodes:
                incoming = df[df['End Node'] == node]
                if not incoming.empty:
                    val = incoming['Downstream Invert (ft)'].min()
                    df.loc[df['Start Node'] == node, 'Min Up Invert (ft)'] = f"{val:.2f}" if pd.notna(val) and val != 0 else "-"
                else:
                    df.loc[df['Start Node'] == node, 'Min Up Invert (ft)'] = "-"

                outgoing = df[df['Start Node'] == node]
                if not outgoing.empty:
                    val = outgoing['Upstream Invert (ft)'].min()
                    df.loc[df['End Node'] == node, 'Min Down Invert (ft)'] = f"{val:.2f}" if pd.notna(val) and val != 0 else "-"
                else:
                    df.loc[df['End Node'] == node, 'Min Down Invert (ft)'] = "-"
            return df

        pipe_config = {
            "Name": st.column_config.TextColumn(disabled=True),
            "Start Node": st.column_config.TextColumn(disabled=True),
            "End Node": st.column_config.TextColumn(disabled=True),
            "Length (ft)": st.column_config.NumberColumn(disabled=True, format="%.2f"),
            "Discharge (cfs)": st.column_config.NumberColumn(disabled=True, format="%.3f"),
            "Manning n": st.column_config.NumberColumn(min_value=0.008, max_value=0.05, format="%.3f", step=0.001),
            "Type": st.column_config.SelectboxColumn(options=["Pipe", "Box"]),
            "Span/Diameter": st.column_config.SelectboxColumn(
                options=[f"{i} in" for i in range(12,61,6)] + [f"{i} ft" for i in range(2,16)]
            ),
            "Depth (ft)": st.column_config.NumberColumn(min_value=2.0, max_value=15.0, format="%.2f", step=0.5),
            "Upstream Invert (ft)": st.column_config.NumberColumn(format="%.2f", step=0.01),
            "Downstream Invert (ft)": st.column_config.NumberColumn(format="%.2f", step=0.01),
            "Min Up Invert (ft)": st.column_config.TextColumn(disabled=True),
            "Min Down Invert (ft)": st.column_config.TextColumn(disabled=True),
            "Slope (%)": st.column_config.NumberColumn(disabled=True, format="%.3f"),
            "Normal Depth (ft)": st.column_config.NumberColumn(disabled=True, format="%.3f"),
            "Flow Area (ft²)": st.column_config.NumberColumn(disabled=True, format="%.3f"),
            "Velocity (ft/s)": st.column_config.NumberColumn(disabled=True, format="%.2f"),
            "Full Capacity (cfs)": st.column_config.NumberColumn(disabled=True, format="%.3f"),
            "Visual": st.column_config.TextColumn("Visual % Full", disabled=True),
        }

        edited_pipes = st.data_editor(
            st.session_state.pipes.drop(columns=['% Full'], errors='ignore'),
            num_rows="fixed",
            use_container_width=True,
            column_config=pipe_config,
            key="pipe_editor_stable"
        )

        if st.button("ðﾟﾚﾀ Calculate All Pipe Hydraulics"):
            df = edited_pipes.copy()
            for i, row in df.iterrows():
                df.at[i, 'Discharge (cfs)'] = get_upstream_discharge(
                    row['Start Node'], st.session_state.links, st.session_state.inlets
                )
            
            updated = calculate_min_inverts(df)
            for i, row in updated.iterrows():
                hyd = get_pipe_hydraulics(row)
                for k, v in hyd.items():
                    if k != 'Visual':
                        updated.at[i, k] = v
                
                perc = float(hyd.get('% Full', 0))
                filled = int(round(perc / 10))
                color = "ðﾟﾟﾠ" if perc < 30 else "ðﾟﾟﾢ" if perc < 80 else "ðﾟﾟﾡ" if perc <= 90 else "ðﾟﾔﾴ"
                bar = color * filled + "⬜" * (10 - filled)
                updated.at[i, 'Visual'] = f"{bar} {perc:.1f}%"

            st.session_state.pipes = updated
            st.success("✅ All calculations finished and saved successfully!")
            st.rerun()

        st.markdown("""
        **Visual Legend**  
        ðﾟﾟﾠ Too small (< 30%) ðﾟﾟﾢ Good (30–80%) ðﾟﾟﾡ Caution (80–90%) ðﾟﾔﾴ Over capacity (> 90%)
        """)

# ====================== DITCH DESIGN TAB ======================
with tab6:
    st.header("ðﾟﾚﾧ Ditch Design")
    if st.button("ðﾟﾔﾄ Sync Incoming Flows (From Drainage & Ditches)", key="btn_sync_network_ditches"):
        st.session_state.cached_ditches = st.session_state.links[
            st.session_state.links['Type'].astype(str).str.contains('Ditch', case=False, na=False)
        ].copy()
        
        ditches_sync = st.session_state.cached_ditches
        current_names_sync = set(ditches_sync['Link Name'].values)
        st.session_state.ditches_link_names = current_names_sync

        def get_upstream_discharge_sync(start_node, links_df, drainage_df, visited=None):
            if visited is None: visited = set()
            if start_node in visited: return 0.0
            visited.add(start_node)

            total = 0.0
            match = drainage_df[drainage_df['Node'] == start_node]
            if not match.empty:
                total += float(match['Discharge (cfs)'].iloc[0])

            upstream = links_df[
                (links_df['Type'].astype(str).str.contains('Ditch', case=False)) & 
                (links_df['End Node'] == start_node)
            ]
            for _, link in upstream.iterrows():
                total += get_upstream_discharge_sync(link['Start Node'], links_df, drainage_df, visited.copy())

            return round(total, 3)

        def calculate_min_inverts_sync(df):
            df = df.copy()
            nodes = pd.concat([df['Start Node'], df['End Node']]).unique()
            for node in nodes:
                incoming = df[df['End Node'] == node]
                if not incoming.empty:
                    val = incoming['Downstream Invert (ft)'].min()
                    df.loc[df['Start Node'] == node, 'Min Up Invert (ft)'] = f"{val:.2f}" if pd.notna(val) and val != 0 else "-"
                else:
                    df.loc[df['Start Node'] == node, 'Min Up Invert (ft)'] = "-"

                outgoing = df[df['Start Node'] == node]
                if not outgoing.empty:
                    val = outgoing['Upstream Invert (ft)'].min()
                    df.loc[df['End Node'] == node, 'Min Down Invert (ft)'] = f"{val:.2f}" if pd.notna(val) and val != 0 else "-"
                else:
                    df.loc[df['End Node'] == node, 'Min Down Invert (ft)'] = "-"
            return df

        def get_default_ditch_row(name, start, end, length, flow):
            return {
                'Name': str(name), 'Start Node': str(start), 'End Node': str(end), 
                'Length (ft)': float(length), 'Discharge (cfs)': float(flow),
                'Manning n': 0.013, 'Type': 'Trapezoidal', 'Left Slope': '3:1', 
                'Bottom Width (ft)': 2.0, 'Right Slope': '3:1', 'Allowable Depth (ft)': 1.0, 
                'Upstream Invert (ft)': 640.00, 'Downstream Invert (ft)': 638.00, 
                'Min Up Invert (ft)': "-", 'Min Down Invert (ft)': "-", 'Slope (%)': 0.50, 
                'Normal Depth (ft)': 0.0, 'Flow Area (ft²)': 0.0, 'Velocity (ft/s)': 0.0, 
                'Full Capacity (cfs)': 0.0, 'Visual': ''
            }

        old_df = (
            st.session_state.ditches.copy() 
            if 'ditches' in st.session_state and not st.session_state.ditches.empty 
            else pd.DataFrame()
        )

        new_rows_list = []
        for _, fresh_link in ditches_sync.iterrows():
            link_name = str(fresh_link['Link Name'])
            start_node = str(fresh_link['Start Node'])
            end_node = str(fresh_link['End Node'])
            length_val = round(float(fresh_link['Length (ft)']), 2)

            live_flow = get_upstream_discharge_sync(start_node, st.session_state.links, st.session_state.drainage_main)
            is_exact_match = False
            existing_record = None

            if not old_df.empty and 'Name' in old_df.columns:
                match_records = old_df[old_df['Name'] == link_name]
                if not match_records.empty:
                    old_row = match_records.iloc[0]
                    if (str(old_row['Start Node']) == start_node and 
                        str(old_row['End Node']) == end_node and 
                        round(float(old_row['Length (ft)']), 2) == length_val):
                        is_exact_match = True
                        existing_record = old_row.to_dict()

            if is_exact_match:
                final_row = existing_record
                final_row['Discharge (cfs)'] = float(live_flow)
            else:
                final_row = get_default_ditch_row(link_name, start_node, end_node, length_val, live_flow)

            new_rows_list.append(final_row)

        if new_rows_list:
            merged_df = pd.DataFrame(new_rows_list)
            merged_df = calculate_min_inverts_sync(merged_df)
            
            numeric_cols = [
                'Length (ft)', 'Discharge (cfs)', 'Manning n', 'Bottom Width (ft)', 
                'Allowable Depth (ft)', 'Upstream Invert (ft)', 'Downstream Invert (ft)', 
                'Slope (%)', 'Normal Depth (ft)', 'Flow Area (ft²)', 'Velocity (ft/s)', 'Full Capacity (cfs)'
            ]
            string_cols = ['Name', 'Start Node', 'End Node', 'Type', 'Left Slope', 'Right Slope', 'Min Up Invert (ft)', 'Min Down Invert (ft)', 'Visual']
            
            for col in numeric_cols:
                if col in merged_df.columns:
                    merged_df[col] = pd.to_numeric(merged_df[col], errors='coerce').fillna(0.0)
            for col in string_cols:
                if col in merged_df.columns:
                    merged_df[col] = merged_df[col].astype(str)

            target_order = [
                'Name', 'Start Node', 'End Node', 'Length (ft)', 
                'Discharge (cfs)', 'Manning n', 'Type', 'Left Slope', 
                'Bottom Width (ft)', 'Right Slope', 'Allowable Depth (ft)', 
                'Upstream Invert (ft)', 'Downstream Invert (ft)', 
                'Min Up Invert (ft)', 'Min Down Invert (ft)', 'Slope (%)', 
                'Normal Depth (ft)', 'Flow Area (ft²)', 'Velocity (ft/s)', 
                'Full Capacity (cfs)', 'Visual'
            ]
            existing_cols = [col for col in target_order if col in merged_df.columns]
            st.session_state.ditches = merged_df[existing_cols]
            st.session_state.ditches_initialized = True
            st.success("✅ Row-by-row sync complete!")
        else:
            st.session_state.ditches = pd.DataFrame()
            st.warning("Sync finished, but no links with Type='Ditch' were found.")
        st.rerun()     
        
    if 'cached_ditches' not in st.session_state:
        st.session_state.cached_ditches = st.session_state.links[
            st.session_state.links['Type'].astype(str).str.contains('Ditch', case=False, na=False)
        ].copy()

    ditches = st.session_state.cached_ditches

    if ditches.empty:
        st.warning("No Ditches found in Links tab. Please add links with Type = 'Ditch' and click Sync above.")
    else:
        if 'ditches_link_names' not in st.session_state:
            st.session_state.ditches_link_names = set(ditches['Link Name'].values)

        current_names = st.session_state.ditches_link_names

        if 'ditches_initialized' not in st.session_state or 'ditches' not in st.session_state or st.session_state.ditches.empty or set(st.session_state.ditches.get('Name', [])) != current_names:
            ditch_df = pd.DataFrame({
                'Name': ditches['Link Name'].values,
                'Start Node': ditches['Start Node'].values,
                'End Node': ditches['End Node'].values,
                'Length (ft)': ditches['Length (ft)'].values.round(2),
            })

            ditch_df['Discharge (cfs)'] = 0.0
            ditch_df['Manning n'] = 0.013
            ditch_df['Type'] = 'Trapezoidal'
            ditch_df['Left Slope'] = '3:1'
            ditch_df['Bottom Width (ft)'] = 2.0
            ditch_df['Right Slope'] = '3:1'
            ditch_df['Allowable Depth (ft)'] = 1.0
            ditch_df['Upstream Invert (ft)'] = 640.00
            ditch_df['Downstream Invert (ft)'] = 638.00
            ditch_df['Min Up Invert (ft)'] = "-"
            ditch_df['Min Down Invert (ft)'] = "-"
            ditch_df['Slope (%)'] = 0.50
            ditch_df['Normal Depth (ft)'] = 0.0
            ditch_df['Flow Area (ft²)'] = 0.0
            ditch_df['Velocity (ft/s)'] = 0.0
            ditch_df['Full Capacity (cfs)'] = 0.0
            ditch_df['Visual'] = ''

            st.session_state.ditches = ditch_df.copy()
            st.session_state.ditches_initialized = True

        def get_upstream_discharge(start_node, links, drainage_df, visited=None):
            if visited is None: visited = set()
            if start_node in visited: return 0.0
            visited.add(start_node)

            total = 0.0
            match = drainage_df[drainage_df['Node'] == start_node]
            if not match.empty:
                total += float(match['Discharge (cfs)'].iloc[0])

            upstream = links[
                (links['Type'].astype(str).str.contains('Ditch', case=False)) & 
                (links['End Node'] == start_node)
            ]
            for _, link in upstream.iterrows():
                total += get_upstream_discharge(link['Start Node'], links, drainage_df, visited.copy())

            return round(total, 3)

        def calculate_min_inverts(df):
            df = df.copy()
            nodes = pd.concat([df['Start Node'], df['End Node']]).unique()
            for node in nodes:
                incoming = df[df['End Node'] == node]
                if not incoming.empty:
                    val = incoming['Downstream Invert (ft)'].min()
                    df.loc[df['Start Node'] == node, 'Min Up Invert (ft)'] = f"{val:.2f}" if pd.notna(val) and val != 0 else "-"
                else:
                    df.loc[df['Start Node'] == node, 'Min Up Invert (ft)'] = "-"

                outgoing = df[df['Start Node'] == node]
                if not outgoing.empty:
                    val = outgoing['Upstream Invert (ft)'].min()
                    df.loc[df['End Node'] == node, 'Min Down Invert (ft)'] = f"{val:.2f}" if pd.notna(val) and val != 0 else "-"
                else:
                    df.loc[df['End Node'] == node, 'Min Down Invert (ft)'] = "-"
            return df

        ditch_config = {
            "Name": st.column_config.TextColumn(disabled=True),
            "Start Node": st.column_config.TextColumn(disabled=True),
            "End Node": st.column_config.TextColumn(disabled=True),
            "Length (ft)": st.column_config.NumberColumn(disabled=True, format="%.2f"),
            "Discharge (cfs)": st.column_config.NumberColumn(disabled=True, format="%.3f"),
            "Manning n": st.column_config.NumberColumn(min_value=0.008, max_value=0.05, format="%.3f", step=0.001),
            "Type": st.column_config.SelectboxColumn(options=["Triangular", "Trapezoidal"]),
            "Left Slope": st.column_config.SelectboxColumn(options=[f"{i}:1" for i in range(1,11)]),
            "Bottom Width (ft)": st.column_config.NumberColumn(min_value=0.0, format="%.2f", step=0.5),
            "Right Slope": st.column_config.SelectboxColumn(options=[f"{i}:1" for i in range(1,11)]),
            "Allowable Depth (ft)": st.column_config.NumberColumn(min_value=0.0, max_value=10.0, format="%.2f", step=0.001),
            "Upstream Invert (ft)": st.column_config.NumberColumn(format="%.2f", step=0.01),
            "Downstream Invert (ft)": st.column_config.NumberColumn(format="%.2f", step=0.01),
            "Min Up Invert (ft)": st.column_config.TextColumn(disabled=True),
            "Min Down Invert (ft)": st.column_config.TextColumn(disabled=True),
            "Slope (%)": st.column_config.NumberColumn(disabled=True, format="%.3f"),
            "Normal Depth (ft)": st.column_config.NumberColumn(disabled=True, format="%.3f"),
            "Flow Area (ft²)": st.column_config.NumberColumn(disabled=True, format="%.3f"),
            "Velocity (ft/s)": st.column_config.NumberColumn(disabled=True, format="%.2f"),
            "Full Capacity (cfs)": st.column_config.NumberColumn(disabled=True, format="%.3f"),
            "Visual": st.column_config.TextColumn("Visual % Full", disabled=True),
        }

        edited_ditches = st.data_editor(
            st.session_state.ditches.drop(columns=['% Full'], errors='ignore'),
            num_rows="fixed",
            use_container_width=True,
            column_config=ditch_config,
            key="ditch_editor_stable"
        )
        
        if st.button("ðﾟﾚﾀ Calculate All Ditch Hydraulics"):
            df = edited_ditches.copy()
            for i, row in df.iterrows():
                df.at[i, 'Discharge (cfs)'] = get_upstream_discharge(
                    row['Start Node'], st.session_state.links, st.session_state.drainage_main
                )
            
            updated = calculate_min_inverts(df)
            for i, row in updated.iterrows():
                hyd = get_ditch_hydraulics(row)
                for k, v in hyd.items():
                    if k != 'Visual':
                        updated.at[i, k] = v
                
                perc = float(hyd.get('% Full', 0))
                filled = int(round(perc / 10))
                color = "ðﾟﾟﾠ" if perc < 30 else "ðﾟﾟﾢ" if perc < 80 else "ðﾟﾟﾡ" if perc <= 90 else "ðﾟﾔﾴ"
                bar = color * filled + "⬜" * (10 - filled)
                updated.at[i, 'Visual'] = f"{bar} {perc:.1f}%"

            st.session_state.ditches = updated
            st.success("✅ All calculations finished and saved successfully!")
            st.rerun()

        st.markdown("""
        **Visual Legend** ðﾟﾟﾠ Too small (< 30%) ðﾟﾟﾢ Good (30–80%) ðﾟﾟﾡ Caution (80–90%) ðﾟﾔﾴ Over capacity (> 90%)
        """)

# ====================== PROFILES TAB ======================
with tab7:
    st.header("ðﾟﾓﾊ Hydraulic Profile Generator")

    st.markdown("#### ðﾟﾓﾐ Global Structural & Scaling Rules")
    col_len_method, col_scale, col_exagg = st.columns(3)
    
    with col_len_method:
        length_method = st.selectbox(
            "Pipe Length Definition Method", 
            options=["Center-to-Center", "Construction (Inner Wall to Inner Wall)"]
        )
    with col_scale:
        pdf_scale = st.selectbox("Engineering Output Scale (1 inch = X feet)", options=[50, 100], index=0)
    with col_exagg:
        vert_exagg = st.number_input("Vertical Exaggeration Scale", min_value=1.0, max_value=20.0, value=5.0, step=1.0)

    st.write("---")

    if 'profile_rows' not in st.session_state:
        st.session_state.profile_rows = [
            {"start_node": "", "outfall_node": "", "method": "Crown", "user_hgl": 0.0, "format": "DXF"}
        ]
    
    if 'profile_status' not in st.session_state:
        st.session_state.profile_status = {}

    all_available_nodes = [""]
    outfall_nodes = [""]
    if 'nodes' in st.session_state and not st.session_state.nodes.empty:
        all_available_nodes += sorted(st.session_state.nodes['Node Name'].dropna().unique().tolist())
        outfall_nodes += sorted(st.session_state.nodes[st.session_state.nodes['Type'] == 'Outfall']['Node Name'].dropna().unique().tolist())

    updated_rows = []
    for idx, row in enumerate(st.session_state.profile_rows):
        st.markdown(f"##### ðﾟﾓﾈ Profile Definition Line #{idx + 1}")
        
        (
            col_start, col_outfall, col_method, 
            col_user_hgl, col_format, col_run, 
            col_dl, col_dl_pdf, col_remove
        ) = st.columns([1.6, 1.6, 1.3, 1.3, 1.0, 1.3, 1.3, 1.3, 1.0])
        
        with col_start:
            s_node = st.selectbox(
                "Start Node", options=all_available_nodes, 
                index=all_available_nodes.index(row["start_node"]) if row["start_node"] in all_available_nodes else 0, 
                key=f"prof_start_{idx}"
            )
        
        with col_outfall:
            o_node = st.selectbox(
                "Outfall Node", options=outfall_nodes, 
                index=outfall_nodes.index(row["outfall_node"]) if row["outfall_node"] in outfall_nodes else 0, 
                key=f"prof_outfall_{idx}"
            )
        
        with col_method:
            o_method = st.selectbox(
                "Outfall Method", options=["User Input", "Crown", "Free outfall"], 
                index=["User Input", "Crown", "Free outfall"].index(row["method"]), 
                key=f"prof_method_{idx}"
            )
        
        with col_user_hgl:
            if o_method == "User Input":
                uhgl = st.number_input("User HGL Elev (ft)", value=float(row["user_hgl"]), format="%.3f", step=0.01, key=f"prof_hgl_val_{idx}")
            else:
                st.number_input("User HGL Elev (ft)", value=0.000, format="%.3f", disabled=True, key=f"prof_hgl_val_disabled_{idx}")
                uhgl = 0.0
                
        with col_format:
            fmt = st.selectbox("Format", options=["DXF"], index=["DXF"].index(row["format"]), key=f"prof_fmt_{idx}")

        with col_run:
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("ðﾟﾚﾀ Run Profile", key=f"prof_run_{idx}", use_container_width=True, type="primary"):
                if not s_node or not o_node:
                    st.error("❌ Select both nodes.")
                elif s_node == o_node:
                    st.error("❌ Cannot be identical.")
                elif 'pipes' not in st.session_state or st.session_state.pipes.empty:
                    st.error("❌ Calculate/Sync pipes first.")
                else:
                    with st.spinner("Processing CAD & Printing PDF Sheet..."):
                        try:
                            # Use tempfile.TemporaryDirectory() for Streamlit Community Cloud (Writable /tmp)
                            with tempfile.TemporaryDirectory() as tmpdir:
                                run_token = str(uuid.uuid4())[:8]
                                
                                nodes_json_path = os.path.join(tmpdir, f"temp_nodes_{idx}_{run_token}.json")
                                links_json_path = os.path.join(tmpdir, f"temp_links_{idx}_{run_token}.json")
                                pipes_json_path = os.path.join(tmpdir, f"temp_pipes_{idx}_{run_token}.json")
                                inlets_json_path = os.path.join(tmpdir, f"temp_inlets_{idx}_{run_token}.json")
                                ditches_json_path = os.path.join(tmpdir, f"temp_ditches_{idx}_{run_token}.json")
                                payload_json_path = os.path.join(tmpdir, f"temp_payload_{idx}_{run_token}.json")
                                
                                nodes_df = st.session_state.nodes.copy()
                                links_df = st.session_state.links.copy()
                                pipes_df = st.session_state.pipes.copy()
                                inlets_df = st.session_state.inlets.copy() if 'inlets' in st.session_state else pd.DataFrame()
                                ditches_df = st.session_state.ditches.copy() if 'ditches' in st.session_state else pd.DataFrame()

                                nodes_df.to_json(nodes_json_path, orient="records")
                                links_df.to_json(links_json_path, orient="records")
                                pipes_df.to_json(pipes_json_path, orient="records")
                                
                                if not inlets_df.empty:
                                    inlets_df.to_json(inlets_json_path, orient="records")
                                else:
                                    with open(inlets_json_path, "w", encoding="utf-8") as f: import json; json.dump([], f)
                                    
                                if not ditches_df.empty:
                                    ditches_df.to_json(ditches_json_path, orient="records")
                                else:
                                    with open(ditches_json_path, "w", encoding="utf-8") as f: import json; json.dump([], f)
                                
                                payload = {
                                    "start_node": s_node, "outfall_node": o_node,
                                    "method": o_method, "user_hgl": uhgl, "format": fmt,
                                    "length_method": length_method,
                                    "vertical_exaggeration": float(vert_exagg),
                                    "nodes_json": nodes_json_path, "links_json": links_json_path,
                                    "pipes_json": pipes_json_path, "inlets_json": inlets_json_path,
                                    "ditches_json": ditches_json_path, "row_index": idx,             
                                    "run_token": run_token,
                                    "app_root": tmpdir 
                                }
                                
                                
                                import json
                                with open(payload_json_path, "w", encoding="utf-8") as f:
                                    json.dump(payload, f)
                                
                                # python_runner = sys.executable
                                # real_app_root = os.path.dirname(os.path.abspath(__file__)).replace('\\', '/') if "__file__" in globals() or "__file__" in locals() else os.getcwd().replace('\\', '/')
                                
                                # inline_command = (
                                #     f"import sys; "
                                #     f"sys.path.insert(0, '{real_app_root}'); "
                                #     f"import profile_generator; "
                                #     f"profile_generator.run_headless_pipeline('{payload_json_path}')"
                                # )
                                
                                # subprocess.run([python_runner, "-c", inline_command], capture_output=True, text=True, check=True)  
                                
                                python_runner = sys.executable
                                script_dir = os.path.dirname(os.path.abspath(__file__)).replace('\\', '/') if "__file__" in globals() or "__file__" in locals() else os.getcwd().replace('\\', '/')
                                payload_path = payload_json_path.replace("\\", "/")
                                
                                cmd = [
                                    python_runner,
                                    "-c",
                                    f"import sys; sys.path.insert(0, {repr(script_dir)}); import profile_generator; profile_generator.run_headless_pipeline({repr(payload_path)})"
                                ]
                                
                                subprocess.run(cmd, capture_output=True, text=True, check=True)
                                
                                output_filename_cad = os.path.join(tmpdir, f"profile_output_{idx}_{run_token}.dxf")
                                output_filename_pdf = os.path.join(tmpdir, f"profile_output_{idx}_{run_token}.pdf")
                                
                                dxf_stable = False
                                for attempt in range(10):
                                    if os.path.exists(output_filename_cad):
                                        size_before = os.path.getsize(output_filename_cad)
                                        time.sleep(0.2)
                                        size_after = os.path.getsize(output_filename_cad)
                                        if size_before == size_after and size_after > 500:
                                            dxf_stable = True
                                            break
                                    time.sleep(0.2)

                                if not dxf_stable:
                                    st.error(f"❌ DXF generation timed out or failed.")
                                elif os.path.exists(output_filename_cad):
                                    try:
                                        doc_dxf = ezdxf.readfile(output_filename_cad)
                                        msp = doc_dxf.modelspace()

                                        for layer in doc_dxf.layers:
                                            lname = layer.dxf.name.upper()
                                            if "TEXT" in lname or "LABEL" in lname or "NOTE" in lname:
                                                layer.color = 250
                                            elif "HGL" in lname or "HYD" in lname: 
                                                layer.color = 5
                                            elif "PROP" in lname or "GROUND" in lname: 
                                                layer.color = 3
                                            elif "STRUC" in lname or "WALL" in lname: 
                                                layer.color = 1
                                            elif "PIPE" in lname or "CONDUIT" in lname: 
                                                layer.color = 4
                                            elif "HATCH" in lname: 
                                                layer.color = 8
                                            elif "JOINT" in lname: 
                                                layer.color = 6
                                            elif "GRID" in lname: 
                                                layer.color = 9
                                            else: 
                                                layer.color = 7

                                        ctx = RenderContext(doc_dxf)
                                        ctx.set_current_layout(msp)

                                        fig = plt.figure(figsize=(16.5, 11.7), dpi=600)
                                        ax = fig.add_axes([0.08, 0.08, 0.84, 0.84])
                                        ax.set_facecolor('#FFFFFF')

                                        backend = MatplotlibBackend(ax)
                                        render_config = Configuration.defaults().with_changes(
                                            text_policy=TextPolicy.REPLACE
                                        )
                                        frontend = Frontend(ctx, backend, config=render_config)
                                        frontend.draw_layout(msp, finalize=True)

                                        for collection in ax.collections:
                                            collection.set_edgecolor('#000000')
                                            collection.set_facecolor('#000000')

                                        v_exagg_factor = float(vert_exagg)
                                        if v_exagg_factor > 1.0:
                                            ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda y, pos: f"{y / v_exagg_factor:.2f}"))
                                        
                                        ax.set_axis_off()
                                        ax.set_aspect(1.0, adjustable='box')

                                        x_coords = []
                                        y_coords = []
                                        for entity in msp:
                                            if entity.dxftype() == 'LINE':
                                                x_coords.extend([entity.dxf.start.x, entity.dxf.end.x])
                                                y_coords.extend([entity.dxf.start.y, entity.dxf.end.y])
                                            elif entity.dxftype() == 'LWPOLYLINE':
                                                for pt in entity.get_points():
                                                    x_coords.append(pt[0]); y_coords.append(pt[1])
                                            elif entity.dxftype() == 'TEXT':
                                                x_coords.append(entity.dxf.insert.x)
                                                y_coords.append(entity.dxf.insert.y)

                                        if x_coords and y_coords:
                                            min_x, max_x = min(x_coords), max(x_coords)
                                            min_y, max_y = min(y_coords), max(y_coords)
                                            min_x = min_x - 10.0 

                                            feet_per_page = 14.5 * float(pdf_scale)
                                            total_length = max_x - min_x
                                            num_pages = max(1, math.ceil(total_length / feet_per_page))

                                            ax.set_ylim(min_y - 15, max_y + 15)

                                            with PdfPages(output_filename_pdf) as pdf:
                                                for i in range(num_pages):
                                                    left = min_x + (i * feet_per_page)
                                                    right = left + feet_per_page
                                                    ax.set_xlim(left, right)
                                                    pdf.savefig(fig, dpi=600)
                                            plt.close(fig)
                                        else:
                                            st.error("❌ No geometry found in DXF.")
                                            
                                    except Exception as conversion_error:
                                        log_path = os.path.join(tempfile.gettempdir(), "app_errors.log")
                                        with open(log_path, "a", encoding="utf-8") as f:
                                            f.write(f"\n[{datetime.now()}] --- RENDER ERROR ---\n")
                                            f.write(traceback.format_exc())
                                        st.warning(f"⚠️ PDF rendering engine failed. Check temporary logs for details.")

                                    # Read files into RAM bytes so they persist in session state without relying on disk
                                    cad_bytes = b""
                                    pdf_bytes = b""
                                    if os.path.exists(output_filename_cad):
                                        with open(output_filename_cad, "rb") as f:
                                            cad_bytes = f.read()
                                    if os.path.exists(output_filename_pdf):
                                        with open(output_filename_pdf, "rb") as f:
                                            pdf_bytes = f.read()

                                    st.session_state.profile_status[idx] = {
                                        "generated": True,
                                        "cad_bytes": cad_bytes,
                                        "pdf_bytes": pdf_bytes,
                                    }
                                    st.success("ðﾟﾎﾉ Engineering CAD Profile successfully plotted!")
                                    st.rerun()

                        # ✅ Updated code to capture the actual error text
                        except subprocess.CalledProcessError as freecad_err:
                            log_path = os.path.join(tempfile.gettempdir(), "app_errors.log")
                            with open(log_path, "a", encoding="utf-8") as f:
                                f.write(f"\n[{datetime.now()}] --- SUBPROCESS ERROR ---\n")
                                f.write(f"Return Code: {freecad_err.returncode}\n")
                                if freecad_err.stderr:
                                    f.write(f"Stderr:\n{freecad_err.stderr}\n")
                                if freecad_err.stdout:
                                    f.write(f"Stdout:\n{freecad_err.stdout}\n")
                                    
                            error_detail = freecad_err.stderr.strip() if freecad_err.stderr else "Check app_errors.log for details"
                            st.error(f"❌ Subprocess Engine failed: {error_detail}")
                            
                            
                        except Exception as global_err:
                            st.error(f"❌ Execution failure: {global_err}")
                            
        with col_dl:
            st.markdown("<br>", unsafe_allow_html=True)
            status_dict = st.session_state.profile_status.get(idx, {"generated": False})
            is_generated = status_dict.get("generated", False)
            cad_bytes = status_dict.get("cad_bytes")
            
            clean_start = str(s_node).strip().replace(" ", "_")
            clean_end = str(o_node).strip().replace(" ", "_")
            
            custom_download_name_cad = f"Profile-FROM-{clean_start}-TO-{clean_end}.{fmt.lower()}"
            custom_download_name_pdf = f"Profile-FROM-{clean_start}-TO-{clean_end}.pdf"
            
            if is_generated and cad_bytes:
                st.download_button(
                    label=f"ðﾟﾓﾥ CAD ({fmt})",
                    data=io.BytesIO(cad_bytes),
                    file_name=custom_download_name_cad,
                    mime="application/octet-stream",
                    use_container_width=True,
                    key=f"profile_dl_btn_cad_{idx}"
                )
            else:
                st.button("ðﾟﾓﾥ CAD Locked", disabled=True, use_container_width=True, key=f"profile_dl_cad_disabled_{idx}")

        with col_dl_pdf:
            st.markdown("<br>", unsafe_allow_html=True)
            pdf_bytes = status_dict.get("pdf_bytes")
            
            if is_generated and pdf_bytes:
                st.download_button(
                    label="ðﾟﾓﾄ Sheet (PDF)",
                    data=io.BytesIO(pdf_bytes),
                    file_name=custom_download_name_pdf,
                    mime="application/pdf",
                    use_container_width=True,
                    key=f"profile_dl_btn_pdf_{idx}"
                )
            else:
                st.button("ðﾟﾓﾄ PDF Locked", disabled=True, use_container_width=True, key=f"profile_dl_pdf_disabled_{idx}")

        with col_remove:
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("ðﾟﾗﾑ️ Remove", key=f"prof_remove_{idx}", use_container_width=True) and len(st.session_state.profile_rows) > 1:
                st.session_state.profile_rows.pop(idx)
                if idx in st.session_state.profile_status: 
                    st.session_state.profile_status.pop(idx)
                st.rerun()
                
        updated_rows.append({
            "start_node": s_node, "outfall_node": o_node,
            "method": o_method, "user_hgl": uhgl, "format": fmt
        })
        st.markdown("<hr style='margin: 0.5em 0;'>", unsafe_allow_html=True)
        
    st.session_state.profile_rows = updated_rows

    if st.button("➕ Add Profile Row Entry", type="secondary"):
        st.session_state.profile_rows.append(
            {"start_node": "", "outfall_node": "", "method": "Crown", "user_hgl": 0.0, "format": "DXF"}
        )
        st.rerun()
