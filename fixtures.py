"""Original typed sample data. These people and purchases are fictional."""
DEMO_RECEIPT = """description,quantity,unit_price
NEMA17 stepper motor,2,18.47
GT2 timing belt loop,3,4.19
M3 socket head cap screw,40,0.07
6061 aluminium plate,1,21.83
Arduino Nano controller board,1,12.73
2200mAh LiPo battery,1,16.91
Bench tidy kit,1,6.37
M3 socket head cap screw,40,0.07"""

DEMO_BOM = """description,quantity
NEMA17 stepper motor,2
GT2 timing belt loop,2
M3 socket head cap screw,40
6061 aluminium plate,1
Arduino Nano controller board,1
2200mAh LiPo battery,1"""

DEMO_MEMBERS = [
    {"id": "alex", "name": "Alex", "role": "Motion", "email": "alex@example.test"},
    {"id": "mina", "name": "Mina", "role": "Controls", "email": "mina@example.test"},
    {"id": "jules", "name": "Jules", "role": "Fabrication", "email": "jules@example.test"},
]
