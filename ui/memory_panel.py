from __future__ import annotations
import html
import json
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QLineEdit,QPushButton,QTabWidget,QWidget,QTreeWidget,QTreeWidgetItem,QTextBrowser


class MemoryPanel(QDialog):
    """Second Brain: Overview / Tree / Graph / Timeline / retrieval explanation."""

    def __init__(self, memory, parent=None):
        super().__init__(parent)
        self.memory = memory
        self.brain = getattr(memory, 'second_brain', None)
        self.rows_by_id = {}
        self.setWindowTitle('Second Brain')
        self.resize(1040,720)
        self.setStyleSheet('QDialog,QWidget{background:#050608;color:#eef4f8} QLineEdit,QTreeWidget,QTextBrowser{background:#080c11;border:1px solid #22303b;padding:8px} QPushButton{background:#101822;border:1px solid #263746;padding:8px 12px}')
        lay=QVBoxLayout(self)
        top=QHBoxLayout(); self.search=QLineEdit(); self.search.setPlaceholderText('Search memory…')
        btn=QPushButton('Search'); btn.clicked.connect(self.refresh); top.addWidget(self.search,1); top.addWidget(btn); lay.addLayout(top)
        self.tabs=QTabWidget(); lay.addWidget(self.tabs,1)
        self.overview=QTextBrowser(); self.tree=QTreeWidget(); self.tree.setHeaderLabels(['Subject','Type','Confidence'])
        self.graph_view=QTextBrowser(); self.timeline=QTreeWidget(); self.timeline.setHeaderLabels(['Time','Subject','Type'])
        self.why=QTextBrowser(); self.why.setAccessibleName('Why this memory was retrieved')
        for name,w in [('Overview',self.overview),('Tree',self.tree),('Graph',self.graph_view),('Timeline',self.timeline),('Why Retrieved',self.why)]:
            page=QWidget(); pl=QVBoxLayout(page); pl.addWidget(w); self.tabs.addTab(page,name)
        self.tree.itemSelectionChanged.connect(self.show_selected_explanation)
        self.timeline.itemSelectionChanged.connect(self.show_selected_explanation)
        self.refresh()

    def _graph(self):
        if self.brain is not None:
            return self.brain.graph()
        return self.memory.graph()

    def _search_rows(self,query):
        if query and self.brain is not None:
            return self.brain.context(query,100)
        if query:
            return self.memory.search(query,100)
        return self._graph()['nodes']

    @staticmethod
    def _explanation_html(row):
        explanation=row.get('retrieval_explanation')
        if not explanation:
            return '<h3>No retrieval claim</h3><p>This memory is being inspected directly. Run a search to see why Personal AI selected it for a real retrieval query.</p>'
        items=[
            ('Memory ID',explanation.get('memory_id')),('Subject / type',f"{explanation.get('subject','')} / {explanation.get('type','')}"),
            ('Source',explanation.get('source')),('Source time',explanation.get('source_timestamp')),('Confidence',explanation.get('confidence')),
            ('Verified',explanation.get('verified')),('Sensitivity',explanation.get('sensitivity')),('Age (days)',explanation.get('age_days')),
            ('Semantic score',explanation.get('semantic_score')),('Salience score',explanation.get('salience_score')),
            ('Relationships',explanation.get('relationship_count')),('Relationship rank contribution',explanation.get('relationship_contribution')),
            ('State',explanation.get('memory_state')),('Contradiction',explanation.get('contradiction_state')),('Superseded by',explanation.get('superseded_by')),
            ('Query',explanation.get('retrieval_query')),('Used at',explanation.get('used_at')),('Reason selected',explanation.get('selection_reason')),
            ('Evidence',json.dumps(explanation.get('evidence_references') or [],ensure_ascii=False)),
        ]
        rows=''.join(f"<tr><td style='color:#81939d;padding:4px 12px 4px 0'>{html.escape(str(label))}</td><td>{html.escape('' if value is None else str(value))}</td></tr>" for label,value in items)
        return f'<h3>Why Personal AI retrieved this memory</h3><table>{rows}</table>'

    def show_selected_explanation(self):
        item=None
        if self.tree.selectedItems(): item=self.tree.selectedItems()[0]
        elif self.timeline.selectedItems(): item=self.timeline.selectedItems()[0]
        if item is None: return
        memory_id=item.data(0,Qt.ItemDataRole.UserRole); row=self.rows_by_id.get(memory_id)
        if row:
            self.why.setHtml(self._explanation_html(row))
            self.tabs.setCurrentIndex(4)

    def refresh(self):
        query=self.search.text().strip(); rows=self._search_rows(query); graph=self._graph(); self.rows_by_id={row.get('id'):row for row in rows if row.get('id')}
        self.tree.clear(); self.timeline.clear(); children={}
        for memory in rows:
            item=QTreeWidgetItem([str(memory.get('subject','')),str(memory.get('type','')),str(memory.get('confidence',''))]); item.setData(0,Qt.ItemDataRole.UserRole,memory.get('id')); children[memory.get('id')]=item
        for memory in rows:
            item=children[memory.get('id')]; parent=children.get(memory.get('parent_id')); (parent.addChild(item) if parent else self.tree.addTopLevelItem(item))
            timeline_item=QTreeWidgetItem([str(memory.get('occurred_at') or memory.get('created_at','')),str(memory.get('subject','')),str(memory.get('type',''))]); timeline_item.setData(0,Qt.ItemDataRole.UserRole,memory.get('id')); self.timeline.addTopLevelItem(timeline_item)
        explanation_count=sum(1 for row in rows if row.get('retrieval_explanation'))
        self.overview.setHtml(f"<h2>Second Brain</h2><p><b>{len(graph['nodes'])}</b> memories · <b>{len(graph['edges'])}</b> relationships</p><p><b>{explanation_count}</b> memories have a query-specific retrieval explanation in this view.</p><p>Search to inspect why a memory was selected. Graph, Tree and Detail remain separate views.</p>")
        edge_lines=[f"{e.get('source_id')} —{e.get('relation')}→ {e.get('target_id')}" for e in graph['edges'][:250]]; self.graph_view.setPlainText('\n'.join(edge_lines) if edge_lines else 'No memory relationships yet.')
        self.why.setHtml('<h3>Why Retrieved</h3><p>Select a searched memory to inspect source, confidence, recency, salience, contradiction state and evidence.</p>')
