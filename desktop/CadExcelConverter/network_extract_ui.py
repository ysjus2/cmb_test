from __future__ import annotations
import math
import threading
import tkinter as tk
from pathlib import Path
from tkinter import ttk, messagebox, filedialog
from converter import ConversionStats
from layer_defaults import is_default_hidden
from network_extract import FiberNetwork, conduit_records, export_network, is_background


class NetworkExtractionMixin:
    def _build_extract_toolbar(self,parent):
        self.export_scope=None
        self.fiber_network=None
        self.route_start=None
        self.pipe_diameters={}
        bar=ttk.Frame(parent)
        bar.pack(fill='x',pady=(0,4))
        for label,command in [('광주간선 추출',self._begin_fiber_route),('100mm 주관로 추출',self._begin_main_conduit),('보이는 항목 Excel 추출',self._run_excel),('전체 도면 보기',self._reset_network_filter)]:
            ttk.Button(bar,text=label,command=command).pack(side='left',padx=(0,5))
        self.extract_hint=tk.StringVar(value='광주간선: 시작 함체/끝점 → 끝 함체/끝점 선택')
        ttk.Label(bar,textvariable=self.extract_hint).pack(side='left',padx=8)

    def _clear_network_state(self):
        self.export_scope=None;self.fiber_network=None;self.route_start=None;self.pipe_diameters={}
        self.viewer.entity_filter=None;self.viewer.network_click=None;self.viewer.route_nodes={};self.viewer.route_start_marker=None
        self.extract_hint.set('광주간선: 시작 함체/끝점 → 끝 함체/끝점 선택')

    def _reset_network_filter(self):
        self.export_scope=None;self.route_start=None
        self.viewer.entity_filter=None;self.viewer.network_click=None;self.viewer.route_nodes={};self.viewer.route_start_marker=None
        self.viewer.set_mode('select');self.viewer.selected.clear();self.viewer.fit_view()
        self.extract_hint.set('전체 도면 표시 / 일반 Excel 추출 모드')

    def _show_scope(self,scope):
        self.export_scope=scope
        background={e.index for e in self.viewer.scene.entities if is_background(e)}
        display_indices=set(scope['indices']) | background
        self.viewer.entity_filter=display_indices
        layers={self.viewer.scene.entities[i].layer for i in display_indices}
        for iid in self.tree.get_children():
            if self.layer_names.get(iid) in layers and not is_default_hidden(self.layer_names.get(iid)):self._set_checked(iid,True)
        self.viewer.network_click=None;self.viewer.route_nodes={};self.viewer.route_start_marker=None
        self.viewer.mode='select';self.viewer.selected.clear()
        # Fit the selected route, then draw the surrounding map at that same scale.
        self.viewer.entity_filter=set(scope['indices'])
        self.viewer.fit_view()
        self.viewer.entity_filter=display_indices
        self.viewer.redraw()

    def _begin_fiber_route(self):
        if self.busy:return
        if not self.viewer.scene or not self.input_path:
            messagebox.showinfo('광주간선 추출','먼저 DXF 도면을 열어주세요.');return
        try:self.fiber_network=FiberNetwork(self.viewer.scene,self.input_path)
        except Exception as exc:messagebox.showerror('광주간선 추출',str(exc));return
        if not self.fiber_network.edges:
            messagebox.showinfo('광주간선 추출','지선을 제외한 연결 가능한 광케이블이 없습니다.');return
        self.export_scope=None;self.route_start=None;self.viewer.entity_filter=None
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
        self.status_var.set('선택 경로와 배경 지형도 표시 / 배경은 Excel 추출에서 제외')

    def _begin_main_conduit(self):
        if self.busy:return
        if not self.viewer.scene or not self.input_path:
            messagebox.showinfo('100mm 주관로 추출','먼저 DXF 도면을 열어주세요.');return
        self._reset_network_filter()
        records=conduit_records(self.viewer.scene,self.input_path,self.pipe_diameters)
        if not records:
            messagebox.showinfo('100mm 주관로 추출','읽을 수 있는 관로 객체가 없습니다.');return
        unknown=[r for r in records if r['diameter'] is None]
        if unknown:
            self._show_pipe_diameter_editor(records)
        else:self._apply_main_conduit(records)

    def _apply_main_conduit(self,records):
        # Refresh local user assignments, but keep explicit DXF diameter authoritative.
        records=conduit_records(self.viewer.scene,self.input_path,self.pipe_diameters)
        main=[r for r in records if r['diameter']==100]
        unknown=sum(r['diameter'] is None for r in records)
        drop=sum(r['diameter']==50 for r in records)
        if not main:
            messagebox.showwarning('100mm 주관로 추출',f'지름이 확인된 100mm 관로가 없습니다. 미확인 {unknown}개 / 50mm {drop}개는 추출하지 않습니다. 원래 CAD의 관경 정보를 확인한 후 지정해주세요.');return False
        self._show_scope({'kind':'pipe','records':records,'indices':{r['entity'].index for r in main}})
        self.extract_hint.set(f'100mm {len(main)}개 표시 / 50mm {drop}개·미확인 {unknown}개 제외')
        return True

    def _show_pipe_diameter_editor(self,records):
        win=tk.Toplevel(self);win.title('관경 확인 — PL0/P0 코드만으로 지름을 추정하지 않습니다');win.geometry('740x520')
        ttk.Label(win,text='원래 CAD에서 확인한 관로만 100mm/50mm로 지정해주세요. 설정은 현재 도면 세션에만 적용됩니다.',wraplength=700).pack(fill='x',padx=10,pady=10)
        tree=ttk.Treeview(win,columns=('id','code','diameter','length'),show='headings',selectmode='extended')
        for column,label in [('id','객체ID'),('code','원본 코드'),('diameter','확인된 지름'),('length','경로 길이(m)')]:tree.heading(column,text=label);tree.column(column,width=155)
        tree.pack(fill='both',expand=True,padx=10)
        from network_extract import cable_length
        by={r['entity'].handle:r for r in records}
        def refresh():
            for r in conduit_records(self.viewer.scene,self.input_path,self.pipe_diameters):
                h=r['entity'].handle
                vals=(h,r['code'],f"{r['diameter']}mm" if r['diameter'] else '미확인',round(cable_length(r['item']['points']),2))
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
        shown=self.viewer.entity_filter
        indices={e.index for e in self.viewer.scene.entities if e.index in scope['indices'] and (shown is None or e.index in shown) and e.layer in self.viewer.visible_layers and self.viewer.entity_items.get(e.index)}
        if not indices:
            messagebox.showinfo('필요 항목 Excel 추출','화면에 표시된 추출 대상이 없습니다.');return
        label='광주간선' if scope['kind']=='fiber' else '100mm_주관로'
        out=filedialog.asksaveasfilename(title=f'{label} Excel 추출',defaultextension='.xlsx',initialfile=Path(self.input_path).stem+'_'+label+'.xlsx',filetypes=[('Excel','*.xlsx')])
        if not out:return
        if scope['kind']=='pipe':scope={**scope,'records':conduit_records(self.viewer.scene,self.input_path,self.pipe_diameters)}
        self.busy=True;self._show_progress();self._set_progress(10,'화면에 표시된 필요 항목만 Excel 추출')
        scene=self.viewer.scene;epsg=int(self.epsg_var.get())
        def worker():
            try:
                rows=export_network(out,scene,scope,indices,epsg)
                if scope['kind']=='fiber':
                    count=sum(scope['network'].edges[h].index in indices for h in scope['route'])
                else:
                    count=sum(r['diameter']==100 and r['entity'].index in indices for r in scope['records'])
                stats=ConversionStats(entities=count,rows=rows)
                self.q.put(('done',(stats,out)))
            except Exception as exc:self.q.put(('error',str(exc)))
        threading.Thread(target=worker,daemon=True).start()
