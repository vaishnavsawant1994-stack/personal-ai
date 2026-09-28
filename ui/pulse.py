from __future__ import annotations

import math
import random

from PyQt6.QtCore import QPointF, QTimer, Qt
from PyQt6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QRadialGradient
from PyQt6.QtWidgets import QWidget


class PulseWidget(QWidget):
    """Personal AI Home V1 living neural field: presentation only, never authority."""

    STATE_ALIASES = {"memory_retrieval":"memory","retrieving_memory":"memory","knowledge_retrieval":"knowledge","retrieving_knowledge":"knowledge","tool_action":"acting","tool":"acting","action":"acting","responding":"speaking","response":"speaking","needs_approval":"approval","waiting_approval":"approval","ready":"active"}
    STATE_SPEEDS = {"idle":.012,"active":.022,"listening":.046,"understanding":.038,"thinking":.061,"memory":.042,"knowledge":.048,"acting":.072,"speaking":.052,"approval":.010,"background":.006,"success":.014,"warning":.018,"error":.026}
    STATE_ENERGY = {"idle":.50,"active":.62,"listening":.82,"understanding":.76,"thinking":1.00,"memory":.94,"knowledge":.88,"acting":.94,"speaking":.88,"approval":.38,"background":.23,"success":.68,"warning":.58,"error":.54}
    STATE_AMPLITUDE = {"idle":.014,"active":.019,"listening":.029,"understanding":.024,"thinking":.038,"memory":.031,"knowledge":.028,"acting":.026,"speaking":.032,"approval":.011,"background":.007,"success":.012,"warning":.015,"error":.020}
    CORE_NODES = ((-.27,-.10),(-.19,-.27),(-.05,-.19),(.12,-.26),(.26,-.14),(.19,-.02),(.28,.14),(.09,.24),(-.07,.18),(-.24,.25),(-.21,.04),(-.08,-.04),(.05,.03),(.15,.10),(-.02,.30),(.00,-.32),(-.32,.10),(.30,-.02))
    CORE_EDGES = ((0,2),(0,10),(1,2),(1,11),(1,15),(2,11),(2,12),(2,3),(3,12),(3,4),(4,5),(4,17),(5,12),(5,13),(5,17),(6,13),(6,7),(7,13),(7,8),(7,14),(8,12),(8,14),(8,9),(9,10),(9,14),(10,11),(10,16),(11,12),(12,13))
    FLOW_PATHS = (((-.34,-.06),(-.22,-.17),(-.10,-.14),(.04,-.04)),((-.16,-.34),(-.07,-.24),(.08,-.12),(.22,-.18)),((.31,-.19),(.24,-.08),(.10,.03),(.20,.19)),((.25,.25),(.12,.19),(-.02,.08),(-.18,.18)),((-.30,.28),(-.22,.16),(-.08,.05),(.05,.13)))

    def __init__(self,parent=None):
        super().__init__(parent); self.t=0.; self.state="idle"; self.reduce_motion=False
        self.memory_labels=("Project","Person","Decision","Conversation")
        self.seed=[random.Random(101+i).uniform(-1.,1.) for i in range(48)]
        self.timer=QTimer(self); self.timer.timeout.connect(self.tick); self.timer.start(16)
        self.setAccessibleName("Personal AI living core")

    @classmethod
    def normalize_state(cls,state:str)->str:
        key=str(state or "").strip().lower().replace("-","_").replace(" ","_")
        return cls.STATE_ALIASES.get(key,key if key in cls.STATE_SPEEDS else "warning")

    def set_state(self,state):
        self.state=self.normalize_state(state)
        interval=120 if self.reduce_motion else (100 if self.state=="background" else 16)
        if self.timer.interval()!=interval:self.timer.setInterval(interval)
        self.update()
    def set_memory_labels(self,labels):
        cleaned=[str(i).strip() for i in labels if str(i).strip()]
        if cleaned:self.memory_labels=tuple(cleaned[:4])
        self.update()
    def set_reduce_motion(self,value:bool): self.reduce_motion=bool(value); self.timer.setInterval(120 if self.reduce_motion else 16); self.update()
    def tick(self): self.t+=self.STATE_SPEEDS[self.state]*(.18 if self.reduce_motion else 1.); self.update()

    def _palette(self):
        if self.state=="error": return QColor(234,158,143),QColor(184,102,92)
        if self.state=="warning": return QColor(225,196,143),QColor(170,132,78)
        if self.state=="success": return QColor(157,224,190),QColor(82,157,124)
        if self.state=="approval": return QColor(214,205,166),QColor(154,144,104)
        if self.state=="memory": return QColor(155,220,216),QColor(84,154,153)
        if self.state=="knowledge": return QColor(171,206,233),QColor(95,136,171)
        return QColor(164,224,236),QColor(83,151,169)

    def _node_position(self,cx,cy,width,height,index,amplitude=None):
        nx,ny=self.CORE_NODES[index]; amp=self.STATE_AMPLITUDE[self.state] if amplitude is None else amplitude
        if self.reduce_motion: amp*=.42
        seed=self.seed[index]; phase=self.t*(.62+(index%4)*.07)+seed*2.4; breath=1.+math.sin(self.t*.72+index*.17)*amp*.34
        return QPointF(cx+nx*width*.78*breath+math.sin(phase)*width*amp*.070,cy+ny*height*.88*breath+math.cos(phase*.83)*height*amp*.076)

    def _curve_between(self,a,b,index,bend_scale=1.):
        mx=(a.x()+b.x())*.5; my=(a.y()+b.y())*.5; vx=b.x()-a.x(); vy=b.y()-a.y(); length=max(1.,math.hypot(vx,vy)); direction=-1. if index%2 else 1.; bend=(8.+(index%5)*3.)*direction*bend_scale
        path=QPainterPath(a); path.quadTo(QPointF(mx-vy/length*bend,my+vx/length*bend),b); return path

    def _draw_flow_paths(self,painter,cx,cy,width,height,primary):
        energy=self.STATE_ENERGY[self.state]; amp=self.STATE_AMPLITUDE[self.state]*(.42 if self.reduce_motion else 1.)
        for index,template in enumerate(self.FLOW_PATHS):
            phase=self.t*(.34+index*.025)+self.seed[24+index]; points=[]
            for pi,(nx,ny) in enumerate(template): points.append(QPointF(cx+nx*width*.78+math.sin(phase+pi*1.2)*width*amp*.085,cy+ny*height*.88+math.cos(phase*.9+pi)*height*amp*.095))
            path=QPainterPath(points[0]); path.cubicTo(points[1],points[2],points[3]); pen=QPen(QColor(primary.red(),primary.green(),primary.blue(),max(16,int((82-index*5)*energy)))); pen.setWidthF(1.12 if index in (1,3) else .88); painter.setPen(pen); painter.setBrush(Qt.BrushStyle.NoBrush); painter.drawPath(path)

    def _draw_lattice(self,painter,cx,cy,width,height,primary):
        energy=self.STATE_ENERGY[self.state]; points=[self._node_position(cx,cy,width,height,i) for i in range(len(self.CORE_NODES))]; self._draw_flow_paths(painter,cx,cy,width,height,primary); active=int(self.t*1.45)%4
        for ei,(source,target) in enumerate(self.CORE_EDGES):
            alpha=int((88+(ei%4)*15)*energy); boost=0.
            if self.state in ("thinking","understanding") and ei%4==active: alpha+=58; boost=.38
            pen=QPen(QColor(primary.red(),primary.green(),primary.blue(),min(188,max(16,alpha)))); pen.setWidthF(.72+(ei%3)*.12+boost); painter.setPen(pen); painter.setBrush(Qt.BrushStyle.NoBrush); painter.drawPath(self._curve_between(points[source],points[target],ei))
        count=11 if self.state=="background" else len(points)
        for index,point in enumerate(points[:count]):
            alpha=int((104+(index%4)*18)*energy); radius=1.45+(index%3)*.36
            if self.state=="thinking" and index%4==active: alpha=min(220,alpha+72); radius+=1.25; painter.setPen(Qt.PenStyle.NoPen); painter.setBrush(QColor(primary.red(),primary.green(),primary.blue(),24)); painter.drawEllipse(point,radius+6.,radius+6.)
            painter.setPen(Qt.PenStyle.NoPen); painter.setBrush(QColor(primary.red(),primary.green(),primary.blue(),max(18,alpha))); painter.drawEllipse(point,radius,radius)

    def _draw_listening(self,painter,cx,cy,width,height,primary):
        if self.state!="listening": return
        for i,(target_index,(ox,oy)) in enumerate(zip((0,4,6,9),((-.36,-.20),(.36,-.22),(.37,.20),(-.36,.22)))):
            target=self._node_position(cx,cy,width,height,target_index); origin=QPointF(cx+ox*width,cy+oy*height); progress=(self.t*.30+i*.19)%1.; start=QPointF(origin.x()+(target.x()-origin.x())*progress*.35,origin.y()+(target.y()-origin.y())*progress*.35); path=self._curve_between(start,target,i+40,1.75); painter.setPen(QPen(QColor(primary.red(),primary.green(),primary.blue(),int(122*(1.-progress*.34))),1.05)); painter.setBrush(Qt.BrushStyle.NoBrush); painter.drawPath(path); painter.setPen(Qt.PenStyle.NoPen); painter.setBrush(QColor(primary.red(),primary.green(),primary.blue(),86)); painter.drawEllipse(start,1.8,1.8)

    def _draw_thinking(self,painter,cx,cy,width,height,primary):
        if self.state not in ("understanding","thinking"): return
        for i in range(9 if self.state=="thinking" else 5):
            ei=(i*3+int(self.t*2.))%len(self.CORE_EDGES); si,ti=self.CORE_EDGES[ei]; a=self._node_position(cx,cy,width,height,si); b=self._node_position(cx,cy,width,height,ti); q=(self.t*.23+i*.115)%1.; point=QPointF(a.x()+(b.x()-a.x())*q,a.y()+(b.y()-a.y())*q); painter.setPen(Qt.PenStyle.NoPen); painter.setBrush(QColor(primary.red(),primary.green(),primary.blue(),34)); painter.drawEllipse(point,6.,6.); painter.setBrush(QColor(primary.red(),primary.green(),primary.blue(),176)); painter.drawEllipse(point,2.35,2.35)

    def _draw_memory(self,painter,cx,cy,width,height,primary):
        if self.state!="memory": return
        anchors=((-0.30,-0.25),(0.32,-0.20),(0.31,0.25),(-0.31,0.24)); font=QFont(); font.setPointSizeF(8.2); painter.setFont(font)
        for index,(source_index,(ax,ay)) in enumerate(zip((1,4,6,9),anchors)):
            source=self._node_position(cx,cy,width,height,source_index); endpoint=QPointF(cx+ax*width,cy+ay*height); painter.setPen(QPen(QColor(primary.red(),primary.green(),primary.blue(),118),1.02)); painter.setBrush(Qt.BrushStyle.NoBrush); painter.drawPath(self._curve_between(source,endpoint,index+60,2.)); painter.setPen(Qt.PenStyle.NoPen); painter.setBrush(QColor(primary.red(),primary.green(),primary.blue(),188)); painter.drawEllipse(endpoint,2.7,2.7); painter.setBrush(QColor(primary.red(),primary.green(),primary.blue(),26)); painter.drawEllipse(endpoint,7.,7.); painter.setPen(QColor(primary.red(),primary.green(),primary.blue(),148)); painter.drawText(int(endpoint.x()+(10 if ax>=0 else -70)),int(endpoint.y()-6),self.memory_labels[index%len(self.memory_labels)])

    def _draw_knowledge(self,painter,cx,cy,width,height,primary):
        if self.state!="knowledge": return
        for i,(source_xy,target_index) in enumerate(zip(((-.25,-.34),(.00,-.39),(.27,-.32)),(1,15,4))):
            source=QPointF(cx+source_xy[0]*width,cy+source_xy[1]*height); target=self._node_position(cx,cy,width,height,target_index); painter.setPen(QPen(QColor(primary.red(),primary.green(),primary.blue(),92),.95)); painter.setBrush(Qt.BrushStyle.NoBrush); painter.drawPath(self._curve_between(source,target,i+70,1.8))

    def _draw_action(self,painter,cx,cy,width,height,primary):
        if self.state!="acting": return
        start=self._node_position(cx,cy,width,height,17); end=QPointF(start.x()+width*.105,start.y()-height*.035); painter.setPen(QPen(QColor(primary.red(),primary.green(),primary.blue(),148),1.20)); painter.setBrush(Qt.BrushStyle.NoBrush); painter.drawPath(self._curve_between(start,end,80,1.5)); painter.setPen(Qt.PenStyle.NoPen); painter.setBrush(QColor(primary.red(),primary.green(),primary.blue(),190)); painter.drawEllipse(end,3.,3.)

    def _draw_speaking(self,painter,cx,cy,width,height,primary):
        if self.state!="speaking": return
        for i,(source_index,angle) in enumerate(zip((3,4,17,6,7),(-1.22,-.68,-.05,.58,1.10))):
            source=self._node_position(cx,cy,width,height,source_index); reach=width*(.072+.009*math.sin(self.t*2.3+i)); end=QPointF(source.x()+math.cos(angle)*reach,source.y()+math.sin(angle)*height*.095); painter.setPen(QPen(QColor(primary.red(),primary.green(),primary.blue(),92+i*9),.96)); painter.setBrush(Qt.BrushStyle.NoBrush); painter.drawPath(self._curve_between(source,end,i+90,1.35)); painter.setPen(Qt.PenStyle.NoPen); painter.setBrush(QColor(primary.red(),primary.green(),primary.blue(),82)); painter.drawEllipse(end,1.7,1.7)

    def paintEvent(self,_):
        painter=QPainter(self); painter.setRenderHint(QPainter.RenderHint.Antialiasing); width,height=self.width(),self.height(); cx,cy=width*.50,height*.50; primary,secondary=self._palette(); energy=self.STATE_ENERGY[self.state]; glow=QRadialGradient(QPointF(cx,cy),min(width,height)*.45); glow.setColorAt(0,QColor(primary.red(),primary.green(),primary.blue(),int(34*energy))); glow.setColorAt(.42,QColor(secondary.red(),secondary.green(),secondary.blue(),int(16*energy))); glow.setColorAt(1,QColor(0,0,0,0)); painter.setPen(Qt.PenStyle.NoPen); painter.setBrush(glow); painter.drawEllipse(QPointF(cx,cy),min(width,height)*.43,min(width,height)*.33)
        self._draw_lattice(painter,cx,cy,width,height,primary); self._draw_listening(painter,cx,cy,width,height,primary); self._draw_thinking(painter,cx,cy,width,height,primary); self._draw_memory(painter,cx,cy,width,height,primary); self._draw_knowledge(painter,cx,cy,width,height,primary); self._draw_action(painter,cx,cy,width,height,primary); self._draw_speaking(painter,cx,cy,width,height,primary)
