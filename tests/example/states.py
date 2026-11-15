#!/usr/bin/env python3
"""states.py CASES.json: what each state of the side-menu example means (the client Lua run on fake-nui, as the
example's models.lua writes it). One line per assertion, 'FAIL <name>' for a broken one; exit 1 when any failed."""
import json, sys

cases = {c['name']: c for c in json.load(open(sys.argv[1], encoding='utf-8'))}
failed = 0


def check(name, cond):
    global failed
    print(('ok   ' if cond else 'FAIL ') + name)
    failed += 0 if cond else 1


def get(state, field, default=None):
    return cases.get(state, {}).get('model', {}).get(field, default)


def rows(state):
    return [r['id'] for r in get(state, 'rows', [])]


def owned(state):
    return [r['id'] for r in get(state, 'rows', []) if r['own']]


check('states: the six states, in order', list(cases) == ['browse', 'picked', 'confirm', 'bought', 'mods', 'empty'])
fields = {'title', 'place', 'cash', 'tab', 'tabs', 'rows', 'pick', 'canBuy', 'askOn', 'askHead', 'askLine', 'askPrice'}
check('states: every model carries every field the markup binds', all(set(c['model']) == fields for c in cases.values()))
check('browse: the shop, the first tab, the cash, nothing picked',
      get('browse', 'title') == 'STREET GEAR' and get('browse', 'tab') == 'guns' and get('browse', 'cash') == 'E$ 2 400'
      and get('browse', 'pick') == '' and get('browse', 'canBuy') is False and get('browse', 'askOn') is False)
check('browse: the guns tab lists its four guns', rows('browse') == ['unity', 'lexington', 'overture', 'malorian'])
check('picked: the Overture is picked and affordable', get('picked', 'pick') == 'overture' and get('picked', 'canBuy') is True)
check('confirm: the dialog is open for the Unity at its price, and says what is left',
      get('confirm', 'askOn') is True and get('confirm', 'askHead') == 'Unity' and get('confirm', 'askPrice') == 'E$ 450'
      and 'E$ 1 950' in get('confirm', 'askLine', ''))
check('confirm: nothing is charged or owned yet', get('confirm', 'cash') == 'E$ 2 400' and owned('confirm') == [])
check('bought: the player was charged the price', get('bought', 'cash') == 'E$ 1 950')
check('bought: the Unity (and only it) is marked owned', owned('bought') == ['unity'])
check('bought: the dialog is closed and the owned item cannot be bought again',
      get('bought', 'askOn') is False and get('bought', 'canBuy') is False)
check('mods: the mods tab lists the scope', get('mods', 'tab') == 'mods' and rows('mods') == ['scope'])
check('empty: the ammo tab is an empty list', get('empty', 'tab') == 'ammo' and get('empty', 'rows') == [])
check('clicks: browse, picked and confirm click what the markup offers',
      [(k['sel'], k['event']) for k in cases['browse']['clicks']] == [('#tabs .tab', 'tab'), ('#list .row', 'pick'), ('#foot .close', 'close')]
      and [(k['sel'], k['event']) for k in cases['picked']['clicks']] == [('#foot .buy', 'buy')]
      and [(k['sel'], k['event']) for k in cases['confirm']['clicks']] == [('#ask .btn.go', 'confirm')])
sys.exit(1 if failed else 0)
