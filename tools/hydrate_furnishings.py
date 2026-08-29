"""Hydrate the Consumer_Furnishings sub-tree with realistic per-item metadata.

The general industrial hydrator (hydrate_taxonomy.py) uses keyword heuristics
tuned for plant/rig/vessel objects and would give a couch Room-scale mass and
structural sockets. Furnishings need household-accurate physics, materials,
interaction types, and connection sockets so the v2.0 pipeline can bind them.

This script ONLY touches leaves under
Commercial_Institutional_Residential/Residential/Consumer_Furnishings and is
idempotent (deterministic uuid5 from Taxonomy_Path; skips already-hydrated
leaves). It rebuilds the CSV to match after appending.

Run after hydrate_taxonomy.py, or standalone.
"""
import json
import csv
import uuid
import os

BASE = r"c:\Users\JohnM\My Applications\Kiro\CEO_Kiro\CEO_Attempt\data"
JSON_PATH = os.path.join(BASE, "master_taxonomy_engine.json")
CSV_PATH = os.path.join(BASE, "master_taxonomy_engine.csv")

NS = uuid.UUID("6ba7b814-9dad-11d1-80b4-00c04fd430c8")
DOMAIN = "Commercial_Institutional_Residential"
PREFIX = "c1b2c3d4"
ROOT = "Buildings/Consumer_Furnishings"

# ---------------------------------------------------------------------------
# Per-leaf metadata table. Fields per entry:
#   scale, mass_kg, bbox [x,y,z] meters, interaction, material_shader,
#   sockets (list of dicts), destruction (dict)
# Sockets model how a household object connects: power, water, data, or a
# structural/support relationship (rests_on / mounts_to / stacks_in).
# Interaction types: Static | Dynamic | Destructible | Animated.
# ---------------------------------------------------------------------------

# Reusable socket builders --------------------------------------------------
def rests_on(surface="Floor"):
    return {"type": "support", "direction": "inflow", "connects_to": surface}

def power():
    return {"type": "power_ac", "direction": "inflow", "connects_to": "Wall_Outlet"}

def water_supply():
    return {"type": "water_supply", "direction": "inflow", "connects_to": "Plumbing_Supply"}

def drain():
    return {"type": "drain", "direction": "outflow", "connects_to": "Plumbing_Drain"}

def data():
    return {"type": "data_network", "direction": "bidirectional", "connects_to": "Home_Network"}

def av_in():
    return {"type": "av_input", "direction": "inflow", "connects_to": "Media_Source"}

def mounts_to(surface="Wall"):
    return {"type": "mount", "direction": "inflow", "connects_to": surface}

def ceiling():
    return {"type": "ceiling_mount", "direction": "inflow", "connects_to": "Ceiling"}

# Destruction presets -------------------------------------------------------
D_SOFT = {"intact": 1.0, "worn": 0.6, "torn": 0.3, "destroyed": 0.0, "fragmentation_pattern": "fabric_tear_foam"}
D_WOOD = {"intact": 1.0, "scratched": 0.6, "cracked": 0.3, "splintered": 0.0, "fragmentation_pattern": "wood_splinter"}
D_GLASS = {"intact": 1.0, "chipped": 0.6, "cracked": 0.3, "shattered": 0.0, "fragmentation_pattern": "glass_shatter"}
D_CERAMIC = {"intact": 1.0, "chipped": 0.7, "cracked": 0.3, "shattered": 0.0, "fragmentation_pattern": "ceramic_shatter"}
D_APPLIANCE = {"intact": 1.0, "dented": 0.7, "malfunction": 0.3, "dead": 0.0, "fragmentation_pattern": "panel_crumple"}
D_ELECTRONIC = {"intact": 1.0, "scratched": 0.7, "cracked_screen": 0.3, "dead": 0.0, "fragmentation_pattern": "screen_shatter_board"}
D_METAL = {"intact": 1.0, "dented": 0.6, "bent": 0.3, "broken": 0.0, "fragmentation_pattern": "metal_deform"}
D_PLANT = {"intact": 1.0, "wilting": 0.6, "dead": 0.2, "decomposed": 0.0, "fragmentation_pattern": "organic_decay"}
D_PAPER = {"intact": 1.0, "creased": 0.6, "torn": 0.3, "destroyed": 0.0, "fragmentation_pattern": "paper_tear"}

