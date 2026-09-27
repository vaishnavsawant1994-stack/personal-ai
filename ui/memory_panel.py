from __future__ import annotations
import json
from PyQt6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QLineEdit,QPushButton,QTabWidget,QWidget,QTreeWidget,QTreeWidgetItem,QTextBrowser,QLabel

class MemoryPanel(QDialog):
    """Second Brain desktop foundation: Overview / Tree / Graph / Timeline."""
    def __init__(self,memory,parent=None):
        super().__init__(parent); self.memory=memory
        self.setWindowTitle("Second Brain"); self.resize(980,680)
        self.setStyleSheet("QDialog,QWidget{background:#050608;color:#eef4f8} QLineEdit,QTreeWidget,QTextBrowser{background:#080c11;border:1px solid #22303b;padding:8px} QPushButton{background:#101822;border:1px solid #263746;padding:8px 12px}")
        lay=QVBoxLayout(self)
        top=QHBoxLayout(); self.search=QLineEdit(); self.search.setPlaceholderText("Search memory…")
        btn=QPushButton("Search"); btn.clicked.connect(self.refresh); top.addWidget(self.search,1); top.addWidget(btn); lay.addLayout(top)
        self.tabs=QTabWidget(); lay.addWidget(self.tabs,1)
        self.overview=QTextBrowser(); self.tree=QTreeWidget(); self.tree.setHeaderLabels(["Subject","Type","Confidence"])
        self.graph_view=QTextBrowser(); self.timeline=QTreeWidget(); self.timeline.setHeaderLabels(["Time","Subject","Type"])
        for name,w in [("Overview",self.overview),("Tree",self.tree),("Graph",self.graph_view),("Timeline",self.timeline)]:
            page=QWidget(); pl=QVBoxLayout(page); pl.addWidget(w); self.tabs.addTab(page,name)
        self.refresh()

    def refresh(self):
        q=self.search.text().strip(); rows=self.memory.search(q,100) if q else self.memory.graph()["nodes"]
        graph=self.memory.graph(); self.tree.clear(); self.timeline.clear()
        children={}
        for m in rows:
            item=QTreeWidgetItem([str(m.get("subject","")),str(m.get("type","")),str(m.get("confidence",""))])
            children[m.get("id")]=item
        for m in rows:
            item=children[m.get("id")]; parent=children.get(m.get("parent_id"))
            (parent.addChild(item) if parent else self.tree.addTopLevelItem(item))
            self.timeline.addTopLevelItem(QTreeWidgetItem([str(m.get("created_at","")),str(m.get("subject","")),str(m.get("type",""))]))
        self.overview.setHtml(f"<h2>Second Brain</h2><p><b>{len(graph['nodes'])}</b> memories · <b>{len(graph['edges'])}</b> relationships</p><p>Search, inspect hierarchy, relationships and memory timeline here.</p>")
        edge_lines=[f"{e.get('source_id')} —{e.get('relation')}→ {e.get('target_id')}" for e in graph["edges"][:250]]
        self.graph_view.setPlainText("\n".join(edge_lines) if edge_lines else "No memory relationships yet.")
