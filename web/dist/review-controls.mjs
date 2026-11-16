export const activeExecution=status=>['queued','starting','running','cancelling'].includes(status);

export function reviewControlState(project,{inFlight=false,running=false}={}){
 const report=project?.online_report,execution=report?.execution;
 const terminated=Boolean(report?.terminated_at);
 const intent=project?.online_control_request||(report?.termination_requested?'terminate':'pause');
 const retry=!terminated&&!inFlight&&Boolean((project?.online_cancel_error||project?.online_control_request&&execution?.status!=='cancelling'));
 const stopping=!terminated&&!retry&&Boolean(inFlight||execution?.status==='cancelling');
 const pending=project?.online_pending_request||project?.online_execution_pending;
 const paused=!terminated&&!retry&&!stopping&&!pending&&!running&&(
  project?.online_paused??(report?.status==='cancelled'||execution?.status==='cancelled'));
 return {intent,terminated,retry,stopping,paused,
  running:!terminated&&!paused&&!retry&&!stopping&&Boolean(running||pending||report?.status==='reviewing'||activeExecution(execution?.status)),
  canTerminate:!terminated&&(paused||report?.status==='failed'||['failed','expired'].includes(execution?.status))};
}

export function reviewControlButtons(state,attribute){
 if(state.terminated)return '';
 const button=(action,label,tone)=>`<button type="button" class="btn small review-control review-control-${tone}" ${attribute(action)}>${label}</button>`;
 if(state.retry){
  if(state.intent==='pause')return button('pause','暂停','pause')+button('terminate-review','中断','stop');
  return button('retry-control','重试中断','stop');
 }
 if(state.stopping)return '';
 return (state.running?button('pause','暂停','pause'):state.paused?button('continue-review','继续','continue'):'')+
  (state.running||state.canTerminate?button('terminate-review','中断','stop'):'');
}
