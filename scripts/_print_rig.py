import json
rig = json.load(open('projects/pista_patinaje/rig.json'))
fixtures = rig['fixtures']
print(f'Total: {len(fixtures)} fixtures')
print()
print('LAYOUT (vista cenital, techo):')
print('  ID           uni  dmx    X       Y    Z      tilt   dim')
for fx in fixtures:
    pos = fx['position']
    mc = fx['manual_channels']
    print(f'  {fx["fixture_id"]:<12s} {fx["universe"]}    {fx["dmx_start"]:3d}  '
          f'({pos[0]:5.1f}, {pos[1]:.0f}, {pos[2]:5.1f})  '
          f'{mc.get("tilt","-")}  {mc.get("dim","-")}')
print()
print('Focus: pan=0.5 tilt=0.333 (90deg abajo) dim=1.0 shutter=1.0')
