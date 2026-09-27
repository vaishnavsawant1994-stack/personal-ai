from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from qualification.program import P3QualificationProgram


@dataclass(frozen=True)
class TrialResult:
    task: str
    passed: bool
    latency_ms: float | None = None
    metrics: dict[str, bool] | None = None
    evidence: dict[str, Any] | None = None


class QualificationHarness:
    """Thin external-test harness for P3.2-P3.8.

    The harness accepts measured results from hardware/device runners. It does
    not infer success from code presence and it does not expose a model-facing
    method for promoting qualification levels.
    """

    def __init__(self, program: P3QualificationProgram):
        self.program = program

    @classmethod
    def open(cls, path: Path):
        return cls(P3QualificationProgram(path))

    def run_session(
        self,
        stage: str,
        *,
        evidence_class: str,
        environment: dict,
        trials: list[TrialResult],
        duration_seconds: float,
    ):
        session_id = self.program.start_session(
            stage,
            evidence_class=evidence_class,
            environment=environment,
        )
        try:
            for trial in trials:
                self.program.record_trial(
                    session_id,
                    trial.task,
                    passed=trial.passed,
                    latency_ms=trial.latency_ms,
                    metrics=trial.metrics,
                    evidence=trial.evidence,
                )
        finally:
            self.program.finish_session(session_id, duration_seconds=duration_seconds)
        return {'session_id': session_id, 'evaluation': self.program.evaluate(stage)}

    def record_screen_task(self, session_id: str, *, passed: bool, latency_ms: float, observe_verified: bool, action_verified: bool, approval_correct: bool, unverified_success: bool = False, destructive_without_approval: bool = False, evidence: dict | None = None):
        return self.program.record_trial(
            session_id,
            'observe-understand-act-verify',
            passed=passed,
            latency_ms=latency_ms,
            metrics={
                'observe_verified': observe_verified,
                'action_verified': action_verified,
                'approval_correct': approval_correct,
                'unverified_success': unverified_success,
                'destructive_without_approval': destructive_without_approval,
            },
            evidence=evidence,
        )

    def record_safety_trial(self, session_id: str, *, passed: bool, unauthorized_denied: bool, stale_approval_denied: bool, revoked_device_denied: bool, authority_bypass: bool = False, stale_approval_accepted: bool = False, revoked_device_accepted: bool = False, evidence: dict | None = None):
        return self.program.record_trial(
            session_id,
            'permission-identity-safety',
            passed=passed,
            metrics={
                'unauthorized_denied': unauthorized_denied,
                'stale_approval_denied': stale_approval_denied,
                'revoked_device_denied': revoked_device_denied,
                'authority_bypass': authority_bypass,
                'stale_approval_accepted': stale_approval_accepted,
                'revoked_device_accepted': revoked_device_accepted,
            },
            evidence=evidence,
        )

    def record_workflow_recovery(self, session_id: str, *, passed: bool, restart_recovered: bool, retry_bounded: bool, approval_resume_verified: bool, rollback_recorded: bool, lost_run: bool = False, duplicate_side_effect: bool = False, latency_ms: float | None = None, evidence: dict | None = None):
        return self.program.record_trial(
            session_id,
            'workflow-recovery',
            passed=passed,
            latency_ms=latency_ms,
            metrics={
                'restart_recovered': restart_recovered,
                'retry_bounded': retry_bounded,
                'approval_resume_verified': approval_resume_verified,
                'rollback_recorded': rollback_recorded,
                'lost_run': lost_run,
                'duplicate_side_effect': duplicate_side_effect,
            },
            evidence=evidence,
        )

    def record_memory_trial(self, session_id: str, *, passed: bool, latency_ms: float, recall_relevant: bool, conflict_resolved: bool, temporal_answer_correct: bool, source_traceable: bool, fabricated_memory: bool = False, deleted_history_on_supersession: bool = False, evidence: dict | None = None):
        return self.program.record_trial(
            session_id,
            'second-brain-quality',
            passed=passed,
            latency_ms=latency_ms,
            metrics={
                'recall_relevant': recall_relevant,
                'conflict_resolved': conflict_resolved,
                'temporal_answer_correct': temporal_answer_correct,
                'source_traceable': source_traceable,
                'fabricated_memory': fabricated_memory,
                'deleted_history_on_supersession': deleted_history_on_supersession,
            },
            evidence=evidence,
        )

    def record_handoff(self, session_id: str, *, passed: bool, latency_ms: float, handoff_preserved_context: bool, device_attribution_correct: bool, revocation_enforced: bool, cross_user_context_leak: bool = False, revoked_device_handoff: bool = False, evidence: dict | None = None):
        return self.program.record_trial(
            session_id,
            'cross-device-handoff',
            passed=passed,
            latency_ms=latency_ms,
            metrics={
                'handoff_preserved_context': handoff_preserved_context,
                'device_attribution_correct': device_attribution_correct,
                'revocation_enforced': revocation_enforced,
                'cross_user_context_leak': cross_user_context_leak,
                'revoked_device_handoff': revoked_device_handoff,
            },
            evidence=evidence,
        )

    def record_soak_operation(self, session_id: str, *, passed: bool, latency_ms: float, runtime_alive: bool, audit_continuous: bool, no_unbounded_growth: bool, deadlock: bool = False, uncaught_crash: bool = False, audit_gap: bool = False, evidence: dict | None = None):
        return self.program.record_trial(
            session_id,
            'soak-operation',
            passed=passed,
            latency_ms=latency_ms,
            metrics={
                'runtime_alive': runtime_alive,
                'audit_continuous': audit_continuous,
                'no_unbounded_growth': no_unbounded_growth,
                'deadlock': deadlock,
                'uncaught_crash': uncaught_crash,
                'audit_gap': audit_gap,
            },
            evidence=evidence,
        )

    def record_competitive_task(self, session_id: str, *, passed: bool, same_task_protocol: bool, competitor_result_recorded: bool, personal_ai_result_recorded: bool, self_awarded_superior: bool = False, missing_competitor_evidence: bool = False, latency_ms: float | None = None, evidence: dict | None = None):
        return self.program.record_trial(
            session_id,
            'competitive-task',
            passed=passed,
            latency_ms=latency_ms,
            metrics={
                'same_task_protocol': same_task_protocol,
                'competitor_result_recorded': competitor_result_recorded,
                'personal_ai_result_recorded': personal_ai_result_recorded,
                'self_awarded_superior': self_awarded_superior,
                'missing_competitor_evidence': missing_competitor_evidence,
            },
            evidence=evidence,
        )
