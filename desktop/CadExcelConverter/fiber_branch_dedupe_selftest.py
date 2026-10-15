from types import SimpleNamespace

from network_extract_ui import NetworkExtractionMixin


class Dummy(NetworkExtractionMixin):
    pass


def main():
    app=Dummy()
    edges={
        'AB': SimpleNamespace(index=1),
        'BC': SimpleNamespace(index=2),
        'BD': SimpleNamespace(index=3),
        'DE': SimpleNamespace(index=4),
    }
    app.fiber_network=SimpleNamespace(
        edges=edges,
        by_handle={},
    )

    # 국사 A -> 분기 B -> C가 이미 선택된 상태.
    selected={'AB','BC'}

    # 다음 목표 A -> B -> D -> E.
    scope={
        'route':['AB','BD','DE'],
        'nodes':['A','B','D','E'],
    }
    segments=app._fiber_new_segments(scope,selected)
    assert len(segments)==1
    assert segments[0]['route']==['BD','DE']
    assert segments[0]['nodes']==['B','D','E']
    assert segments[0]['start']=='B'
    assert segments[0]['end']=='E'
    assert segments[0]['indices']=={3,4}

    # 앞/뒤가 이미 선택된 특이 구조에서도 새 연속구간만 분리.
    selected={'AB','DE'}
    scope={
        'route':['AB','BC','BD','DE'],
        'nodes':['A','B','C','D','E'],
    }
    segments=app._fiber_new_segments(scope,selected)
    assert len(segments)==1
    assert segments[0]['route']==['BC','BD']
    assert segments[0]['nodes']==['B','C','D']

    # 전부 이미 포함된 경로는 새 구간 없음.
    selected={'AB','BC'}
    scope={'route':['AB','BC'],'nodes':['A','B','C']}
    assert app._fiber_new_segments(scope,selected)==[]

    print('FIBER BRANCH DEDUPE TEST OK')


if __name__=='__main__':
    main()
