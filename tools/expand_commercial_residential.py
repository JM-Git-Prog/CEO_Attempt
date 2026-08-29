"""Expand Commercial_Institutional_Residential for far more descriptive object creation.

Adds new tree nodes AND hydrates them with realistic, household/commercial-accurate
metadata in one idempotent pass. Only touches the CIR domain. Deterministic uuid5
IDs from Taxonomy_Path; skips already-present paths; rebuilds the CSV to match.

Sections added:
  Consumer_Furnishings/* new subcats  (Outdoor, Kids_Nursery, Office_Workspace,
      Fitness_Recreation, Pet, Cleaning_Utility, Personal_Everyday)
  Hardware_Fixtures                    (knobs, hinges, switches, outlets, faucets...)
  Commercial_Interiors/*               (Retail, Office, Hospitality, Food_Service,
      Education, Fitness_Gym)
  Residential_Detail                   (finer building-shell + surface elements)

Run after hydrate_furnishings.py, or standalone (idempotent).
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
M = "materials/furnishing/"
MC = "materials/commercial/"
MH = "materials/hardware/"
MB = "materials/construction/"

# ── Socket + destruction builders ──────────────────────────────────────────
def sock(t, d, c):
    return {"type": t, "direction": d, "connects_to": c}

def rests_on(s="Floor"): return sock("support", "inflow", s)
def power(): return sock("power_ac", "inflow", "Wall_Outlet")
def water_supply(): return sock("water_supply", "inflow", "Plumbing_Supply")
def drain(): return sock("drain", "outflow", "Plumbing_Drain")
def data(): return sock("data_network", "bidirectional", "Home_Network")
def mounts_to(s="Wall"): return sock("mount", "inflow", s)
def ceiling(): return sock("ceiling_mount", "inflow", "Ceiling")

D_SOFT = {"intact": 1.0, "worn": 0.6, "torn": 0.3, "destroyed": 0.0, "fragmentation_pattern": "fabric_tear_foam"}
D_WOOD = {"intact": 1.0, "scratched": 0.6, "cracked": 0.3, "splintered": 0.0, "fragmentation_pattern": "wood_splinter"}
D_GLASS = {"intact": 1.0, "chipped": 0.6, "cracked": 0.3, "shattered": 0.0, "fragmentation_pattern": "glass_shatter"}
D_CERAMIC = {"intact": 1.0, "chipped": 0.7, "cracked": 0.3, "shattered": 0.0, "fragmentation_pattern": "ceramic_shatter"}
D_APPLIANCE = {"intact": 1.0, "dented": 0.7, "malfunction": 0.3, "dead": 0.0, "fragmentation_pattern": "panel_crumple"}
D_ELECTRONIC = {"intact": 1.0, "scratched": 0.7, "cracked_screen": 0.3, "dead": 0.0, "fragmentation_pattern": "screen_shatter_board"}
D_METAL = {"intact": 1.0, "dented": 0.6, "bent": 0.3, "broken": 0.0, "fragmentation_pattern": "metal_deform"}
D_PLASTIC = {"intact": 1.0, "scuffed": 0.6, "cracked": 0.3, "shattered": 0.0, "fragmentation_pattern": "plastic_crack"}
D_PLANT = {"intact": 1.0, "wilting": 0.6, "dead": 0.2, "decomposed": 0.0, "fragmentation_pattern": "organic_decay"}
D_PAPER = {"intact": 1.0, "creased": 0.6, "torn": 0.3, "destroyed": 0.0, "fragmentation_pattern": "paper_tear"}
D_RIGID = {"intact": 1.0, "damaged": 0.6, "failed": 0.2, "destroyed": 0.0, "fragmentation_pattern": "rigid_fracture"}

# ── Metadata rows: leaf -> (scale, mass, [x,y,z], interaction, material, sockets, destruction) ──
# Grouped by the sub-tree they belong to; TREE (below) references these by leaf name.

TABLE = {}

def add(group_items):
    TABLE.update(group_items)

# Outdoor / patio -----------------------------------------------------------
add({
    "Patio_Chair": ("Component", 6, [0.6, 0.85, 0.6], "Dynamic", M+"resin_metal_outdoor", [rests_on()], D_METAL),
    "Patio_Table": ("Component", 15, [1.2, 0.72, 0.8], "Dynamic", M+"metal_glass_outdoor", [rests_on()], D_GLASS),
    "Patio_Umbrella": ("Component", 12, [2.5, 2.4, 2.5], "Animated", M+"aluminum_canvas", [rests_on()], D_SOFT),
    "Adirondack_Chair": ("Component", 10, [0.8, 0.95, 0.9], "Dynamic", M+"wood_composite_outdoor", [rests_on()], D_WOOD),
    "Outdoor_Sofa": ("Component", 40, [2.0, 0.8, 0.85], "Dynamic", M+"wicker_cushion_outdoor", [rests_on()], D_SOFT),
    "Hammock": ("Component", 5, [3.0, 0.4, 1.2], "Animated", M+"woven_rope_fabric", [mounts_to("Post")], D_SOFT),
    "Grill_BBQ": ("Component", 45, [1.2, 1.1, 0.6], "Dynamic", MC+"steel_cast_iron", [rests_on(), sock("gas_supply", "inflow", "Propane_Tank")], D_METAL),
    "Fire_Pit": ("Component", 30, [0.9, 0.5, 0.9], "Dynamic", MC+"steel_stone", [rests_on()], D_METAL),
    "Planter_Box": ("Component", 20, [1.0, 0.5, 0.4], "Static", M+"wood_composite_soil", [rests_on()], D_WOOD),
    "Garden_Hose_Reel": ("SubComponent", 4, [0.5, 0.6, 0.4], "Dynamic", M+"plastic_metal", [rests_on(), water_supply()], D_PLASTIC),
    "Outdoor_Storage_Shed_Box": ("Component", 35, [1.5, 1.3, 0.8], "Static", M+"resin_outdoor", [rests_on()], D_PLASTIC),
    "Trampoline": ("Component", 60, [3.6, 0.9, 3.6], "Dynamic", M+"steel_frame_mat", [rests_on()], D_METAL),
})

# Kids / nursery ------------------------------------------------------------
add({
    "Changing_Table": ("Component", 20, [0.9, 1.0, 0.5], "Static", M+"wood_finished", [rests_on()], D_WOOD),
    "High_Chair": ("Component", 8, [0.55, 1.0, 0.6], "Dynamic", M+"plastic_metal", [rests_on()], D_PLASTIC),
    "Toy_Chest": ("Component", 12, [0.8, 0.5, 0.45], "Dynamic", M+"wood_finished", [rests_on()], D_WOOD),
    "Rocking_Horse": ("Component", 6, [0.8, 0.7, 0.3], "Animated", M+"wood_painted", [rests_on()], D_WOOD),
    "Play_Mat": ("SubComponent", 2, [1.5, 0.03, 1.5], "Static", M+"foam_interlocking", [rests_on()], D_SOFT),
    "Baby_Monitor": ("SubComponent", 0.4, [0.1, 0.15, 0.08], "Static", M+"plastic_case", [rests_on(), power(), data()], D_ELECTRONIC),
    "Stroller": ("Component", 9, [1.0, 1.05, 0.6], "Dynamic", M+"aluminum_fabric", [rests_on()], D_METAL),
    "Kids_Bookcase": ("Component", 15, [0.7, 1.0, 0.3], "Static", M+"wood_painted", [rests_on(), mounts_to()], D_WOOD),
    "Building_Blocks_Set": ("SubComponent", 1.5, [0.3, 0.2, 0.3], "Dynamic", M+"plastic_wood_blocks", [sock("stored_in", "inflow", "Toy_Chest")], D_PLASTIC),
})

# Office / workspace --------------------------------------------------------
add({
    "Standing_Desk": ("Component", 40, [1.4, 1.1, 0.7], "Animated", M+"laminate_steel_frame", [rests_on(), power()], D_METAL),
    "Ergonomic_Task_Chair": ("Component", 16, [0.65, 1.15, 0.65], "Animated", M+"mesh_plastic_metal", [rests_on()], D_METAL),
    "Monitor_Arm": ("SubComponent", 3, [0.5, 0.5, 0.2], "Animated", MH+"steel_articulated", [sock("clamps_to", "inflow", "Desk")], D_METAL),
    "Keyboard": ("SubComponent", 0.9, [0.44, 0.03, 0.13], "Dynamic", M+"plastic_keys", [sock("rests_on", "inflow", "Desk"), data()], D_PLASTIC),
    "Computer_Mouse": ("SubComponent", 0.1, [0.06, 0.04, 0.11], "Dynamic", M+"plastic_shell", [sock("rests_on", "inflow", "Desk"), data()], D_PLASTIC),
    "Desk_Organizer": ("SubComponent", 0.8, [0.25, 0.12, 0.15], "Dynamic", M+"plastic_wood", [sock("rests_on", "inflow", "Desk")], D_PLASTIC),
    "Printer": ("SubComponent", 8, [0.45, 0.3, 0.4], "Dynamic", M+"plastic_case", [rests_on(), power(), data()], D_APPLIANCE),
    "Paper_Shredder": ("SubComponent", 6, [0.35, 0.5, 0.25], "Dynamic", M+"plastic_steel", [rests_on(), power()], D_APPLIANCE),
    "Whiteboard": ("Component", 8, [1.5, 1.0, 0.03], "Static", M+"melamine_aluminum", [mounts_to()], D_RIGID),
    "Corkboard": ("SubComponent", 3, [0.9, 0.6, 0.03], "Static", M+"cork_wood_frame", [mounts_to()], D_SOFT),
    "Desk_Phone": ("SubComponent", 1, [0.2, 0.1, 0.2], "Dynamic", M+"plastic_case", [sock("rests_on", "inflow", "Desk"), power(), data()], D_ELECTRONIC),
    "Surge_Protector_Strip": ("SubComponent", 0.5, [0.35, 0.04, 0.06], "Static", M+"plastic_case", [rests_on(), power()], D_ELECTRONIC),
})

# Fitness / recreation ------------------------------------------------------
add({
    "Treadmill": ("Room", 90, [1.8, 1.4, 0.85], "Animated", MC+"steel_belt_electronics", [rests_on(), power()], D_APPLIANCE),
    "Stationary_Bike": ("Component", 40, [1.1, 1.3, 0.55], "Animated", MC+"steel_electronics", [rests_on(), power()], D_METAL),
    "Dumbbell_Set": ("SubComponent", 20, [0.4, 0.2, 0.2], "Dynamic", MC+"cast_iron_rubber", [sock("rests_on", "inflow", "Rack")], D_METAL),
    "Weight_Bench": ("Component", 25, [1.2, 0.5, 0.4], "Static", MC+"steel_upholstery", [rests_on()], D_METAL),
    "Yoga_Mat": ("SubComponent", 1.2, [1.8, 0.01, 0.6], "Static", M+"foam_rubber", [rests_on()], D_SOFT),
    "Punching_Bag": ("Component", 35, [0.4, 1.2, 0.4], "Dynamic", MC+"leather_fill", [ceiling()], D_SOFT),
    "Pool_Table": ("Room", 180, [2.5, 0.8, 1.4], "Static", MC+"slate_felt_wood", [rests_on()], D_WOOD),
    "Dartboard": ("SubComponent", 2, [0.45, 0.45, 0.05], "Static", M+"sisal_wood", [mounts_to()], D_SOFT),
    "Foosball_Table": ("Component", 60, [1.4, 0.9, 0.75], "Animated", MC+"wood_steel_rods", [rests_on()], D_WOOD),
})

# Pet -----------------------------------------------------------------------
add({
    "Dog_Bed": ("Component", 3, [0.9, 0.2, 0.7], "Dynamic", M+"cushion_fabric", [rests_on()], D_SOFT),
    "Cat_Tree": ("Component", 12, [0.6, 1.5, 0.6], "Static", M+"carpet_wood_post", [rests_on()], D_SOFT),
    "Pet_Crate": ("Component", 8, [0.9, 0.65, 0.6], "Dynamic", M+"steel_wire_plastic", [rests_on()], D_METAL),
    "Aquarium_Tank": ("Component", 40, [0.9, 0.5, 0.4], "Static", M+"glass_tank_water", [rests_on(), power(), water_supply()], D_GLASS),
    "Bird_Cage": ("Component", 6, [0.5, 1.4, 0.5], "Static", M+"steel_wire", [rests_on()], D_METAL),
    "Litter_Box": ("SubComponent", 2, [0.5, 0.2, 0.4], "Dynamic", M+"plastic_tray", [rests_on()], D_PLASTIC),
    "Pet_Food_Bowl": ("SubComponent", 0.4, [0.2, 0.06, 0.2], "Dynamic", M+"ceramic_steel", [rests_on()], D_CERAMIC),
})

# Cleaning / utility --------------------------------------------------------
add({
    "Broom": ("SubComponent", 0.8, [0.3, 1.3, 0.05], "Dynamic", M+"plastic_bristle_wood", [mounts_to("Utility_Wall")], D_PLASTIC),
    "Mop_Bucket": ("SubComponent", 3, [0.4, 0.9, 0.3], "Dynamic", M+"plastic_metal", [rests_on()], D_PLASTIC),
    "Ironing_Board": ("Component", 6, [1.3, 0.9, 0.4], "Animated", M+"steel_padded", [rests_on()], D_METAL),
    "Clothes_Iron": ("SubComponent", 1.5, [0.25, 0.13, 0.11], "Dynamic", M+"plastic_steel_plate", [sock("rests_on", "inflow", "Ironing_Board"), power(), water_supply()], D_APPLIANCE),
    "Laundry_Hamper": ("SubComponent", 2, [0.5, 0.6, 0.4], "Dynamic", M+"woven_plastic_fabric", [rests_on()], D_SOFT),
    "Drying_Rack": ("Component", 4, [0.8, 1.0, 0.55], "Animated", M+"steel_folding", [rests_on()], D_METAL),
    "Recycling_Bin": ("SubComponent", 3, [0.45, 0.6, 0.4], "Dynamic", M+"plastic_bin", [rests_on()], D_PLASTIC),
    "Cleaning_Cart": ("Component", 10, [0.9, 1.0, 0.5], "Dynamic", MC+"plastic_steel_cart", [rests_on()], D_PLASTIC),
    "Tool_Chest": ("Component", 45, [0.7, 0.9, 0.45], "Dynamic", MH+"steel_drawers", [rests_on()], D_METAL),
    "Step_Ladder": ("Component", 6, [0.5, 1.5, 0.9], "Animated", MH+"aluminum_folding", [rests_on()], D_METAL),
})

# Personal / everyday items -------------------------------------------------
add({
    "Backpack": ("SubComponent", 1.2, [0.35, 0.5, 0.2], "Dynamic", M+"nylon_fabric", [sock("hangs_from", "inflow", "Hook")], D_SOFT),
    "Handbag_Purse": ("SubComponent", 0.8, [0.35, 0.28, 0.15], "Dynamic", M+"leather_fabric", [sock("rests_on", "inflow", "Surface")], D_SOFT),
    "Suitcase": ("Component", 4, [0.5, 0.75, 0.3], "Dynamic", M+"polycarbonate_shell", [rests_on()], D_PLASTIC),
    "Umbrella": ("SubComponent", 0.5, [0.1, 0.9, 0.1], "Animated", M+"nylon_metal", [sock("stored_in", "inflow", "Umbrella_Stand")], D_SOFT),
    "Wall_Coat_Hook": ("SubComponent", 0.2, [0.1, 0.06, 0.05], "Static", MH+"steel_hook", [mounts_to()], D_METAL),
    "Key_Rack": ("SubComponent", 0.3, [0.25, 0.1, 0.03], "Static", MH+"wood_metal_hooks", [mounts_to()], D_WOOD),
    "Book_Stack": ("SubComponent", 3, [0.25, 0.3, 0.2], "Dynamic", M+"paper_cardboard", [sock("rests_on", "inflow", "Surface")], D_PAPER),
    "Eyeglasses": ("SubComponent", 0.05, [0.14, 0.04, 0.05], "Dynamic", M+"plastic_glass_lens", [sock("rests_on", "inflow", "Surface")], D_PLASTIC),
    "Water_Bottle": ("SubComponent", 0.6, [0.07, 0.25, 0.07], "Dynamic", M+"steel_plastic", [sock("rests_on", "inflow", "Surface")], D_METAL),
    "Remote_Control": ("SubComponent", 0.15, [0.05, 0.02, 0.16], "Dynamic", M+"plastic_case", [sock("rests_on", "inflow", "Surface")], D_PLASTIC),
    "Phone_Charger": ("SubComponent", 0.1, [0.05, 0.03, 0.05], "Static", M+"plastic_cable", [power()], D_ELECTRONIC),
    "Wall_Calendar": ("SubComponent", 0.2, [0.3, 0.4, 0.01], "Static", M+"paper", [mounts_to()], D_PAPER),
})

# Hardware / fixtures (SubComponent-scale interactive detail) ----------------
add({
    "Door_Knob": ("SubComponent", 0.4, [0.06, 0.06, 0.09], "Animated", MH+"brass_steel", [sock("mounts_to", "inflow", "Door")], D_METAL),
    "Door_Lever_Handle": ("SubComponent", 0.4, [0.12, 0.06, 0.06], "Animated", MH+"steel_chrome", [sock("mounts_to", "inflow", "Door")], D_METAL),
    "Deadbolt_Lock": ("SubComponent", 0.5, [0.07, 0.15, 0.06], "Animated", MH+"steel_hardened", [sock("mounts_to", "inflow", "Door")], D_METAL),
    "Door_Hinge": ("SubComponent", 0.3, [0.1, 0.1, 0.02], "Animated", MH+"steel_plated", [sock("joins", "bidirectional", "Door_Frame")], D_METAL),
    "Cabinet_Pull": ("SubComponent", 0.1, [0.12, 0.03, 0.03], "Dynamic", MH+"brushed_metal", [sock("mounts_to", "inflow", "Cabinet")], D_METAL),
    "Light_Switch": ("SubComponent", 0.1, [0.07, 0.12, 0.04], "Dynamic", MH+"plastic_switch", [mounts_to(), power()], D_PLASTIC),
    "Dimmer_Switch": ("SubComponent", 0.12, [0.07, 0.12, 0.05], "Animated", MH+"plastic_electronic", [mounts_to(), power()], D_ELECTRONIC),
    "Wall_Outlet": ("SubComponent", 0.1, [0.07, 0.12, 0.04], "Static", MH+"plastic_receptacle", [mounts_to(), power()], D_PLASTIC),
    "Thermostat_Wall": ("SubComponent", 0.2, [0.1, 0.1, 0.03], "Dynamic", MH+"plastic_electronic", [mounts_to(), power(), data()], D_ELECTRONIC),
    "Faucet_Kitchen": ("SubComponent", 2, [0.15, 0.35, 0.2], "Animated", MH+"steel_chrome", [sock("mounts_to", "inflow", "Sink"), water_supply()], D_METAL),
    "Faucet_Bathroom": ("SubComponent", 1.5, [0.12, 0.2, 0.15], "Animated", MH+"steel_chrome", [sock("mounts_to", "inflow", "Sink"), water_supply()], D_METAL),
    "Shower_Head": ("SubComponent", 0.8, [0.12, 0.12, 0.2], "Animated", MH+"steel_chrome_plastic", [sock("mounts_to", "inflow", "Wall"), water_supply()], D_METAL),
    "Smoke_Detector_Residential": ("SubComponent", 0.2, [0.12, 0.04, 0.12], "Static", MH+"plastic_electronic", [ceiling(), sock("battery", "inflow", "Battery")], D_ELECTRONIC),
    "Doorbell": ("SubComponent", 0.15, [0.05, 0.1, 0.03], "Dynamic", MH+"plastic_electronic", [mounts_to(), power(), data()], D_ELECTRONIC),
    "Cabinet_Hinge_Soft_Close": ("SubComponent", 0.15, [0.1, 0.06, 0.04], "Animated", MH+"steel_damped", [sock("joins", "bidirectional", "Cabinet")], D_METAL),
    "Register_Vent_Cover": ("SubComponent", 0.5, [0.3, 0.02, 0.15], "Static", MH+"steel_louvered", [mounts_to("Floor")], D_METAL),
    "Electrical_Outlet_Cover": ("SubComponent", 0.05, [0.07, 0.12, 0.01], "Static", MH+"plastic_plate", [mounts_to()], D_PLASTIC),
})

# Commercial interiors — retail --------------------------------------------
add({
    "Retail_Display_Shelf": ("Component", 40, [1.2, 1.8, 0.5], "Static", MC+"steel_gondola", [rests_on()], D_METAL),
    "Clothing_Rack": ("Component", 15, [1.5, 1.6, 0.6], "Dynamic", MC+"steel_chrome", [rests_on()], D_METAL),
    "Checkout_Counter": ("Room", 80, [2.0, 1.0, 0.7], "Static", MC+"laminate_steel", [rests_on(), power()], D_RIGID),
    "Cash_Register_POS": ("SubComponent", 5, [0.4, 0.35, 0.35], "Dynamic", MC+"plastic_electronic", [sock("rests_on", "inflow", "Counter"), power(), data()], D_ELECTRONIC),
    "Mannequin": ("Component", 12, [0.5, 1.8, 0.35], "Static", MC+"fiberglass_composite", [rests_on()], D_RIGID),
    "Shopping_Cart": ("Component", 12, [1.0, 1.0, 0.6], "Dynamic", MC+"steel_wire", [rests_on()], D_METAL),
    "Shopping_Basket": ("SubComponent", 1, [0.45, 0.25, 0.3], "Dynamic", MC+"plastic_handled", [sock("stacks_in", "inflow", "Basket_Stand")], D_PLASTIC),
    "Display_Freezer_Case": ("Room", 200, [2.5, 1.8, 0.9], "Dynamic", MC+"steel_glass_refrigerated", [rests_on(), power()], D_APPLIANCE),
    "Price_Signage_Holder": ("SubComponent", 0.3, [0.1, 0.15, 0.05], "Static", MC+"acrylic_metal", [sock("clips_to", "inflow", "Shelf")], D_PLASTIC),
})

# Commercial interiors — office --------------------------------------------
add({
    "Cubicle_Partition": ("Component", 30, [1.5, 1.5, 0.05], "Static", MC+"fabric_panel_frame", [rests_on(), sock("joins", "bidirectional", "Adjacent_Panel")], D_SOFT),
    "Conference_Table": ("Room", 120, [3.0, 0.75, 1.2], "Static", MC+"wood_veneer_steel", [rests_on(), power(), data()], D_WOOD),
    "Reception_Desk": ("Room", 100, [2.4, 1.1, 0.8], "Static", MC+"laminate_composite", [rests_on(), power(), data()], D_RIGID),
    "Water_Cooler": ("Component", 18, [0.35, 1.1, 0.35], "Dynamic", MC+"plastic_steel", [rests_on(), power(), water_supply()], D_APPLIANCE),
    "Vending_Machine": ("Room", 250, [1.0, 1.9, 0.85], "Dynamic", MC+"steel_glass_electronic", [rests_on(), power()], D_APPLIANCE),
    "Server_Rack_Cabinet": ("Room", 150, [0.6, 2.0, 1.0], "Static", MC+"steel_ventilated", [rests_on(), power(), data()], D_METAL),
    "Projector_Screen_Retractable": ("Component", 10, [2.4, 0.15, 0.15], "Animated", MC+"fabric_metal_housing", [ceiling(), mounts_to()], D_METAL),
})

# Commercial interiors — hospitality / food service ------------------------
add({
    "Restaurant_Booth": ("Room", 90, [1.5, 1.2, 1.4], "Static", MC+"upholstery_wood_frame", [rests_on()], D_SOFT),
    "Bar_Counter": ("Room", 200, [3.0, 1.1, 0.6], "Static", MC+"wood_stone_steel", [rests_on(), water_supply(), drain()], D_WOOD),
    "Commercial_Range": ("Room", 180, [1.5, 0.9, 0.8], "Dynamic", MC+"stainless_steel", [rests_on(), sock("gas_supply", "inflow", "Gas_Line"), power()], D_APPLIANCE),
    "Commercial_Refrigerator": ("Room", 250, [1.4, 2.0, 0.8], "Dynamic", MC+"stainless_steel", [rests_on(), power()], D_APPLIANCE),
    "Prep_Table_Stainless": ("Room", 60, [1.8, 0.9, 0.7], "Static", MC+"stainless_steel", [rests_on()], D_METAL),
    "Espresso_Machine_Commercial": ("Component", 35, [0.8, 0.55, 0.6], "Dynamic", MC+"stainless_steel_brass", [sock("rests_on", "inflow", "Counter"), power(), water_supply()], D_APPLIANCE),
    "Hotel_Luggage_Cart": ("Component", 40, [1.1, 1.8, 0.6], "Dynamic", MC+"brass_carpet", [rests_on()], D_METAL),
    "Buffet_Warming_Tray": ("SubComponent", 4, [0.6, 0.25, 0.35], "Dynamic", MC+"stainless_steel", [sock("rests_on", "inflow", "Buffet_Table"), power()], D_METAL),
})

# Commercial interiors — education / gym -----------------------------------
add({
    "School_Desk": ("Component", 15, [0.6, 0.75, 0.5], "Dynamic", MC+"laminate_steel", [rests_on()], D_RIGID),
    "Lecture_Podium": ("Component", 25, [0.6, 1.2, 0.5], "Static", MC+"wood_electronic", [rests_on(), power(), data()], D_WOOD),
    "Locker_Bank": ("Room", 120, [1.8, 1.8, 0.45], "Static", MC+"steel_painted", [rests_on(), mounts_to()], D_METAL),
    "Bleacher_Section": ("Room", 400, [4.0, 1.5, 2.0], "Static", MC+"aluminum_steel_frame", [rests_on()], D_METAL),
    "Gym_Wall_Mirror": ("Room", 60, [2.4, 1.8, 0.03], "Static", MC+"mirror_glass_safety", [mounts_to()], D_GLASS),
    "Cafeteria_Table_Folding": ("Room", 70, [2.4, 0.75, 0.75], "Animated", MC+"laminate_steel_folding", [rests_on()], D_RIGID),
})

# Residential detail — finer shell / surface elements ----------------------
add({
    "Interior_Door_Slab": ("Component", 25, [0.9, 2.0, 0.04], "Animated", MB+"wood_hollow_core", [sock("hinges_to", "bidirectional", "Door_Frame")], D_WOOD),
    "Exterior_Entry_Door": ("Component", 45, [0.9, 2.1, 0.06], "Animated", MB+"steel_insulated_core", [sock("hinges_to", "bidirectional", "Door_Frame")], D_METAL),
    "Window_Sash_Double_Hung": ("Component", 20, [1.0, 1.4, 0.1], "Animated", MB+"vinyl_glass_ig", [sock("mounts_to", "inflow", "Window_Frame")], D_GLASS),
    "Baseboard_Trim": ("SubComponent", 2, [2.4, 0.1, 0.02], "Static", MB+"wood_mdf_painted", [mounts_to("Wall_Base")], D_WOOD),
    "Crown_Molding": ("SubComponent", 2, [2.4, 0.12, 0.05], "Static", MB+"wood_mdf_painted", [mounts_to("Wall_Ceiling_Joint")], D_WOOD),
    "Stair_Balustrade": ("Component", 30, [3.0, 1.0, 0.1], "Static", MB+"wood_metal_rail", [mounts_to("Stair_Stringer")], D_WOOD),
    "Fireplace_Mantel": ("Component", 40, [1.5, 1.2, 0.4], "Static", MB+"wood_stone", [mounts_to()], D_WOOD),
    "Kitchen_Countertop_Slab": ("Component", 90, [2.4, 0.04, 0.65], "Static", MB+"granite_quartz", [sock("rests_on", "inflow", "Base_Cabinet")], D_RIGID),
    "Base_Cabinet_Unit": ("Component", 40, [0.6, 0.85, 0.6], "Static", MB+"wood_laminate_box", [rests_on(), sock("joins", "bidirectional", "Adjacent_Cabinet")], D_WOOD),
    "Wall_Cabinet_Unit": ("Component", 25, [0.6, 0.7, 0.35], "Static", MB+"wood_laminate_box", [mounts_to()], D_WOOD),
    "Kitchen_Backsplash_Tile": ("SubComponent", 15, [2.4, 0.6, 0.01], "Static", MB+"ceramic_tile_grout", [mounts_to()], D_CERAMIC),
    "Ceiling_Fan": ("Component", 12, [1.3, 0.4, 1.3], "Animated", M+"metal_wood_blades", [ceiling(), power()], D_METAL),
    "Recessed_Downlight": ("SubComponent", 0.5, [0.15, 0.15, 0.12], "Static", M+"metal_led_trim", [ceiling(), power()], D_ELECTRONIC),
    "Radiator_Panel": ("Component", 25, [1.0, 0.6, 0.1], "Static", MB+"steel_hydronic", [mounts_to(), water_supply()], D_METAL),
})

# ── The tree structure to inject (subcat -> ordered leaf list) ─────────────
NEW_SUBTREES = {
    # Extend Consumer_Furnishings with these new subcats
    "Consumer_Furnishings": {
        "Outdoor_Patio": ["Patio_Chair", "Patio_Table", "Patio_Umbrella", "Adirondack_Chair", "Outdoor_Sofa", "Hammock", "Grill_BBQ", "Fire_Pit", "Planter_Box", "Garden_Hose_Reel", "Outdoor_Storage_Shed_Box", "Trampoline"],
        "Kids_Nursery": ["Changing_Table", "High_Chair", "Toy_Chest", "Rocking_Horse", "Play_Mat", "Baby_Monitor", "Stroller", "Kids_Bookcase", "Building_Blocks_Set"],
        "Office_Workspace": ["Standing_Desk", "Ergonomic_Task_Chair", "Monitor_Arm", "Keyboard", "Computer_Mouse", "Desk_Organizer", "Printer", "Paper_Shredder", "Whiteboard", "Corkboard", "Desk_Phone", "Surge_Protector_Strip"],
        "Fitness_Recreation": ["Treadmill", "Stationary_Bike", "Dumbbell_Set", "Weight_Bench", "Yoga_Mat", "Punching_Bag", "Pool_Table", "Dartboard", "Foosball_Table"],
        "Pet": ["Dog_Bed", "Cat_Tree", "Pet_Crate", "Aquarium_Tank", "Bird_Cage", "Litter_Box", "Pet_Food_Bowl"],
        "Cleaning_Utility": ["Broom", "Mop_Bucket", "Ironing_Board", "Clothes_Iron", "Laundry_Hamper", "Drying_Rack", "Recycling_Bin", "Cleaning_Cart", "Tool_Chest", "Step_Ladder"],
        "Personal_Everyday": ["Backpack", "Handbag_Purse", "Suitcase", "Umbrella", "Wall_Coat_Hook", "Key_Rack", "Book_Stack", "Eyeglasses", "Water_Bottle", "Remote_Control", "Phone_Charger", "Wall_Calendar"],
    },
    # New top-level CIR branches
    "Hardware_Fixtures": ["Door_Knob", "Door_Lever_Handle", "Deadbolt_Lock", "Door_Hinge", "Cabinet_Pull", "Light_Switch", "Dimmer_Switch", "Wall_Outlet", "Thermostat_Wall", "Faucet_Kitchen", "Faucet_Bathroom", "Shower_Head", "Smoke_Detector_Residential", "Doorbell", "Cabinet_Hinge_Soft_Close", "Register_Vent_Cover", "Electrical_Outlet_Cover"],
    "Commercial_Interiors": {
        "Retail": ["Retail_Display_Shelf", "Clothing_Rack", "Checkout_Counter", "Cash_Register_POS", "Mannequin", "Shopping_Cart", "Shopping_Basket", "Display_Freezer_Case", "Price_Signage_Holder"],
        "Office": ["Cubicle_Partition", "Conference_Table", "Reception_Desk", "Water_Cooler", "Vending_Machine", "Server_Rack_Cabinet", "Projector_Screen_Retractable"],
        "Hospitality_Food_Service": ["Restaurant_Booth", "Bar_Counter", "Commercial_Range", "Commercial_Refrigerator", "Prep_Table_Stainless", "Espresso_Machine_Commercial", "Hotel_Luggage_Cart", "Buffet_Warming_Tray"],
        "Education_Fitness": ["School_Desk", "Lecture_Podium", "Locker_Bank", "Bleacher_Section", "Gym_Wall_Mirror", "Cafeteria_Table_Folding"],
    },
    "Residential_Detail": ["Interior_Door_Slab", "Exterior_Entry_Door", "Window_Sash_Double_Hung", "Baseboard_Trim", "Crown_Molding", "Stair_Balustrade", "Fireplace_Mantel", "Kitchen_Countertop_Slab", "Base_Cabinet_Unit", "Wall_Cabinet_Unit", "Kitchen_Backsplash_Tile", "Ceiling_Fan", "Recessed_Downlight", "Radiator_Panel"],
}


def deterministic_id(path):
    return f"{PREFIX}{str(uuid.uuid5(NS, path))[8:]}"


def entry_for(tax_path, leaf):
    scale, mass, bbox, interaction, material, sockets, destruction = TABLE[leaf]
    return {
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


def main():
    with open(JSON_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    cir = data["taxonomy_tree"][DOMAIN]
    existing_paths = {e["Taxonomy_Path"] for e in data["entries"]}
    added = 0
    unmatched = []

    # 1. Extend Consumer_Furnishings with new subcats
    cf = cir.setdefault("Consumer_Furnishings", {})
    for subcat, leaves in NEW_SUBTREES["Consumer_Furnishings"].items():
        cf.setdefault(subcat, leaves)
        for leaf in leaves:
            tax_path = f"Buildings/Consumer_Furnishings/{subcat}/{leaf}"
            if tax_path in existing_paths:
                continue
            if leaf not in TABLE:
                unmatched.append(leaf); continue
            data["entries"].append(entry_for(tax_path, leaf))
            existing_paths.add(tax_path); added += 1

    # 2. Hardware_Fixtures (flat list)
    cir.setdefault("Hardware_Fixtures", NEW_SUBTREES["Hardware_Fixtures"])
    for leaf in NEW_SUBTREES["Hardware_Fixtures"]:
        tax_path = f"Buildings/Hardware_Fixtures/{leaf}"
        if tax_path in existing_paths:
            continue
        if leaf not in TABLE:
            unmatched.append(leaf); continue
        data["entries"].append(entry_for(tax_path, leaf))
        existing_paths.add(tax_path); added += 1

    # 3. Commercial_Interiors (nested)
    ci = cir.setdefault("Commercial_Interiors", {})
    for subcat, leaves in NEW_SUBTREES["Commercial_Interiors"].items():
        ci.setdefault(subcat, leaves)
        for leaf in leaves:
            tax_path = f"Buildings/Commercial_Interiors/{subcat}/{leaf}"
            if tax_path in existing_paths:
                continue
            if leaf not in TABLE:
                unmatched.append(leaf); continue
            data["entries"].append(entry_for(tax_path, leaf))
            existing_paths.add(tax_path); added += 1

    # 4. Residential_Detail (flat list)
    cir.setdefault("Residential_Detail", NEW_SUBTREES["Residential_Detail"])
    for leaf in NEW_SUBTREES["Residential_Detail"]:
        tax_path = f"Buildings/Residential_Detail/{leaf}"
        if tax_path in existing_paths:
            continue
        if leaf not in TABLE:
            unmatched.append(leaf); continue
        data["entries"].append(entry_for(tax_path, leaf))
        existing_paths.add(tax_path); added += 1

    if unmatched:
        print(f"WARNING: {len(unmatched)} leaves missing metadata: {unmatched}")

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
            lod = e["LOD_Threshold"]; bbox = e["Bounding_Volume"]; ds = e["Destruction_States"]
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
