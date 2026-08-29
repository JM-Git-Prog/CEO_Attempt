"""Hydrate all taxonomy leaf nodes with full Entity-Component metadata payloads.

Walks the taxonomy_tree, and for every leaf node that does not yet have a hydrated
entry in `entries`, generates a domain-appropriate metadata payload. Appends new
entries to the JSON and rebuilds the CSV.

Run repeatedly / idempotent: only fills in missing leaves.
"""
import json
import csv
import uuid
import os

BASE = r"c:\Users\JohnM\My Applications\Kiro\CEO_Kiro\CEO_Attempt\data"
JSON_PATH = os.path.join(BASE, "master_taxonomy_engine.json")
CSV_PATH = os.path.join(BASE, "master_taxonomy_engine.csv")

# Deterministic UUID namespace so re-runs produce stable IDs per taxonomy path.
NS = uuid.UUID("6ba7b814-9dad-11d1-80b4-00c04fd430c8")


def get_leaves(obj, prefix=""):
    """Return list of (full_path, leaf_name) for every leaf under obj."""
    leaves = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            child_prefix = f"{prefix}/{k}" if prefix else k
            leaves.extend(get_leaves(v, child_prefix))
    elif isinstance(obj, list):
        for item in obj:
            leaves.append((f"{prefix}/{item}", item))
    return leaves


# ---------------------------------------------------------------------------
# Per-domain metadata profiles. Each profile maps a scale heuristic derived from
# the leaf name / domain to physically plausible defaults. Keyword overrides let
# specific object families get tailored sockets / destruction / materials.
# ---------------------------------------------------------------------------

def choose_scale(domain, path, name):
    p = path.lower()
    n = name.lower()
    # Planetary
    if domain == "Planetary_Environmental":
        if any(k in n for k in ["plate", "trench", "ridge", "sheet", "ice_sheet", "rift", "ozone", "thermosphere", "mesosphere"]):
            return "Planetary"
        if any(k in n for k in ["range", "glacier", "canyon", "delta", "biome", "shelf", "cell", "front", "storm", "aquifer", "fjord"]):
            return "Regional"
        if any(k in n for k in ["lake", "fan", "swamp", "flat", "lagoon", "bank", "pack", "iceberg", "reef", "cone", "sinkhole", "moraine", "scarp", "spring", "waterfall", "vortex", "zone"]):
            return "District"
        if any(k in n for k in ["horizon", "layer", "stratum", "crust", "material"]):
            return "Component"
        return "Regional"
    # Biosphere
    if domain == "Biosphere_Living_Organisms":
        if "biome" in n:
            return "Regional"
        if any(k in n for k in ["mound", "colony", "reef"]):
            return "Building"
        if any(k in n for k in ["organelle", "nucleus", "reticulum", "apparatus", "membrane", "mitochondria", "grain", "hypha", "nodule"]):
            return "SubComponent"
        return "Component"
    # Everything else: engineered assemblies
    if any(k in n for k in ["plant", "hall", "column", "rig", "tower", "dam", "station", "terminal", "yard", "vessel", "building", "sphere", "reactor", "shell", "monocoque", "barrel", "bridge"]):
        return "Building" if any(k in n for k in ["rig", "tower", "column", "sphere", "building", "reactor"]) else "Room"
    if any(k in n for k in ["room", "bay", "hood", "cabinet", "aisle", "ward", "chamber", "car", "unit", "pool", "tank", "basin", "block"]):
        return "Room"
    if any(k in n for k in ["valve", "box", "wheel", "differential", "coupler", "knuckle", "nodule", "detector", "sensor", "manifold", "trap", "preventer", "pig", "filter", "cell"]):
        return "SubComponent"
    return "Component"


LOD_BY_SCALE = {
    "Planetary": [50000, 300000, 1500000],
    "Regional": [500, 5000, 50000],
    "District": [30, 300, 3000],
    "Building": [30, 300, 3000],
    "Room": [8, 80, 800],
    "Component": [2, 20, 200],
    "SubComponent": [0.5, 5, 50],
}

MASS_BY_SCALE = {
    "Planetary": 1.0e17,
    "Regional": 1.0e11,
    "District": 5.0e6,
    "Building": 8.0e5,
    "Room": 4.0e4,
    "Component": 1500.0,
    "SubComponent": 40.0,
}

