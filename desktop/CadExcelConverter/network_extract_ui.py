from __future__ import annotations
import math
import threading
import tkinter as tk
from pathlib import Path
from tkinter import ttk, messagebox, filedialog
from converter import ConversionStats
from layer_defaults import is_default_hidden
from network_extract import FiberNetwork, conduit_records, export_network, is_fiber, is_closure, network_export_indices
from catv_poles import catv_pole_rows, export_catv_poles


class NetworkExtractionMixin:
    def _build_extract_toolbar(self,parent):
        self.export_scope=None
        self.fiber_network=None
        self.route_start=None
        self.pipe_diameters={}
        bar=ttk.Frame(parent)
        bar.pack(fill='x',pady=(0,4))
        actions=[('전체 도면 보기',self._reset_network_filter)]
        if getattr(self,'can_extract',True):
            actions=[
                ('광주간선 추출',self._begin_fiber_route),
                ('100mm 주관로 추출',self._begin_main_conduit),
                ('자가주 좌표 추출',self._run_catv_pole_excel),
                ('관로 속성 확인',self._inspect_conduits),
                ('Excel 추출',self._run_excel),
                ('전체 도면 보기',self._reset_network_filter),
            ]
        for label,command in actions:
            ttk.Button(bar,text=label,command=command).pack(side='left',padx=(0,5))
        self.extract_hint=tk.StringVar(value='광주간선: 시작 함체/끝점 → 끝 함체/끝점 선택')
        ttk.Label(bar,textvariable=self.extract_hint).pack(side='left',padx=8)

    def _run_catv_pole_excel(self):
        if self.busy:return
        if not self.viewer.scene or not self.input_path:
            messagebox.showinfo('자가주 좌표 추출','먼저 DXF 도면을 열어주세요.');return
        rows,missing=catv_pole_rows(self.viewer.scene,self.input_path,int(self.epsg_var.get()))
        if not rows:
            messagebox.showinfo('자가주 좌표 추출',f'추출 가능한 Pole-CATV 자가주가 없습니다. 좌표 미확인 {len(missing)}개.');return
        handles={row[0] for row in rows}
        self._show_scope({'kind':'catv','indices':{e.index for e in self.viewer.scene.entities if e.handle in handles and e.entity_type=='INSERT'}})
        self.extract_hint.set(f'자가주 {len(rows)}개만 표시 / 지형·명칭 숨김')
        out=filedialog.asksaveasfilename(title='전체 자가주 좌표 Excel 추출',defaultextension='.xlsx',initialfile=Path(self.input_path).stem+'_자가주_좌표.xlsx',filetypes=[('Excel','*.xlsx')])
        if not out:return
        self.busy=True;self._show_progress();self._set_progress(10,'전체 자가주 삽입 좌표 추출')
        if missing:self._log(f'자가주 좌표 미확인 {len(missing)}개 제외: '+', '.join(missing))
        def worker():
            try:
                count=export_catv_poles(out,rows)
                self.q.put(('done',(ConversionStats(entities=count,rows=count),out)))
            except Exception as exc:self.q.put(('error',str(exc)))
        threading.Thread(target=worker,daemon=True).start()

    def _clear_network_state(self):
        self.viewer.hide_extraction_text=False
        self.export_scope=None;self.fiber_network=None;self.route_start=None;self.pipe_diameters={}
        self.viewer.entity_filter=None;self.viewer.network_click=None;self.viewer.route_nodes={};self.viewer.route_start_marker=None
        self.extract_hint.set('광주간선: 시작 함체/끝점 → 끝 함체/끝점 선택')

    def _reset_network_filter(self):
        self.viewer.hide_extraction_text=False
        self.export_scope=None;self.route_start=None
        self.viewer.entity_filter=None;self.viewer.network_click=None;self.viewer.route_nodes={};self.viewer.route_start_marker=None
        self.viewer.set_mode('select');self.viewer.selected.clear();self.viewer.fit_view()
        self.extract_hint.set('전체 도면 표시 / 일반 Excel 추출 모드')

    def _show_scope(self,scope):
        self.viewer.hide_extraction_text=True
        self.export_scope=scope
        display_indices=set(scope['indices'])
        self.viewer.entity_filter=display_indices
        layers={self.viewer.scene.entities[i].layer for i in display_indices}
        for iid in self.tree.get_children():
            name=self.layer_names.get(iid)
            if name in layers and not is_default_hidden(name):
                self.checked_layers.add(name);self.visible_layers.add(name);self._refresh_row(iid)
        self.viewer.visible_layers=set(self.visible_layers)
        self.viewer.network_click=None;self.viewer.route_nodes={};self.viewer.route_start_marker=None
        self.viewer.mode='select';self.viewer.selected.clear()
        # Fit and draw only extraction targets, once, without terrain or labels.
        self.viewer.fit_view()

    def _begin_fiber_route(self):
        if self.busy:return
        if not self.viewer.scene or not self.input_path:
            messagebox.showinfo('광주간선 추출','먼저 DXF 도면을 열어주세요.');return
        try:self.fiber_network=FiberNetwork(self.viewer.scene,self.input_path)
        except Exception as exc:messagebox.showerror('광주간선 추출',str(exc));return
        if not self.fiber_network.edges:
            messagebox.showinfo('광주간선 추출','지선을 제외한 연결 가능한 광케이블이 없습니다.');return
        self.viewer.hide_extraction_text=True
        self.export_scope=None;self.route_start=None
        self.viewer.entity_filter={e.index for e in self.viewer.scene.entities if is_fiber(e) or is_closure(e)}
        layers={self.viewer.scene.entities[e.index].layer for e in self.fiber_network.edges.values()}
        layers.update(e.layer for e in self.viewer.scene.entities if 'CLOSURE' in e.layer.upper())
        for iid in self.tree.get_children():
            if self.layer_names.get(iid) in layers and not is_default_hidden(self.layer_names.get(iid)):self._set_checked(iid,True)
        self.viewer.network_click=self._fiber_route_click
        self.viewer.route_nodes=self.fiber_network.positions
        self.viewer.mode='fiber_route';self.viewer.redraw()
        self.extract_hint.set('시작 함체/광케이블 끝점을 클릭하세요. ESC: 취소')

    def _fiber_route_click(self,event):
        hits=[]
        for node,point in self.fiber_network.positions.items():
            sx,sy=self.viewer.world_to_screen(*point)
            distance=math.hypot(event.x-sx,event.y-sy)
            if distance<=18:hits.append((distance,node))
        if not hits:
            self.extract_hint.set('표시된 작은 점(함체/광케이블 끝점)을 클릭해주세요.');return
        hits.sort()
        if len(hits)>1 and abs(hits[0][0]-hits[1][0])<1:
            self.extract_hint.set('끝점이 겹칩니다. 확대해서 구분되는 끝점을 선택해주세요.');return
        node=hits[0][1]
        if self.route_start is None:
            self.route_start=node;self.viewer.route_start_marker=self.fiber_network.positions[node]
            self.extract_hint.set('끝 함체/광케이블 끝점을 클릭하세요. ESC: 취소');self.viewer.redraw();return
        try:scope=self.fiber_network.unique_route(self.route_start,node)
        except ValueError as exc:
            messagebox.showwarning('광주간선 추출',str(exc));return
        self._show_scope(scope)
        cable_count=len(scope['route']);closure_count=len(scope['indices'])-cable_count
        self.extract_hint.set(f'선택 경로: 광케이블 {cable_count}개 / 함체 {closure_count}개. Excel 추출을 누르세요.')
        self.status_var.set('선택 광 경로와 시작·끝 기기만 표시')

    def _begin_main_conduit(self):
        if self.busy:return
        if not self.viewer.scene or not self.input_path:
            messagebox.showinfo('100mm 주관로 추출','먼저 DXF 도면을 열어주세요.');return
        self._reset_network_filter()
        records=conduit_records(self.viewer.scene,self.input_path,self.pipe_diameters)
        if not records:
            messagebox.showinfo('100mm 주관로 추출','읽을 수 있는 관로 객체가 없습니다.');return
        self._apply_main_conduit(records)

    def _inspect_conduits(self):
        if self.busy or not self.viewer.scene or not self.input_path:return
        self._show_pipe_diameter_editor(conduit_records(self.viewer.scene,self.input_path,self.pipe_diameters))

    def _apply_main_conduit(self,records):
        # Refresh local user assignments, but keep explicit DXF diameter authoritative.
        records=conduit_records(self.viewer.scene,self.input_path,self.pipe_diameters)
        main=[r for r in records if r['diameter']==100 and len(r['item']['points'])>=2]
        unknown=sum(r['diameter'] is None for r in records)
        drop=sum(r['diameter']==50 for r in records)
        other=sum(r['diameter'] not in (None,50,100) for r in records)
        missing=sum(len(r['item']['points'])<2 for r in records)
        if not main:
            messagebox.showwarning('100mm 주관로 추출',f'지름이 확인된 100mm 관로가 없습니다. 미확인 {unknown}개 / 50mm {drop}개는 추출하지 않습니다. 원래 CAD의 관경 정보를 확인한 후 지정해주세요.');return False
        self._show_scope({'kind':'pipe','records':records,'indices':{r['entity'].index for r in main}})
        self.extract_hint.set(f'100mm {len(main)}개 / 50mm {drop}·기타 {other}·미기재 {unknown} / 형상 미확인 {missing}')
        return True

    def _show_pipe_diameter_editor(self,records):
        win=tk.Toplevel(self);win.title('관로 속성 — 원본 관경·본수 확인');win.geometry('1000x520')
        ttk.Label(win,text='100*3 = 100mm 관 3본. 원본 표기가 있는 관로는 자동 판독합니다. 미기재 관로만 실제 관경 확인 후 지정하세요.',wraplength=960).pack(fill='x',padx=10,pady=10)
        tree=ttk.Treeview(win,columns=('id','code','diameter','count','raw','length'),show='headings',selectmode='extended')
        for column,label in [('id','순수 객체ID'),('code','관로 코드'),('diameter','관경'),('count','본수'),('raw','원본관경표기'),('length','경로 길이(m)')]:tree.heading(column,text=label);tree.column(column,width=155)
        tree.pack(fill='both',expand=True,padx=10)
        from network_extract import cable_length
        by={r['entity'].handle:r for r in records}
        def refresh():
            for r in conduit_records(self.viewer.scene,self.input_path,self.pipe_diameters):
                h=r['entity'].handle
                vals=(h,r['code'],f"{r['diameter']}mm" if r['diameter'] else '미확인',r['count'] or '미확인',r['raw'] or '미기재',round(cable_length(r['item']['points']),2) if r['item']['points'] else '형상 미확인')
                if tree.exists(h):tree.item(h,values=vals)
                else:tree.insert('','end',iid=h,values=vals)
        def assign(diameter):
            for handle in tree.selection():
                if diameter is None:self.pipe_diameters.pop(handle,None)
                else:self.pipe_diameters[handle]=diameter
            refresh()
        def preview():
            indices={by[h]['entity'].index for h in tree.selection()}
            if not indices:return
            self._show_scope({'kind':'pipe','records':records,'indices':indices})
            self.extract_hint.set('선택 관로 위치 확인 중 / 지름 미확인·50mm는 Excel에서 제외')
        def apply():
            if self._apply_main_conduit(records):win.destroy()
        controls=ttk.Frame(win);controls.pack(fill='x',padx=10,pady=10)
        for label,command in [('선택 관로 위치 보기',preview),('100mm 지정',lambda:assign(100)),('50mm 지정',lambda:assign(50)),('미확인으로',lambda:assign(None)),('100mm만 적용',apply)]:
            ttk.Button(controls,text=label,command=command).pack(side='left',padx=3)
        refresh()

    def _run_network_excel(self):
        if self.busy:return
        scope=self.export_scope
        if scope['kind']=='catv':
            self._run_catv_pole_excel();return
        if scope['kind']=='pipe':
            scope={**scope,'records':conduit_records(self.viewer.scene,self.input_path,self.pipe_diameters)}
            scope['indices']={r['entity'].index for r in scope['records'] if r['diameter']==100 and len(r['item']['points'])>=2}
        shown=self.viewer.entity_filter
        indices=network_export_indices(self.viewer.scene,scope,self.viewer.visible_layers,shown,self.viewer.entity_items)
        if not indices:
            messagebox.showinfo('필요 항목 Excel 추출','화면에 표시된 추출 대상이 없습니다.');return
        label='광주간선' if scope['kind']=='fiber' else '100mm_주관로'
        out=filedialog.asksaveasfilename(title=f'{label} Excel 추출',defaultextension='.xlsx',initialfile=Path(self.input_path).stem+'_'+label+'.xlsx',filetypes=[('Excel','*.xlsx')])
        if not out:return
        self.busy=True;self._show_progress();self._set_progress(10,'전체 100mm 관로와 시작·끝 시설 위치 추출' if scope['kind']=='pipe' else '화면에 표시된 필요 항목만 Excel 추출')
        scene=self.viewer.scene;epsg=int(self.epsg_var.get())
        source_path=self.input_path
        def worker():
            try:
                rows=export_network(out,scene,scope,indices,epsg,source_path=source_path)
                if scope['kind']=='fiber':
                    count=sum(scope['network'].edges[h].index in indices for h in scope['route'])
                else:
                    count=sum(r['diameter']==100 and r['entity'].index in indices for r in scope['records'])
                stats=ConversionStats(entities=count,rows=rows)
                self.q.put(('done',(stats,out)))
            except Exception as exc:self.q.put(('error',str(exc)))
        threading.Thread(target=worker,daemon=True).start()