M = "materials/furnishing/"

# leaf -> (scale, mass, bbox, interaction, material, sockets, destruction)
FURN = {
    # Seating -------------------------------------------------------------
    "Sofa_Couch": ("Component", 55, [2.0, 0.9, 0.9], "Dynamic", M+"upholstery_fabric", [rests_on()], D_SOFT),
    "Sectional_Sofa": ("Component", 110, [2.8, 0.9, 1.8], "Dynamic", M+"upholstery_fabric", [rests_on()], D_SOFT),
    "Loveseat": ("Component", 40, [1.5, 0.9, 0.9], "Dynamic", M+"upholstery_fabric", [rests_on()], D_SOFT),
    "Recliner": ("Component", 45, [0.9, 1.1, 1.0], "Animated", M+"upholstery_leather", [rests_on()], D_SOFT),
    "Armchair": ("Component", 30, [0.9, 0.9, 0.9], "Dynamic", M+"upholstery_fabric", [rests_on()], D_SOFT),
    "Accent_Chair": ("Component", 12, [0.7, 0.8, 0.7], "Dynamic", M+"upholstery_fabric", [rests_on()], D_SOFT),
    "Dining_Chair": ("Component", 6, [0.5, 0.9, 0.5], "Dynamic", M+"wood_finished", [rests_on()], D_WOOD),
    "Office_Chair": ("Component", 14, [0.6, 1.1, 0.6], "Animated", M+"mesh_plastic_metal", [rests_on()], D_METAL),
    "Bar_Stool": ("Component", 7, [0.4, 0.75, 0.4], "Dynamic", M+"wood_metal", [rests_on()], D_METAL),
    "Bean_Bag": ("Component", 4, [0.9, 0.7, 0.9], "Dynamic", M+"vinyl_bead_fill", [rests_on()], D_SOFT),
    "Ottoman_Footstool": ("Component", 8, [0.6, 0.4, 0.6], "Dynamic", M+"upholstery_fabric", [rests_on()], D_SOFT),
    "Bench": ("Component", 15, [1.2, 0.45, 0.4], "Dynamic", M+"wood_finished", [rests_on()], D_WOOD),
    # Tables / surfaces ---------------------------------------------------
    "Coffee_Table": ("Component", 18, [1.1, 0.45, 0.6], "Dynamic", M+"wood_glass_top", [rests_on()], D_WOOD),
    "Side_End_Table": ("Component", 9, [0.5, 0.6, 0.5], "Dynamic", M+"wood_finished", [rests_on()], D_WOOD),
    "Dining_Table": ("Component", 35, [1.8, 0.75, 0.9], "Dynamic", M+"wood_finished", [rests_on()], D_WOOD),
    "Console_Table": ("Component", 20, [1.2, 0.8, 0.35], "Dynamic", M+"wood_finished", [rests_on(), mounts_to()], D_WOOD),
    "Desk": ("Component", 30, [1.4, 0.75, 0.7], "Dynamic", M+"wood_laminate", [rests_on()], D_WOOD),
    "Nightstand": ("Component", 12, [0.45, 0.6, 0.4], "Dynamic", M+"wood_finished", [rests_on()], D_WOOD),
    "Dressing_Table": ("Component", 22, [1.0, 0.75, 0.45], "Dynamic", M+"wood_finished_mirror", [rests_on()], D_WOOD),
    "Kitchen_Island_Furniture": ("Component", 90, [1.5, 0.9, 0.7], "Static", M+"wood_stone_top", [rests_on()], D_WOOD),
    # Storage / casegoods -------------------------------------------------
    "Bookshelf": ("Component", 35, [0.8, 1.8, 0.3], "Static", M+"wood_laminate", [rests_on(), mounts_to()], D_WOOD),
    "Wardrobe_Armoire": ("Component", 70, [1.2, 2.0, 0.6], "Static", M+"wood_finished", [rests_on(), mounts_to()], D_WOOD),
    "Dresser_Drawers": ("Component", 45, [1.0, 0.9, 0.5], "Dynamic", M+"wood_finished", [rests_on()], D_WOOD),
    "Sideboard_Buffet": ("Component", 50, [1.6, 0.85, 0.45], "Static", M+"wood_finished", [rests_on()], D_WOOD),
    "TV_Media_Console": ("Component", 30, [1.6, 0.5, 0.4], "Static", M+"wood_laminate", [rests_on()], D_WOOD),
    "Filing_Cabinet": ("Component", 28, [0.45, 1.3, 0.6], "Dynamic", M+"steel_painted", [rests_on()], D_METAL),
    "Display_Cabinet": ("Component", 40, [0.9, 1.8, 0.4], "Static", M+"wood_glass_front", [rests_on(), mounts_to()], D_GLASS),
    "Coat_Rack": ("Component", 5, [0.5, 1.7, 0.5], "Dynamic", M+"wood_metal", [rests_on()], D_METAL),
    "Shoe_Rack": ("Component", 6, [0.7, 0.8, 0.3], "Dynamic", M+"metal_wire", [rests_on()], D_METAL),
    "Storage_Bin_Basket": ("SubComponent", 2, [0.4, 0.35, 0.4], "Dynamic", M+"woven_plastic", [rests_on(), {"type": "stacks_in", "direction": "inflow", "connects_to": "Shelf"}], D_SOFT),
    # Sleeping ------------------------------------------------------------
    "Bed_Frame": ("Component", 50, [2.0, 0.5, 1.6], "Static", M+"wood_metal", [rests_on()], D_WOOD),
    "Mattress": ("Component", 30, [2.0, 0.3, 1.6], "Dynamic", M+"mattress_foam_fabric", [{"type": "rests_on", "direction": "inflow", "connects_to": "Bed_Frame"}], D_SOFT),
    "Bunk_Bed": ("Component", 80, [2.0, 1.7, 1.0], "Static", M+"wood_metal", [rests_on()], D_WOOD),
    "Crib": ("Component", 25, [1.4, 1.0, 0.75], "Static", M+"wood_finished", [rests_on()], D_WOOD),
    "Headboard": ("Component", 18, [1.6, 1.2, 0.1], "Static", M+"upholstery_wood", [mounts_to(), {"type": "attaches_to", "direction": "inflow", "connects_to": "Bed_Frame"}], D_WOOD),
    # Lighting ------------------------------------------------------------
    "Floor_Lamp": ("Component", 6, [0.4, 1.6, 0.4], "Dynamic", M+"metal_shade_fabric", [rests_on(), power()], D_METAL),
    "Table_Lamp": ("SubComponent", 2.5, [0.35, 0.55, 0.35], "Dynamic", M+"ceramic_shade_fabric", [{"type": "rests_on", "direction": "inflow", "connects_to": "Surface"}, power()], D_CERAMIC),
    "Desk_Lamp": ("SubComponent", 1.5, [0.2, 0.5, 0.2], "Animated", M+"metal_plastic", [{"type": "rests_on", "direction": "inflow", "connects_to": "Desk"}, power()], D_METAL),
    "Pendant_Light_Residential": ("SubComponent", 3, [0.4, 0.5, 0.4], "Static", M+"metal_glass_shade", [ceiling(), power()], D_GLASS),
    "Chandelier": ("Component", 15, [0.9, 0.8, 0.9], "Static", M+"metal_crystal", [ceiling(), power()], D_GLASS),
    "Ceiling_Flush_Mount": ("SubComponent", 2, [0.4, 0.15, 0.4], "Static", M+"glass_metal_diffuser", [ceiling(), power()], D_GLASS),
    "Wall_Sconce": ("SubComponent", 1.5, [0.2, 0.3, 0.15], "Static", M+"metal_glass_shade", [mounts_to(), power()], D_GLASS),
    "Track_Lighting": ("Component", 4, [1.2, 0.12, 0.1], "Static", M+"metal_track_fixtures", [ceiling(), power()], D_METAL),
    "String_Lights": ("SubComponent", 0.3, [3.0, 0.05, 0.05], "Static", M+"wire_led_bulbs", [mounts_to(), power()], D_ELECTRONIC),
    "LED_Strip": ("SubComponent", 0.1, [2.0, 0.02, 0.01], "Static", M+"adhesive_led_strip", [mounts_to(), power()], D_ELECTRONIC),
    # Soft goods ----------------------------------------------------------
    "Area_Rug": ("Component", 8, [2.4, 0.02, 1.6], "Static", M+"woven_textile", [rests_on()], D_SOFT),
    "Runner_Rug": ("Component", 3, [2.5, 0.02, 0.7], "Static", M+"woven_textile", [rests_on()], D_SOFT),
    "Curtain_Drapes": ("Component", 3, [1.5, 2.4, 0.05], "Dynamic", M+"drapery_fabric", [{"type": "hangs_from", "direction": "inflow", "connects_to": "Curtain_Rod"}], D_SOFT),
    "Throw_Blanket": ("SubComponent", 1.5, [1.5, 0.05, 1.2], "Dynamic", M+"knit_fabric", [{"type": "drapes_over", "direction": "inflow", "connects_to": "Seating"}], D_SOFT),
    "Throw_Pillow": ("SubComponent", 0.8, [0.45, 0.15, 0.45], "Dynamic", M+"cushion_fabric", [{"type": "rests_on", "direction": "inflow", "connects_to": "Seating"}], D_SOFT),
    "Bed_Linens": ("SubComponent", 2, [2.0, 0.1, 1.6], "Dynamic", M+"cotton_bedding", [{"type": "covers", "direction": "inflow", "connects_to": "Mattress"}], D_SOFT),
    "Towel": ("SubComponent", 0.4, [0.7, 0.02, 0.4], "Dynamic", M+"terry_cloth", [{"type": "hangs_from", "direction": "inflow", "connects_to": "Towel_Rack"}], D_SOFT),
    "Tablecloth": ("SubComponent", 0.6, [1.8, 0.02, 0.9], "Dynamic", M+"table_linen", [{"type": "drapes_over", "direction": "inflow", "connects_to": "Dining_Table"}], D_SOFT),
    # Major appliances ----------------------------------------------------
    "Refrigerator": ("Room", 90, [0.9, 1.8, 0.75], "Dynamic", M+"steel_enamel", [rests_on(), power()], D_APPLIANCE),
    "Mini_Fridge": ("Component", 25, [0.5, 0.85, 0.5], "Dynamic", M+"steel_enamel", [rests_on(), power()], D_APPLIANCE),
    "Oven_Range": ("Room", 70, [0.76, 0.9, 0.7], "Dynamic", M+"steel_enamel", [rests_on(), power(), {"type": "gas_supply", "direction": "inflow", "connects_to": "Gas_Line"}], D_APPLIANCE),
    "Cooktop": ("Component", 15, [0.6, 0.1, 0.5], "Dynamic", M+"glass_ceramic_steel", [mounts_to("Countertop"), power()], D_GLASS),
    "Microwave": ("Component", 15, [0.5, 0.3, 0.4], "Dynamic", M+"steel_plastic", [rests_on(), power()], D_APPLIANCE),
    "Dishwasher": ("Component", 45, [0.6, 0.85, 0.6], "Dynamic", M+"steel_enamel", [power(), water_supply(), drain()], D_APPLIANCE),
    "Washing_Machine": ("Component", 70, [0.6, 0.85, 0.6], "Dynamic", M+"steel_enamel", [power(), water_supply(), drain()], D_APPLIANCE),
    "Clothes_Dryer": ("Component", 40, [0.6, 0.85, 0.6], "Dynamic", M+"steel_enamel", [power(), {"type": "vent", "direction": "outflow", "connects_to": "Exterior_Vent"}], D_APPLIANCE),
    "Range_Hood_Residential": ("Component", 12, [0.9, 0.4, 0.5], "Dynamic", M+"steel_brushed", [mounts_to(), power(), {"type": "vent", "direction": "outflow", "connects_to": "Exterior_Vent"}], D_METAL),
    "Water_Heater_Tank": ("Component", 60, [0.55, 1.5, 0.55], "Static", M+"steel_insulated", [water_supply(), power()], D_APPLIANCE),
    # Small appliances ----------------------------------------------------
    "Toaster": ("SubComponent", 1.5, [0.3, 0.2, 0.18], "Dynamic", M+"steel_plastic", [{"type": "rests_on", "direction": "inflow", "connects_to": "Countertop"}, power()], D_APPLIANCE),
    "Coffee_Maker": ("SubComponent", 3, [0.25, 0.35, 0.2], "Dynamic", M+"plastic_steel", [{"type": "rests_on", "direction": "inflow", "connects_to": "Countertop"}, power(), water_supply()], D_APPLIANCE),
    "Electric_Kettle": ("SubComponent", 1, [0.2, 0.25, 0.16], "Dynamic", M+"steel_plastic", [{"type": "rests_on", "direction": "inflow", "connects_to": "Countertop"}, power()], D_APPLIANCE),
    "Blender": ("SubComponent", 2, [0.18, 0.4, 0.18], "Dynamic", M+"plastic_glass", [{"type": "rests_on", "direction": "inflow", "connects_to": "Countertop"}, power()], D_GLASS),
    "Food_Processor": ("SubComponent", 3, [0.22, 0.4, 0.22], "Dynamic", M+"plastic_steel", [{"type": "rests_on", "direction": "inflow", "connects_to": "Countertop"}, power()], D_APPLIANCE),
    "Stand_Mixer": ("SubComponent", 5, [0.35, 0.35, 0.22], "Animated", M+"cast_metal_enamel", [{"type": "rests_on", "direction": "inflow", "connects_to": "Countertop"}, power()], D_METAL),
    "Air_Fryer": ("SubComponent", 4, [0.3, 0.35, 0.3], "Dynamic", M+"plastic_steel", [{"type": "rests_on", "direction": "inflow", "connects_to": "Countertop"}, power()], D_APPLIANCE),
    "Rice_Cooker": ("SubComponent", 2.5, [0.28, 0.25, 0.28], "Dynamic", M+"plastic_steel", [{"type": "rests_on", "direction": "inflow", "connects_to": "Countertop"}, power()], D_APPLIANCE),
    "Vacuum_Cleaner": ("Component", 6, [0.3, 1.1, 0.3], "Dynamic", M+"plastic_composite", [rests_on(), power()], D_APPLIANCE),
    "Space_Heater": ("SubComponent", 3, [0.3, 0.4, 0.2], "Dynamic", M+"plastic_metal", [rests_on(), power()], D_APPLIANCE),
    "Fan_Portable": ("SubComponent", 3, [0.4, 0.5, 0.25], "Animated", M+"plastic_metal", [rests_on(), power()], D_APPLIANCE),
    "Air_Purifier": ("SubComponent", 5, [0.35, 0.55, 0.2], "Dynamic", M+"plastic_composite", [rests_on(), power()], D_APPLIANCE),
    "Humidifier": ("SubComponent", 3, [0.25, 0.35, 0.25], "Dynamic", M+"plastic_composite", [rests_on(), power(), water_supply()], D_APPLIANCE),
    # Electronics ---------------------------------------------------------
    "Television": ("Component", 15, [1.2, 0.7, 0.08], "Dynamic", M+"glass_plastic_panel", [{"type": "rests_on", "direction": "inflow", "connects_to": "TV_Media_Console"}, mounts_to(), power(), av_in()], D_ELECTRONIC),
    "Computer_Monitor": ("SubComponent", 4, [0.6, 0.4, 0.05], "Dynamic", M+"glass_plastic_panel", [{"type": "rests_on", "direction": "inflow", "connects_to": "Desk"}, power(), data()], D_ELECTRONIC),
    "Desktop_Computer": ("SubComponent", 8, [0.2, 0.45, 0.45], "Dynamic", M+"steel_plastic_case", [rests_on(), power(), data()], D_ELECTRONIC),
    "Laptop": ("SubComponent", 1.5, [0.35, 0.02, 0.25], "Dynamic", M+"aluminum_plastic", [{"type": "rests_on", "direction": "inflow", "connects_to": "Surface"}, power(), data()], D_ELECTRONIC),
    "Game_Console": ("SubComponent", 3, [0.3, 0.08, 0.25], "Dynamic", M+"plastic_composite", [rests_on(), power(), av_in(), data()], D_ELECTRONIC),
    "Speaker_System": ("SubComponent", 5, [0.25, 0.4, 0.25], "Dynamic", M+"wood_fabric_grille", [rests_on(), power(), av_in()], D_WOOD),
    "Soundbar": ("SubComponent", 3, [1.0, 0.08, 0.1], "Dynamic", M+"plastic_fabric_grille", [{"type": "rests_on", "direction": "inflow", "connects_to": "TV_Media_Console"}, power(), av_in()], D_ELECTRONIC),
    "Router_Modem": ("SubComponent", 0.5, [0.2, 0.15, 0.15], "Static", M+"plastic_case", [rests_on(), power(), data()], D_ELECTRONIC),
    "Tablet_Device": ("SubComponent", 0.5, [0.25, 0.01, 0.17], "Dynamic", M+"glass_aluminum", [{"type": "rests_on", "direction": "inflow", "connects_to": "Surface"}, power()], D_ELECTRONIC),
    "Smart_Speaker": ("SubComponent", 1, [0.1, 0.18, 0.1], "Static", M+"plastic_fabric", [rests_on(), power(), data()], D_ELECTRONIC),
    "Projector": ("SubComponent", 3, [0.3, 0.12, 0.25], "Dynamic", M+"plastic_case", [rests_on(), ceiling(), power(), av_in()], D_ELECTRONIC),
    "Turntable_Stereo": ("SubComponent", 5, [0.45, 0.15, 0.35], "Animated", M+"wood_plastic_metal", [rests_on(), power(), av_in()], D_ELECTRONIC),
    # Kitchen tableware ---------------------------------------------------
    "Dinner_Plate": ("SubComponent", 0.5, [0.27, 0.03, 0.27], "Dynamic", M+"ceramic_glazed", [{"type": "stacks_in", "direction": "inflow", "connects_to": "Cabinet"}], D_CERAMIC),
    "Bowl": ("SubComponent", 0.4, [0.18, 0.08, 0.18], "Dynamic", M+"ceramic_glazed", [{"type": "stacks_in", "direction": "inflow", "connects_to": "Cabinet"}], D_CERAMIC),
    "Drinking_Glass": ("SubComponent", 0.3, [0.08, 0.14, 0.08], "Dynamic", M+"glass_clear", [{"type": "stacks_in", "direction": "inflow", "connects_to": "Cabinet"}], D_GLASS),
    "Mug": ("SubComponent", 0.35, [0.12, 0.1, 0.09], "Dynamic", M+"ceramic_glazed", [{"type": "rests_on", "direction": "inflow", "connects_to": "Surface"}], D_CERAMIC),
    "Cutlery_Set": ("SubComponent", 1, [0.3, 0.05, 0.2], "Dynamic", M+"stainless_steel", [{"type": "stored_in", "direction": "inflow", "connects_to": "Drawer"}], D_METAL),
    "Cooking_Pot": ("SubComponent", 2, [0.25, 0.18, 0.25], "Dynamic", M+"stainless_steel", [{"type": "rests_on", "direction": "inflow", "connects_to": "Cooktop"}], D_METAL),
    "Frying_Pan": ("SubComponent", 1.2, [0.45, 0.06, 0.28], "Dynamic", M+"cast_iron_nonstick", [{"type": "rests_on", "direction": "inflow", "connects_to": "Cooktop"}], D_METAL),
    "Cutting_Board": ("SubComponent", 0.8, [0.4, 0.03, 0.28], "Dynamic", M+"wood_bamboo", [{"type": "rests_on", "direction": "inflow", "connects_to": "Countertop"}], D_WOOD),
    "Knife_Block": ("SubComponent", 1.5, [0.15, 0.25, 0.1], "Static", M+"wood_steel_blades", [{"type": "rests_on", "direction": "inflow", "connects_to": "Countertop"}], D_WOOD),
    "Water_Pitcher": ("SubComponent", 0.6, [0.14, 0.25, 0.14], "Dynamic", M+"glass_plastic", [{"type": "rests_on", "direction": "inflow", "connects_to": "Surface"}], D_GLASS),
    "Wine_Glass": ("SubComponent", 0.2, [0.08, 0.2, 0.08], "Dynamic", M+"glass_thin", [{"type": "rests_on", "direction": "inflow", "connects_to": "Surface"}], D_GLASS),
    "Serving_Tray": ("SubComponent", 0.7, [0.45, 0.04, 0.3], "Dynamic", M+"wood_metal", [{"type": "rests_on", "direction": "inflow", "connects_to": "Surface"}], D_WOOD),
    # Decor ---------------------------------------------------------------
    "Framed_Picture": ("SubComponent", 1, [0.4, 0.5, 0.03], "Static", M+"wood_frame_glass", [mounts_to()], D_GLASS),
    "Wall_Art_Canvas": ("SubComponent", 1.5, [0.8, 0.6, 0.04], "Static", M+"canvas_wood_frame", [mounts_to()], D_PAPER),
    "Wall_Mirror": ("Component", 5, [0.6, 0.9, 0.03], "Static", M+"mirror_glass_frame", [mounts_to()], D_GLASS),
    "Vase": ("SubComponent", 1, [0.15, 0.3, 0.15], "Dynamic", M+"ceramic_glazed", [{"type": "rests_on", "direction": "inflow", "connects_to": "Surface"}], D_CERAMIC),
    "Potted_Plant_Live": ("Component", 6, [0.4, 0.9, 0.4], "Organic", M+"foliage_soil_ceramic", [{"type": "rests_on", "direction": "inflow", "connects_to": "Floor"}], D_PLANT),
    "Artificial_Plant": ("Component", 3, [0.4, 0.9, 0.4], "Static", M+"plastic_foliage", [{"type": "rests_on", "direction": "inflow", "connects_to": "Floor"}], D_SOFT),
    "Wall_Clock": ("SubComponent", 1, [0.3, 0.3, 0.05], "Animated", M+"plastic_glass_face", [mounts_to(), {"type": "battery", "direction": "inflow", "connects_to": "Battery"}], D_GLASS),
    "Table_Clock": ("SubComponent", 0.5, [0.15, 0.12, 0.08], "Animated", M+"plastic_metal", [{"type": "rests_on", "direction": "inflow", "connects_to": "Surface"}], D_METAL),
    "Candle": ("SubComponent", 0.3, [0.08, 0.12, 0.08], "Dynamic", M+"wax_wick", [{"type": "rests_on", "direction": "inflow", "connects_to": "Surface"}], D_SOFT),
    "Sculpture_Figurine": ("SubComponent", 1.5, [0.2, 0.3, 0.2], "Static", M+"ceramic_metal_resin", [{"type": "rests_on", "direction": "inflow", "connects_to": "Surface"}], D_CERAMIC),
    "Bookend": ("SubComponent", 1, [0.12, 0.18, 0.1], "Dynamic", M+"metal_wood_stone", [{"type": "rests_on", "direction": "inflow", "connects_to": "Shelf"}], D_METAL),
    "Magazine_Rack": ("SubComponent", 2, [0.35, 0.4, 0.25], "Dynamic", M+"metal_wood", [rests_on()], D_METAL),
    "Wastebasket": ("SubComponent", 1, [0.28, 0.35, 0.28], "Dynamic", M+"plastic_metal", [rests_on()], D_METAL),
    "Doormat": ("SubComponent", 1, [0.75, 0.02, 0.45], "Static", M+"coir_rubber", [rests_on()], D_SOFT),
    # Bathroom fixtures ---------------------------------------------------
    "Toilet": ("Component", 45, [0.4, 0.75, 0.65], "Dynamic", M+"vitreous_china", [{"type": "mounts_to", "direction": "inflow", "connects_to": "Floor"}, water_supply(), drain()], D_CERAMIC),
    "Bathroom_Vanity_Sink": ("Component", 35, [0.6, 0.85, 0.5], "Dynamic", M+"ceramic_wood_cabinet", [{"type": "mounts_to", "direction": "inflow", "connects_to": "Wall"}, water_supply(), drain()], D_CERAMIC),
    "Bathtub": ("Room", 80, [1.7, 0.6, 0.75], "Static", M+"acrylic_enamel", [{"type": "mounts_to", "direction": "inflow", "connects_to": "Floor"}, water_supply(), drain()], D_CERAMIC),
    "Shower_Stall": ("Room", 60, [0.9, 2.1, 0.9], "Static", M+"acrylic_glass_tile", [{"type": "mounts_to", "direction": "inflow", "connects_to": "Wall"}, water_supply(), drain()], D_GLASS),
    "Towel_Rack": ("SubComponent", 0.8, [0.6, 0.1, 0.1], "Static", M+"steel_chrome", [mounts_to()], D_METAL),
    "Medicine_Cabinet": ("Component", 8, [0.5, 0.7, 0.15], "Static", M+"steel_mirror_glass", [mounts_to()], D_GLASS),
    "Toilet_Paper_Holder": ("SubComponent", 0.3, [0.15, 0.08, 0.08], "Static", M+"steel_chrome", [mounts_to()], D_METAL),
    # Window / wall treatments -------------------------------------------
    "Window_Blinds": ("SubComponent", 2, [1.0, 1.4, 0.05], "Animated", M+"aluminum_pvc_slats", [{"type": "mounts_to", "direction": "inflow", "connects_to": "Window_Frame"}], D_METAL),
    "Roller_Shade": ("SubComponent", 1.5, [1.0, 1.5, 0.06], "Animated", M+"fabric_roller", [{"type": "mounts_to", "direction": "inflow", "connects_to": "Window_Frame"}], D_SOFT),
    "Curtain_Rod": ("SubComponent", 1, [1.8, 0.04, 0.04], "Static", M+"metal_rod", [mounts_to()], D_METAL),
    "Wall_Shelf_Floating": ("SubComponent", 3, [0.8, 0.05, 0.2], "Static", M+"wood_bracket", [mounts_to()], D_WOOD),
    "Pegboard": ("SubComponent", 4, [1.0, 1.2, 0.02], "Static", M+"hardboard_hooks", [mounts_to()], D_WOOD),
    "Bulletin_Board": ("SubComponent", 3, [0.9, 0.6, 0.03], "Static", M+"cork_wood_frame", [mounts_to()], D_SOFT),
}