BBOX_BY_SCALE = {
    "Planetary": [100000, 100000, 20000],
    "Regional": [4000, 4000, 2000],
    "District": [400, 400, 100],
    "Building": [40, 40, 40],
    "Room": [8, 6, 4],
    "Component": [2, 1.5, 2],
    "SubComponent": [0.4, 0.3, 0.3],
}

INTERACTION_BY_DOMAIN = {
    "Planetary_Environmental": "Static",
    "Civil_Infrastructure_Heavy_Industry": "Static",
    "Commercial_Institutional_Residential": "Static",
    "Transportation_Logistics": "Dynamic",
    "Biosphere_Living_Organisms": "Organic",
}

MATERIAL_ROOT = {
    "Planetary_Environmental": "materials/geology/generic_terrain",
    "Civil_Infrastructure_Heavy_Industry": "materials/industrial/carbon_steel_industrial",
    "Commercial_Institutional_Residential": "materials/construction/composite_assembly",
    "Transportation_Logistics": "materials/vehicle/alloy_assembly",
    "Biosphere_Living_Organisms": "materials/organic/tissue_generic",
}


def material_for(domain, name):
    n = name.lower()
    if domain == "Planetary_Environmental":
        if any(k in n for k in ["water", "lake", "river", "estuary", "spring", "waterfall", "lagoon", "aquifer", "delta", "fjord"]):
            return "materials/water/generic_fluid"
        if any(k in n for k in ["ice", "glacier", "snow", "permafrost", "iceberg"]):
            return "materials/cryosphere/ice_composite"
        if any(k in n for k in ["cloud", "storm", "fog", "dust", "ozone", "mesosphere", "thermosphere", "cell", "vortex", "front"]):
            return "materials/atmosphere/volumetric_generic"
        if any(k in n for k in ["reef", "mangrove"]):
            return "materials/ocean/reef_calcium"
        return "materials/geology/rock_terrain_composite"
    if domain == "Biosphere_Living_Organisms":
        if any(k in n for k in ["organelle", "nucleus", "membrane", "reticulum", "apparatus", "mitochondria"]):
            return "materials/organic/lipid_bilayer_membrane"
        if any(k in n for k in ["bark", "trunk", "root", "wood", "cone", "heartwood"]):
            return "materials/organic/woody_tissue"
        if any(k in n for k in ["flower", "fruit", "seed", "pollen", "leaf", "canopy"]):
            return "materials/organic/soft_plant_tissue"
        if any(k in n for k in ["shell", "coral", "exoskeleton"]):
            return "materials/organic/calcium_carbonate"
        return "materials/organic/animal_tissue_subsurface"
    if domain == "Transportation_Logistics":
        if "aerospace" in name.lower() or any(k in n for k in ["turbofan", "avionics", "rotor", "satellite", "rocket", "heat_shield", "docking", "eclss", "swashplate", "spar", "fuselage", "wing"]):
            return "materials/aerospace/titanium_composite"
        if any(k in n for k in ["marine", "hull", "bulkhead", "ballast", "rudder", "azipod", "propeller", "anchor", "davit", "bridge", "cargo", "thruster", "diesel"]):
            return "materials/marine/coated_steel"
        if any(k in n for k in ["rail", "bogie", "hopper", "pantograph", "coupler", "brake_disc", "locomotive"]):
            return "materials/rail/cast_steel"
        return "materials/automotive/formed_steel_alloy"
    if domain == "Civil_Infrastructure_Heavy_Industry":
        if any(k in n for k in ["concrete", "basin", "tank", "dam", "vessel", "containment"]):
            return "materials/industrial/reinforced_concrete"
        if any(k in n for k in ["transformer", "busbar", "breaker", "switch", "winding", "cable", "exciter"]):
            return "materials/electrical/conductor_assembly"
        return "materials/industrial/heavy_plate_steel"
    # Commercial
    if any(k in n for k in ["concrete", "pile", "slab", "footing", "wall", "beam"]):
        return "materials/construction/reinforced_concrete"
    if any(k in n for k in ["steel", "column", "truss", "rafter", "tray"]):
        return "materials/construction/structural_steel"
    if any(k in n for k in ["panel", "board", "switch", "ups", "generator", "motor", "pdu"]):
        return "materials/electrical/enclosure_assembly"
    if any(k in n for k in ["duct", "ahu", "vav", "chiller", "boiler", "tower", "fcu", "crac", "pump", "hood", "cabinet", "filter", "hepa"]):
        return "materials/mechanical/sheet_metal_assembly"
    return "materials/construction/composite_assembly"


