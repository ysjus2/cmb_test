from pyproj import Transformer

from network_extract import OnlineFiberNetwork


def line(fid, coords, region='R'):
    return {
        'type':'Feature',
        'id':fid,
        'geometry':{'type':'LineString','coordinates':coords},
        'properties':{
            'group_id':'FIBER',
            'source_handle':fid,
            'layer':'CN_F_CABLE',
            'entity_type':'LWPOLYLINE',
            '_cmb_region_code':region,
            'attributes':{'ESSEN_302':fid},
        },
    }


def main():
    to_wgs=Transformer.from_crs('EPSG:5174','EPSG:4326',always_xy=True)

    a=to_wgs.transform(200000.0,300000.0)
    b1=to_wgs.transform(200100.0,300000.0)
    # 중간 함체 심벌이 없어 케이블 끝점 사이에 1.4m 공백이 있는 경우.
    b2=to_wgs.transform(200101.4,300000.0)
    c=to_wgs.transform(200200.0,300000.0)

    network=OnlineFiberNetwork([
        line('A-B',[a,b1],'R1'),
        line('B-C',[b2,c],'R2'),
    ],epsg=5174)

    nodes=sorted(network.positions,key=lambda n:network.positions[n][0])
    assert len(nodes)==3, network.positions
    route=network.unique_route(nodes[0],nodes[-1])
    assert len(route['route'])==2

    # 5m를 넘는 끝점은 자동 연결하지 않는다.
    d1=to_wgs.transform(201000.0,300000.0)
    d2=to_wgs.transform(201100.0,300000.0)
    e=to_wgs.transform(201200.0,300000.0)
    network2=OnlineFiberNetwork([
        line('D-X',[d1,d2],'R1'),
        line('Y-E',[to_wgs.transform(201106.0,300000.0),e],'R2'),
    ],epsg=5174)
    assert len(network2.positions)==4

    print('MISSING CLOSURE ENDPOINT JOIN TEST OK')


if __name__=='__main__':
    main()
