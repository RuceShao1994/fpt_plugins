from shapely.geometry import Point

from FFxivPythonTrigger import *
from FFxivPythonTrigger.Utils import sector
from FFxivPythonTrigger.memory.StructFactory import *
from shapely.ops import cascaded_union, nearest_points

import math

ActionSendOpcode = 844  # cn5.45
PositionSetOpcode = 0x326  # cn5.45
PositionAdjustOpcode = 0xd7  # cn5.45

FRONT = 1
SIDE = 2
BACK = 3

skills = {
    7481: BACK,  # 月光，背
    7482: SIDE,  # 花车，侧
}

Vector3 = OffsetStruct({
    'x': c_float,
    'z': c_float,
    'y': c_float,
})
PositionSetPack = OffsetStruct({
    'r': (c_float, 0),
    'unk0': (c_ushort, 0x4),
    'unk1': (c_ushort, 0x6),
    'pos': (Vector3, 0x8),
    'unk2': (c_uint, 0x14),
}, 24)
ActionSend = OffsetStruct({
    '_unk_ushort0': (c_ushort, 0x0),
    '_unk_ushort1': (c_ushort, 0x2),
    'skill_id': (c_uint, 0x4),
    'cnt': (c_ushort, 0x8),
    '_unk_ushort4': (c_ushort, 0xa),
    '_unk_ushort5': (c_ushort, 0xc),
    '_unk_ushort6': (c_ushort, 0xe),
    'target_id': (c_uint, 0x10),
}, 32)
PositionAdjustPack = OffsetStruct({
    'old_r': (c_float, 0x0),
    'new_r': (c_float, 0x4),
    'unk0': (c_ushort, 0x8),
    'unk1': (c_ushort, 0xA),
    'old_pos': (Vector3, 0xC),
    'new_pos': (Vector3, 0x18),
    'unk2': (c_uint, 0x24),
}, 40)

angle = math.pi / 2 - 0.1


def get_nearest(me_pos, target, mode, dis=3):
    radius = target.HitboxRadius + dis - 0.5
    if mode == SIDE:
        area1 = sector(target.pos.x, target.pos.y, radius, angle, target.pos.r + math.pi / 2)
        area2 = sector(target.pos.x, target.pos.y, radius, angle, target.pos.r - math.pi / 2)
        area = cascaded_union([area1, area2])
    elif mode == FRONT:
        area = sector(target.pos.x, target.pos.y, radius, angle, target.pos.r)
    elif mode == BACK:
        area = sector(target.pos.x, target.pos.y, radius, angle, target.pos.r - math.pi)
    else:
        area = target.hitbox

    area = area.difference(Point(target.pos.x, target.pos.y).buffer(0.5))
    me = Point(me_pos.x, me_pos.y)
    p1 = me if area.contains(me) else nearest_points(area, me)[0]
    return p1.x, p1.y


class AFix(PluginBase):
    name = "AFix"

    def __init__(self):
        super().__init__()
        self.last_reset = perf_counter()
        api.XivNetwork.register_makeup(ActionSendOpcode, self.makeup_action)
        self.register_event(f'network/action_effect', self.coor_return)
        self.adjust_mode = True
        self.adjust_sig = 0
        self.register_event('network/position_adjust', self.deal_adjust)
        self.register_event('network/position_set', self.deal_set)

    def _onunload(self):
        api.XivNetwork.unregister_makeup(ActionSendOpcode, self.makeup_action)

    def deal_adjust(self, evt):
        self.adjust_mode = True
        self.adjust_sig = evt.raw_msg.unk1 & 0xf

    def deal_set(self, evt):
        self.adjust_mode = False

    def goto(self, new_x=None, new_y=None):
        c = api.Coordinate()
        target = Vector3(x=new_x if new_x is not None else c.x, y=new_y if new_y is not None else c.y, z=c.z)
        if self.adjust_mode:
            msg = PositionAdjustPack(old_r=c.r, new_r=c.r, old_pos=target, new_pos=target, unk0=0x4000, unk1=0x40 | self.adjust_sig)
            code = PositionAdjustOpcode
        else:
            msg = PositionSetPack(r=c.r, pos=target, unk2=0x93)
            code = PositionSetOpcode
        api.XivNetwork.send_messages([(code, bytearray(msg))], False)

    def coor_return(self, evt):
        if self.last_reset + 1 > perf_counter() or evt.source_id != api.XivMemory.actor_table.get_me().id or evt.action_type != 'action' or evt.action_id not in skills:
            return
        frame_inject.register_once_call(self.goto)
        self.last_reset = perf_counter()

    def makeup_action(self, header, raw):
        d = ActionSend.from_buffer(raw)
        if d.skill_id in skills:
            t = api.XivMemory.actor_table.get_actor_by_id(d.target_id)
            if t is not None:
                self.goto(*get_nearest(api.Coordinate(), t, skills[d.skill_id]))
        return header, bytearray(d)