def sockets_for(domain, name):
    n = name.lower()
    s = []
    if domain == "Planetary_Environmental":
        if any(k in n for k in ["water", "river", "lake", "estuary", "delta", "aquifer", "spring"]):
            s = [{"type": "inflow", "direction": "inflow", "connects_to": "Upstream_Source"},
                 {"type": "outflow", "direction": "outflow", "connects_to": "Downstream_Sink"}]
        elif any(k in n for k in ["cloud", "storm", "cell", "front", "vortex", "plume", "fog", "dust"]):
            s = [{"type": "moisture_flux", "direction": "bidirectional", "connects_to": "Atmosphere"},
                 {"type": "pressure", "direction": "bidirectional", "connects_to": "Adjacent_Cell"}]
        else:
            s = [{"type": "boundary", "direction": "bidirectional", "connects_to": "Adjacent_Feature"}]
        return s
    if domain == "Biosphere_Living_Organisms":
        s = [{"type": "nutrient_exchange", "direction": "bidirectional", "connects_to": "Host_System"},
             {"type": "metabolic_io", "direction": "bidirectional", "connects_to": "Environment"}]
        return s
    if domain == "Transportation_Logistics":
        s = [{"type": "power_input", "direction": "inflow", "connects_to": "Power_Bus"},
             {"type": "control_signal", "direction": "inflow", "connects_to": "Control_System"},
             {"type": "mechanical_output", "direction": "outflow", "connects_to": "Downstream_Assembly"}]
        return s
    if domain == "Civil_Infrastructure_Heavy_Industry":
        s = [{"type": "process_inflow", "direction": "inflow", "connects_to": "Upstream_Unit"},
             {"type": "process_outflow", "direction": "outflow", "connects_to": "Downstream_Unit"},
             {"type": "control_monitoring", "direction": "outflow", "connects_to": "SCADA"}]
        return s
    # Commercial / MEP / structural
    if any(k in n for k in ["panel", "board", "switch", "ups", "generator", "motor", "pdu"]):
        s = [{"type": "power_input", "direction": "inflow", "connects_to": "Upstream_Distribution"},
             {"type": "power_output", "direction": "outflow", "connects_to": "Branch_Loads"},
             {"type": "monitoring", "direction": "outflow", "connects_to": "BMS"}]
    elif any(k in n for k in ["duct", "ahu", "vav", "chiller", "boiler", "tower", "fcu", "crac", "pump", "heater", "stack", "drain", "trap", "preventer"]):
        s = [{"type": "medium_supply", "direction": "inflow", "connects_to": "Distribution_Main"},
             {"type": "medium_return", "direction": "outflow", "connects_to": "Return_Main"},
             {"type": "control", "direction": "inflow", "connects_to": "BMS"}]
    else:
        s = [{"type": "structural_connection", "direction": "bidirectional", "connects_to": "Adjacent_Member"},
             {"type": "load_path", "direction": "inflow", "connects_to": "Support_Structure"}]
    return s


def destruction_for(domain, scale, name):
    n = name.lower()
    d = {"intact": 1.0, "damaged": 0.6, "critical": 0.2, "destroyed": 0.0}
    if domain == "Planetary_Environmental":
        d["fragmentation_pattern"] = "erosion_decay"
    elif domain == "Biosphere_Living_Organisms":
        d = {"intact": 1.0, "stressed": 0.6, "necrotic": 0.2, "decomposed": 0.0, "fragmentation_pattern": "organic_decay"}
    elif domain == "Transportation_Logistics":
        d["fragmentation_pattern"] = "mechanical_failure"
    elif domain == "Civil_Infrastructure_Heavy_Industry":
        d["fragmentation_pattern"] = "structural_failure"
        if any(k in n for k in ["tank", "column", "sphere", "vessel", "transformer", "reactor"]):
            d["blast_radius_m"] = 100
    else:
        d["fragmentation_pattern"] = "structural_collapse"
        if any(k in n for k in ["switch", "board", "panel", "ups"]):
            d["blast_radius_m"] = 3
    return d


