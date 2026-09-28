from __future__ import annotations
from pathlib import Path
from devices.continuity_sync import ContinuitySync
from future_intelligence.gates import TrustGate
from future_intelligence.everyday import EverydayIntelligence
from future_intelligence.deep_brain import LifeGraph
from future_intelligence.second_brain_graph import SecondBrainLifeGraph
from future_intelligence.operations import PersonalOperations
from future_intelligence.multimodal import WorldUnderstanding
from future_intelligence.everywhere import PersonalAIEverywhere
from future_intelligence.sovereignty import HybridIntelligenceRouter
from future_intelligence.autonomy import AdvancedAutonomy
from future_intelligence.autonomy_runtime import install as install_autonomy_runtime
from core.p10_approval_continuation import install as install_p10_turn_continuation

install_autonomy_runtime(AdvancedAutonomy)


class FutureIntelligenceProgram:
    """Integrated P4-P10 runtime foundation, deliberately gated by P3 evidence."""

    def __init__(self, data_dir: Path, *, runtime: dict):
        root = Path(data_dir)
        self.gate = TrustGate(); self.runtime = runtime
        self.everyday = EverydayIntelligence(root/'everyday.sqlite3',memory=runtime.get('memory'),second_brain=runtime.get('second_brain'),proactive=runtime.get('proactive'),continuity=runtime.get('continuity'),integrations=runtime.get('integrations'),events=runtime.get('events'))
        if runtime.get('memory') is not None:
            try: runtime['memory'].everyday_intelligence=self.everyday
            except Exception: pass
        runtime['everyday_intelligence']=self.everyday
        self.life_graph=LifeGraph(root/'life-graph.sqlite3'); self.second_brain_life_graph=SecondBrainLifeGraph(self.life_graph,runtime.get('second_brain')); runtime['second_brain_life_graph']=self.second_brain_life_graph
        # PersonalOperations coordinates P6 but delegates consequential execution and
        # approval consumption directly to the already-qualified AgentExecutor.  The
        # CanonicalTurnRuntime remains the outer logical-turn authority and must not
        # be recursively re-entered by an operation approval resume.
        turn_executor=runtime.get('executor'); governed_executor=runtime.get('agent_executor') or turn_executor
        self.operations=PersonalOperations(gate=self.gate,executor=governed_executor,automations=runtime.get('automations'),events=runtime.get('events'),second_brain=runtime.get('second_brain'),memory=runtime.get('memory'),everyday=self.everyday,path=root/'operations.sqlite3')
        memory=runtime.get('memory')
        self.world=WorldUnderstanding(gate=self.gate,events=runtime.get('events'),path=root/'world.sqlite3',device_registry=runtime.get('device_registry'),audit=getattr(memory,'audit',None) if memory is not None else None)
        executor=turn_executor; approvals=getattr(governed_executor,'approvals',None) if governed_executor is not None else None
        epoch_provider=approvals.current_security_epoch if approvals is not None and hasattr(approvals,'current_security_epoch') else (lambda:0)
        self.continuity_sync=ContinuitySync(runtime.get('continuity'),gate=self.gate,device_registry=runtime.get('device_registry'),security_epoch_provider=epoch_provider,operations=self.operations,world=self.world,events=runtime.get('events')); runtime['continuity_sync']=self.continuity_sync
        self.everywhere=PersonalAIEverywhere(gate=self.gate,device_registry=runtime.get('device_registry'),continuity=runtime.get('continuity'),continuity_sync=self.continuity_sync)
        # P9 compatibility surface delegates to the canonical P9+W8 router.
        self.hybrid=HybridIntelligenceRouter(gate=self.gate,canonical_router=runtime.get('models'))
        canonical_stop=runtime.get('emergency_stop_provider')
        if canonical_stop is None and runtime.get('automations') is not None:
            budgets=getattr(runtime.get('automations'),'budgets',None)
            if budgets is not None and hasattr(budgets,'emergency_stopped'): canonical_stop=budgets.emergency_stopped
        self.autonomy=AdvancedAutonomy(gate=self.gate,operations=self.operations,events=runtime.get('events'),path=root/'autonomy.sqlite3',executor=governed_executor,automations=runtime.get('automations'),models=runtime.get('models'),memory=runtime.get('second_brain') or runtime.get('memory'),knowledge=runtime.get('knowledge'),world=self.world,continuity=self.continuity_sync,emergency_stop_provider=canonical_stop)
        runtime['advanced_autonomy']=self.autonomy
        if turn_executor is not None: install_p10_turn_continuation(type(turn_executor))

    def status(self):
        p5_link=self.second_brain_life_graph.status(); p4_status=self.everyday.safe_status()
        return {'p4':{'implemented':True,'activation':'safe-now','lifecycle':p4_status},'p5':{'implemented':True,'activation':'safe-now','second_brain_linked':p5_link['linked'],'linked_memory_nodes':p5_link['memory_nodes']},'p6':{'implemented':True,'activation':self.gate.decision('p6').reason,'operations':self.operations.safe_status()},'p7':{'implemented':True,'activation':self.gate.decision('p7').reason},'p8':{'implemented':True,'activation':self.gate.decision('p8').reason},'p9':{'implemented':True,'activation':self.gate.decision('p9').reason,'canonical_router':self.hybrid.authoritative},'p10':{'implemented':True,'activation':self.gate.decision('p10').reason,'autonomy':self.autonomy.status()}}
