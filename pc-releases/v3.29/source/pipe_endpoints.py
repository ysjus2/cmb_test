import math
import re
from network_extract import entity_position


def facility_type(entity):
    if entity.entity_type != 'INSERT':return None
    name=(str(entity.layer)+' '+str(entity.block_name)).upper()
    if 'MANHOLE' in name or '맨홀' in name:return '맨홀'
    if 'HANDHOLE' in name or '핸드홀' in name:return '핸드홀'
    if 'POLE-' in name or 'POLE_POLE' in name or '전주' in name:return '전주'
    return None


def facility_name(entity):
    attributes={str(k).strip().upper():str(v).strip() for k,v in entity.attributes.items()}
    for key in ('POLE_CODE','POLE_NO','전주코드','전주번호','ID','NAME','이름','번호'):
        value=attributes.get(key,'')
        if value and value!='-':return value
    # Only use a recognizable explicit pole-number pattern; do not guess XDATA schemas.
    for appid,values in entity.xdata or []:
        for value in values:
            match=re.search(r'(?<![A-Za-z0-9])\d{4}[Xx]\d{3}(?![A-Za-z0-9])',str(value))
            if match:return match.group(0)
    return '코드미등록'


class PipeEndpointResolver:
    def __init__(self,scene,tolerance=0.1):
        self.tolerance=tolerance
        self.nodes=[]
        self.buckets={}
        for e in scene.entities:
            kind=facility_type(e)
            if kind:
                position=entity_position(e)
                if position:
                    node=(e,kind,position)
                    self.nodes.append(node)
                    cell=(math.floor(position[0]/tolerance),math.floor(position[1]/tolerance))
                    self.buckets.setdefault(cell,[]).append(node)

    def resolve(self,point):
        cx,cy=math.floor(point[0]/self.tolerance),math.floor(point[1]/self.tolerance)
        nearby=[node for dx in (-1,0,1) for dy in (-1,0,1) for node in self.buckets.get((cx+dx,cy+dy),[])]
        candidates=[(e,kind,position) for e,kind,position in nearby if math.dist(point,position)<=self.tolerance]
        if len(candidates)==1:
            e,kind,position=candidates[0]
            return {'type':kind,'name':facility_name(e),'point':position,'handle':e.handle}
        # Missing or overlapping facilities must not be replaced by an arbitrary nearest pole.
        return {'type':'복수시설' if candidates else '미확인','name':'','point':tuple(point),'handle':''}