def display_name(name):
    return name.replace("_", " ")


def deterministic_id(domain_prefix, path):
    u = uuid.uuid5(NS, path)
    # keep v4-style formatting but stable
    return f"{domain_prefix}{str(u)[8:]}"


DOMAIN_PREFIX = {
    "Planetary_Environmental": "a1b2c3d4",
    "Civil_Infrastructure_Heavy_Industry": "b1b2c3d4",
    "Commercial_Institutional_Residential": "c1b2c3d4",
    "Transportation_Logistics": "d1b2c3d4",
    "Biosphere_Living_Organisms": "e1b2c3d4",
}

# Taxonomy_Path root remap so hydrated entries mirror the sample entries' style.
PATH_ROOT_REMAP = {
    "Commercial_Institutional_Residential": "Buildings",
    "Transportation_Logistics": "Transportation",
    "Civil_Infrastructure_Heavy_Industry": "Civil_Infrastructure",
    "Biosphere_Living_Organisms": "Biosphere",
    "Planetary_Environmental": "Planetary_Environmental",
}


def main():
    with open(JSON_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    existing_names = {e["Taxonomy_Path"].split("/")[-1] for e in data["entries"]}
    tree = data["taxonomy_tree"]

    added = 0
    for domain, subtree in tree.items():
        prefix = DOMAIN_PREFIX[domain]
        root_remap = PATH_ROOT_REMAP[domain]
        for full_path, leaf in get_leaves(subtree):
            if leaf in existing_names:
                continue
            # Build a taxonomy path: <root_remap>/<middle segments>/<leaf>
            segments = full_path.split("/")
            tail = "/".join(segments)  # e.g. Geosphere/Lithosphere/Mountain_Range
            tax_path = f"{root_remap}/{tail}"
            scale = choose_scale(domain, full_path, leaf)
            entry = {
                "Entity_ID": deterministic_id(prefix, tax_path),
                "Domain_Class": domain,
                "Taxonomy_Path": tax_path,
                "Display_Name": display_name(leaf),
                "LOD_Threshold": LOD_BY_SCALE[scale],
                "Network_Sockets": sockets_for(domain, leaf),
                "Material_Shader": material_for(domain, leaf),
                "Destruction_States": destruction_for(domain, scale, leaf),
                "Scale_Class": scale,
                "Interaction_Type": INTERACTION_BY_DOMAIN[domain],
                "Mass_kg": MASS_BY_SCALE[scale],
                "Bounding_Volume": BBOX_BY_SCALE[scale],
            }
            data["entries"].append(entry)
            existing_names.add(leaf)
            added += 1

    # Update statistics
    data["statistics"]["total_entries"] = len(data["entries"])

    with open(JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    print(f"Added {added} entries. Total now: {len(data['entries'])}")

    # Rebuild CSV
    fieldnames = [
        "Entity_ID", "Domain_Class", "Taxonomy_Path", "Display_Name",
        "LOD_Near_m", "LOD_Mid_m", "LOD_Far_m", "Scale_Class", "Interaction_Type",
        "Mass_kg", "BBox_X_m", "BBox_Y_m", "BBox_Z_m", "Material_Shader",
        "Network_Socket_Count", "Destruction_Pattern", "Blast_Radius_m",
    ]
    with open(CSV_PATH, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(fieldnames)
        for e in data["entries"]:
            lod = e["LOD_Threshold"]
            bbox = e["Bounding_Volume"]
            ds = e["Destruction_States"]
            w.writerow([
                e["Entity_ID"], e["Domain_Class"], e["Taxonomy_Path"], e["Display_Name"],
                lod[0], lod[1], lod[2], e["Scale_Class"], e["Interaction_Type"],
                e["Mass_kg"], bbox[0], bbox[1], bbox[2], e["Material_Shader"],
                len(e["Network_Sockets"]), ds.get("fragmentation_pattern", ""),
                ds.get("blast_radius_m", ""),
            ])
    print(f"CSV rebuilt with {len(data['entries'])} rows.")


if __name__ == "__main__":
    main()
