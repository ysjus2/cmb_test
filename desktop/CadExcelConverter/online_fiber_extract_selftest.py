from pyproj import Transformer

from network_extract import fetch_all_online_fiber


def feature(fid, coords, region):
    return {
        'type':'Feature',
        'id':fid,
        'geometry':{'type':'LineString','coordinates':coords},
        'properties':{
            'group_id':'FIBER',
            'source_handle':fid,
            'layer':'CN_F_CABLE',
            'entity_type':'LWPOLYLINE',
            'region_code':region,
            'attributes':{'ESSEN_302':fid},
        },
    }


class Client:
    def __init__(self):
        to_wgs=Transformer.from_crs('EPSG:5174','EPSG:4326',always_xy=True)
        a=to_wgs.transform(200000.0,300000.0)
        b=to_wgs.transform(200100.0,300000.0)
        c=to_wgs.transform(200200.0,300000.0)
        self.data={
            'R1':[feature('R1-A-B',[a,b],'R1')],
            'R2':[feature('R2-B-C',[b,c],'R2')],
        }

    def regions(self):
        return [
            {'id':'R1','name':'지역1'},
            {'id':'R2','name':'지역2'},
            {'id':'R3','name':'지역3'},
        ]

    def online_layers(self,region):
        return {'bounds':{'west':120,'south':30,'east':135,'north':40}}

    def online_objects(self,region,bbox,limit=5000,groups=None,timeout=120):
        return {'features':list(self.data.get(region,[]))}


def main():
    client=Client()
    network,summary=fetch_all_online_fiber(client,regions=['R1','R2'],epsg=5174)
    assert summary['regions']==2
    assert len(network.edges)==2

    nodes=sorted(network.positions,key=lambda n:network.positions[n][0])
    assert len(nodes)==3
    route=network.unique_route(nodes[0],nodes[-1])
    assert len(route['route'])==2

    network_one,summary_one=fetch_all_online_fiber(client,regions=['R1'],epsg=5174)
    assert summary_one['regions']==1
    assert len(network_one.edges)==1

    print('ONLINE FIBER REGION SELECTION + BOUNDARY LINK TEST OK')


if __name__=='__main__':
    main()