def deterministic_id(path):
    u = uuid.uuid5(NS, path)
    return f"{PREFIX}{str(u)[8:]}"


def main():
    with open(JSON_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    existing_paths = {e["Taxonomy_Path"] for e in data["entries"]}
    added = 0
    unmatched = []

    # Walk the Consumer_Furnishings sub-tree to preserve sub-category in the path.
    cf = data["taxonomy_tree"][DOMAIN]["Consumer_Furnishings"]
    for subcat, leaves in cf.items():
        for leaf in leaves:
            tax_path = f"{ROOT}/{subcat}/{leaf}"
            if tax_path in existing_paths:
                continue
            if leaf not in FURN:
                unmatched.append(leaf)
                continue
            scale, mass, bbox, interaction, material, sockets, destruction = FURN[leaf]
            entry = {
                "Entity_ID": deterministic_id(tax_path),
                "Domain_Class": DOMAIN,
                "Taxonomy_Path": tax_path,
                "Display_Name": leaf.replace("_", " "),
                "LOD_Threshold": [1, 10, 100] if scale in ("Component", "SubComponent") else [3, 30, 300],
                "Network_Sockets": sockets,
                "Material_Shader": material,
                "Destruction_States": destruction,
                "Scale_Class": scale,
                "Interaction_Type": interaction,
                "Mass_kg": mass,
                "Bounding_Volume": bbox,
            }
            data["entries"].append(entry)
            existing_paths.add(tax_path)
            added += 1

    if unmatched:
        print(f"WARNING: {len(unmatched)} leaves have no metadata table entry: {unmatched}")

    data["statistics"]["total_entries"] = len(data["entries"])

    with open(JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    print(f"Added {added} furnishings entries. Total now: {len(data['entries'])}")

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
